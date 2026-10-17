"""Validate the distributed ZIP by running its EXE from a relocated clean environment."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
from uuid import uuid4
import zipfile

BASE = Path(__file__).resolve().parent
NAME = 'KurumiMarket-v0.8.0-Windows-x64'

if __name__ == '__main__':
    archive = BASE/'release'/(NAME+'.zip')
    location = BASE/'artifacts'/('便携版 独立验证-'+uuid4().hex[:6])
    location.mkdir()
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None
        names = bundle.namelist()
        forbidden = {'settings.json', 'settings.tmp', 'disk_audit.json', 'disk_audit.py', 'installed_apps.json'}
        for name in names:
            path = Path(name)
            assert not path.is_absolute() and '..' not in path.parts
            assert path.name.lower() not in forbidden, name
            assert '.runtime' not in path.parts and '.build-venv' not in path.parts
            assert 'kurumi-official-pv' not in name
        for relative in ['KurumiMarket.exe', '_internal/python312.dll', 'assets/kurumi.ico',
                         'assets/kurumi-sheet-v3.png', 'assets/market-calendar.json',
                         'assets/audio/chance-ai.wav', 'assets/audio/normal.wav']:
            assert NAME+'/'+relative in names, relative
        bundle.extractall(location)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    assert archive.with_suffix('.zip.sha256').read_text(encoding='ascii').split()[0] == digest
    executable = location/NAME/'KurumiMarket.exe'
    different_cwd = location/'不同的启动目录'
    different_cwd.mkdir()
    environment = dict(os.environ)
    for key in ['PYTHONPATH', 'PYTHONHOME', 'VIRTUAL_ENV', 'TCL_LIBRARY', 'TK_LIBRARY']:
        environment.pop(key, None)
    environment['PATH'] = str(Path(environment.get('SystemRoot', 'C:/Windows'))/'System32')
    report_path = BASE/'artifacts/packaged-release-check.json'
    result = subprocess.run([str(executable), '--self-test-report', str(report_path)],
                            cwd=different_cwd, env=environment, timeout=45,
                            capture_output=True, text=True)
    report = json.loads(report_path.read_text(encoding='utf-8')) if report_path.exists() else {}
    assert result.returncode == 0 and report.get('success') and report.get('frozen'), (result.returncode, report, result.stderr)
    assert Path(report['base']).resolve() == executable.parent.resolve()
    assert not (executable.parent/'settings.json').exists()
    report.update(archive=str(archive), archive_bytes=archive.stat().st_size, sha256=digest,
                  privacy_audit='passed', relocated_unicode_path=True, unrelated_working_directory=True,
                  python_environment_removed=True, bundled_file_count=len(names))
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))

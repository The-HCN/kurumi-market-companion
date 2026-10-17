"""Build the shareable Windows portable ZIP from an isolated build environment."""
from datetime import datetime
import hashlib
from importlib import metadata
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import zipfile

BASE = Path(__file__).resolve().parent
VERSION = '0.8.0'
NAME = f'KurumiMarket-v{VERSION}-Windows-x64'
ASSETS = ['kurumi-sheet-v3.png', 'kurumi.ico', 'market-calendar.json',
          'audio/normal.wav', 'audio/chance-ai.wav', 'audio/chance-ai.json']

def main():
    if sys.platform != 'win32' or platform.architecture()[0] != '64bit':
        raise RuntimeError('Build this release with 64-bit Python on Windows.')
    target = BASE/'release'/NAME
    archive = target.parent/(target.name+'.zip')
    if target.exists() or archive.exists():
        raise FileExistsError('Release already exists; use a new version or build location.')
    work = BASE/'artifacts'/('windows-build-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
    work.mkdir(parents=True)
    version_info = work/'version.txt'
    version_info.write_text("""VSVersionInfo(
  ffi=FixedFileInfo(filevers=(0,8,0,0), prodvers=(0,8,0,0), mask=0x3f, flags=0x0,
    OS=0x40004, fileType=0x1, subtype=0x0, date=(0,0)),
  kids=[StringFileInfo([StringTable('080404B0', [
    StringStruct('FileDescription', '久留美 · 市场陪伴助手'),
    StringStruct('FileVersion', '0.8.0'), StringStruct('ProductVersion', '0.8.0'),
    StringStruct('ProductName', 'Kurumi Market Companion'),
    StringStruct('OriginalFilename', 'KurumiMarket.exe')])]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])])
""", encoding='utf-8')
    command = [sys.executable, '-m', 'PyInstaller', '--onedir', '--windowed',
               '--name', 'KurumiMarket', '--icon', str(BASE/'assets/kurumi.ico'),
               '--version-file', str(version_info), '--hidden-import', 'pystray._win32',
               '--collect-all', 'tzdata', '--distpath', str(work/'dist'),
               '--workpath', str(work/'work'), '--specpath', str(work), str(BASE/'app.py')]
    subprocess.run(command, cwd=BASE, check=True)
    shutil.copytree(work/'dist/KurumiMarket', target)
    for relative in ASSETS:
        out = target/'assets'/relative
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(BASE/'assets'/relative, out)
    guide = '''久留美 · 市场陪伴助手 v0.8.0 / Windows 64 位便携版

1. 将整个压缩包解压到一个可写入的文件夹。
2. 双击 KurumiMarket.exe，无需安装 Python；旧版如在运行，请先从托盘退出。
3. 不要单独移走 EXE；assets 和 _internal 文件夹需要一起保留。

使用：
“字号”：正文和气泡可分别拖动滑块，或输入 12–40 号数字。
“悬浮模式”：拖动人物移动，单击切换消息，双击回到面板。
气泡可查看全文、调整字号、固定展开；鼠标移入暂停收起。
“声音”：普通提示音为一声“叮”，也可选择内置 AI「チャンス！」语音。
“消息源”：财联社快讯、行情互动、刷新频率及可选 RSS。
关闭主面板会继续在托盘运行，退出请用托盘右键菜单。
Ctrl+Alt+K 显示/隐藏；Ctrl+Alt+M 打开面板。

配置与更新：
首次退出后在本文件夹生成 settings.json，保存个人自选和偏好。
导入的音频保存在 assets/audio/ 中。此压缩包不含开发者个人配置。
更新时解压到新文件夹，退出旧程序后可复制自己的 settings.json 与导入音频。
本版本不自动检查更新、不设置开机启动、不连接交易账户。
删除解压文件夹即可移除程序。

信息：
新闻与行情来自公开来源，需要联网，快照可能延迟。
A 股交易日历覆盖 2026 年；港股/美股覆盖 2026–2027 年。
系统适用范围：Windows 10/11，64 位；本机 Windows 环境已验证。
角色为同人形象，语音为 AI 合成，非官方应用。
第三方许可随包提供在 LICENSES 文件夹。
'''
    (target/'使用说明.txt').write_text(guide, encoding='utf-8-sig')
    licenses = target/'LICENSES'
    licenses.mkdir()
    versions = {}
    for package in ('pillow', 'pystray', 'six', 'tzdata', 'pyinstaller'):
        dist = metadata.distribution(package)
        versions[package] = dist.version
        for file in dist.files or []:
            if any(word in file.name.lower() for word in ('license', 'copying', 'notice')):
                source = Path(dist.locate_file(file))
                if source.is_file():
                    destination = licenses/(package+'-'+file.name)
                    if not destination.exists():
                        shutil.copy2(source, destination)
    python_license = Path(sys.base_prefix)/'LICENSE.txt'
    if python_license.exists():
        shutil.copy2(python_license, licenses/'Python-LICENSE.txt')
    for library in ('tcl8.6', 'tk8.6'):
        license_file = Path(sys.base_prefix)/'tcl'/library/'license.terms'
        if license_file.exists():
            shutil.copy2(license_file, licenses/(library+'-license.terms'))
    manifest = {'product': 'Kurumi Market Companion', 'version': VERSION,
                'platform': 'Windows x64', 'python': platform.python_version(),
                'dependencies': versions, 'personal_configuration_included': False,
                'assets': ASSETS}
    (target/'release.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as output:
        for file in sorted(target.rglob('*')):
            if file.is_file():
                output.write(file, str(Path(NAME)/file.relative_to(target)))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix('.zip.sha256').write_text(digest+'  '+archive.name+'\n', encoding='ascii')
    print(json.dumps({'archive': str(archive), 'bytes': archive.stat().st_size, 'sha256': digest}, ensure_ascii=False))

if __name__ == '__main__':
    main()

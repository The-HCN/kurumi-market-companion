"""Offline end-to-end diagnostics for the actual packaged executable."""
import copy
from datetime import datetime
import json
from pathlib import Path
import sys
import tempfile
import time
import traceback
from uuid import uuid4
from zoneinfo import ZoneInfo

from app_paths import BASE
from market_data import SHANGHAI
from market_status import market_session
from sound_engine import WinMCI

def run_check(Companion, SingleInstance, DesktopIntegration, report_path):
    import tkinter as tk
    report = dict(frozen=bool(getattr(sys, 'frozen', False)), base=str(BASE), checks=[], errors=[])
    root = app = guard = None
    success = False
    with tempfile.TemporaryDirectory(prefix='KurumiReleaseCheck-') as temporary:
        try:
            for relative in ['assets/kurumi.ico', 'assets/kurumi-sheet-v3.png', 'assets/market-calendar.json',
                             'assets/audio/normal.wav', 'assets/audio/chance-ai.wav']:
                assert (BASE/relative).is_file(), relative
            report['checks'].append('external_assets')
            assert ZoneInfo('America/New_York').key == 'America/New_York'
            assert market_session('A股', datetime(2026, 10, 1, 10, tzinfo=SHANGHAI)) == '休市'
            report['checks'].append('tzdata_and_offline_calendar')
            backend = WinMCI()
            try:
                report['audio_ms'] = {name: backend.play(BASE/'assets/audio'/name, 0)
                                      for name in ['normal.wav', 'chance-ai.wav']}
            finally:
                backend.stop()
            report['checks'].append('silent_native_audio_decode')
            root = tk.Tk()
            namespace = Companion.__init__.__globals__
            load = namespace['load_settings']
            settings = copy.deepcopy(namespace['DEFAULTS'])
            settings.update(cls_enabled=False, indices_enabled=False, muted=True, stocks=[], notification_mode='manual')
            namespace['load_settings'] = lambda path: settings
            try:
                app = Companion(root)
            finally:
                namespace['load_settings'] = load
            app.path = Path(temporary)/'settings.json'
            app.fetch_public_source = lambda name: None
            guard = SingleInstance('Kurumi.ReleaseCheck.'+uuid4().hex)
            assert guard.primary
            second = SingleInstance(guard.scope)
            assert not second.primary and guard.activated()
            second.close()
            report['checks'].append('single_instance_activation')
            app.desktop = DesktopIntegration(app, guard)
            started = time.monotonic()

            def finish():
                app.finish_typing()
                assert app.overlay.bubble_text.get('1.0', 'end-1c') == '这是便携版的界面验证消息。'
                assert app.overlay.source.get().startswith('演示')
                report['checks'].extend(['tk_and_pillow_sprites', 'font_slider_and_input', 'pet_and_bubble'])
                assert json.loads(app.path.read_text(encoding='utf-8'))['bubble_text_size'] == 24
                report['checks'].append('isolated_settings_persistence')
                app.close()

            def ready():
                if not app.desktop.ready:
                    if time.monotonic()-started > 7:
                        raise RuntimeError('Tray unavailable: '+getattr(app.desktop, 'error', 'timeout'))
                    root.after(100, ready)
                    return
                report['checks'].append('windows_tray')
                app.configure_fonts()
                app.font_controls['news']['value'].set('22')
                app.font_controls['news']['commit']()
                app.font_controls['bubble']['value'].set('24')
                app.font_controls['bubble']['commit']()
                app.font_dialog.destroy()
                app.show_compact()
                app.speak(dict(title='这是便携版的界面验证消息。', source='发布验证', demo=True,
                               received='10-17 12:00:00', published='演示场景', url=''), manual=True)
                root.after(550, finish)

            def callback_error(kind, value, tb):
                report['errors'].append(''.join(traceback.format_exception(kind, value, tb)))
                try:
                    app.close()
                except Exception:
                    root.destroy()
            root.report_callback_exception = callback_error
            root.after(100, ready)
            root.mainloop()
            success = not report['errors'] and 'isolated_settings_persistence' in report['checks']
        except Exception:
            report['errors'].append(traceback.format_exc())
            if app is not None:
                try:
                    app.close()
                except Exception:
                    pass
            elif root is not None:
                root.destroy()
        finally:
            if guard is not None:
                guard.close()
    report['success'] = success
    Path(report_path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if success else 1

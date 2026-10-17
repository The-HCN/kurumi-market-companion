"""Windows integration QA for tray, activation, policy and reversible transitions."""
import ctypes
import json
from pathlib import Path
import subprocess
import sys
import time
import tkinter as tk
import traceback
from unittest.mock import patch
from uuid import uuid4
from app import Companion, DEFAULTS
from desktop import DesktopIntegration, SingleInstance
from PIL import ImageGrab

scope = 'Kurumi.DesktopQA.'+uuid4().hex
guard = SingleInstance(scope)
root = tk.Tk()
settings = json.loads(json.dumps(DEFAULTS))
settings.update(cls_enabled=False, indices_enabled=False, stocks=[], typewriter_ms=42)
with patch('app.load_settings', return_value=settings):
    app = Companion(root)
Path('artifacts').mkdir(exist_ok=True)
app.path = Path('artifacts/desktop-qa-settings.json')
app.fetch_public_source = lambda name: None
app.desktop = DesktopIntegration(app, guard)
errors = []
started = time.monotonic()
user = ctypes.WinDLL('user32', use_last_error=True)
user.GetForegroundWindow.restype = ctypes.c_void_p

def cleanup():
    app.desktop.close()
    guard.close()
    root.destroy()

def fail(exc_type, exc, tb):
    errors.append(''.join(traceback.format_exception(exc_type, exc, tb)))
    cleanup()
root.report_callback_exception = fail

def wait_ready():
    if app.desktop.ready and getattr(app.desktop, 'hotkeys_ready', False):
        assert app.desktop.tray.visible
        print('Tray visible; hotkeys registered:', app.desktop.hotkeys)
        app.on_window_close()
        assert app.assistant_hidden and root.state() == 'withdrawn'
        code = "from desktop import SingleInstance; g=SingleInstance("+repr(scope)+"); assert not g.primary; print('Existing instance signalled')"
        child = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True,
                               timeout=4, creationflags=subprocess.CREATE_NO_WINDOW)
        assert child.returncode == 0, child.stderr
        root.after(300, check_activation)
    elif time.monotonic()-started > 8:
        raise AssertionError('Tray failed: '+getattr(app.desktop, 'error', 'not ready'))
    else:
        root.after(100, wait_ready)

def check_activation():
    assert not app.assistant_hidden and root.state() == 'normal'
    app.desktop.tray()  # Invoke the same default callback used by a tray click.
    app.set_notification_mode('important')
    regular = dict(id='regular', title='普通快讯', source='测试源', demo=False)
    important = dict(regular, id='important', important=True)
    app.enqueue_news([regular, important])
    assert [n['id'] for n in app.pending] == ['important']
    app.set_notification_mode('manual')
    app.enqueue_news([important])
    assert not app.pending
    user.PostThreadMessageW(app.desktop.hotkey_thread_id, 0x0312, 1, 0)
    root.after(250, check_hotkey_hide)

def check_hotkey_hide():
    assert app.assistant_hidden
    user.PostThreadMessageW(app.desktop.hotkey_thread_id, 0x0312, 2, 0)
    root.after(250, check_hotkey_restore)

def check_hotkey_restore():
    assert not app.assistant_hidden and root.state() == 'normal'
    app.show_compact()
    app.overlay.hide_bubble(immediate=True)
    global sentinel, foreground
    sentinel = tk.Toplevel(root)
    sentinel.title('久留美 · 焦点验证')
    sentinel.geometry('300x100+50+80')
    tk.Label(sentinel, text='自动气泡不应抢走这个窗口的焦点。').pack(pady=25)
    sentinel.focus_force()
    root.update()
    foreground = user.GetForegroundWindow()
    app.demo_reaction('happy')
    assert float(app.overlay.bubble.attributes('-alpha')) < .1
    assert app.overlay.animator.job is not None
    root.after(65, check_mid_animation)

def check_mid_animation():
    alpha = float(app.overlay.bubble.attributes('-alpha'))
    print('Mid-transition opacity:', round(alpha, 3))
    assert 0 < alpha < 1
    root.after(240, check_full_animation)

def check_full_animation():
    bubble = app.overlay.bubble
    assert float(bubble.attributes('-alpha')) >= .99
    assert bubble.winfo_y() == app.overlay.bubble_target[1]
    assert user.GetForegroundWindow() == foreground, 'Bubble stole keyboard focus'
    x, y = bubble.winfo_rootx(), bubble.winfo_rooty()
    ImageGrab.grab(bbox=(x, y, x+bubble.winfo_width(), y+bubble.winfo_height())).save('artifacts/v4-bubble.png')
    app.overlay.hide_bubble()
    root.after(55, reverse_animation)

def reverse_animation():
    alpha = float(app.overlay.bubble.attributes('-alpha'))
    assert 0 < alpha < 1
    app.overlay.show_bubble()
    assert float(app.overlay.bubble.attributes('-alpha')) > 0  # No flash to zero.
    root.after(300, check_reversal)

def check_reversal():
    assert app.overlay.bubble.state() == 'normal'
    assert float(app.overlay.bubble.attributes('-alpha')) >= .99
    app.hide_assistant()
    assert app.overlay.bubble.state() == 'withdrawn'
    root.after(300, finish)

def finish():
    assert app.overlay.bubble.state() == 'withdrawn'
    assert app.overlay.animator.job is None
    app.restore()
    sentinel.destroy()
    root.update()
    x, y = root.winfo_rootx(), root.winfo_rooty()
    ImageGrab.grab(bbox=(x, y, x+root.winfo_width(), y+root.winfo_height())).save('artifacts/v4-panel.png')
    cleanup()

root.after(100, wait_ready)
root.mainloop()
if errors:
    raise RuntimeError('\n'.join(errors))
print('Desktop QA passed: tray, duplicate launch, hotkey dispatch, three modes, animation opacity/position, focus, reversal and cancellation.')

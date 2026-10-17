"""Review bubble readability, hover/pin behavior, full text, and screen bounds."""
import json
from pathlib import Path
import tkinter as tk
import traceback
from unittest.mock import patch
from PIL import ImageGrab
from app import Companion, DEFAULTS

root = tk.Tk()
settings = json.loads(json.dumps(DEFAULTS))
settings.update(cls_enabled=False, indices_enabled=False, muted=True)
with patch('app.load_settings', return_value=settings):
    app = Companion(root)
app.path = Path('artifacts/overlay-review-settings.json')
app.fetch_public_source = lambda name: None
errors = []
def fail(kind, value, tb):
    errors.append(''.join(traceback.format_exception(kind, value, tb)))
    root.destroy()
root.report_callback_exception = fail

def capture(win, name):
    x, y = win.winfo_rootx(), win.winfo_rooty()
    ImageGrab.grab(bbox=(x, y, x+win.winfo_width(), y+win.winfo_height())).save('artifacts/'+name+'.png')

def start():
    app.show_compact()
    app.overlay.pointer_inside = lambda: False
    app.speak(dict(title='这是一条短消息，久留美提醒你查看市场动态。', content='这是完整的消息内容。'*30,
                   source='界面验证', demo=True, received='10-17 12:00:00', published='演示场景', url=''), manual=True)
    app.finish_typing()
    root.after(400, short_message)

def short_message():
    ov = app.overlay
    assert '【' not in ov.bubble_text.get('1.0', 'end-1c')
    assert '界面验证' in ov.source.get()
    assert ov.hide_job is not None and ov.countdown_job is not None
    last = ov.bubble_text.bbox('end-2c')
    assert last and last[1]+last[3] <= ov.bubble_text.winfo_height()-6, (last, ov.bubble_text.winfo_height())
    ov.pin_button.invoke()
    assert ov.hide_job is None and ov.countdown_job is None
    assert not app.settings['bubble_autohide']
    root.after(150, pin_shown)

def pin_shown():
    ov = app.overlay
    capture(ov.bubble, 'v8-bubble-short')
    ov.pin_button.invoke()
    ov.pointer_inside = lambda: True
    ov.end_speech()
    assert ov.hide_job is None and ov.status.get() == '正在阅读'
    ov.pointer_inside = lambda: False
    ov.end_speech()
    assert ov.hide_job is not None
    before = set(root.winfo_children())
    ov.detail_button.invoke()
    root.update()
    added = [w for w in root.winfo_children() if w not in before and isinstance(w, tk.Toplevel)]
    assert len(added) == 1 and added[0].winfo_viewable()
    assert '市场快讯' in added[0].title()
    added[0].destroy()
    app.apply_font_sizes(bubble='extra')
    app.speak(dict(title='这是超大字体的长消息，检查换行和滚动阅读体验。'*8,
                   source='界面验证', demo=True, received='10-17 12:00:00'), manual=True)
    app.finish_typing()
    root.after(400, long_message)

def long_message():
    ov = app.overlay
    ov.bubble_text.yview_moveto(0)
    capture(ov.bubble, 'v8-bubble-large')
    left, top, right, bottom = ov.workarea()
    for x, y in [(left, top), (right-ov.size, top), (right-ov.size, bottom-ov.size-44)]:
        ov.pet.geometry(f'+{x}+{y}')
        root.update_idletasks()
        ov.position_bubble()
        root.update_idletasks()
        assert left <= ov.bubble.winfo_x() <= right-ov.bubble.winfo_width()
        assert top <= ov.bubble.winfo_y() <= bottom-ov.bubble.winfo_height()
    ov.resize(200, save=False)
    ov.show_toolbar()
    root.update_idletasks()
    assert all(w.winfo_x()+w.winfo_width() <= 200 for w in ov.toolbar.winfo_children())
    ov.hide_bubble(immediate=True)
    assert ov.hide_job is None and ov.countdown_job is None
    app.audio.close()
    root.destroy()

root.after(300, start)
root.mainloop()
if errors:
    raise RuntimeError('\n'.join(errors))
print('Overlay passed: separated metadata, short/long layout, pin, hover pause, countdown cancellation, full text, corners, small toolbar.')

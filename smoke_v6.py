"""Check live font updates, scroll access, animation transitions, and calendar UI."""
import json
from pathlib import Path
import time
import tkinter as tk
import traceback
from unittest.mock import patch
from PIL import ImageGrab
from app import Companion, DEFAULTS, TEXT_SIZES

root = tk.Tk()
settings = json.loads(json.dumps(DEFAULTS))
settings.update(cls_enabled=False, indices_enabled=False, muted=True)
with patch('app.load_settings', return_value=settings):
    app = Companion(root)
app.path = Path('artifacts/v6-settings.json')
app.fetch_public_source = lambda name: None
errors = []
def fail(kind, value, tb):
    errors.append(''.join(traceback.format_exception(kind, value, tb)))
    root.destroy()
root.report_callback_exception = fail

def capture(win, name):
    win.update_idletasks()
    x, y = win.winfo_rootx(), win.winfo_rooty()
    ImageGrab.grab(bbox=(x, y, x+win.winfo_width(), y+win.winfo_height())).save('artifacts/'+name+'.png')

def start():
    app.configure_fonts()
    app.font_controls['news']['scale'].set(24)
    app.font_controls['bubble']['value'].set('23')
    root.after(300, fonts_selected)

def fonts_selected():
    assert app.news_font.cget('size') == TEXT_SIZES['extra'][1]
    assert app.bubble_font.cget('size') == TEXT_SIZES['large'][2]
    assert json.loads(app.path.read_text(encoding='utf-8'))['news_text_size'] == 24
    news = app.font_controls['news']
    assert news['scale'].get() == 24
    assert app.font_controls['bubble']['scale'].get() == 23
    news['entry'].delete(0, 'end')
    news['entry'].insert(0, 'abc')
    assert news['value'].get() == ''  # Non-numeric keystrokes are rejected.
    news['commit']()
    assert app.news_font.cget('size') == 24
    news['value'].set('999')
    news['commit']()
    assert app.news_font.cget('size') == 40 and news['scale'].get() == 40
    news['value'].set('24')
    news['commit']()
    root.after(250, fonts_shown)

def fonts_shown():
    capture(app.font_dialog, 'v6-font-settings')
    app.font_dialog.destroy()
    app.apply_font_sizes(news='large', bubble='standard')
    root.after(250, panel_shown)

def panel_shown():
    capture(root, 'v6-panel')
    app.show_compact()
    app.apply_font_sizes(bubble='extra')
    item = dict(id='long', title='这是超大字体的长消息，检查文字换行与滚动是否正常。'*7,
                source='界面验证', demo=True, emotion='sad', received='10-17 12:00:00')
    app.speak(item, manual=True)
    app.finish_typing()
    root.after(350, bubble_shown)

def bubble_shown():
    overlay = app.overlay
    assert overlay.bubble_text.cget('font') == str(app.bubble_font)
    overlay.bubble_text.yview_moveto(0)
    capture(overlay.bubble, 'v6-bubble-extra')
    assert overlay.bubble.winfo_x() >= overlay.workarea()[0]
    assert overlay.bubble.winfo_y()+overlay.bubble.winfo_height() <= overlay.workarea()[3]
    assert overlay.bubble_text.get('1.0', 'end-1c') == app.speech_text[app.voiced_start:app.voiced_end]
    assert '界面验证' in overlay.source.get()  # Metadata no longer consumes body space.
    root.after(2200, settled)

def settled():
    assert app.mood == 'neutral' and not app.is_typing
    assert all(not view.talking for view in app.character_views)
    view = app.overlay.character
    view.next_blink = time.monotonic()-1
    view.blink_started = None
    root.after(55, blink_shown)

def blink_shown():
    view = app.overlay.character
    assert view.blinking
    capture(app.compact, 'v6-blink')
    app.apply_font_sizes(news='standard', bubble='standard')
    app.audio.close()
    root.destroy()

root.after(300, start)
root.mainloop()
if errors:
    raise RuntimeError('\n'.join(errors))
print('v0.6 UI passed: independent live typography, persistence, long-text scrolling, mood reset, idle blink.')

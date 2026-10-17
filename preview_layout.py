"""Review real data at minimum size, with large fonts and all market filters."""
from pathlib import Path
import time
import tkinter as tk
import traceback
from PIL import ImageGrab
from app import Companion

root = tk.Tk()
app = Companion(root)
app.path = Path('artifacts/layout-review-settings.json')
app.settings.update(muted=True, cls_enabled=True, indices_enabled=True)
errors = []
started = time.monotonic()
def fail(kind, value, tb):
    errors.append(''.join(traceback.format_exception(kind, value, tb)))
    root.destroy()
root.report_callback_exception = fail

def capture(name):
    x, y = root.winfo_rootx(), root.winfo_rooty()
    ImageGrab.grab(bbox=(x, y, x+root.winfo_width(), y+root.winfo_height())).save('artifacts/'+name+'.png')

def loaded():
    if app.indices and app.stock_quotes and any(n['source'] == '财联社电报' for n in app.news):
        app.pending.clear()
        app.speak(next(n for n in app.news if n['source'] == '财联社电报'), manual=True)
        app.finish_typing()
        root.geometry('1380x920')
        app.apply_font_sizes(news='extra', bubble='extra')
        app.filter_market('港股')
        root.after(900, minimum)
    elif time.monotonic()-started > 40:
        raise RuntimeError('Real data timeout: '+str(app.source_status))
    else:
        root.after(300, loaded)

def minimum():
    visible = [v for v in app.index_cards.values() if v['frame'].winfo_ismapped()]
    assert len(visible) == 1
    assert visible[0]['frame'].winfo_width() > app.index_grid.winfo_width()*.9
    assert app.sound_button.winfo_rootx() >= root.winfo_rootx()
    capture('v8-minimum-large-font')
    app.filter_market('美股')
    root.after(250, us_market)

def us_market():
    assert len([v for v in app.index_cards.values() if v['frame'].winfo_ismapped()]) == 2
    root.geometry('1540x1020')
    app.apply_font_sizes(news='standard', bubble='standard')
    app.filter_market('全部')
    root.after(900, finish)

def finish():
    assert len([v for v in app.index_cards.values() if v['frame'].winfo_ismapped()]) == 4
    capture('v8-live')
    app.audio.close()
    root.destroy()

root.after(1000, loaded)
root.mainloop()
if errors:
    raise RuntimeError('\n'.join(errors))
print('Layout review passed: live sources, minimum window, largest fonts, HK / US / all index layouts.')

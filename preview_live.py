"""Verify live adapters inside the UI and capture a reviewable window."""
from pathlib import Path
import time
import traceback
import tkinter as tk
from PIL import ImageGrab
from app import Companion

root = tk.Tk()
app = Companion(root)
app.path = Path('artifacts/preview-settings.json')
# Review doesn't change user preferences and always exercises enabled sources.
app.settings.update(cls_enabled=True, indices_enabled=True)
errors = []
start = time.monotonic()

def fail(exc_type, exc, tb):
    errors.append(''.join(traceback.format_exception(exc_type, exc, tb)))
    root.destroy()
root.report_callback_exception = fail

def capture():
    root.update()
    Path('artifacts').mkdir(exist_ok=True)
    x, y = root.winfo_rootx(), root.winfo_rooty()
    ImageGrab.grab(bbox=(x, y, x+root.winfo_width(), y+root.winfo_height())).save('artifacts/v3-live.png')
    print('Live UI:', len([n for n in app.news if n['source'] == '财联社电报']), 'CLS headlines;', len(app.indices), 'indices;', len(app.stock_quotes), 'stock quotes')
    root.destroy()

def check():
    if getattr(app, 'cls_initialized', False) and app.indices and app.stock_quotes and not app.source_busy:
        app.pending.clear()
        item = next(n for n in app.news if n['source'] == '财联社电报')
        app.speak(item, manual=True)
        app.finish_typing()
        root.after(300, capture)
    elif time.monotonic() - start > 40:
        errors.append('Live load timed out: ' + str(app.source_status))
        root.destroy()
    else:
        root.after(400, check)

root.after(1000, check)
root.mainloop()
if errors:
    raise RuntimeError('\n'.join(errors))

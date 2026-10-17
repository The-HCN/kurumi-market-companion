"""Verify rendered mouth changes at both slow and fast typewriter settings."""
import json
from pathlib import Path
import time
import tkinter as tk
import traceback
from unittest.mock import patch
from app import Companion, DEFAULTS

root = tk.Tk()
settings = json.loads(json.dumps(DEFAULTS))
settings.update(cls_enabled=False, indices_enabled=False, muted=True)
with patch('app.load_settings', return_value=settings):
    app = Companion(root)
app.path = Path('artifacts/mouth-qa-settings.json')
app.fetch_public_source = lambda name: None
errors, counts = [], []
def fail(kind, value, tb):
    errors.append(''.join(traceback.format_exception(kind, value, tb)))
    root.destroy()
root.report_callback_exception = fail

def start(speed):
    app.settings['typewriter_ms'] = speed
    app.speak(dict(title='机会来了保持关注市场变化'*10, source='界面验证', demo=True,
                   received='10-17 12:00:00', emotion='neutral'), manual=True)
    # Skip the heading, then let the normal typewriter run.
    root.after_cancel(app.type_job)
    app.speech_position = app.voiced_start
    app.type_next()
    frames = []
    started = time.monotonic()
    def sample():
        frames.append(app.character_views[-1].mouth_open)
        if time.monotonic()-started < 1.8:
            root.after(20, sample)
        else:
            changes = sum(a != b for a, b in zip(frames, frames[1:]))
            assert changes >= 10, (speed, changes)
            counts.append((speed, changes))
            app.finish_typing()
            assert not app.speech_motion.running
            assert all(not view.mouth_open for view in app.character_views)
            if speed == 100:
                app.show_compact()
                assert app.overlay.character.speech_motion is app.speech_motion
                root.after(300, lambda: start(20))
            else:
                app.audio.close()
                root.destroy()
    root.after(40, sample)

root.after(300, lambda: start(100))
root.mainloop()
if errors:
    raise RuntimeError('\n'.join(errors))
print('Rendered mouth transitions passed:', counts, '; immediate stop and shared panel/pet timing passed.')

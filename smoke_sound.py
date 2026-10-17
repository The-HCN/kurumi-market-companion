"""No-audio window QA; original voice content is never fabricated."""
from pathlib import Path
import json
import tkinter as tk
import traceback
from unittest.mock import patch
from PIL import ImageGrab
from app import Companion, DEFAULTS, BASE
from sound_engine import build_chime


class RecordingAudio:
    def __init__(self):
        self.requests = []
        self.stops = 0
    def play(self, settings, preview=False):
        self.requests.append((dict(settings), preview))
        return True
    def stop(self):
        self.stops += 1
    def close(self):
        pass


root = tk.Tk()
settings = json.loads(json.dumps(DEFAULTS))
settings.update(cls_enabled=False, indices_enabled=False, stocks=[])
with patch('app.load_settings', return_value=settings):
    app = Companion(root)
Path('artifacts').mkdir(exist_ok=True)
app.path = Path('artifacts/sound-qa-settings.json')
app.fetch_public_source = lambda name: None
app.audio.close()
app.audio = RecordingAudio()
errors = []

def fail(kind, value, tb):
    errors.append(''.join(traceback.format_exception(kind, value, tb)))
    root.destroy()
root.report_callback_exception = fail

def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)

def button(text):
    return next(w for w in descendants(app.sound_dialog) if isinstance(w, tk.Button) and w.cget('text') == text)

def check_dialog():
    app.configure_sound()
    root.update()
    root.after(400, check_controls)

def check_controls():
    win = app.sound_dialog
    x, y = win.winfo_rootx(), win.winfo_rooty()
    ImageGrab.grab(bbox=(x, y, x+win.winfo_width(), y+win.winfo_height())).save('artifacts/v5-sound-settings.png')
    button('▶ 试听').invoke()
    assert app.audio.requests[-1][1] is True
    assert app.audio.requests[-1][0]['sound_mode'] == 'normal'
    button('使用 AI「チャンス！」').invoke()
    button('▶ 试听').invoke()
    assert app.audio.requests[-1][0]['sound_mode'] == 'voice'
    assert app.audio.requests[-1][0]['voice_file'].endswith('chance-ai.wav')
    example = BASE/'artifacts'/'qa-import-only.wav'
    build_chime(example)
    # Simulate choosing a user clip, without copying test audio into production assets.
    with patch('app.filedialog.askopenfilename', return_value=str(example)), patch('app.import_voice', return_value=example):
        button('导入久留美音频…').invoke()
    scale = next(w for w in descendants(win) if isinstance(w, tk.Scale))
    scale.set(37)
    button('▶ 试听').invoke()
    assert app.audio.requests[-1][0]['sound_mode'] == 'voice'
    assert app.audio.requests[-1][0]['sound_volume'] == 37
    button('保存').invoke()
    assert app.settings['voice_file'].endswith('qa-import-only.wav')
    assert app.settings['sound_mode'] == 'voice'
    assert '久留美' in app.sound_button.cget('text')
    item = dict(id='sound-test', title='一条测试消息', source='测试源', demo=True, received='10-15 12:00:00')
    count = len(app.audio.requests)
    app.speak(item, manual=True)
    assert len(app.audio.requests) == count  # Manual reading stays quiet.
    app.speak(item, manual=False)
    assert len(app.audio.requests) == count+1
    app.toggle_mute()
    stops = app.audio.stops
    app.speak(item, manual=False)
    assert len(app.audio.requests) == count+1 and stops > 0
    app.settings['muted'] = False
    app.set_notification_mode('manual')
    app.speak(item, manual=False)
    assert len(app.audio.requests) == count+1
    root.destroy()

root.after(300, check_dialog)
root.mainloop()
if errors:
    raise RuntimeError('\n'.join(errors))
print('Sound UI passed: preview, imported clip selection, volume, persistence, automatic-only sound, pause and manual mode.')

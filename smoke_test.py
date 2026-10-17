"""Deterministic window checks. Captures only the application's own window."""
from pathlib import Path
import json
import tkinter as tk
import traceback
from unittest.mock import patch
from PIL import ImageGrab
from app import Companion, DEFAULTS
from market_data import SHANGHAI, stock_key
from datetime import datetime, timedelta

root = tk.Tk()
settings = json.loads(json.dumps(DEFAULTS))
settings.update(cls_enabled=False, indices_enabled=False, typewriter_ms=42)
with patch('app.load_settings', return_value=settings):
    app = Companion(root)
Path('artifacts').mkdir(exist_ok=True)
app.path = Path('artifacts/smoke-settings.json')
app.fetch_public_source = lambda name: None
errors = []

def fail(exc_type, exc, tb):
    errors.append(''.join(traceback.format_exception(exc_type, exc, tb)))
    root.destroy()
root.report_callback_exception = fail
root.update()
assert len(app.news) == 3
app.filter_market('港股')
app.add_demo()
assert app.news[0]['market'] == '港股'
assert not app.add_news(dict(app.news[0]))
app.filter_market('全部')
app.toggle_mute()
app.add_demo()
assert not app.pending
app.toggle_mute()
stock = app.settings['stocks'][0]
key = stock['market'] + ':' + stock['symbol']
old = stock['price']
app.settings['alerts'][key] = dict(target=old+1, direction='above')
stock['price'] += 2
app.check_alert(stock, old)
assert key not in app.settings['alerts']
assert '模拟到价' in app.news[0]['title']

# First snapshot announces only the latest item; failures keep old headlines.
app.settings['cls_enabled'] = True
records = [dict(id='test-real-'+str(i), title='公开快讯测试：市场上涨', source='测试源',
                published='10-15 12:00', demo=False, market='全部', url='') for i in range(3)]
app.pending.clear()
app.receive_public('cls', records, None)
assert len(app.pending) == 1 and app.pending[0]['id'] == 'test-real-0'
count = len(app.news)
app.receive_public('cls', None, '测试网络故障')
assert len(app.news) == count and '未更新' in app.feed_status.cget('text')
app.pending.clear()
stock = app.settings['stocks'][0]
key = stock_key(stock)
app.settings['alerts'][key] = dict(target=100, direction='above', mode='live')
old_quote = dict(key=key, market=stock['market'], symbol=stock['symbol'], name=stock['name'],
                 timestamp=(datetime.now(SHANGHAI)-timedelta(days=1)).strftime('%Y%m%d%H%M%S'),
                 price=105, base=99, change=6, source='测试行情', demo=False)
app.receive_stocks([old_quote])
assert key in app.settings['alerts']  # Yesterday's quote cannot fire a real alert.
fresh_quote = dict(old_quote, timestamp=datetime.now(SHANGHAI).strftime('%Y%m%d%H%M%S'))
app.receive_stocks([fresh_quote])
assert key not in app.settings['alerts']
assert not app.news[0]['demo'] and '到价' in app.news[0]['title']
app.pending.clear()
app.demo_reaction('happy')
assert app.is_typing and len(app.bubble.get()) == 1
assert app.character_views[0].talking

def capture(window, filename):
    window.update()
    x, y = window.winfo_rootx(), window.winfo_rooty()
    ImageGrab.grab(bbox=(x, y, x+window.winfo_width(), y+window.winfo_height())).save(filename)

def check_partial():
    assert 1 < len(app.bubble.get()) < len(app.speech_text)
    assert app.character_views[0].talking and app.mood == 'happy'
    capture(root, 'artifacts/v3-typing.png')
    app.demo_reaction('sad')
    assert app.speech_position == 1 and app.mood == 'sad'
    root.after(300, check_interruption)

def check_interruption():
    assert app.is_typing and app.mood == 'sad'
    app.finish_typing()
    assert not app.is_typing and app.bubble.get() == app.speech_text
    assert not app.character_views[0].talking
    app.show_compact()
    assert app.compact_bubble is app.bubble
    app.overlay.hide_bubble(immediate=True)
    assert app.overlay.bubble.state() == 'withdrawn' and app.compact.state() == 'normal'
    app.overlay.toggle_bubble()
    assert app.overlay.bubble.state() == 'normal'
    app.settings['bubble_autoshow'] = False
    app.overlay.hide_bubble(immediate=True)
    app.overlay.start_speech()
    assert app.overlay.bubble.state() == 'withdrawn'
    app.settings['bubble_autoshow'] = True
    app.demo_reaction('happy')
    assert all(view.talking and view.mood == 'happy' for view in app.character_views)
    root.after(600, capture_compact)

def capture_compact():
    app.finish_typing()
    capture(app.compact, 'artifacts/v3-companion.png')
    capture(app.overlay.bubble, 'artifacts/v3-bubble.png')
    assert app.overlay.hide_job is not None
    root.after(8300, check_autohide)

def check_autohide():
    assert app.overlay.bubble.state() == 'withdrawn'
    assert app.compact.state() == 'normal'
    app.restore()
    assert app.overlay.bubble.state() == 'withdrawn'
    app.settings['cls_enabled'] = False
    app.demo_reaction('sad')
    app.finish_typing()
    root.after(300, capture_panel)

def capture_panel():
    capture(root, 'artifacts/v3-panel.png')
    app.settings['stocks'][0]['price'] = old
    app.save()
    root.destroy()

root.after(700, check_partial)
root.mainloop()
if errors:
    raise RuntimeError('\n'.join(errors))
print('UI passed: dedup, mute, alerts, source ingestion/failure, incremental text, interruption, mouth states, smile/cry, compact sync.')

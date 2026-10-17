"""Kurumi Market Companion — local Windows prototype, no model API required."""
from __future__ import annotations

import json
import math
import ctypes
import queue
import threading
import time
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, simpledialog, filedialog
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import webbrowser
import xml.etree.ElementTree as ET
from uuid import uuid4

from character import CharacterView
from notifications import MODES, should_announce
from sound_engine import AudioPlayer, SOUND_MODES, import_voice
from market_status import market_session, quote_status
from speech_motion import SpeechMotion
from app_paths import BASE
from market_data import (fetch_cls, fetch_indices, fetch_stock_quotes, emotion_for, quote_reaction,
                         bubble_text, stock_key, quote_code, quote_is_fresh, quote_datetime, queued_news)

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except (AttributeError, OSError):
    pass

try:
    # Give this application its own taskbar group instead of Python's identity.
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('Kurumi.MarketCompanion.Desktop')
except (AttributeError, OSError):
    pass

BG, CARD, PANEL = '#11121b', '#1c1e2b', '#252737'
TEXT, MUTED, PINK, RED, GREEN = '#f7f3fa', '#c1c3d3', '#f3a6c6', '#ff7b92', '#69d9b1'
MARKETS = ['全部', 'A股', '港股', '美股']
TEXT_SIZES = {'standard': ('标准', 18, 20), 'large': ('大号', 21, 23), 'extra': ('超大号', 24, 26)}
FONT_MIN, FONT_MAX = 12, 40

def font_size(value, role):
    if isinstance(value, str) and value in TEXT_SIZES:
        value = TEXT_SIZES[value][1 if role == 'news' else 2]
    elif isinstance(value, str) and value.isascii() and value.isdigit():
        value = int(value)
    if type(value) is not int:
        return 18 if role == 'news' else 20
    return max(FONT_MIN, min(FONT_MAX, value))

DEFAULTS = {
    'muted': False, 'topmost': False, 'rss': '', 'cls_enabled': True,
    'indices_enabled': True, 'typewriter_ms': 42, 'refresh_seconds': 30,
    'bubble_autohide': True, 'bubble_autoshow': True, 'pet_size': 260, 'pet_position': [],
    'notification_mode': 'all',
    'news_text_size': 18, 'bubble_text_size': 20,
    'sound_mode': 'normal', 'sound_volume': 60, 'voice_file': '', 'voice_name': '',
    'stocks': [
        {'symbol': '600519', 'name': '贵州茅台', 'market': 'A股', 'price': 1500.0, 'base': 1480.0},
        {'symbol': '300750', 'name': '宁德时代', 'market': 'A股', 'price': 250.0, 'base': 253.0},
        {'symbol': '00700', 'name': '腾讯控股', 'market': '港股', 'price': 420.0, 'base': 415.0},
        {'symbol': '09988', 'name': '阿里巴巴', 'market': '港股', 'price': 100.0, 'base': 102.0},
        {'symbol': 'NVDA', 'name': '英伟达', 'market': '美股', 'price': 180.0, 'base': 175.0},
        {'symbol': 'AAPL', 'name': '苹果', 'market': '美股', 'price': 230.0, 'base': 232.0},
    ], 'alerts': {},
}


def safe_url(url):
    p = urlparse(url)
    return p.scheme in ('https', 'http') and bool(p.hostname) and not p.username


def parse_feed(data):
    """Accept RSS 2 and Atom; all feed content stays plain text."""
    root = ET.fromstring(data)
    records = []
    for item in root.iter():
        if item.tag.rsplit('}', 1)[-1] not in ('item', 'entry'):
            continue
        fields = {}
        link = ''
        for child in item:
            key = child.tag.rsplit('}', 1)[-1]
            fields[key] = ''.join(child.itertext()).strip()
            if key == 'link' and (not child.attrib.get('rel') or child.attrib['rel'] == 'alternate'):
                link = child.attrib.get('href') or fields[key]
        title = fields.get('title', '')[:500]
        if not title:
            continue
        records.append({'id': fields.get('guid') or fields.get('id') or link or title,
                        'title': title, 'url': link if safe_url(link) else '',
                        'published': fields.get('pubDate') or fields.get('published') or fields.get('updated') or '来源未提供',
                        'market': '全部', 'source': 'RSS · ' + (urlparse(link).hostname or '订阅源'),
                        'demo': False})
    return records[:80]


def crossed(previous, current, target, direction):
    return previous < target <= current if direction == 'above' else previous > target >= current


def load_settings(path):
    settings = json.loads(json.dumps(DEFAULTS))
    try:
        saved = json.loads(path.read_text(encoding='utf-8'))
        for key in settings:
            if key in saved and isinstance(saved[key], type(settings[key])):
                settings[key] = saved[key]
        for stock in settings['stocks']:
            if stock['market'] not in MARKETS[1:] or float(stock['price']) <= 0 or float(stock['base']) <= 0:
                raise ValueError('Invalid stock')
        settings['typewriter_ms'] = max(20, min(100, settings['typewriter_ms']))
        if settings['refresh_seconds'] not in (15, 30, 60):
            settings['refresh_seconds'] = 30
        if settings['pet_size'] not in (200, 260, 320):
            settings['pet_size'] = 260
        if settings['notification_mode'] not in MODES:
            settings['notification_mode'] = 'all'
        if settings['sound_mode'] not in SOUND_MODES:
            settings['sound_mode'] = 'normal'
        settings['sound_volume'] = max(0, min(100, settings['sound_volume']))
        for key, role in (('news_text_size', 'news'), ('bubble_text_size', 'bubble')):
            settings[key] = font_size(saved.get(key, settings[key]), role)
    except (OSError, ValueError, KeyError, TypeError):
        return json.loads(json.dumps(DEFAULTS))
    return settings


class Companion:
    def __init__(self, root):
        self.root = root
        icon = BASE / 'assets' / 'kurumi.ico'
        if icon.exists():
            root.iconbitmap(str(icon))
            root.iconbitmap(default=str(icon))
        root.tk.call('tk', 'scaling', 4 / 3)
        self.path = BASE / 'settings.json'
        self.settings = load_settings(self.path)
        self.news_font = tkfont.Font(root=root, family='Microsoft YaHei UI', size=self.settings['news_text_size'])
        self.bubble_font = tkfont.Font(root=root, family='Microsoft YaHei UI', size=self.settings['bubble_text_size'])
        self.reaction_job = None
        self.speech_motion = SpeechMotion()
        self.market = '全部'
        self.news = []
        self.seen = set()
        self.inbox = queue.Queue()
        self.audio = AudioPlayer(BASE, report=lambda message: self.inbox.put(('sound', message)))
        self.last_sound_status = '可选择普通提示音，或导入久留美音频片段。'
        self.counter = 0
        self.compact = None
        self.pending = []
        self.rss_busy = False
        self.source_busy = set()
        self.source_status = {}
        self.indices = []
        self.stock_quotes = {}
        self.quote_issues = {}
        self.source_failures = {}
        self.source_retry_at = {}
        self.last_reaction = {}
        self.character_views = []
        self.is_typing = False
        self.type_job = None
        self.speech_token = 0
        self.current_item = None
        self.mood = 'neutral'
        self.desktop = None
        self.assistant_hidden = False
        self.resume_compact = False
        self.hidden_dialogs = []
        self.hotkey_warnings = []
        root.title('久留美 · 市场陪伴助手 v0.8')
        root.geometry('1540x1020')
        root.minsize(1380, 920)
        root.configure(bg=BG)
        root.option_add('*Font', ('Microsoft YaHei UI', 16))
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('Kurumi.Vertical.TScrollbar', background=PANEL, troughcolor=CARD,
                        bordercolor=CARD, arrowcolor=MUTED, lightcolor=PANEL, darkcolor=PANEL,
                        arrowsize=14, width=14)
        style.map('Kurumi.Vertical.TScrollbar', background=[('active', '#3b3e52')])
        root.attributes('-topmost', self.settings['topmost'])
        root.protocol('WM_DELETE_WINDOW', self.on_window_close)
        self.build()
        self.add_demo(initial=True)
        self.render_stocks()
        self.root.after(150, self.poll)
        self.root.after(300000, self.scheduled_rss)
        self.live_job = self.root.after(self.settings['refresh_seconds'] * 1000, self.scheduled_live)
        self.root.after(600, self.refresh_live)
        if self.settings['rss']:
            self.fetch_rss()

    def label(self, parent, text, size=10, color=TEXT, bg=None, **kwargs):
        size = max(14, size + 5) if size <= 15 else size + 2
        return tk.Label(parent, text=text, font=('Microsoft YaHei UI', size), fg=color,
                        bg=bg or parent.cget('bg'), **kwargs)

    def button(self, parent, text, command, accent=False):
        return tk.Button(parent, text=text, command=command, bg=PINK if accent else PANEL,
                         fg=BG if accent else TEXT, activebackground='#d992b3', activeforeground=BG,
                         relief='flat', bd=0, padx=13, pady=8, cursor='hand2')

    def scrollbar(self, parent, command):
        return ttk.Scrollbar(parent, orient='vertical', command=command, style='Kurumi.Vertical.TScrollbar')

    def build(self):
        header = tk.Frame(self.root, bg=BG)
        header.pack(fill='x', padx=24, pady=(18, 16))
        brand = tk.Frame(header, bg=BG)
        brand.pack(side='left')
        self.label(brand, '久留美 · 市场助手', 20).pack(anchor='w')
        self.label(brand, 'KURUMI  /  市场陪伴助手', 9, MUTED).pack(anchor='w', pady=(3, 0))
        self.button(header, '悬浮模式 ↗', self.show_compact, True).pack(side='right')
        self.button(header, '消息源', self.configure_rss).pack(side='right', padx=8)
        self.notify_button = self.button(header, '', self.show_notification_menu)
        self.notify_button.pack(side='right', padx=(0, 8))
        self.sound_button = self.button(header, '', self.configure_sound)
        self.sound_button.pack(side='right', padx=(0, 8))
        self.button(header, '字号', self.configure_fonts).pack(side='right', padx=(0, 8))
        bar = tk.Frame(self.root, bg=CARD)
        bar.pack(fill='x', padx=24, pady=(0, 16))
        topbar = tk.Frame(bar, bg=CARD)
        topbar.pack(fill='x')
        self.label(topbar, '市场概览', 12).pack(side='left', padx=14, pady=8)
        self.time_label = self.label(topbar, '', 10, MUTED)
        self.time_label.pack(side='right', padx=14)
        self.index_line = self.label(topbar, '腾讯行情 · 快照可能延迟', 9, MUTED, anchor='w')
        self.index_line.pack(side='left', padx=6)
        self.index_grid = tk.Frame(bar, bg=CARD)
        self.index_grid.pack(fill='x', padx=8, pady=(0, 8))
        self.index_cards = {}
        for column, (symbol, market, name) in enumerate([('sh000001', 'A股', '上证指数'), ('r_hkHSI', '港股', '恒生指数'),
                                                         ('usDJI', '美股', '道琼斯'), ('usIXIC', '美股', '纳斯达克')]):
            tile = tk.Frame(self.index_grid, bg=PANEL, highlightbackground='#343648', highlightthickness=1)
            tile.grid(row=0, column=column, sticky='nsew', padx=5)
            self.index_grid.columnconfigure(column, weight=1, uniform='indices')
            heading = tk.Frame(tile, bg=PANEL)
            heading.pack(fill='x', padx=12, pady=(8, 2))
            self.label(heading, name, 10).pack(side='left')
            phase = self.label(heading, '', 8, MUTED)
            phase.pack(side='right', padx=(10, 0))
            price = self.label(tile, '--', 19, TEXT, anchor='w')
            price.pack(fill='x', padx=12)
            change = self.label(tile, '', 9, MUTED, anchor='w')
            change.pack(fill='x', padx=12, pady=(0, 3))
            stamp = self.label(tile, '', 8, MUTED, anchor='w')
            stamp.pack(fill='x', padx=12, pady=(0, 8))
            self.index_cards[symbol] = dict(frame=tile, market=market, heading=heading, phase=phase,
                                            price=price, change=change, stamp=stamp, compact=False)
        footer = tk.Frame(self.root, bg=BG)
        footer.pack(side='bottom', fill='x', padx=24, pady=10)
        self.desktop_status = self.label(footer, '本地运行 · 配置保存在本机', 9, MUTED)
        self.desktop_status.pack(side='left')
        self.label(footer, 'KURUMI  ·  v0.8', 9, MUTED).pack(side='right')
        body = tk.Frame(self.root, bg=BG)
        body.pack(fill='both', expand=True, padx=24)
        body.columnconfigure(0, weight=0, minsize=320)
        body.columnconfigure(1, weight=1, minsize=430)
        body.columnconfigure(2, weight=0, minsize=400)
        body.rowconfigure(0, weight=1)
        left = tk.Frame(body, bg=CARD, width=265)
        left.grid(row=0, column=0, sticky='nsew', padx=(0, 14))
        self.label(left, '我的自选', 15).pack(anchor='w', padx=16, pady=(16, 5))
        self.label(left, '点击股票设置到价提醒', 9, MUTED).pack(anchor='w', padx=16)
        self.button(left, '＋ 添加自选', self.add_stock).pack(side='bottom', fill='x', padx=14, pady=(0, 14))
        stock_canvas = tk.Canvas(left, bg=CARD, highlightthickness=0, width=245)
        self.stock_canvas = stock_canvas
        stock_scroll = self.scrollbar(left, stock_canvas.yview)
        stock_scroll.pack(side='right', fill='y', pady=12)
        stock_canvas.pack(fill='both', expand=True, padx=(10, 0), pady=12)
        stock_canvas.configure(yscrollcommand=stock_scroll.set)
        self.stock_frame = tk.Frame(stock_canvas, bg=CARD)
        stock_window = stock_canvas.create_window(0, 0, window=self.stock_frame, anchor='nw')
        self.stock_frame.bind('<Configure>', lambda e: stock_canvas.configure(scrollregion=stock_canvas.bbox('all')))
        stock_canvas.bind('<Configure>', lambda e: stock_canvas.itemconfigure(stock_window, width=e.width))
        center = tk.Frame(body, bg=BG)
        center.grid(row=0, column=1, sticky='nsew', padx=(0, 14))
        title = tk.Frame(center, bg=BG)
        title.pack(fill='x')
        self.label(title, '市场消息', 15).pack(side='left')
        self.button(title, '↻ 刷新', self.refresh_all).pack(side='right')
        filters = tk.Frame(center, bg=BG)
        filters.pack(fill='x', pady=12)
        self.filter_buttons = {}
        for market in MARKETS:
            b = self.button(filters, market, lambda m=market: self.filter_market(m), market == self.market)
            b.pack(side='left', padx=(0, 6))
            self.filter_buttons[market] = b
        self.feed_status = self.label(center, '财联社电报 · 正在准备连接', 9, MUTED, anchor='w', wraplength=390, justify='left')
        self.feed_status.pack(fill='x', pady=(0, 10))
        container = tk.Frame(center, bg=BG)
        container.pack(fill='both', expand=True)
        self.canvas = tk.Canvas(container, bg=BG, highlightthickness=0)
        scrollbar = self.scrollbar(container, self.canvas.yview)
        scrollbar.pack(side='right', fill='y')
        self.canvas.pack(side='left', fill='both', expand=True)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.news_frame = tk.Frame(self.canvas, bg=BG)
        self.news_window = self.canvas.create_window(0, 0, window=self.news_frame, anchor='nw')
        self.news_frame.bind('<Configure>', lambda e: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>', lambda e: self.canvas.itemconfigure(self.news_window, width=e.width))
        self.canvas.bind_all('<MouseWheel>', self.scroll_news)
        right = tk.Frame(body, bg=CARD, width=400)
        right.grid(row=0, column=2, sticky='nsew')
        right.grid_propagate(False)
        right.columnconfigure(0, weight=1)
        controls = tk.Frame(right, bg=CARD)
        controls.pack(side='bottom', fill='x')
        options = tk.Frame(controls, bg=CARD)
        options.pack(fill='x', padx=12, pady=(0, 10))
        self.mute_button = self.button(options, '', self.toggle_mute)
        self.mute_button.pack(side='left')
        self.pin_button = self.button(options, '', self.toggle_pin)
        self.pin_button.pack(side='right')
        companion_header = tk.Frame(right, bg=CARD)
        companion_header.pack(fill='x', padx=14, pady=(12, 8))
        self.label(companion_header, '久留美', 13, PINK).pack(side='left')
        self.button(companion_header, '演示 ▾', self.show_demo_menu).pack(side='right')
        self.bubble = tk.StringVar(value='我准备好啦！有新消息会在这里告诉你。\n点「演示 ▾」可以试试表情。')
        bubble_box = tk.Frame(right, bg=PANEL, height=190, highlightbackground='#3d3547', highlightthickness=1)
        bubble_box.pack(fill='x', padx=14)
        bubble_box.pack_propagate(False)
        self.bubble_label = tk.Text(bubble_box, font=self.bubble_font, bg=PANEL, fg=TEXT,
                                   wrap='char', height=7, width=1, relief='flat', padx=14, pady=12,
                                   spacing3=4, cursor='arrow', state='disabled', takefocus=False)
        bubble_scroll = self.scrollbar(bubble_box, self.bubble_label.yview)
        bubble_scroll.pack(side='right', fill='y')
        self.bubble_label.configure(yscrollcommand=bubble_scroll.set)
        self.bubble_label.pack(fill='both', expand=True)
        self.panel_source = tk.StringVar(value='点击消息即可播报')
        self.last_panel_body = None
        def update_bubble(*_):
            raw = self.bubble.get()
            if self.current_item:
                body = raw.split('\n', 1)[1].split('\n\n', 1)[0] if '\n' in raw else ''
                self.panel_source.set(self.current_item.get('source', '市场消息')+' · '+self.current_item.get('received', '')[-8:])
            else:
                body = raw
            if body == self.last_panel_body:
                return
            self.bubble_label.configure(state='normal')
            self.bubble_label.delete('1.0', 'end')
            self.bubble_label.insert('1.0', body)
            self.bubble_label.configure(state='disabled')
            if self.is_typing:
                self.bubble_label.see('end')
            else:
                self.bubble_label.yview_moveto(0)
            self.last_panel_body = body
        self.bubble.trace_add('write', update_bubble)
        update_bubble()
        self.bubble_label.bind('<Button-1>', lambda e: self.finish_typing())
        self.label(right, '', 9, MUTED, textvariable=self.panel_source, wraplength=360, anchor='w', justify='left').pack(fill='x', padx=14, pady=(6, 2))
        character = CharacterView(right, BASE / 'assets' / 'kurumi-sheet-v3.png', bg=CARD)
        character.speech_motion = self.speech_motion
        self.character_views.append(character)
        character.pack(expand=True, fill='both')
        self.mood_label = self.label(right, '平静 · 点击气泡可跳过逐字动画', 9, MUTED)
        self.mood_label.pack(pady=(0, 8))
        self.update_controls()
        self.clock()

    def scroll_news(self, event):
        if isinstance(event.widget, tk.Text):
            return
        if event.widget.winfo_toplevel() != self.root or not event.delta:
            return
        node = event.widget
        while node is not None and node != self.root:
            target = self.stock_canvas if node in (self.stock_canvas, self.stock_frame) else self.canvas if node in (self.canvas, self.news_frame) else None
            if target is not None:
                target.yview_scroll(-1 if event.delta > 0 else 1, 'units')
                return
            node = node.master

    def save(self):
        try:
            temp = self.path.with_suffix('.tmp')
            temp.write_text(json.dumps(self.settings, ensure_ascii=False, indent=2), encoding='utf-8')
            temp.replace(self.path)
        except OSError as exc:
            messagebox.showerror('配置保存失败', str(exc), parent=self.root)

    def apply_font_sizes(self, news=None, bubble=None):
        for key, value, role in (('news_text_size', news, 'news'), ('bubble_text_size', bubble, 'bubble')):
            if value is not None:
                self.settings[key] = font_size(value, role)
        self.news_font.configure(size=self.settings['news_text_size'])
        self.bubble_font.configure(size=self.settings['bubble_text_size'])
        if getattr(self, 'overlay', None):
            self.overlay.position_bubble()
        self.save()

    def configure_fonts(self):
        if getattr(self, 'font_dialog', None) and self.font_dialog.winfo_exists():
            self.font_dialog.lift()
            return
        win = self.font_dialog = tk.Toplevel(self.root)
        win.title('字体大小')
        win.geometry('760x680')
        win.configure(bg=CARD)
        self.label(win, '调到看着舒服', 18).pack(anchor='w', padx=24, pady=(20, 10))
        self.label(win, '拖动滑块或输入字号（12–40），立即预览并自动保存。', 10, MUTED).pack(anchor='w', padx=24)
        self.font_vars = {}
        self.font_controls = {}
        validate = (win.register(lambda text: text == '' or (text.isascii() and text.isdigit() and len(text) <= 3)), '%P')
        def add_control(key, title, role, preview, font):
            self.label(win, title, 12).pack(anchor='w', padx=24, pady=(20, 4))
            row = tk.Frame(win, bg=CARD)
            row.pack(fill='x', padx=24)
            entry_value = self.font_vars[key] = tk.StringVar(value=str(self.settings[key]))
            slider_value = tk.IntVar(value=self.settings[key])
            control = self.font_controls[role] = dict(job=None, updating=False, value=entry_value)
            def commit(event=None):
                if control['job'] is not None:
                    win.after_cancel(control['job'])
                    control['job'] = None
                text = entry_value.get()
                value = font_size(int(text) if text.isdigit() else self.settings[key], role)
                control['updating'] = True
                slider_value.set(value)
                entry_value.set(str(value))
                control['updating'] = False
                self.apply_font_sizes(**{role: value})
                return 'break' if event and event.keysym == 'Return' else None
            def changed(*_):
                if control['updating']:
                    return
                if control['job'] is not None:
                    win.after_cancel(control['job'])
                    control['job'] = None
                text = entry_value.get()
                if text.isdigit() and FONT_MIN <= int(text) <= FONT_MAX:
                    control['updating'] = True
                    slider_value.set(int(text))
                    control['updating'] = False
                    control['job'] = win.after(120, commit)
            def slide(value):
                if not control['updating']:
                    text = str(round(float(value)))
                    if text != entry_value.get():
                        entry_value.set(text)
            entry = tk.Spinbox(row, from_=FONT_MIN, to=FONT_MAX, increment=1,
                               textvariable=entry_value, command=commit, width=4, justify='center',
                               bg=PANEL, fg=TEXT, insertbackground=TEXT, buttonbackground=PANEL,
                               relief='flat', validate='key', validatecommand=validate)
            entry.pack(side='right', ipady=8)
            self.label(row, '号', 10, MUTED).pack(side='right', padx=(10, 8))
            scale = tk.Scale(row, from_=FONT_MIN, to=FONT_MAX, resolution=1, orient='horizontal',
                             variable=slider_value, command=slide, showvalue=False,
                             bg=CARD, troughcolor=PANEL, activebackground=PINK,
                             highlightthickness=0, sliderlength=26)
            scale.pack(side='left', fill='x', expand=True, padx=(0, 16))
            control.update(scale=scale, entry=entry, commit=commit)
            entry.bind('<Return>', commit)
            entry.bind('<FocusOut>', commit)
            entry_value.trace_add('write', changed)
            box = tk.Frame(win, bg=PANEL, height=92)
            box.pack(fill='x', padx=24, pady=(8, 0))
            box.pack_propagate(False)
            tk.Label(box, text=preview, font=font, bg=PANEL, fg=TEXT, anchor='w').pack(fill='both', expand=True, padx=16)
        add_control('news_text_size', '消息正文与详情', 'news', '这是一条市场消息。', self.news_font)
        add_control('bubble_text_size', '人物气泡（面板与悬浮）', 'bubble', '久留美告诉你。', self.bubble_font)
        footer = tk.Frame(win, bg=CARD)
        footer.pack(fill='x', padx=24, pady=24)
        def reset():
            for role, value in [('news', 18), ('bubble', 20)]:
                self.font_controls[role]['value'].set(str(value))
                self.font_controls[role]['commit']()
        def done():
            for control in self.font_controls.values():
                control['commit']()
            win.destroy()
        self.button(footer, '恢复推荐字号', reset).pack(side='left')
        self.button(footer, '完成', done, True).pack(side='right')
        win.protocol('WM_DELETE_WINDOW', done)

    def clock(self):
        from market_data import SHANGHAI
        self.time_label.configure(text=datetime.now(SHANGHAI).strftime('%m.%d  %H:%M:%S'))
        minute = datetime.now(SHANGHAI).strftime('%Y%m%d%H%M')
        if getattr(self, 'status_minute', None) != minute:
            self.status_minute = minute
            self.render_stocks()
            self.render_indices()
        self.root.after(1000, self.clock)

    def filter_market(self, market):
        self.market = market
        for key, button in self.filter_buttons.items():
            button.configure(bg=PINK if key == market else PANEL, fg=BG if key == market else TEXT)
        self.render_news()
        self.render_stocks()
        self.render_indices()
        if self.indices:
            self.react_to_indices()

    def render_stocks(self):
        for child in self.stock_frame.winfo_children():
            child.destroy()
        stocks = [s for s in self.settings['stocks'] if self.market in ('全部', s['market'])]
        for stock in stocks[:10]:
            key = stock_key(stock)
            quote = self.stock_quotes.get(key)
            issue = self.quote_issues.get(key)
            fresh = quote and not issue and quote_is_fresh(quote)
            change = quote['change'] if quote else None
            row = tk.Frame(self.stock_frame, bg=PANEL, cursor='hand2')
            row.pack(fill='x', pady=4)
            top = tk.Frame(row, bg=PANEL)
            top.pack(fill='x', padx=10, pady=(8, 0))
            self.label(top, stock['name'], 10).pack(side='left')
            self.label(top, f'{change:+.2f}%' if quote else '--', 11,
                       (RED if change >= 0 else GREEN) if fresh else MUTED).pack(side='right')
            bottom = tk.Frame(row, bg=PANEL)
            bottom.pack(fill='x', padx=10, pady=(3, 2))
            self.label(bottom, f"{stock['market']} · {stock['symbol']}", 8, MUTED).pack(side='left')
            self.label(bottom, f"{quote['price']:,.2f}" if quote else '--', 10, TEXT if fresh else MUTED).pack(side='right')
            stamp = self.quote_time(quote['timestamp']) if quote else ''
            state = quote_status(stock['market'], quote, True if self.source_failures.get('stocks') else issue)
            status = state['session'] + ' · ' + state['data'] + '\n更新：' + state['source_time']
            self.label(row, status, 8, MUTED, wraplength=260,
                       justify='left', anchor='w').pack(fill='x', padx=10, pady=(0, 7))
            def bind_all(widget, item):
                widget.bind('<Button-1>', lambda e, s=item: self.stock_dialog(s))
                for child in widget.winfo_children():
                    bind_all(child, item)
            bind_all(row, stock)

    def render_news(self):
        for child in self.news_frame.winfo_children():
            child.destroy()
        items = [n for n in self.news if self.market == '全部' or n['market'] in ('全部', self.market)]
        for item in items[:80]:
            card = tk.Frame(self.news_frame, bg=CARD, highlightbackground='#343648', highlightthickness=1)
            card.pack(fill='x', pady=(0, 10))
            tag = f"{'演示 · ' if item['demo'] else ''}{item['source']}  ·  {'全市场' if item['market'] == '全部' else item['market']}"
            self.label(card, tag, 9, PINK, anchor='w', wraplength=330, justify='left').pack(fill='x', padx=14, pady=(12, 7))
            title = self.label(card, item['title'], 11, wraplength=330, justify='left', anchor='w')
            title.configure(font=self.news_font)
            title.pack(fill='x', padx=14)
            title.configure(cursor='hand2')
            title.bind('<Button-1>', lambda e, n=item: self.view_news(n) if n.get('content') else self.speak(n, manual=True))
            card.bind('<Configure>', lambda e, l=title: l.configure(wraplength=max(200, e.width - 30)))
            self.label(card, '发布：' + item['published'], 8, MUTED, wraplength=320, anchor='w').pack(fill='x', padx=14, pady=(8, 0))
            action = tk.Frame(card, bg=CARD)
            action.pack(fill='x', padx=14, pady=(0, 10))
            self.button(action, '▷ 播报', lambda n=item: self.speak(n, manual=True)).pack(side='left')
            if item['url']:
                self.button(action, '原文 ↗', lambda u=item['url']: webbrowser.open(u)).pack(side='right')
            if item.get('content'):
                self.button(action, '详情', lambda n=item: self.view_news(n)).pack(side='right', padx=4)
        if not items:
            self.label(self.news_frame, '还没有这个市场的消息。', 11, MUTED).pack(pady=30)

    def add_news(self, item, announce=True):
        if item['id'] in self.seen:
            return False
        self.seen.add(item['id'])
        item['received'] = datetime.now().strftime('%m-%d %H:%M:%S')
        self.news.insert(0, item)
        self.news = self.news[:200]
        if announce and not self.settings['muted']:
            self.enqueue_news([item])
        return True

    def enqueue_news(self, items):
        items = [item for item in items if should_announce(item, self.settings)]
        now = time.monotonic()
        for item in items:
            item['_queued_at'] = now
        self.pending = queued_news(self.pending + list(items), now=now)

    def view_news(self, item):
        win = tk.Toplevel(self.root)
        win.title('市场快讯 · ' + item['source'])
        win.geometry('820x620')
        win.configure(bg=CARD)
        self.label(win, item['source'] + ' · ' + item['published'], 10, PINK).pack(anchor='w', padx=20, pady=14)
        text = tk.Text(win, wrap='word', bg=PANEL, fg=TEXT, relief='flat', padx=16, pady=16,
                       font=('Microsoft YaHei UI', 16), spacing1=3, spacing3=6)
        text.insert('1.0', item.get('content') or item['title'])
        text.configure(font=self.news_font)
        text.configure(state='disabled')
        text.pack(fill='both', expand=True, padx=20)
        self.button(win, '打开原文 ↗', lambda: webbrowser.open(item['url'])).pack(pady=12)

    def set_character(self, mood, talking):
        if not talking:
            self.speech_motion.stop()
            for view in self.character_views:
                view.mouth_open = False
        self.mood = mood
        for character in self.character_views:
            character.mood = mood
            character.talking = talking
        label = {'neutral': '平静', 'happy': '开心', 'sad': '哭泣'}[mood]
        self.mood_label.configure(text=label + (' · 正在说话' if talking else ' · 点击气泡可跳过逐字动画'))

    def speak(self, item, manual=False):
        if self.reaction_job is not None:
            self.root.after_cancel(self.reaction_job)
            self.reaction_job = None
        if not manual and should_announce(item, self.settings):
            self.audio.play(self.settings)
        self.current_manual = manual
        self.speech_token += 1
        if self.type_job is not None:
            self.root.after_cancel(self.type_job)
            self.type_job = None
        self.current_item = item
        self.speech_text = bubble_text(item)
        self.voiced_start = self.speech_text.find('\n') + 1
        self.voiced_end = self.speech_text.find('\n\n', self.voiced_start)
        if self.voiced_end < 0:
            self.voiced_end = len(self.speech_text)
        self.speech_motion.start()
        self.speech_position = 0
        self.is_typing = True
        self.set_character(item.get('emotion') or emotion_for(item['title']), True)
        self.bubble.set('')
        if getattr(self, 'overlay', None):
            self.overlay.start_speech(manual=manual)
        # Reserve enough time for typing plus reading; automatic items never cut a line short.
        self.next_speech = time.monotonic() + len(self.speech_text) * self.settings['typewriter_ms'] / 1000 + 5
        self.type_next()

    def type_next(self):
        self.type_job = None
        self.speech_position += 1
        self.bubble.set(self.speech_text[:self.speech_position])
        if self.speech_position >= len(self.speech_text):
            self.is_typing = False
            self.bubble_label.yview_moveto(0)
            self.set_character(self.mood, False)
            self.settle_reaction()
            if getattr(self, 'overlay', None):
                self.overlay.end_speech()
            return
        character = self.speech_text[self.speech_position-1]
        delay = self.settings['typewriter_ms'] + (170 if character in '。，！？；、,.!?;…\n' else 0)
        self.speech_motion.character(character, self.voiced_start < self.speech_position <= self.voiced_end,
                                     hold=delay/1000)
        self.type_job = self.root.after(delay, self.type_next)

    def finish_typing(self):
        if not self.is_typing:
            return
        if self.type_job is not None:
            self.root.after_cancel(self.type_job)
            self.type_job = None
        self.bubble.set(self.speech_text)
        self.is_typing = False
        self.bubble_label.yview_moveto(0)
        self.set_character(self.mood, False)
        self.settle_reaction()
        self.next_speech = time.monotonic() + 5
        if getattr(self, 'overlay', None):
            self.overlay.end_speech()

    def demo_reaction(self, mood):
        item = {'id': 'demo-' + uuid4().hex, 'title': '模拟：市场指数上涨 1.20%，今天的盘面红彤彤！' if mood == 'happy' else '模拟：市场指数下跌 1.20%，呜呜，先看看发生了什么。',
                'source': '涨跌互动演示', 'market': self.market, 'published': '演示场景', 'url': '', 'demo': True, 'emotion': mood}
        self.add_news(item, announce=False)
        self.render_news()
        self.speak(item, manual=True)

    def show_demo_menu(self):
        if getattr(self, 'demo_menu', None):
            self.demo_menu.destroy()
        self.demo_menu = tk.Menu(self.root, tearoff=False, bg=PANEL, fg=TEXT,
                                 activebackground=PINK, activeforeground=BG)
        self.demo_menu.add_command(label='快讯演示', command=self.add_demo)
        self.demo_menu.add_command(label='上涨 · 笑', command=lambda: self.demo_reaction('happy'))
        self.demo_menu.add_command(label='下跌 · 哭', command=lambda: self.demo_reaction('sad'))
        try:
            self.demo_menu.tk_popup(self.root.winfo_pointerx(), self.root.winfo_pointery())
        finally:
            self.demo_menu.grab_release()

    def settle_reaction(self):
        if self.reaction_job is not None:
            self.root.after_cancel(self.reaction_job)
        def settle():
            self.reaction_job = None
            if not self.is_typing:
                self.set_character('neutral', False)
        self.reaction_job = self.root.after(2200, settle)

    def add_demo(self, initial=False):
        templates = [
            ('A股', '市场快讯演示', '模拟：主要指数上涨，市场成交活跃。久留美开心地告诉你盘面变化。'),
            ('港股', '市场快讯演示', '模拟：港股主要指数下跌，部分板块走低。呜呜，我会继续关注消息。'),
            ('美股', '市场快讯演示', '模拟：今晚关注经济数据与政策消息。先听消息，再看市场反应。'),
            ('全部', '市场快讯演示', '模拟：全球市场消息更新。宏观政策、行业动态都可以在这里播报。'),
        ]
        count = 3 if initial else 1
        for _ in range(count):
            market, source, title = templates[self.counter % len(templates)]
            if self.market != '全部' and not initial:
                market = self.market
            self.counter += 1
            item = {'id': 'demo-' + uuid4().hex, 'title': title, 'market': market,
                    'source': source, 'published': '演示场景，无实际发布时间', 'url': '', 'demo': True}
            self.add_news(item, announce=False)
        self.render_news()
        if not initial:
            self.speak(item, manual=True)
        # Demo messages only animate the mascot; they never modify live prices.

    def simulate_quotes(self):
        for index, stock in enumerate(self.settings['stocks']):
            old = stock['price']
            stock['price'] = round(max(.01, old * (1 + math.sin(self.counter + index) * .007)), 2)
            self.check_alert(stock, old)
        self.render_stocks()

    def check_alert(self, stock, old):
        key = stock['market'] + ':' + stock['symbol']
        alert = self.settings['alerts'].get(key)
        if alert and alert.get('mode', 'demo') == 'demo' and crossed(old, stock['price'], alert['target'], alert['direction']):
            self.add_news({'id': 'alert-' + uuid4().hex, 'title': f"模拟到价：{stock['name']} 已穿越 {alert['target']:.2f}，当前演示价格 {stock['price']:.2f}。提醒已触发一次。", 'market': stock['market'], 'source': '价格提醒', 'published': '模拟行情触发', 'url': '', 'demo': True})
            del self.settings['alerts'][key]
            self.save()
            self.render_news()

    def add_stock(self):
        if len(self.settings['stocks']) >= 10:
            messagebox.showinfo('自选已满', '原型最多展示 10 只自选，请先删除一只。', parent=self.root)
            return
        value = simpledialog.askstring('添加自选', '输入：市场,代码,名称\n例如：美股,MSFT,微软\n市场可选：A股 / 港股 / 美股', parent=self.root)
        if value is None:
            return
        fields = [f.strip() for f in value.replace('，', ',').split(',')]
        if len(fields) != 3 or fields[0] not in MARKETS[1:] or not all(fields) or any(len(f) > 30 for f in fields):
            messagebox.showerror('格式不正确', '请使用示例格式，名称与代码不超过 30 个字符。', parent=self.root)
            return
        market, symbol, name = fields
        symbol = symbol.upper()
        if market == '港股' and symbol.isdigit():
            symbol = symbol.zfill(5)
        try:
            quote_code(dict(market=market, symbol=symbol))
        except ValueError as exc:
            messagebox.showerror('股票代码无效', str(exc), parent=self.root)
            return
        if any(s['symbol'] == symbol and s['market'] == market for s in self.settings['stocks']):
            messagebox.showinfo('已在自选', '这只股票已添加。', parent=self.root)
            return
        self.settings['stocks'].append(dict(market=market, symbol=symbol, name=name, price=100.0, base=100.0))
        self.save()
        self.render_stocks()
        self.fetch_public_source('stocks')

    def stock_dialog(self, stock):
        win = tk.Toplevel(self.root)
        win.title(stock['name'] + ' · 到价提醒')
        win.geometry('540x550')
        win.configure(bg=CARD)
        key = stock['market'] + ':' + stock['symbol']
        self.label(win, stock['name'] + '  ' + stock['symbol'], 17).pack(pady=15)
        quote = self.stock_quotes.get(key)
        reference = quote['price'] if quote else None
        self.label(win, f"公开快照 {reference:,.2f}" if quote else '暂未获取行情，请稍后刷新', 11, PINK).pack()
        self.label(win, ('源站时间：' + self.quote_time(quote['timestamp'])) if quote else '', 9, MUTED).pack(pady=3)
        self.label(win, '只在近 3 分钟的有效快照到达时检测；\n旧快照、获取失败和演示播报不会触发真实提醒。', 9, MUTED, justify='left').pack(pady=6)
        alert = self.settings['alerts'].get(key)
        current = (f"当前提醒：{alert['target']:.2f}" + ('（旧演示提醒，请重新设置）' if alert.get('mode') != 'live' else '')) if alert else '当前没有提醒'
        self.label(win, current, 10, MUTED).pack(pady=10)
        entry = tk.Entry(win, bg=PANEL, fg=TEXT, insertbackground=TEXT, relief='flat', font=('Microsoft YaHei UI', 18))
        if reference:
            entry.insert(0, f"{reference * 1.005:.2f}")
        entry.pack(padx=30, fill='x', ipady=8)
        def set_alert():
            latest = self.stock_quotes.get(key)
            if not latest:
                messagebox.showinfo('等待行情', '先获取该股票的公开快照，再设置目标价格。', parent=win)
                return
            try:
                target = float(entry.get())
                if not math.isfinite(target) or target <= 0 or target == latest['price']:
                    raise ValueError()
            except ValueError:
                messagebox.showerror('价格无效', '请输入大于零且不同于当前快照价格的数值。', parent=win)
                return
            self.settings['alerts'][key] = dict(target=target, direction='above' if target > latest['price'] else 'below', mode='live')
            self.save()
            win.destroy()
        self.button(win, '保存一次性到价提醒', set_alert, True).pack(fill='x', padx=30, pady=12)
        def test_alert():
            item = dict(id='preview-'+uuid4().hex, title=stock['name'] + '：这是到价提醒的样式演示，不改变真实报价或已设置的提醒。',
                        market=stock['market'], source='提醒样式演示', published='演示场景', url='', demo=True)
            self.add_news(item, announce=False)
            self.render_news()
            self.speak(item, manual=True)
            win.destroy()
        self.button(win, '预览提醒样式（不修改行情）', test_alert).pack(fill='x', padx=30)
        def cancel_alert():
            self.settings['alerts'].pop(key, None)
            self.save()
            win.destroy()
        self.button(win, '取消当前提醒', cancel_alert).pack(fill='x', padx=30, pady=6)
        def remove():
            self.settings['stocks'].remove(stock)
            self.settings['alerts'].pop(key, None)
            self.save()
            self.render_stocks()
            win.destroy()
        self.button(win, '移出自选', remove).pack(pady=12)

    def update_controls(self):
        self.mute_button.configure(text='恢复播报' if self.settings['muted'] else '暂停播报')
        self.pin_button.configure(text='取消置顶' if self.settings['topmost'] else '面板置顶')
        self.notify_button.configure(text='提醒：'+MODES[self.settings['notification_mode']])
        self.sound_button.configure(text='声音：'+{'normal': '提示音', 'voice': '久留美', 'off': '关闭'}[self.settings['sound_mode']])

    def show_notification_menu(self):
        if getattr(self, 'notification_menu', None):
            self.notification_menu.destroy()
        self.notification_menu = tk.Menu(self.root, tearoff=False)
        self.notification_var = tk.StringVar(value=self.settings['notification_mode'])
        for key, label in MODES.items():
            self.notification_menu.add_radiobutton(label=label, variable=self.notification_var, value=key,
                                                  command=lambda mode=key: self.set_notification_mode(mode))
        try:
            self.notification_menu.tk_popup(self.notify_button.winfo_rootx(), self.notify_button.winfo_rooty()+self.notify_button.winfo_height())
        finally:
            self.notification_menu.grab_release()

    def set_notification_mode(self, mode):
        if mode not in MODES:
            return
        self.settings['notification_mode'] = mode
        if mode == 'manual':
            self.audio.stop()
        self.pending = [n for n in self.pending if should_announce(n, self.settings)]
        if self.current_item and not getattr(self, 'current_manual', False) and not should_announce(self.current_item, self.settings):
            self.finish_typing()
            if getattr(self, 'overlay', None):
                self.overlay.hide_bubble(immediate=True)
        self.update_controls()
        self.save()
        if self.desktop:
            self.desktop.sync()

    def toggle_mute(self):
        self.settings['muted'] = not self.settings['muted']
        self.pending.clear()
        if self.settings['muted']:
            self.audio.stop()
            self.finish_typing()
        self.update_controls()
        self.save()
        if self.desktop:
            self.desktop.sync()

    def toggle_pin(self):
        self.settings['topmost'] = not self.settings['topmost']
        self.root.attributes('-topmost', self.settings['topmost'])
        self.update_controls()
        self.save()

    def configure_sound(self):
        if getattr(self, 'sound_dialog', None) and self.sound_dialog.winfo_exists():
            self.sound_dialog.lift()
            return
        win = self.sound_dialog = tk.Toplevel(self.root)
        win.title('消息提示音')
        win.geometry('760x800')
        win.configure(bg=CARD)
        self.label(win, '有消息时，听一声提醒', 18).pack(anchor='w', padx=24, pady=(20, 10))
        mode = tk.StringVar(value=self.settings['sound_mode'])
        volume = tk.IntVar(value=self.settings['sound_volume'])
        voice_file = tk.StringVar(value=self.settings['voice_file'])
        voice_name = tk.StringVar(value=self.settings['voice_name'] or '尚未导入久留美音频')
        for value, title in SOUND_MODES.items():
            tk.Radiobutton(win, text=title, variable=mode, value=value, bg=CARD, fg=TEXT, selectcolor=PANEL,
                           activebackground=CARD, activeforeground=TEXT).pack(anchor='w', padx=20, pady=3)
        self.label(win, '内置 AI 少女声「チャンス！」（机会！），也可导入音频。\n支持 WAV / MP3，建议 1–5 秒；每次最多播放 8 秒。', 9, MUTED,
                   wraplength=490, justify='left').pack(anchor='w', padx=24, pady=10)
        self.label(win, '', 10, PINK, textvariable=voice_name, wraplength=480, anchor='w').pack(fill='x', padx=24)
        def choose_voice():
            path = filedialog.askopenfilename(title='导入久留美原作音频片段', parent=win,
                                             filetypes=[('音频文件', '*.wav *.mp3'), ('WAV', '*.wav'), ('MP3', '*.mp3')])
            if not path:
                return
            try:
                imported = import_voice(path, BASE/'assets'/'audio')
                voice_file.set(str(imported.relative_to(BASE)))
                voice_name.set(Path(path).name)
                mode.set('voice')
            except (OSError, ValueError) as exc:
                messagebox.showerror('无法导入音频', str(exc), parent=win)
        imports = tk.Frame(win, bg=CARD)
        imports.pack(fill='x', padx=24, pady=10)
        self.button(imports, '导入久留美音频…', choose_voice).pack(side='left')
        def use_ai_voice():
            voice_file.set('assets/audio/chance-ai.wav')
            voice_name.set('AI 少女声 · チャンス！（机会！）')
            mode.set('voice')
            self.sound_status_var.set('AI 合成日语少女声，本地播放；可点击试听。')
        if (BASE/'assets/audio/chance-ai.wav').exists():
            self.button(imports, '使用 AI「チャンス！」', use_ai_voice).pack(side='left', padx=8)
        self.label(win, '提示音音量（不修改系统音量）', 10).pack(anchor='w', padx=24)
        tk.Scale(win, from_=0, to=100, variable=volume, orient='horizontal', bg=CARD, fg=TEXT,
                 troughcolor=PANEL, highlightthickness=0).pack(fill='x', padx=24)
        self.sound_status_var = tk.StringVar(value=self.last_sound_status)
        self.label(win, '', 9, MUTED, textvariable=self.sound_status_var, wraplength=490,
                   justify='left', anchor='w').pack(fill='x', padx=24, pady=8)
        row = tk.Frame(win, bg=CARD)
        row.pack(fill='x', padx=24, pady=8)
        def values():
            return dict(sound_mode=mode.get(), sound_volume=volume.get(), voice_file=voice_file.get(), voice_name=voice_name.get())
        def preview():
            if not self.audio.play(values(), preview=True):
                self.sound_status_var.set('声音已关闭，或音量为 0。')
        self.button(row, '▶ 试听', preview, True).pack(side='left')
        self.button(row, '■ 停止', self.audio.stop).pack(side='left', padx=8)
        def apply():
            self.settings.update(values())
            self.audio.stop()
            self.update_controls()
            self.save()
            win.destroy()
        self.button(row, '保存', apply, True).pack(side='right')
        self.label(win, '声音遵守提醒档位与暂停设置；手动查看消息不重复响铃。', 9, MUTED, wraplength=490).pack(anchor='w', padx=24, pady=8)

    def configure_rss(self):
        win = tk.Toplevel(self.root)
        win.title('消息源与播报设置')
        win.geometry('760x1000')
        win.configure(bg=CARD)
        self.label(win, '市场消息与角色互动', 17).pack(anchor='w', padx=24, pady=(20, 12))
        mode = tk.StringVar(value=self.settings['notification_mode'])
        mode_row = tk.Frame(win, bg=CARD)
        mode_row.pack(fill='x', padx=20)
        for value, label in MODES.items():
            tk.Radiobutton(mode_row, text=label, variable=mode, value=value, bg=CARD, fg=TEXT, selectcolor=PANEL,
                           activebackground=CARD, activeforeground=TEXT).pack(side='left')
        self.label(win, '重要消息按来源重点标记及真实到价提醒筛选；手动查看不自动播报。', 9, MUTED, wraplength=490, justify='left').pack(anchor='w', padx=24, pady=(4, 10))
        enabled = tk.BooleanVar(value=self.settings['cls_enabled'])
        indices = tk.BooleanVar(value=self.settings['indices_enabled'])
        for text, variable in [('财联社电报 · 宏观、行业、全球市场快讯', enabled), ('指数涨跌互动 · A股 / 港股 / 美股', indices)]:
            tk.Checkbutton(win, text=text, variable=variable, bg=CARD, fg=TEXT, selectcolor=PANEL,
                           activebackground=CARD, activeforeground=TEXT).pack(anchor='w', padx=20, pady=5)
        self.label(win, '行情和消息可能延迟；休市旧快照不触发表情或提醒。', 9, MUTED, justify='left').pack(anchor='w', padx=24, pady=(2, 10))
        refresh = tk.IntVar(value=self.settings['refresh_seconds'])
        interval_row = tk.Frame(win, bg=CARD)
        interval_row.pack(fill='x', padx=24, pady=6)
        self.label(interval_row, '公开消息 / 行情刷新间隔（秒）', 10).pack(side='left')
        tk.OptionMenu(interval_row, refresh, 15, 30, 60).pack(side='right')
        autohide = tk.BooleanVar(value=self.settings['bubble_autohide'])
        tk.Checkbutton(win, text='悬浮气泡播完 8 秒自动收起', variable=autohide, bg=CARD, fg=TEXT,
                       selectcolor=PANEL, activebackground=CARD, activeforeground=TEXT).pack(anchor='w', padx=20, pady=5)
        self.label(win, '补充 RSS / Atom 订阅（可选，每 5 分钟刷新）', 10).pack(anchor='w', padx=24)
        entry = tk.Entry(win, bg=PANEL, fg=TEXT, insertbackground=TEXT, relief='flat')
        entry.insert(0, self.settings['rss'])
        entry.pack(fill='x', padx=24, pady=10, ipady=7)
        self.label(win, '逐字速度（毫秒 / 字，越小越快）', 10).pack(anchor='w', padx=24)
        speed = tk.Scale(win, from_=20, to=100, resolution=2, orient='horizontal', bg=CARD, fg=TEXT,
                         troughcolor=PANEL, highlightthickness=0, length=440)
        speed.set(self.settings['typewriter_ms'])
        speed.pack(padx=24, fill='x')
        self.button(win, '打开财联社电报原站 ↗', lambda: webbrowser.open('https://www.cls.cn/telegraph')).pack(anchor='w', padx=24, pady=8)
        def apply():
            value = entry.get().strip()
            if value and (not safe_url(value) or urlparse(value).scheme != 'https'):
                messagebox.showerror('地址无效', '补充订阅请填写 HTTPS 地址，或留空。', parent=win)
                return
            self.settings.update(rss=value, cls_enabled=enabled.get(), indices_enabled=indices.get(), typewriter_ms=int(speed.get()),
                                 refresh_seconds=refresh.get(), bubble_autohide=autohide.get())
            self.set_notification_mode(mode.get())
            self.pending.clear()
            self.root.after_cancel(self.live_job)
            self.live_job = self.root.after(self.settings['refresh_seconds'] * 1000, self.scheduled_live)
            if getattr(self, 'overlay', None):
                self.overlay.end_speech()
            self.save()
            win.destroy()
            self.refresh_all()
        self.button(win, '保存并刷新', apply, True).pack(fill='x', padx=24, pady=12)

    def refresh_all(self):
        self.refresh_live(force=True)
        if self.settings['rss']:
            self.fetch_rss()

    def refresh_live(self, force=False):
        if force:
            self.source_retry_at.clear()
        if self.settings['cls_enabled']:
            self.fetch_public_source('cls')
        else:
            self.source_status['cls'] = '财联社已关闭'
            self.update_feed_status()
        if self.settings['indices_enabled']:
            self.fetch_public_source('indices')
        else:
            self.render_indices()
        if self.settings['stocks']:
            self.fetch_public_source('stocks')

    def scheduled_live(self):
        self.refresh_live()
        self.live_job = self.root.after(self.settings['refresh_seconds'] * 1000, self.scheduled_live)

    def update_feed_status(self):
        visible = [value for key, value in self.source_status.items() if key != 'stocks']
        self.feed_status.configure(text='\n'.join(visible) or '等待消息源')

    def fetch_public_source(self, name):
        if name in self.source_busy or time.monotonic() < self.source_retry_at.get(name, 0):
            return
        self.source_busy.add(name)
        if name == 'cls':
            self.source_status['cls'] = '正在读取财联社电报…'
            self.update_feed_status()
        stocks = [dict(s) for s in self.settings['stocks']]
        def worker():
            try:
                records = fetch_cls() if name == 'cls' else fetch_indices() if name == 'indices' else fetch_stock_quotes(stocks)
                self.inbox.put(('public', (name, records, None)))
            except Exception as exc:
                self.inbox.put(('public', (name, None, str(exc)[:80])))
        threading.Thread(target=worker, daemon=True).start()

    def receive_public(self, name, records, error):
        self.source_busy.discard(name)
        if name != 'stocks' and not self.settings['cls_enabled' if name == 'cls' else 'indices_enabled']:
            return
        if error:
            self.source_failures[name] = self.source_failures.get(name, 0) + 1
            wait = min(300, 30 * 2 ** min(4, self.source_failures[name]-1))
            self.source_retry_at[name] = time.monotonic() + wait
            if name == 'cls':
                self.source_status['cls'] = f'财联社未更新（{wait}秒后重试）：' + error
                self.update_feed_status()
            elif name == 'stocks':
                self.quote_issues.update({stock_key(s): error for s in self.settings['stocks']})
                self.source_status['stocks'] = f'自选行情未更新 · 提醒暂停 · {wait}秒后重试'
                self.update_feed_status()
                self.render_stocks()
            else:
                self.render_indices()
            return
        self.source_failures[name] = 0
        self.source_retry_at.pop(name, None)
        if name == 'stocks':
            self.receive_stocks(records)
            return
        if name == 'cls':
            first = not getattr(self, 'cls_initialized', False)
            self.cls_initialized = True
            new = []
            for item in reversed(records):
                if self.add_news(item, announce=False):
                    new.append(item)
            if new and not self.settings['muted']:
                self.enqueue_news(new[-1:] if first else new[-3:])
            self.source_status['cls'] = f'财联社电报 · 新增 {len(new)} 条 · ' + datetime.now().strftime('%H:%M:%S')
            self.update_feed_status()
            self.render_news()
        else:
            self.indices = records
            self.render_indices()
            self.react_to_indices()

    def render_indices(self):
        enabled = self.settings['indices_enabled']
        self.index_line.configure(text='腾讯行情 · 快照可能延迟' if enabled else '指数已关闭 · 自选行情继续更新')
        lookup = {q['symbol']: q for q in self.indices}
        if 'hkHSI' in lookup:
            lookup['r_hkHSI'] = lookup['hkHSI']
        visible = 0
        compact = sum(self.market in ('全部', w['market']) for w in self.index_cards.values()) == 1
        for column in range(4):
            self.index_grid.columnconfigure(column, weight=0, minsize=0, uniform='')
        for symbol, widgets in self.index_cards.items():
            if self.market not in ('全部', widgets['market']):
                widgets['frame'].grid_remove()
                continue
            widgets['frame'].grid(row=0, column=visible, sticky='nsew', padx=5)
            self.index_grid.columnconfigure(visible, weight=1, uniform='indices')
            visible += 1
            if widgets['compact'] != compact:
                widgets['compact'] = compact
                for key in ('heading', 'price', 'change', 'stamp'):
                    widgets[key].pack_forget()
                if compact:
                    widgets['heading'].pack(side='left', padx=12, pady=12)
                    widgets['price'].pack(side='left', padx=20, pady=12)
                    widgets['change'].pack(side='left', padx=12)
                    widgets['stamp'].pack(side='right', padx=16)
                else:
                    widgets['heading'].pack(fill='x', padx=12, pady=(8, 2))
                    widgets['price'].pack(fill='x', padx=12)
                    widgets['change'].pack(fill='x', padx=12, pady=(0, 3))
                    widgets['stamp'].pack(fill='x', padx=12, pady=(0, 8))
            quote = lookup.get(symbol) if enabled else None
            state = quote_status(widgets['market'], quote, enabled and bool(self.source_failures.get('indices')))
            widgets['phase'].configure(text=state['session'])
            widgets['price'].configure(text=f"{quote['price']:,.2f}" if quote else '--')
            change = f"{quote['change']:+.2f}%" if quote else ''
            data = state['data'] if enabled else '已关闭'
            widgets['change'].configure(text=(change+'  ·  ' if change else '')+data,
                                        fg=(RED if quote['change'] >= 0 else GREEN) if quote and state['active'] else MUTED)
            widgets['stamp'].configure(text=state['source_time'] if quote else '等待更新' if enabled else '可在消息源中开启')

    @staticmethod
    def quote_time(value):
        if len(value) == 14 and value.isdigit():
            return value[4:6] + '-' + value[6:8] + ' ' + value[8:10] + ':' + value[10:12]
        return value

    def react_to_indices(self):
        if self.settings['muted'] or not self.settings['indices_enabled']:
            return
        if self.source_failures.get('indices', 0):
            return
        quotes = [q for q in self.indices if self.market in ('全部', q['market']) and quote_is_fresh(q)]
        if not quotes:
            return
        if self.market == '全部':
            quotes = [q for q in quotes if q['market'] == 'A股'] or quotes
        quote = max(quotes, key=lambda q: abs(q['change']))
        mood = quote_reaction(quote)
        if mood == 'neutral':
            return
        last = self.last_reaction.get(quote['symbol'])
        now = time.monotonic()
        if last and (now-last[1] < 120 or abs(quote['change']-last[0]) < .3):
            return
        self.last_reaction[quote['symbol']] = (quote['change'], now)
        item = {'id': 'index-' + uuid4().hex, 'title': f"{quote['name']}最新快照：{quote['change']:+.2f}%，点位 {quote['price']:,.2f}。源站时间 {self.quote_time(quote['timestamp'])}，可能为延迟或休市快照。", 'source': quote['source'],
                'market': quote['market'], 'published': self.quote_time(quote['timestamp']) + '（源站时间）', 'url': '', 'demo': False, 'emotion': mood}
        self.add_news(item, announce=True)
        self.render_news()

    def receive_stocks(self, records):
        by_key = {q['key']: q for q in records}
        for stock in self.settings['stocks']:
            key = stock_key(stock)
            quote = by_key.get(key)
            if quote is None:
                self.quote_issues[key] = '源站未返回该代码'
                continue
            previous = self.stock_quotes.get(key)
            current_time = quote_datetime(quote)
            previous_time = quote_datetime(previous) if previous else None
            if previous_time and current_time and current_time < previous_time:
                self.quote_issues[key] = '源站返回较旧报价，保留最近快照'
                continue
            self.stock_quotes[key] = quote
            self.quote_issues.pop(key, None)
            self.check_live_alert(stock, quote, previous)
        valid = len([s for s in self.settings['stocks'] if stock_key(s) in by_key])
        self.source_status['stocks'] = f'自选行情 · {valid}/{len(self.settings["stocks"])}只已返回 · 旧快照不触发提醒'
        self.update_feed_status()
        self.render_stocks()

    def check_live_alert(self, stock, quote, previous=None):
        key = stock_key(stock)
        alert = self.settings['alerts'].get(key)
        if not alert or alert.get('mode') != 'live' or not quote_is_fresh(quote):
            return
        if previous and quote_datetime(previous) and quote_datetime(quote) <= quote_datetime(previous):
            return
        reached = quote['price'] >= alert['target'] if alert['direction'] == 'above' else quote['price'] <= alert['target']
        if not reached:
            return
        self.add_news(dict(id='live-alert-'+uuid4().hex, title=f"{stock['name']}到价：公开快照 {quote['price']:,.2f}，已到达目标 {alert['target']:,.2f}。", market=stock['market'],
                           source='真实到价提醒 · 腾讯快照', published=self.quote_time(quote['timestamp']) + '（源站时间）', url='', demo=False,
                           emotion='happy' if alert['direction'] == 'above' else 'sad'))
        del self.settings['alerts'][key]
        self.save()
        self.render_news()

    def fetch_rss(self):
        url = self.settings['rss']
        if not url:
            self.feed_status.configure(text='尚未设置订阅源 · 请点击右上角「消息源」')
            return
        if self.rss_busy:
            return
        self.rss_busy = True
        self.source_status['rss'] = '正在读取补充订阅…'
        self.update_feed_status()
        def worker():
            try:
                request = Request(url, headers={'User-Agent': 'KurumiCompanion/0.1', 'Accept': 'application/rss+xml, application/atom+xml, application/xml'})
                with urlopen(request, timeout=15) as response:
                    if not safe_url(response.url) or urlparse(response.url).scheme != 'https':
                        raise ValueError('订阅重定向到了非 HTTPS 地址')
                    data = response.read(2_000_001)
                if len(data) > 2_000_000:
                    raise ValueError('订阅内容超过 2 MB')
                records = parse_feed(data)
                if not records:
                    raise ValueError('没有找到可读的 RSS / Atom 消息')
                self.inbox.put(('news', (url, records)))
            except Exception as exc:
                self.inbox.put(('error', (url, str(exc)[:120])))
        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        if self.desktop and self.desktop.guard and self.desktop.guard.activated():
            self.restore()
        try:
            while True:
                kind, payload = self.inbox.get_nowait()
                if kind == 'sound':
                    self.last_sound_status = payload
                    if getattr(self, 'sound_status_var', None):
                        self.sound_status_var.set(payload)
                    continue
                if kind == 'desktop':
                    action, value = payload
                    if action == 'exit':
                        self.close()
                        return
                    if action == 'restore':
                        self.restore()
                    elif action == 'compact':
                        self.show_compact()
                    elif action == 'toggle':
                        self.toggle_visibility()
                    elif action == 'pause':
                        self.toggle_mute()
                    elif action == 'sound_settings':
                        self.restore()
                        self.configure_sound()
                    elif action == 'mode':
                        self.set_notification_mode(value)
                    elif action == 'hotkey_status':
                        self.hotkey_warnings.append(value)
                        self.desktop_status.configure(text=' / '.join(self.hotkey_warnings))
                    elif action == 'status':
                        self.desktop_status.configure(text=' / '.join(self.hotkey_warnings) if self.hotkey_warnings else value)
                    continue
                if kind == 'public':
                    self.receive_public(*payload)
                    continue
                self.rss_busy = False
                url, value = payload
                if url != self.settings['rss']:
                    if self.settings['rss']:
                        self.fetch_rss()
                    continue
                if kind == 'error':
                    self.source_status['rss'] = '补充订阅读取失败（未更新）：' + value
                    self.update_feed_status()
                else:
                    new = []
                    for item in reversed(value):
                        if self.add_news(item, announce=False):
                            new.append(item)
                    if new and not self.settings['muted']:
                        self.enqueue_news(new[-1:])
                    self.source_status['rss'] = f'RSS · 新增 {len(new)} 条 · ' + datetime.now().strftime('%H:%M:%S')
                    self.update_feed_status()
                    self.render_news()
        except queue.Empty:
            pass
        self.pending = [n for n in queued_news(self.pending) if should_announce(n, self.settings)]
        if self.pending and not self.is_typing and time.monotonic() >= getattr(self, 'next_speech', 0):
            self.speak(self.pending.pop(0))
        self.root.after(150, self.poll)

    def scheduled_rss(self):
        if self.settings['rss']:
            self.fetch_rss()
        self.root.after(300000, self.scheduled_rss)

    def show_compact(self):
        self.assistant_hidden = False
        if not getattr(self, 'overlay', None):
            from overlay import PetOverlay
            self.overlay = PetOverlay(self, BASE / 'assets' / 'kurumi-sheet-v3.png')
            self.compact = self.overlay.pet
            self.compact_bubble = self.bubble
        self.overlay.show()

    def open_current(self):
        if self.current_item and self.current_item.get('url'):
            webbrowser.open(self.current_item['url'])
        else:
            webbrowser.open('https://www.cls.cn/telegraph')

    def restore(self):
        self.assistant_hidden = False
        if getattr(self, 'overlay', None):
            self.overlay.hide()
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        for win in self.hidden_dialogs:
            if win.winfo_exists():
                win.deiconify()
        self.hidden_dialogs.clear()

    def hide_assistant(self):
        self.resume_compact = bool(getattr(self, 'overlay', None) and self.overlay.active)
        ignored = (self.overlay.pet, self.overlay.bubble) if getattr(self, 'overlay', None) else ()
        self.hidden_dialogs = [w for w in self.root.winfo_children() if isinstance(w, tk.Toplevel) and w not in ignored and w.state() != 'withdrawn']
        for win in self.hidden_dialogs:
            win.withdraw()
        if getattr(self, 'overlay', None):
            self.overlay.hide()
        self.root.withdraw()
        self.assistant_hidden = True

    def toggle_visibility(self):
        if not self.assistant_hidden:
            self.hide_assistant()
        elif self.resume_compact:
            self.show_compact()
        else:
            self.restore()

    def on_window_close(self):
        if self.desktop and self.desktop.ready:
            self.hide_assistant()
        else:
            self.close()

    def close(self):
        if self.reaction_job is not None:
            self.root.after_cancel(self.reaction_job)
            self.reaction_job = None
        self.save()
        self.audio.close()
        if self.desktop:
            self.desktop.close()
        self.root.destroy()


if __name__ == '__main__':
    import sys
    from desktop import SingleInstance, DesktopIntegration
    if len(sys.argv) == 3 and sys.argv[1] == '--self-test-report':
        from release_check import run_check
        raise SystemExit(run_check(Companion, SingleInstance, DesktopIntegration, sys.argv[2]))
    guard = SingleInstance()
    if guard.primary:
        try:
            root = tk.Tk()
            app = Companion(root)
            app.desktop = DesktopIntegration(app, guard)
            root.mainloop()
        finally:
            guard.close()

"""Desktop-only character with a separate, dismissible speech bubble."""
import ctypes
import math
import time
import tkinter as tk
from pathlib import Path
from character import CharacterView
from animations import BubbleAnimator, prevent_activation

KEY = '#010203'
PANEL, TEXT, PINK = '#202231', '#f7f3fa', '#f3a6c6'
MUTED = '#c1c3d3'


class PetOverlay:
    def __init__(self, app, asset: Path):
        self.app = app
        self.root = app.root
        self.active = False
        self.hide_job = None
        self.toolbar_job = None
        self.countdown_job = None
        self.follow_text = True
        self.last_text = None
        self.last_token = None
        self.wrap_cache = None
        self.pet = tk.Toplevel(self.root)
        self.pet.configure(bg=KEY)
        self.bubble = tk.Toplevel(self.root)
        self.animator = BubbleAnimator(self.root, self.bubble)
        self.bubble.configure(bg=PANEL, highlightbackground='#746071', highlightthickness=1)
        for window in (self.pet, self.bubble):
            window.overrideredirect(True)
            window.attributes('-topmost', True)
            try:
                window.wm_attributes('-toolwindow', True)
            except tk.TclError:
                pass
            window.withdraw()
        try:
            self.pet.wm_attributes('-transparentcolor', KEY)
        except tk.TclError:
            pass
        self.character = CharacterView(self.pet, asset, bg=KEY, cursor='fleur', chroma_key=True)
        self.character.pack(fill='both', expand=True)
        self.character.mood = app.mood
        self.character.talking = app.is_typing
        self.character.speech_motion = app.speech_motion
        app.character_views.append(self.character)
        self.unread = tk.Label(self.pet, text='●', bg=KEY, fg=PINK, font=('Microsoft YaHei UI', 16))
        tk.Frame(self.bubble, bg=PINK, height=3).pack(fill='x')
        header = tk.Frame(self.bubble, bg=PANEL)
        self.bubble_header = header
        header.pack(fill='x', padx=18, pady=(10, 6))
        tk.Label(header, text='久留美', bg=PANEL, fg=PINK,
                 font=('Microsoft YaHei UI', 16, 'bold')).pack(side='left')
        self.status = tk.StringVar(value='市场消息')
        tk.Label(header, textvariable=self.status, bg=PANEL, fg=MUTED,
                 font=('Microsoft YaHei UI', 14)).pack(side='left', padx=14)
        self.small_button(header, '收起 ×', lambda: self.hide_bubble(immediate=True)).pack(side='right')
        footer = tk.Frame(self.bubble, bg=PANEL)
        self.bubble_footer = footer
        footer.pack(side='bottom', fill='x', padx=18, pady=(4, 14))
        tk.Frame(footer, bg='#454657', height=1).pack(fill='x', pady=(0, 9))
        self.source = tk.StringVar(value='等待市场消息')
        self.source_label = tk.Label(footer, textvariable=self.source, bg=PANEL, fg=MUTED,
                                     font=('Microsoft YaHei UI', 14), anchor='w', justify='left')
        self.source_label.pack(fill='x', pady=(0, 8))
        actions = tk.Frame(footer, bg=PANEL)
        actions.pack(fill='x')
        self.detail_button = self.small_button(actions, '查看全文 ↗', self.view_message)
        self.detail_button.pack(side='left')
        self.small_button(actions, '字号', app.configure_fonts).pack(side='left', padx=8)
        self.pin_button = self.small_button(actions, '固定消息', self.toggle_autohide)
        self.pin_button.pack(side='right')
        content = tk.Frame(self.bubble, bg=PANEL)
        content.pack(fill='both', expand=True)
        label = tk.Text(content, bg=PANEL, fg=TEXT, font=app.bubble_font, wrap='char',
                        padx=20, pady=12, width=1, height=3, relief='flat', spacing3=7,
                        state='disabled', takefocus=False, cursor='arrow')
        def scroll_text(*args):
            self.follow_text = False
            self.cancel_hide()
            label.yview(*args)
        scrollbar = app.scrollbar(content, scroll_text)
        scrollbar.pack(side='right', fill='y')
        label.configure(yscrollcommand=scrollbar.set)
        label.pack(fill='both', expand=True)
        self.bubble_text = label
        def update_text(*_):
            if not label.winfo_exists():
                return
            item = app.current_item
            raw = app.bubble.get()
            if item and raw.startswith('【'):
                text = raw.split('\n', 1)[1].split('\n\n', 1)[0] if '\n' in raw else ''
            else:
                text = raw
            if self.last_token != app.speech_token:
                self.last_token = app.speech_token
                self.follow_text = True
                self.last_text = None
            self.refresh_footer()
            if text == self.last_text:
                return
            previous_view = label.yview()[0]
            label.configure(state='normal')
            label.delete('1.0', 'end')
            label.insert('1.0', text)
            label.configure(state='disabled')
            if app.is_typing and self.follow_text:
                label.see('end')
            else:
                label.yview_moveto(previous_view if not self.follow_text else 0)
            self.last_text = text
        self.text_trace = app.bubble.trace_add('write', update_text)
        update_text()
        def skip_typing(event):
            app.finish_typing()
            return 'break'
        label.bind('<Button-1>', skip_typing)
        label.bind('<MouseWheel>', self.read_scroll)
        self.bubble.bind('<Enter>', lambda e: self.cancel_hide())
        self.bubble.bind('<Leave>', lambda e: self.end_speech())
        self.toolbar = tk.Frame(self.pet, bg=PANEL)
        self.small_button(self.toolbar, '面板', app.restore).pack(side='left', expand=True)
        self.small_button(self.toolbar, '消息', self.toggle_bubble).pack(side='left', expand=True)
        self.pause_button = self.small_button(self.toolbar, '暂停', self.toggle_pause)
        self.pause_button.pack(side='left', expand=True)
        self.small_button(self.toolbar, '⋯', lambda: self.context_menu(None)).pack(side='right', expand=True)
        for button in self.toolbar.winfo_children():
            button.configure(padx=5)
        self.character.bind('<Button-1>', self.drag_start)
        self.character.bind('<B1-Motion>', self.drag)
        self.character.bind('<ButtonRelease-1>', self.drag_end)
        self.character.bind('<Double-Button-1>', lambda e: app.restore())
        self.pet.bind('<Enter>', lambda e: self.show_toolbar())
        self.pet.bind('<Leave>', lambda e: self.delay_hide_toolbar())
        self.character.bind('<Button-3>', self.context_menu)
        self.pet.bind('<Escape>', lambda e: self.hide_bubble(immediate=True))
        self.bubble.bind('<Escape>', lambda e: self.hide_bubble(immediate=True))
        self.resize(app.settings['pet_size'], save=False)

    def small_button(self, parent, text, command):
        return tk.Button(parent, text=text, command=command, font=('Microsoft YaHei UI', 14),
                         bg='#303346', fg=TEXT, activebackground='#494154', activeforeground=TEXT,
                         relief='flat', bd=0, padx=9, pady=7, cursor='hand2')

    def refresh_footer(self):
        item = self.app.current_item
        if item:
            prefix = '演示 · ' if item.get('demo') else ''
            self.source.set(prefix+item.get('source', '市场消息')+'  ·  '+item.get('received', '')[-8:])
        self.detail_button.configure(state='normal' if item else 'disabled')
        self.pin_button.configure(text='已固定 ✓' if not self.app.settings['bubble_autohide'] else '固定消息')

    def view_message(self):
        if self.app.current_item:
            item = dict(self.app.current_item)
            item.setdefault('published', '来源未提供')
            item.setdefault('url', '')
            self.cancel_hide()
            self.app.view_news(item)

    def read_scroll(self, event):
        self.follow_text = False
        self.cancel_hide()

    def pointer_inside(self):
        x, y = self.bubble.winfo_pointerxy()
        return (self.bubble.winfo_x() <= x < self.bubble.winfo_x()+self.bubble.winfo_width()
                and self.bubble.winfo_y() <= y < self.bubble.winfo_y()+self.bubble.winfo_height())

    def workarea(self):
        try:
            from ctypes import wintypes
            rect = wintypes.RECT()
            if ctypes.windll.user32.SystemParametersInfoW(48, 0, ctypes.byref(rect), 0):
                return rect.left, rect.top, rect.right, rect.bottom
        except (AttributeError, OSError):
            pass
        return 0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight()-45

    def resize(self, size, save=True):
        left, top, right, bottom = self.workarea()
        self.size = size
        height = size+44
        saved = self.app.settings.get('pet_position', [])
        try:
            x, y = saved if len(saved) == 2 else (right-size-24, bottom-height-20)
            x = min(max(left, int(x)), right-size)
            y = min(max(top, int(y)), bottom-height)
        except (TypeError, ValueError):
            x, y = right-size-24, bottom-height-20
        self.pet.geometry(f'{size}x{height}+{x}+{y}')
        self.app.settings['pet_size'] = size
        if save:
            self.app.save()
        self.position_bubble()

    def show(self):
        self.active = True
        self.pet.update_idletasks()
        prevent_activation(self.pet)
        self.pet.deiconify()
        self.root.withdraw()
        self.start_speech()
        if not self.app.is_typing:
            self.end_speech()

    def hide(self):
        self.active = False
        self.cancel_hide()
        self.animator.hide(immediate=True)
        self.pet.withdraw()

    def position_bubble(self):
        left, top, right, bottom = self.workarea()
        self.pet.update_idletasks()
        x, y = self.pet.winfo_x(), self.pet.winfo_y()
        size = self.app.bubble_font.cget('size')
        width = min(right-left, 520 if size <= 20 else 580 if size <= 23 else 640)
        text = self.app.speech_text[self.app.voiced_start:self.app.voiced_end] if self.app.current_item else self.app.bubble.get()
        wrap_key = (size, width, text)
        if self.wrap_cache is None or self.wrap_cache[0] != wrap_key:
            lines, used = 1, 0
            for char in text:
                char_width = self.app.bubble_font.measure(char)
                if char == '\n' or used+char_width > width-60:
                    lines += 1
                    used = 0
                if char != '\n':
                    used += char_width
            self.wrap_cache = (wrap_key, lines)
        lines = self.wrap_cache[1]
        self.source_label.configure(wraplength=width-40)
        self.bubble.update_idletasks()
        chrome = self.bubble_header.winfo_reqheight()+self.bubble_footer.winfo_reqheight()+70
        height = min(bottom-top, 580, max(280, (self.app.bubble_font.metrics('linespace')+7)*lines+chrome))
        bx = x-width-12 if x-width-12 >= left else x+self.size+12
        bx = max(left, min(bx, right-width))
        by = max(top, min(y-30, bottom-height))
        self.bubble_target = (bx, by)
        self.bubble.geometry(f'{width}x{height}+{bx}+{by}')
        if self.animator.target_visible:
            self.animator.show(self.bubble_target)

    def start_speech(self, manual=False):
        self.cancel_hide()
        self.status.set('正在播报…' if self.app.is_typing else '市场消息')
        if self.active:
            if manual or self.app.settings['bubble_autoshow']:
                self.position_bubble()
                self.show_bubble()
            else:
                self.unread.place(relx=.88, rely=.12, anchor='center')

    def show_bubble(self):
        if self.bubble.state() == 'withdrawn':
            self.position_bubble()
        self.unread.place_forget()
        self.animator.show(self.bubble_target)

    def end_speech(self):
        self.cancel_hide()
        self.refresh_footer()
        if not self.app.is_typing and self.follow_text:
            self.bubble_text.yview_moveto(0)
        if self.active and self.app.settings['bubble_autohide'] and not self.app.is_typing:
            if self.pointer_inside():
                self.status.set('正在阅读')
                return
            self.hide_deadline = time.monotonic()+8
            self.hide_job = self.root.after(8000, self.hide_bubble)
            self.update_countdown()

    def update_countdown(self):
        self.countdown_job = None
        if self.hide_job is not None:
            remaining = max(1, math.ceil(self.hide_deadline-time.monotonic()))
            self.status.set(f'{remaining} 秒后收起')
            self.countdown_job = self.root.after(1000, self.update_countdown)

    def cancel_hide(self):
        if self.hide_job is not None:
            self.root.after_cancel(self.hide_job)
            self.hide_job = None
        if self.countdown_job is not None:
            self.root.after_cancel(self.countdown_job)
            self.countdown_job = None
        if hasattr(self, 'status'):
            self.status.set('正在播报…' if self.app.is_typing else '已固定' if not self.app.settings['bubble_autohide'] else '正在阅读')

    def hide_bubble(self, immediate=False):
        self.cancel_hide()
        self.animator.hide(immediate=immediate)

    def toggle_bubble(self):
        if not self.animator.target_visible:
            self.cancel_hide()
            self.show_bubble()
            self.end_speech()
        else:
            self.hide_bubble()

    def show_toolbar(self):
        if self.toolbar_job is not None:
            self.root.after_cancel(self.toolbar_job)
            self.toolbar_job = None
        self.pause_button.configure(text='恢复' if self.app.settings['muted'] else '暂停')
        self.toolbar.place(relx=.5, rely=1, anchor='s', width=self.size, height=44)

    def delay_hide_toolbar(self):
        if self.toolbar_job is not None:
            self.root.after_cancel(self.toolbar_job)
        self.toolbar_job = self.root.after(350, self.hide_toolbar)

    def hide_toolbar(self):
        self.toolbar_job = None
        x, y = self.pet.winfo_pointerxy()
        if not (self.pet.winfo_x() <= x < self.pet.winfo_x()+self.size and
                self.pet.winfo_y() <= y < self.pet.winfo_y()+self.size+44):
            self.toolbar.place_forget()

    def drag_start(self, event):
        self.drag_offset = (event.x_root-self.pet.winfo_x(), event.y_root-self.pet.winfo_y())
        self.drag_origin = event.x_root, event.y_root

    def drag(self, event):
        left, top, right, bottom = self.workarea()
        x = min(max(left, event.x_root-self.drag_offset[0]), right-self.size)
        y = min(max(top, event.y_root-self.drag_offset[1]), bottom-self.size-44)
        self.pet.geometry(f'+{x}+{y}')
        self.position_bubble()

    def drag_end(self, event):
        if abs(event.x_root-self.drag_origin[0])+abs(event.y_root-self.drag_origin[1]) < 5:
            self.toggle_bubble()
        else:
            self.app.settings['pet_position'] = [self.pet.winfo_x(), self.pet.winfo_y()]
            self.app.save()

    def toggle_pause(self):
        self.app.toggle_mute()
        self.show_toolbar()

    def toggle_autohide(self):
        self.app.settings['bubble_autohide'] = not self.app.settings['bubble_autohide']
        self.app.save()
        self.end_speech()

    def toggle_autoshow(self):
        self.app.settings['bubble_autoshow'] = not self.app.settings['bubble_autoshow']
        self.app.save()
        if not self.app.settings['bubble_autoshow']:
            self.hide_bubble(immediate=True)

    def context_menu(self, event):
        if getattr(self, 'menu', None):
            self.menu.destroy()
        menu = tk.Menu(self.pet, tearoff=False)
        self.menu = menu
        menu.add_command(label='显示 / 收起消息', command=self.toggle_bubble)
        menu.add_command(label='恢复自动播报' if self.app.settings['muted'] else '暂停自动播报', command=self.toggle_pause)
        auto = tk.BooleanVar(value=self.app.settings['bubble_autoshow'])
        menu.add_checkbutton(label='新消息自动弹出气泡', variable=auto, command=self.toggle_autoshow)
        variable = tk.BooleanVar(value=self.app.settings['bubble_autohide'])
        self.menu_vars = [auto, variable]
        menu.add_checkbutton(label='播完自动收起气泡', variable=variable, command=self.toggle_autohide)
        sizes = tk.Menu(menu, tearoff=False)
        for label, size in [('小', 200), ('中', 260), ('大', 320)]:
            sizes.add_command(label=label, command=lambda s=size: self.resize(s))
        menu.add_cascade(label='角色大小', menu=sizes)
        menu.add_command(label='字体大小…', command=self.app.configure_fonts)
        menu.add_separator()
        menu.add_command(label='打开完整面板', command=self.app.restore)
        menu.add_command(label='退出', command=self.app.close)
        try:
            menu.tk_popup(event.x_root if event else self.pet.winfo_pointerx(), event.y_root if event else self.pet.winfo_pointery())
        finally:
            menu.grab_release()

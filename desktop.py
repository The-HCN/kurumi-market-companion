"""Windows single instance, tray and hotkeys; callbacks only enter the UI queue."""
from __future__ import annotations
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import sys
import threading
import time
from app_paths import BASE

if (BASE / '.runtime').is_dir():
    sys.path.append(str(BASE / '.runtime'))


class SingleInstance:
    def __init__(self, scope='Kurumi.MarketCompanion.Desktop'):
        self.primary = True
        self.mutex = self.event = None
        self.scope = scope
        if os.name != 'nt':
            return
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        self.kernel.CreateMutexW.restype = wintypes.HANDLE
        self.kernel.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
        self.kernel.CreateEventW.restype = wintypes.HANDLE
        self.kernel.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
        self.kernel.OpenEventW.restype = wintypes.HANDLE
        self.kernel.SetEvent.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        ctypes.set_last_error(0)
        self.mutex = self.kernel.CreateMutexW(None, False, 'Local\\'+scope)
        if not self.mutex:
            raise ctypes.WinError(ctypes.get_last_error())
        self.primary = ctypes.get_last_error() != 183
        event_name = 'Local\\'+scope+'.Activate'
        if self.primary:
            self.event = self.kernel.CreateEventW(None, False, False, event_name)
            if not self.event:
                self.close()
                raise ctypes.WinError(ctypes.get_last_error())
        else:
            for _ in range(30):
                event = self.kernel.OpenEventW(0x0002, False, event_name)
                if event:
                    self.kernel.SetEvent(event)
                    self.kernel.CloseHandle(event)
                    break
                time.sleep(.05)
            self.close()

    def activated(self):
        return bool(self.event and self.kernel.WaitForSingleObject(self.event, 0) == 0)

    def close(self):
        for name in ('event', 'mutex'):
            handle = getattr(self, name, None)
            if handle:
                self.kernel.CloseHandle(handle)
                setattr(self, name, None)


class DesktopIntegration:
    def __init__(self, app, guard):
        self.app, self.guard = app, guard
        self.tray = None
        self.ready = False
        self.closed = False
        self.hotkey_thread_id = None
        self.hotkey_stop = threading.Event()
        self.mode = app.settings['notification_mode']
        self.muted = app.settings['muted']
        self.tray_thread = threading.Thread(target=self.run_tray, daemon=True)
        self.tray_thread.start()
        self.hotkey_thread = threading.Thread(target=self.run_hotkeys, daemon=True)
        self.hotkey_thread.start()

    def emit(self, action, value=None):
        if not self.closed:
            self.app.inbox.put(('desktop', (action, value)))

    def run_tray(self):
        try:
            import pystray
            from PIL import Image
            item, menu = pystray.MenuItem, pystray.Menu
            def action(name, value=None):
                return lambda icon, selected: self.emit(name, value)
            modes = menu(*(item(label, action('mode', key), radio=True,
                                checked=lambda selected, k=key: self.mode == k)
                           for key, label in [('all', '全部消息'), ('important', '重要消息'), ('manual', '仅手动查看')]))
            self.tray = pystray.Icon('KurumiMarket', Image.open(BASE/'assets'/'kurumi.ico'), '久留美 · 市场陪伴助手', menu(
                item('打开面板  Ctrl+Alt+M', action('restore'), default=True),
                item('显示悬浮人物', action('compact')),
                item('显示 / 隐藏助手  Ctrl+Alt+K', action('toggle')),
                item('提醒分档', modes),
                item('消息提示音…', action('sound_settings')),
                item(lambda selected: '恢复自动播报' if self.muted else '暂停自动播报', action('pause')),
                menu.SEPARATOR, item('退出', action('exit'))))
            def setup(icon):
                if not self.closed:
                    icon.visible = True
                    self.ready = True
                    self.emit('status', '托盘已就绪 · Ctrl+Alt+K 显示/隐藏 · Ctrl+Alt+M 面板')
                else:
                    icon.stop()
            self.tray.run(setup=setup)
        except Exception as exc:
            self.error = str(exc)
            self.emit('status', '托盘不可用，关闭按钮将直接退出；可重新安装 pystray')
        finally:
            self.ready = False

    def run_hotkeys(self):
        if os.name != 'nt':
            return
        user = ctypes.WinDLL('user32', use_last_error=True)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        user.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        user.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        user.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        self.hotkey_thread_id = kernel.GetCurrentThreadId()
        # Create this thread's queue before close() can post WM_QUIT.
        msg = wintypes.MSG()
        user.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)
        registered = []
        try:
            for key, letter in [(1, 'K'), (2, 'M')]:
                if user.RegisterHotKey(None, key, 0x4003, ord(letter)):
                    registered.append(key)
                else:
                    self.emit('hotkey_status', 'Ctrl+Alt+'+letter+' 已被占用，请使用托盘菜单')
            self.hotkeys = tuple(registered)
            self.hotkeys_ready = True
            if self.hotkey_stop.is_set():
                return
            while user.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == 0x0312:
                    self.emit('toggle' if msg.wParam == 1 else 'restore')
        finally:
            for key in registered:
                user.UnregisterHotKey(None, key)

    def sync(self):
        self.mode = self.app.settings['notification_mode']
        self.muted = self.app.settings['muted']
        if self.ready and self.tray:
            self.tray.update_menu()

    def close(self):
        self.closed = True
        self.hotkey_stop.set()
        if self.tray:
            self.tray.stop()
        if self.hotkey_thread_id:
            ctypes.windll.user32.PostThreadMessageW(self.hotkey_thread_id, 0x0012, 0, 0)
        if self.hotkey_thread.is_alive():
            self.hotkey_thread.join(timeout=1)

"""Cancellable Tk transitions for a non-activating speech window."""
import ctypes
import os
import time


def ease_out_cubic(progress):
    return 1 - (1 - max(0, min(1, progress))) ** 3


def prevent_activation(window):
    if os.name != 'nt':
        return
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.GetParent.argtypes = [ctypes.c_void_p]
    user.GetParent.restype = ctypes.c_void_p
    hwnd = user.GetParent(window.winfo_id())
    get_style = user.GetWindowLongPtrW if ctypes.sizeof(ctypes.c_void_p) == 8 else user.GetWindowLongW
    set_style = user.SetWindowLongPtrW if ctypes.sizeof(ctypes.c_void_p) == 8 else user.SetWindowLongW
    get_style.argtypes = [ctypes.c_void_p, ctypes.c_int]
    get_style.restype = ctypes.c_ssize_t
    set_style.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
    set_style.restype = ctypes.c_ssize_t
    set_style(hwnd, -20, get_style(hwnd, -20) | 0x08000000 | 0x80)  # NOACTIVATE | TOOLWINDOW


class BubbleAnimator:
    def __init__(self, root, window):
        self.root, self.window = root, window
        self.job = None
        self.target_visible = False
        self.target = (0, 0)

    def cancel(self):
        if self.job is not None:
            self.root.after_cancel(self.job)
            self.job = None

    def show(self, target):
        self.target = target
        if self.target_visible and self.job is None and self.window.state() != 'withdrawn':
            self.window.geometry(f'+{target[0]}+{target[1]}')
            return
        self.cancel()
        hidden = self.window.state() == 'withdrawn'
        alpha = 0.0 if hidden else float(self.window.attributes('-alpha'))
        y = target[1]+14 if hidden else self.window.winfo_y()
        self.window.attributes('-alpha', alpha)
        self.window.geometry(f'+{target[0]}+{y}')
        self.window.update_idletasks()
        prevent_activation(self.window)
        self.target_visible = True
        self.window.deiconify()
        self.transition(alpha, 1.0, y, target[1], .24)

    def hide(self, immediate=False):
        self.cancel()
        self.target_visible = False
        if immediate or self.window.state() == 'withdrawn':
            self.window.withdraw()
            self.window.attributes('-alpha', 1.0)
            return
        self.transition(float(self.window.attributes('-alpha')), 0.0,
                        self.window.winfo_y(), self.target[1]+8, .16)

    def transition(self, start_alpha, end_alpha, start_y, end_y, duration):
        started = time.monotonic()
        def step():
            self.job = None
            progress = min(1.0, (time.monotonic()-started)/duration)
            eased = ease_out_cubic(progress)
            self.window.attributes('-alpha', start_alpha+(end_alpha-start_alpha)*eased)
            self.window.geometry(f'+{self.target[0]}+{round(start_y+(end_y-start_y)*eased)}')
            if progress < 1:
                self.job = self.root.after(16, step)
            elif not self.target_visible:
                self.window.withdraw()
                self.window.attributes('-alpha', 1.0)
        step()

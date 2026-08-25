from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass

from PIL import ImageGrab


user32 = ctypes.windll.user32


@dataclass
class WindowInfo:
    hwnd: int
    title: str
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    def label(self) -> str:
        return f"{self.title}  ({self.width}x{self.height})"


def list_windows() -> list[WindowInfo]:
    windows: list[WindowInfo] = []
    enum_proc_type = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    @enum_proc_type
    def enum_proc(hwnd: wintypes.HWND, _lparam: wintypes.LPARAM) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        title = buffer.value.strip()
        if not title:
            return True
        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return True
        if rect.right - rect.left < 240 or rect.bottom - rect.top < 160:
            return True
        windows.append(WindowInfo(int(hwnd), title, rect.left, rect.top, rect.right, rect.bottom))
        return True

    user32.EnumWindows(enum_proc, 0)
    return windows


def capture_window(window: WindowInfo):
    """Capture the visible client area of a selected window without sending input."""
    if not user32.IsWindow(window.hwnd):
        raise RuntimeError("选中的窗口已经关闭，请重新刷新窗口列表。")
    if user32.IsIconic(window.hwnd):
        raise RuntimeError("选中的窗口已最小化，请先恢复窗口。")
    rect = wintypes.RECT()
    if not user32.GetWindowRect(window.hwnd, ctypes.byref(rect)):
        raise RuntimeError("无法读取选中窗口的当前位置。")
    if rect.right - rect.left < 1 or rect.bottom - rect.top < 1:
        raise RuntimeError("选中的窗口当前没有可截取区域。")
    # Refresh the cached metadata on every frame. The window can move or resize
    # after the user selected it, while its HWND remains stable.
    window.left = rect.left
    window.top = rect.top
    window.right = rect.right
    window.bottom = rect.bottom
    bbox = (rect.left, rect.top, rect.right, rect.bottom)
    try:
        return ImageGrab.grab(bbox=bbox, all_screens=True, include_layered_windows=True).convert("RGB")
    except TypeError:
        return ImageGrab.grab(bbox=bbox, all_screens=True).convert("RGB")

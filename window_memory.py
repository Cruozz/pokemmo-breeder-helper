"""Remember the main window without touching inventory or game windows."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import sys

from storage import data_dir


def monitor_workareas(root) -> list[tuple[int, int, int, int]]:
    if sys.platform == "win32":
        class MonitorInfo(ctypes.Structure):
            _fields_ = [("size", wintypes.DWORD), ("monitor", wintypes.RECT),
                        ("work", wintypes.RECT), ("flags", wintypes.DWORD)]

        user32 = ctypes.windll.user32
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
                                           ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
        user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MonitorInfo)]
        areas = []

        def collect(monitor, _dc, _rect, _data):
            info = MonitorInfo()
            info.size = ctypes.sizeof(info)
            if user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                r = info.work
                areas.append((r.left, r.top, r.right, r.bottom))
            return True

        user32.EnumDisplayMonitors(None, None, callback_type(collect), 0)
        if areas:
            return areas
    return [(0, 0, root.winfo_screenwidth(), root.winfo_screenheight())]


def visible_state(state: dict, areas: list[tuple[int, int, int, int]]) -> dict:
    """Keep valid positions, including negative coordinates on secondary screens."""
    state = dict(state)
    x, y, w, h = (state[key] for key in ("x", "y", "width", "height"))
    if any(left <= x < right - 64 and top <= y < bottom - 64 for left, top, right, bottom in areas):
        return state
    left, top, right, bottom = min(areas, key=lambda area:
        max(area[0] - x, 0, x - area[2]) ** 2 + max(area[1] - y, 0, y - area[3]) ** 2)
    state.update(width=min(w, right - left), height=min(h, bottom - top),
                 x=max(left, min(x, right - min(w, right - left))),
                 y=max(top, min(y, bottom - min(h, bottom - top))))
    return state


class WindowMemory:
    def __init__(self, root, path: Path | None = None) -> None:
        self.root = root
        self.path = path if path is not None else data_dir() / "window_state.json"
        self.normal = None
        self.maximized = False
        self.pending = None
        try:
            state = json.loads(self.path.read_text(encoding="utf-8"))
            if (isinstance(state, dict) and all(type(state.get(key)) is int for key in ("width", "height", "x", "y"))
                    and 700 <= state["width"] <= 20000 and 600 <= state["height"] <= 20000
                    and abs(state["x"]) <= 100000 and abs(state["y"]) <= 100000
                    and type(state.get("maximized")) is bool):
                state = visible_state(state, monitor_workareas(root))
                self.normal = {key: state[key] for key in ("width", "height", "x", "y")}
                self.maximized = state["maximized"]
                root.geometry(f'{state["width"]}x{state["height"]}+{state["x"]}+{state["y"]}')
                if self.maximized:
                    root.after_idle(lambda: root.state("zoomed"))
        except (OSError, ValueError, TypeError):
            pass
        root.bind("<Configure>", self._schedule, add="+")
        root.bind("<Map>", self._schedule, add="+")

    def _schedule(self, event) -> None:
        if event.widget is not self.root:
            return
        if self.pending is not None:
            self.root.after_cancel(self.pending)
        self.pending = self.root.after_idle(self._remember)

    def _remember(self) -> None:
        self.pending = None
        state = self.root.state()
        if state == "normal" and self.root.winfo_ismapped():
            width, height = self.root.winfo_width(), self.root.winfo_height()
            if width >= 700 and height >= 600:
                self.normal = dict(width=width, height=height, x=self.root.winfo_x(), y=self.root.winfo_y())
                self.maximized = False
        elif state == "zoomed":
            self.maximized = True

    def save(self) -> None:
        self._remember()
        if self.normal is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps({**self.normal, "maximized": self.maximized}) + "\n", encoding="utf-8")
        temporary.replace(self.path)

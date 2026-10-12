"""Remember the main window without touching inventory or game windows."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import sys

from storage import data_dir


def _logical_workarea(root, user32, area):
    converter = getattr(user32, "PhysicalToLogicalPointForPerMonitorDPI", None)
    if converter is None:
        return area
    converter.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    converter.restype = wintypes.BOOL
    first, last = wintypes.POINT(*area[:2]), wintypes.POINT(*area[2:])
    if converter(root.winfo_id(), ctypes.byref(first)) and converter(root.winfo_id(), ctypes.byref(last)):
        return first.x, first.y, last.x, last.y
    return area


def monitor_workareas(root) -> list[tuple[int, int, int, int]]:
    if sys.platform == "win32":
        class MonitorInfo(ctypes.Structure):
            _fields_ = [("size", wintypes.DWORD), ("monitor", wintypes.RECT),
                        ("work", wintypes.RECT), ("flags", wintypes.DWORD)]

        user32 = ctypes.windll.user32
        root.winfo_id()  # Create the Tk HWND before temporarily changing thread awareness.
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
                                           ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
        user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MonitorInfo)]
        areas = []

        def collect(monitor, _dc, _rect, _data):
            info = MonitorInfo()
            info.size = ctypes.sizeof(info)
            if user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                r = info.work
                areas.append(_logical_workarea(root, user32, (r.left, r.top, r.right, r.bottom)))
            return True

        from capture import physical_coordinates
        with physical_coordinates():
            user32.EnumDisplayMonitors(None, None, callback_type(collect), 0)
        if areas:
            return areas
    return [(0, 0, root.winfo_screenwidth(), root.winfo_screenheight())]


def visible_state(state: dict, areas: list[tuple[int, int, int, int]]) -> dict:
    """Keep valid positions, including negative coordinates on secondary screens."""
    state = dict(state)
    x, y, w, h = (state[key] for key in ("x", "y", "width", "height"))
    for left, top, right, bottom in areas:
        if left <= x < right - 64 and top <= y < bottom - 64:
            state.update(width=min(w, right-left-16), height=min(h, bottom-top-40))
            state.update(x=min(x, right-state["width"]), y=min(y, bottom-state["height"]))
            return state
    left, top, right, bottom = min(areas, key=lambda area:
        max(area[0] - x, 0, x - area[2]) ** 2 + max(area[1] - y, 0, y - area[3]) ** 2)
    state.update(width=min(w, right - left-16), height=min(h, bottom - top-40),
                 x=max(left, min(x, right - min(w, right - left-16))),
                 y=max(top, min(y, bottom - min(h, bottom - top-40))))
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
                    and 600 <= state["width"] <= 20000 and 420 <= state["height"] <= 20000
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
            if width >= 600 and height >= 420:
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

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk
import webbrowser

from PIL import Image, ImageTk

from guide_data import TYPE_LABELS
from live_data import (
    INTERVALS, SOURCE_URLS, AlphaReport, CaveRotation, FeedError, LiveClient,
    alpha_status, cave_status, load_cache, local_time, location_label, save_cache,
)
from pokedex_portrait import PokedexPortrait, PortraitAtlas
from species_data import get_species_database
from storage import data_dir


@dataclass
class FeedState:
    data: AlphaReport | CaveRotation | None = None
    verified_at: float = 0
    confirmed: bool = False
    error: str = ""
    failures: int = 0
    next_due: float = 0
    retry_until: float = 0


class EncounterSlot(ttk.Frame):
    def __init__(self, parent, atlas, database):
        super().__init__(parent, padding=(3, 2))
        self.atlas, self.database = atlas, database
        self.photo = None
        self.name = None
        self.image_label = ttk.Label(self, anchor="center")
        self.image_label.pack(fill="x")
        self.name_label = ttk.Label(self, text="未上报", anchor="center", wraplength=108)
        self.name_label.pack(fill="x")
        self.set_name("")

    def set_name(self, name):
        if self.name == name:
            return
        self.name = name
        record = self.database.get(name) if name else None
        self.name_label.configure(text=record.display_name if record else name or "未上报")
        self.photo = None
        if record:
            try:
                picture = self.atlas.crop(record.id).resize((64, 64), Image.Resampling.NEAREST)
                self.photo = ImageTk.PhotoImage(picture, master=self)
            except (OSError, ValueError):
                pass
        if self.photo is None:
            picture = Image.new("RGBA", (64, 64))
            self.photo = ImageTk.PhotoImage(picture, master=self)
        self.image_label.configure(image=self.photo)


class LiveWorkspace(ttk.Frame):
    """Network workers only write a queue; every Tk operation stays on the UI thread."""
    def __init__(self, parent, *, client=None, cache_path: Path | None = None, autostart=True):
        super().__init__(parent, style="Panel.TFrame", padding=12)
        self.client = client if client is not None else LiveClient()
        self.cache_path = cache_path if cache_path is not None else data_dir() / "live_events_cache.json"
        self.feeds = {"alpha": FeedState(), "cave": FeedState()}
        self.result_queue = queue.Queue()
        self.in_flight = False
        self.closed = False
        self.network_enabled = autostart
        self.last_request = -1000.0
        self.active_kinds = set()
        self.poll_after = None
        self.database = get_species_database()
        self.atlas = PortraitAtlas()
        cached = load_cache(self.cache_path)
        for kind, (record, verified) in cached.get("feeds", {}).items():
            self.feeds[kind].data = record
            self.feeds[kind].verified_at = verified
        interval = cached.get("interval", 60)
        self.interval_var = tk.StringVar(self, next((name for name, seconds in INTERVALS.items() if seconds == interval), "1 分钟"))
        self.auto_var = tk.BooleanVar(self, cached.get("auto", True) is not False)
        self.status_vars = {kind: tk.StringVar(self, "尚未刷新") for kind in self.feeds}
        self.clock_vars = {kind: tk.StringVar(self, "") for kind in self.feeds}

        controls = ttk.Frame(self)
        controls.pack(fill="x", pady=(0, 10))
        ttk.Label(controls, text="实时情报", font=("Microsoft YaHei UI", 14, "bold")).pack(side="left")
        self.refresh_button = ttk.Button(controls, text="立即刷新", command=lambda: self.refresh(manual=True))
        self.refresh_button.pack(side="right")
        self.interval_combo = ttk.Combobox(controls, textvariable=self.interval_var, values=list(INTERVALS), state="readonly", width=8)
        self.interval_combo.pack(side="right", padx=8)
        self.interval_combo.bind("<<ComboboxSelected>>", self.settings_changed)
        self.auto_check = ttk.Checkbutton(controls, text="自动刷新", variable=self.auto_var, command=self.settings_changed)
        self.auto_check.pack(side="right")
        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True)
        self.alpha_page = ttk.Frame(self.tabs, padding=12)
        self.cave_page = ttk.Frame(self.tabs, padding=12)
        self.tabs.add(self.alpha_page, text="当前头目")
        self.tabs.add(self.cave_page, text="变化洞窟")

        self.alpha_status = tk.StringVar(self, "正在等待头目资料")
        ttk.Label(self.alpha_page, textvariable=self.alpha_status, style="Field.TLabel", wraplength=590).pack(fill="x", pady=(0, 12))
        alpha_body = ttk.Frame(self.alpha_page)
        alpha_body.pack(fill="both", expand=True)
        self.alpha_portrait = PokedexPortrait(alpha_body)
        self.alpha_portrait.pack(side="left", anchor="n", padx=(0, 18))
        alpha_info = ttk.Frame(alpha_body)
        alpha_info.pack(side="left", fill="both", expand=True)
        self.alpha_name = tk.StringVar(self, "—")
        self.alpha_location = tk.StringVar(self, "")
        self.alpha_time = tk.StringVar(self, "")
        ttk.Label(alpha_info, textvariable=self.alpha_name, font=("Microsoft YaHei UI", 20, "bold")).pack(anchor="w", pady=(12, 14))
        self.location_label = ttk.Label(alpha_info, textvariable=self.alpha_location, wraplength=360)
        self.location_label.pack(anchor="w", pady=(0, 12))
        ttk.Label(alpha_info, textvariable=self.alpha_time, justify="left").pack(anchor="w")
        alpha_info.bind("<Configure>", lambda event: self.location_label.configure(wraplength=max(150, event.width - 12)))
        self._footer(self.alpha_page, "alpha")

        self.cave_status = tk.StringVar(self, "正在等待洞窟资料")
        self.gem_type = tk.StringVar(self, "宝石属性：—")
        ttk.Label(self.cave_page, textvariable=self.cave_status, style="Field.TLabel").pack(anchor="w", pady=(0, 3))
        ttk.Label(self.cave_page, textvariable=self.gem_type, style="Muted.TLabel").pack(anchor="w", pady=(0, 7))
        self.cave_slots = {}
        singles = ttk.LabelFrame(self.cave_page, text="普通单遇", padding=4)
        singles.pack(fill="x", pady=(0, 8))
        self._slots(singles, "singles", 5)
        lower = ttk.Frame(self.cave_page)
        lower.pack(fill="x")
        lower.columnconfigure((0, 1), weight=1, uniform="groups")
        for col, key, title in ((0, "rare_singles", "稀有单遇"), (1, "hordes", "三只群怪")):
            frame = ttk.LabelFrame(lower, text=title, padding=4)
            frame.grid(row=0, column=col, sticky="nsew", padx=(0, 8) if col == 0 else (0, 0))
            self._slots(frame, key, 2)
        self._footer(self.cave_page, "cave")
        for kind in self.feeds:
            self.render(kind)
        self.poll_after = self.after(100, self._tick)

    @property
    def interval(self):
        return INTERVALS.get(self.interval_var.get(), 60)

    def _slots(self, parent, key, count):
        self.cave_slots[key] = []
        for column in range(count):
            parent.columnconfigure(column, weight=1, uniform=key)
            slot = EncounterSlot(parent, self.atlas, self.database)
            slot.grid(row=0, column=column, sticky="nsew")
            self.cave_slots[key].append(slot)

    def _footer(self, parent, kind):
        footer = ttk.Frame(parent)
        footer.pack(side="bottom", fill="x", pady=(12, 0))
        ttk.Label(footer, textvariable=self.status_vars[kind], wraplength=560).pack(anchor="w")
        line = ttk.Frame(footer)
        line.pack(fill="x", pady=(4, 0))
        ttk.Label(line, textvariable=self.clock_vars[kind], style="Muted.TLabel").pack(side="left")
        ttk.Button(line, text="来源网页", command=lambda: webbrowser.open(SOURCE_URLS[kind])).pack(side="right")

    def settings_changed(self, _event=None):
        now = time.monotonic()
        for state in self.feeds.values():
            state.next_due = max(state.retry_until, now + self.interval)
        self._save()

    def _save(self):
        try:
            save_cache(self.cache_path, self.feeds, self.interval, self.auto_var.get())
        except OSError:
            # Read-only storage must not break live queries or the inventory.
            pass

    def refresh(self, manual=False):
        now = time.monotonic()
        if self.closed or self.in_flight or now - self.last_request < 15:
            return
        kinds = [kind for kind, state in self.feeds.items()
                 if now >= state.retry_until and (manual or now >= state.next_due)]
        if not kinds:
            return
        self.in_flight = True
        self.last_request = now
        self.active_kinds = set(kinds)
        self.refresh_button.configure(state="disabled")
        threading.Thread(target=LiveWorkspace._fetch, args=(self.client, self.result_queue, kinds),
                         name="pokemmo-live-info", daemon=True).start()

    @staticmethod
    def _fetch(client, result_queue, kinds):
        for kind in kinds:
            try:
                report = client.fetch(kind)
                result_queue.put((kind, report, None))
            except Exception as error:
                safe_error = error if isinstance(error, FeedError) else FeedError("读取资料失败，稍后重试。")
                result_queue.put((kind, None, safe_error))
        result_queue.put((None, None, None))

    def _apply_result(self, kind, report, error):
        now = time.monotonic()
        state = self.feeds[kind]
        self.active_kinds.discard(kind)
        if error is None:
            state.data = report
            state.verified_at = time.time()
            state.confirmed = True
            state.error = ""
            state.failures = 0
            state.retry_until = 0
            state.next_due = now + self.interval
            self._save()
        else:
            state.error = str(error)
            state.failures += 1
            delay = max(min(900, self.interval * 2 ** min(state.failures, 5)), getattr(error, "retry_after", 0))
            state.next_due = now + delay
            state.retry_until = now + getattr(error, "retry_after", 0)
        self.render(kind)

    def _tick(self):
        self.poll_after = None
        if self.closed:
            return
        while True:
            try:
                kind, report, error = self.result_queue.get_nowait()
            except queue.Empty:
                break
            if kind is None:
                self.in_flight = False
                self.active_kinds.clear()
            else:
                self._apply_result(kind, report, error)
        now = time.monotonic()
        if self.network_enabled and self.auto_var.get() and any(now >= state.next_due for state in self.feeds.values()):
            self.refresh()
        can_refresh = not self.in_flight and now - self.last_request >= 15 and any(now >= state.retry_until for state in self.feeds.values())
        self.refresh_button.configure(state="normal" if can_refresh else "disabled")
        self.update_status()
        self.poll_after = self.after(250, self._tick)

    def update_status(self):
        now, mono = time.time(), time.monotonic()
        for kind, state in self.feeds.items():
            if kind in self.active_kinds:
                text = "正在刷新…"
            elif state.error:
                text = state.error + (" 显示上次资料，当前状态待确认。" if state.data else "")
            elif not state.confirmed and state.data is not None:
                text = "上次缓存 · 当前状态待联网确认"
            elif state.data is None:
                text = "尚未获取资料" if not self.auto_var.get() else "等待刷新…"
            elif now - state.verified_at > max(180, self.interval * 2 + 30):
                text = "资料尚未更新 · 当前状态待确认"
            else:
                text = "Alphapedia 社区上报 · 时间为本机时间"
            self.status_vars[kind].set(text)
            freshness = "最近获取 " + local_time(state.verified_at) if state.verified_at else "尚无成功获取记录"
            cadence = f"{max(0, int(state.next_due - mono))} 秒后刷新" if self.auto_var.get() else "自动刷新已暂停"
            self.clock_vars[kind].set(freshness + "  ·  " + cadence)
        if self.feeds["alpha"].data:
            state = self.feeds["alpha"]
            text = alpha_status(state.data, now)
            if self._stale(state, now) and state.data.expires_at and now < state.data.expires_at:
                text = "当前是否出现待确认 · 以下为上次记录"
            self.alpha_status.set(text)
        if self.feeds["cave"].data:
            state = self.feeds["cave"]
            text = cave_status(state.data, now)
            if self._stale(state, now) and state.data.starts_at <= now < state.data.expires_at:
                text = "当前轮换待确认 · " + text
            self.cave_status.set(text)

    def _stale(self, state, now):
        return not state.confirmed or bool(state.error) or now - state.verified_at > max(180, self.interval * 2 + 30)

    def render(self, kind):
        report = self.feeds[kind].data
        if report is None:
            return
        if kind == "alpha":
            record = self.database.get_by_id(report.species_id) if report.species_id else self.database.get(report.name)
            name = record.display_name if record else report.name
            self.alpha_name.set(name)
            self.alpha_portrait.set_species(record.id if record else None, name)
            self.alpha_location.set(location_label(report.region, report.location))
            self.alpha_time.set(f"上报时间  {local_time(report.reported_at)}\n预计结束  {local_time(report.expires_at)}")
        else:
            self.gem_type.set("宝石属性：" + TYPE_LABELS.get(report.gem_type.upper(), report.gem_type or "未上报"))
            for key, slots in self.cave_slots.items():
                for slot, name in zip(slots, getattr(report, key)):
                    slot.set_name(name)
        self.update_status()

    def destroy(self):
        self.closed = True
        if self.poll_after is not None:
            self.after_cancel(self.poll_after)
            self.poll_after = None
        self.atlas.close()
        super().destroy()

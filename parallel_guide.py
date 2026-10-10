"""Offline HTML guide hosted in an owned native child window, loaded on demand."""
from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
from tkinter import ttk

BASE_DIR = Path(__file__).resolve().parent
GUIDE_TITLE = "平行五通攻略"


def guide_site() -> Path:
    return BASE_DIR / "assets" / "parallel-guide"


def guide_runtime() -> Path:
    if getattr(sys, "frozen", False):
        return BASE_DIR / "parallel-guide-runtime"
    return BASE_DIR / ".runtime" / "parallel-guide-host"


def guide_profile() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "PokeMMO-Breeder-Helper" / "parallel-guide" / "profile"


def verify_guide_assets() -> dict:
    import hashlib
    site = guide_site()
    manifest = json.loads((site / "manifest.json").read_text(encoding="utf-8"))
    for record in manifest["files"]:
        path = site / record["path"]
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
            raise RuntimeError(f"攻略资源缺失或损坏：{record['path']}")
    return {"phases": manifest["phases"], "steps": manifest["steps"], "files": len(manifest["files"]),
            "draft_sha256": manifest["draft_sha256"]}


def run_guide_self_test(parent, directory: Path) -> dict:
    """Exercise the shipped host in an isolated profile, including reopening it."""
    assets = verify_guide_assets()
    withdrawn = parent.state() == "withdrawn"
    previous_geometry = parent.geometry()
    if withdrawn:
        # A withdrawn Tk window has a 1px native client area. Map transparently
        # so the real child window is tested at the supported minimum width.
        parent.attributes("-alpha", 0.0)
        parent.geometry("700x600+0+0")
        parent.deiconify()
        parent.update()
    frame = ttk.Frame(parent, width=700, height=500)
    frame.pack()
    parent.update_idletasks()
    try:
        reports = []
        for attempt in range(2):
            report_path = directory / f"guide-test-{attempt}.json"
            process = subprocess.Popen([
                str(guide_runtime() / "ParallelGuideHost.exe"), "--parent", str(frame.winfo_id()),
                "--owner-pid", str(os.getpid()), "--site", str(guide_site()),
                "--profile", str(directory / "guide-profile"), "--self-test", str(report_path),
            ], cwd=str(guide_runtime()), creationflags=subprocess.CREATE_NO_WINDOW)
            deadline = time.monotonic() + 40
            try:
                while process.poll() is None and time.monotonic() < deadline:
                    parent.update()
                    time.sleep(0.03)
                if process.poll() is None:
                    raise RuntimeError("攻略阅读组件自检超时")
                report = json.loads(report_path.read_text(encoding="utf-8-sig"))
                if process.returncode != 0 or not report.get("ok") or not report.get("embedded"):
                    raise RuntimeError(f"攻略阅读组件自检失败：{report}")
                if attempt and not report.get("progress_on_open"):
                    raise RuntimeError("攻略阅读进度未能跨进程重启保留")
                for path in report.pop("image_paths", []):
                    if not (guide_site() / path).is_file():
                        raise RuntimeError(f"配图缺失：{path}")
                reports.append(report)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
        return {**assets, "host": reports[-1], "reopen_progress": True, "isolated_profile": True}
    finally:
        frame.destroy()
        if withdrawn:
            parent.withdraw()
            parent.geometry(previous_geometry)
            parent.attributes("-alpha", 1.0)


class ParallelGuideWorkspace(ttk.Frame):
    def __init__(self, parent, *, autostart: bool = True, profile: Path | None = None):
        super().__init__(parent, style="App.TFrame")
        self.profile = profile or guide_profile()
        self.autostart = autostart
        self.process = None
        self.poll_id = None
        self.status_path = None
        self.message = ttk.Label(self, text="正在打开平行五通攻略…", anchor="center", justify="center")
        self.message.pack(fill="both", expand=True)
        self.retry_button = ttk.Button(self, text="重新打开攻略", command=self.start)
        self.bind("<Map>", self._on_map, add="+")
        self.bind("<Destroy>", self._on_destroy, add="+")

    def _on_map(self, event):
        if event.widget is self and self.autostart and self.process is None:
            self.after_idle(self.start)

    def start(self):
        if self.process is not None and self.process.poll() is None:
            return
        self.retry_button.pack_forget()
        self.message.configure(text="正在打开平行五通攻略…")
        self.message.pack(fill="both", expand=True)
        try:
            if os.name != "nt":
                raise RuntimeError("攻略内嵌页面需要 Windows 10／11。")
            executable = guide_runtime() / "ParallelGuideHost.exe"
            if not executable.is_file():
                raise RuntimeError("缺少攻略阅读组件，请重新下载完整版本。\n源码运行请先执行 scripts/build-parallel-guide-host.ps1。")
            if not (guide_site() / "index.html").is_file():
                raise RuntimeError("攻略资源缺失，请重新下载完整版本。")
            self.profile.parent.mkdir(parents=True, exist_ok=True)
            self.status_path = self.profile.parent / ("session-" + uuid.uuid4().hex + ".json")
            self.update_idletasks()
            self.process = subprocess.Popen([
                str(executable), "--parent", str(self.winfo_id()), "--owner-pid", str(os.getpid()),
                "--site", str(guide_site()), "--profile", str(self.profile), "--status", str(self.status_path),
            ], cwd=str(guide_runtime()), creationflags=subprocess.CREATE_NO_WINDOW)
            self._poll()
        except (OSError, RuntimeError) as error:
            self.process = None
            self._show_error(str(error))

    def _show_error(self, text):
        self.message.configure(text=text)
        self.message.pack(fill="both", expand=True)
        self.retry_button.pack(pady=12)

    def _poll(self):
        self.poll_id = None
        if self.process is None:
            return
        if self.status_path and self.status_path.is_file():
            try:
                status = json.loads(self.status_path.read_text(encoding="utf-8-sig"))
                if status.get("ready"):
                    self.message.pack_forget()
                elif status.get("error"):
                    # The host renders an actionable error inside its child window.
                    self.message.pack_forget()
            except (OSError, ValueError):
                pass
        if self.process.poll() is not None:
            self.process = None
            self._show_error("攻略阅读组件已关闭，点击下方按钮重新打开。")
            self._remove_status()
            return
        self.poll_id = self.after(300, self._poll)

    def _remove_status(self):
        if self.status_path:
            try:
                self.status_path.unlink(missing_ok=True)
            except OSError:
                pass
            self.status_path = None

    def shutdown(self):
        if self.poll_id is not None:
            self.after_cancel(self.poll_id)
            self.poll_id = None
        if self.process is not None and self.process.poll() is None:
            # Ask only our own host to close normally so WebView2 flushes its profile.
            try:
                status = json.loads(self.status_path.read_text(encoding="utf-8-sig")) if self.status_path else {}
                handle = int(status.get("hwnd", 0))
                if handle:
                    user32 = ctypes.WinDLL("user32", use_last_error=True)
                    owner = ctypes.c_ulong()
                    user32.GetWindowThreadProcessId(ctypes.c_void_p(handle), ctypes.byref(owner))
                    if owner.value == self.process.pid:
                        user32.PostMessageW(ctypes.c_void_p(handle), 0x0010, 0, 0)
                self.process.wait(timeout=2)
            except (OSError, ValueError, subprocess.TimeoutExpired):
                self.process.terminate()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
            self.process = None
        self._remove_status()

    def _on_destroy(self, event):
        if event.widget is self:
            self.shutdown()

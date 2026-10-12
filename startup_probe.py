"""Internal release timing probe, always using temporary application data."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch


def run_probe(destination, import_started, version):
    from app import App
    import tkinter as tk
    imported = time.perf_counter()
    with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"LOCALAPPDATA": directory}):
        root = tk.Tk()
        root.withdraw()
        instance = App(root)
        root.update_idletasks()
        ready = time.perf_counter()
        instance.close()
        closed = time.perf_counter()
    value = dict(version=version, frozen=bool(getattr(sys, "frozen", False)), isolated_data=True,
                 import_seconds=round(imported-import_started, 3),
                 ui_seconds=round(ready-imported, 3), close_seconds=round(closed-ready, 3),
                 elapsed_seconds=round(closed-import_started, 3))
    Path(destination).resolve().write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0

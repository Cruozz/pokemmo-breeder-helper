from __future__ import annotations

import json
import os
from pathlib import Path

from models import Monster


def data_dir() -> Path:
    roots = []
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        roots.append(Path(local_app_data))
    roots.append(Path.home() / "AppData" / "Local")
    roots.append(Path.home())
    roots.append(Path.cwd())

    last_error: OSError | None = None
    for root in roots:
        path = root / "PokeMMO-Breeder-Helper"
        try:
            path.mkdir(parents=True, exist_ok=True)
            return path
        except OSError as exc:
            last_error = exc
    raise RuntimeError(f"无法创建素材库存目录：{last_error}")


def inventory_path() -> Path:
    return data_dir() / "inventory.json"


def load_inventory() -> list[Monster]:
    path = inventory_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [Monster.from_dict(item) for item in data if isinstance(item, dict)]


def save_inventory(items: list[Monster]) -> None:
    path = inventory_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps([item.to_dict() for item in items], ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
    """Legacy JSON path retained for one-time migration and user backups."""
    return data_dir() / "inventory.json"


def database_path() -> Path:
    return data_dir() / "inventory.db"


def active_plan_path() -> Path:
    return data_dir() / "active_plan.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(database_path(), timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS inventory (
            id TEXT PRIMARY KEY,
            species TEXT NOT NULL,
            page TEXT NOT NULL DEFAULT '',
            slot TEXT NOT NULL DEFAULT '',
            verified INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT NOT NULL,
            payload TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_inventory_species ON inventory(species);
        CREATE INDEX IF NOT EXISTS idx_inventory_location ON inventory(page, slot);
        CREATE INDEX IF NOT EXISTS idx_inventory_verified ON inventory(verified);
        CREATE TABLE IF NOT EXISTS consumption_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            occurred_at TEXT NOT NULL,
            plan_id TEXT NOT NULL,
            step_number INTEGER NOT NULL,
            parent_a TEXT NOT NULL,
            parent_b TEXT NOT NULL,
            child TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """
    )
    _migrate_legacy_json(connection)
    return connection


def _insert_monster(connection: sqlite3.Connection, monster: Monster) -> None:
    monster.updated_at = _utc_now()
    payload = json.dumps(monster.to_dict(), ensure_ascii=False, separators=(",", ":"))
    connection.execute(
        """
        INSERT INTO inventory(id, species, page, slot, verified, updated_at, payload)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            species=excluded.species,
            page=excluded.page,
            slot=excluded.slot,
            verified=excluded.verified,
            updated_at=excluded.updated_at,
            payload=excluded.payload
        """,
        (monster.id, monster.species, monster.page, monster.slot, int(monster.verified), monster.updated_at, payload),
    )


def _migrate_legacy_json(connection: sqlite3.Connection) -> None:
    migrated = connection.execute("SELECT value FROM metadata WHERE key='legacy_json_migrated'").fetchone()
    if migrated is not None:
        return
    path = inventory_path()
    imported = 0
    if path.exists() and connection.execute("SELECT COUNT(*) FROM inventory").fetchone()[0] == 0:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            for value in raw if isinstance(raw, list) else []:
                if not isinstance(value, dict):
                    continue
                monster = Monster.from_dict(value)
                if not monster.id:
                    continue
                _insert_monster(connection, monster)
                imported += 1
        except (OSError, json.JSONDecodeError):
            pass
    connection.execute(
        "INSERT OR REPLACE INTO metadata(key, value) VALUES ('legacy_json_migrated', ?)",
        (json.dumps({"at": _utc_now(), "count": imported}),),
    )
    connection.commit()


def load_inventory() -> list[Monster]:
    with closing(_connect()) as connection:
        rows = connection.execute("SELECT payload FROM inventory ORDER BY rowid").fetchall()
    result: list[Monster] = []
    for row in rows:
        try:
            value = json.loads(row["payload"])
            if isinstance(value, dict):
                result.append(Monster.from_dict(value))
        except (json.JSONDecodeError, TypeError):
            continue
    return result


def save_inventory(items: list[Monster]) -> None:
    with closing(_connect()) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("DELETE FROM inventory")
        for monster in items:
            _insert_monster(connection, monster)
        connection.commit()


def consume_parents_and_add_child(
    parent_ids: tuple[str, str],
    child: Monster,
    plan_id: str,
    step_number: int,
) -> tuple[Monster, Monster]:
    if not parent_ids[0] or not parent_ids[1] or parent_ids[0] == parent_ids[1]:
        raise ValueError("父母库存 ID 无效。")
    with closing(_connect()) as connection:
        connection.execute("BEGIN IMMEDIATE")
        rows = connection.execute(
            "SELECT id, payload FROM inventory WHERE id IN (?, ?)",
            parent_ids,
        ).fetchall()
        by_id = {row["id"]: row["payload"] for row in rows}
        missing = [identifier for identifier in parent_ids if identifier not in by_id]
        if missing:
            connection.rollback()
            raise ValueError(f"库存中找不到父母：{', '.join(missing)}")
        if connection.execute("SELECT 1 FROM inventory WHERE id=?", (child.id,)).fetchone() is not None:
            connection.rollback()
            raise ValueError("该步骤的子代已经存在于库存，请刷新或恢复执行方案状态。")
        parents = tuple(Monster.from_dict(json.loads(by_id[identifier])) for identifier in parent_ids)
        connection.execute("DELETE FROM inventory WHERE id IN (?, ?)", parent_ids)
        _insert_monster(connection, child)
        connection.execute(
            """
            INSERT INTO consumption_history(occurred_at, plan_id, step_number, parent_a, parent_b, child)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                _utc_now(),
                plan_id,
                int(step_number),
                json.dumps(parents[0].to_dict(), ensure_ascii=False),
                json.dumps(parents[1].to_dict(), ensure_ascii=False),
                json.dumps(child.to_dict(), ensure_ascii=False),
            ),
        )
        connection.commit()
    return parents[0], parents[1]


def undo_last_consumption() -> tuple[Monster, Monster, Monster] | None:
    with closing(_connect()) as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute("SELECT * FROM consumption_history ORDER BY id DESC LIMIT 1").fetchone()
        if row is None:
            connection.rollback()
            return None
        parent_a = Monster.from_dict(json.loads(row["parent_a"]))
        parent_b = Monster.from_dict(json.loads(row["parent_b"]))
        child = Monster.from_dict(json.loads(row["child"]))
        child_exists = connection.execute("SELECT 1 FROM inventory WHERE id=?", (child.id,)).fetchone()
        if child_exists is None:
            connection.rollback()
            raise ValueError("上一步生成的子代已经不在库存，无法自动撤销。")
        connection.execute("DELETE FROM inventory WHERE id=?", (child.id,))
        _insert_monster(connection, parent_a)
        _insert_monster(connection, parent_b)
        connection.execute("DELETE FROM consumption_history WHERE id=?", (row["id"],))
        connection.commit()
    return parent_a, parent_b, child


def save_active_plan(value: dict[str, Any] | None) -> None:
    path = active_plan_path()
    if value is None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_active_plan() -> dict[str, Any] | None:
    path = active_plan_path()
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None

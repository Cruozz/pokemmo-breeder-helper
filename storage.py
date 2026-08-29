from __future__ import annotations

import json
import os
import sqlite3
import unicodedata
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


def load_accounts() -> list[str]:
    """Load user-defined account/character labels, including empty accounts."""
    with closing(_connect()) as connection:
        row = connection.execute("SELECT value FROM metadata WHERE key='accounts'").fetchone()
    values: list[str] = []
    if row is not None:
        try:
            raw = json.loads(row["value"])
            values = [str(value).strip() for value in raw if str(value).strip()] if isinstance(raw, list) else []
        except (json.JSONDecodeError, TypeError):
            values = []
    return list(dict.fromkeys(["主账号", *values]))


def save_accounts(accounts: list[str]) -> None:
    values = list(dict.fromkeys(["主账号", *(str(value).strip() for value in accounts if str(value).strip())]))
    with closing(_connect()) as connection:
        connection.execute(
            "INSERT OR REPLACE INTO metadata(key, value) VALUES ('accounts', ?)",
            (json.dumps(values, ensure_ascii=False),),
        )
        connection.commit()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _duplicate_text(value: str) -> str:
    """Normalize harmless OCR/editor formatting before duplicate comparison."""
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    ignored = {",", "，", "、", ";", "；", "|"}
    return "".join(character for character in text if not character.isspace() and character not in ignored)


def _high_confidence_duplicate_parts(monster: Monster) -> tuple | None:
    species = _duplicate_text(monster.species)
    gender = str(monster.gender or "").strip().upper()
    nature = _duplicate_text(monster.nature)
    ivs = tuple(monster.ivs)
    moves = tuple(
        sorted(
            {
                normalized
                for move in monster.moves
                if (normalized := _duplicate_text(move))
            }
        )
    )
    if (
        not species
        or gender not in {"F", "M", "N"}
        or not nature
        or len(ivs) != 6
        or any(not isinstance(value, int) or not 0 <= value <= 31 for value in ivs)
        or not moves
    ):
        return None
    return (species, gender, nature, ivs), moves


def high_confidence_duplicate_key(monster: Monster) -> tuple | None:
    """Return the five-field identity requested by the inventory duplicate check.

    Incomplete OCR rows are intentionally excluded: two missing values matching
    each other is not strong enough evidence that two records represent the same
    visible Pokemon.
    """
    parts = _high_confidence_duplicate_parts(monster)
    if parts is None:
        return None
    base, moves = parts
    return (*base, moves)


def are_high_confidence_duplicates(left: Monster, right: Monster) -> bool:
    """Return whether two rows should be offered for manual duplicate review.

    OCR occasionally misses the fourth move. When the other four visible
    identity fields are exact, a three-move list that is a subset of a
    four-move list is still strong enough to review, but never auto-delete.
    """
    left_parts = _high_confidence_duplicate_parts(left)
    right_parts = _high_confidence_duplicate_parts(right)
    if left_parts is None or right_parts is None:
        return False
    left_base, left_moves = left_parts
    right_base, right_moves = right_parts
    if left_base != right_base:
        return False
    left_set = set(left_moves)
    right_set = set(right_moves)
    if left_set == right_set:
        return True
    shorter, longer = sorted((left_set, right_set), key=len)
    return len(shorter) >= 3 and len(longer) - len(shorter) == 1 and shorter < longer


def find_high_confidence_duplicate_groups(inventory: list[Monster]) -> list[list[Monster]]:
    """Group rows connected by a high-confidence manual-review match."""
    candidates = [monster for monster in inventory if _high_confidence_duplicate_parts(monster) is not None]
    neighbours: dict[str, set[str]] = {monster.id: set() for monster in candidates}
    by_id = {monster.id: monster for monster in candidates}
    for index, left in enumerate(candidates[:-1]):
        for right in candidates[index + 1 :]:
            if are_high_confidence_duplicates(left, right):
                neighbours[left.id].add(right.id)
                neighbours[right.id].add(left.id)

    groups: list[list[Monster]] = []
    visited: set[str] = set()
    for monster in candidates:
        if monster.id in visited or not neighbours[monster.id]:
            continue
        pending = [monster.id]
        component: list[Monster] = []
        visited.add(monster.id)
        while pending:
            current_id = pending.pop()
            component.append(by_id[current_id])
            for neighbour_id in neighbours[current_id]:
                if neighbour_id not in visited:
                    visited.add(neighbour_id)
                    pending.append(neighbour_id)
        groups.append(sorted(component, key=lambda item: item.id))
    return sorted(groups, key=lambda items: (_duplicate_text(items[0].species), items[0].iv_string, items[0].id))


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
            child TEXT NOT NULL,
            child_added_to_inventory INTEGER NOT NULL DEFAULT 1,
            plan_snapshot TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS inventory_delete_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            occurred_at TEXT NOT NULL,
            records TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """
    )
    history_columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(consumption_history)").fetchall()
    }
    if "plan_snapshot" not in history_columns:
        connection.execute(
            "ALTER TABLE consumption_history ADD COLUMN plan_snapshot TEXT NOT NULL DEFAULT ''"
        )
        connection.commit()
    if "child_added_to_inventory" not in history_columns:
        connection.execute(
            "ALTER TABLE consumption_history ADD COLUMN child_added_to_inventory INTEGER NOT NULL DEFAULT 1"
        )
        connection.commit()
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


def delete_inventory_records(record_ids: list[str] | tuple[str, ...]) -> list[Monster]:
    """Atomically delete selected inventory rows and keep one undo snapshot."""
    identifiers = list(dict.fromkeys(str(value) for value in record_ids if str(value)))
    if not identifiers:
        return []
    placeholders = ",".join("?" for _value in identifiers)
    with closing(_connect()) as connection:
        connection.execute("BEGIN IMMEDIATE")
        rows = connection.execute(
            f"SELECT id, payload FROM inventory WHERE id IN ({placeholders}) ORDER BY rowid",
            identifiers,
        ).fetchall()
        by_id = {row["id"]: row["payload"] for row in rows}
        deleted = [Monster.from_dict(json.loads(by_id[value])) for value in identifiers if value in by_id]
        if not deleted:
            connection.rollback()
            return []
        connection.execute(f"DELETE FROM inventory WHERE id IN ({placeholders})", identifiers)
        connection.execute(
            "INSERT INTO inventory_delete_history(occurred_at, records) VALUES (?, ?)",
            (_utc_now(), json.dumps([item.to_dict() for item in deleted], ensure_ascii=False)),
        )
        connection.commit()
    return deleted


def undo_last_inventory_deletion() -> list[Monster]:
    """Restore the most recent single or bulk inventory deletion."""
    with closing(_connect()) as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT * FROM inventory_delete_history ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            connection.rollback()
            return []
        try:
            raw = json.loads(row["records"])
            restored = [Monster.from_dict(value) for value in raw if isinstance(value, dict)]
        except (json.JSONDecodeError, TypeError):
            connection.rollback()
            raise ValueError("最近一次删除记录已损坏，无法自动撤销。")
        for monster in restored:
            _insert_monster(connection, monster)
        connection.execute("DELETE FROM inventory_delete_history WHERE id=?", (row["id"],))
        connection.commit()
    return restored


def consume_parents_and_add_child(
    parent_ids: tuple[str, str],
    child: Monster,
    plan_id: str,
    step_number: int,
    parent_labels: tuple[str, str] | None = None,
    plan_snapshot: dict[str, Any] | None = None,
    add_child_to_inventory: bool = True,
) -> tuple[Monster, Monster]:
    if not parent_ids[0] or not parent_ids[1] or parent_ids[0] == parent_ids[1]:
        raise ValueError("父母库存 ID 无效。")
    labels = parent_labels or ("交易行采购素材", "交易行采购素材")
    actual_ids = [identifier for identifier in parent_ids if not identifier.startswith("buy:")]
    with closing(_connect()) as connection:
        connection.execute("BEGIN IMMEDIATE")
        if actual_ids:
            placeholders = ",".join("?" for _identifier in actual_ids)
            rows = connection.execute(
                f"SELECT id, payload FROM inventory WHERE id IN ({placeholders})",
                actual_ids,
            ).fetchall()
        else:
            rows = []
        by_id = {row["id"]: row["payload"] for row in rows}
        missing = [identifier for identifier in actual_ids if identifier not in by_id]
        if missing:
            connection.rollback()
            raise ValueError(f"库存中找不到父母：{', '.join(missing)}")
        if (
            add_child_to_inventory
            and connection.execute("SELECT 1 FROM inventory WHERE id=?", (child.id,)).fetchone() is not None
        ):
            connection.rollback()
            raise ValueError("该步骤的子代已经存在于库存，请刷新或恢复执行方案状态。")
        parents = tuple(
            Monster.from_dict(json.loads(by_id[identifier]))
            if identifier in by_id
            else Monster(
                id=identifier,
                species="交易行采购",
                account="待采购",
                source="孵化规划交易行占位",
                verified=True,
                notes=labels[index],
            )
            for index, identifier in enumerate(parent_ids)
        )
        if actual_ids:
            placeholders = ",".join("?" for _identifier in actual_ids)
            connection.execute(f"DELETE FROM inventory WHERE id IN ({placeholders})", actual_ids)
        if add_child_to_inventory:
            _insert_monster(connection, child)
        connection.execute(
            """
            INSERT INTO consumption_history(
                occurred_at, plan_id, step_number, parent_a, parent_b, child,
                child_added_to_inventory, plan_snapshot
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _utc_now(),
                plan_id,
                int(step_number),
                json.dumps(parents[0].to_dict(), ensure_ascii=False),
                json.dumps(parents[1].to_dict(), ensure_ascii=False),
                json.dumps(child.to_dict(), ensure_ascii=False),
                int(add_child_to_inventory),
                json.dumps(plan_snapshot, ensure_ascii=False) if plan_snapshot else "",
            ),
        )
        connection.commit()
    return parents[0], parents[1]


def undo_last_consumption() -> tuple[Monster, Monster, Monster, dict[str, Any] | None] | None:
    with closing(_connect()) as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute("SELECT * FROM consumption_history ORDER BY id DESC LIMIT 1").fetchone()
        if row is None:
            connection.rollback()
            return None
        parent_a = Monster.from_dict(json.loads(row["parent_a"]))
        parent_b = Monster.from_dict(json.loads(row["parent_b"]))
        child = Monster.from_dict(json.loads(row["child"]))
        child_added_to_inventory = bool(row["child_added_to_inventory"])
        try:
            plan_snapshot = json.loads(row["plan_snapshot"]) if row["plan_snapshot"] else None
        except (json.JSONDecodeError, TypeError):
            plan_snapshot = None
        if child_added_to_inventory:
            child_exists = connection.execute("SELECT 1 FROM inventory WHERE id=?", (child.id,)).fetchone()
            if child_exists is None:
                connection.rollback()
                raise ValueError("上一步生成的子代已经不在库存，无法自动撤销。")
            connection.execute("DELETE FROM inventory WHERE id=?", (child.id,))
        if not parent_a.id.startswith("buy:"):
            _insert_monster(connection, parent_a)
        if not parent_b.id.startswith("buy:"):
            _insert_monster(connection, parent_b)
        connection.execute("DELETE FROM consumption_history WHERE id=?", (row["id"],))
        connection.commit()
    return parent_a, parent_b, child, plan_snapshot


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

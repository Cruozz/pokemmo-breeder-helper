"""Local batch drafts, stored separately from usable inventory."""
from __future__ import annotations

import json
import os
from pathlib import Path
import uuid


class BulkSessionStore:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True,exist_ok=True)

    def directory(self, session_id: str) -> Path:
        identifier = str(uuid.UUID(session_id))
        result = self.root / identifier
        if result.resolve().parent != self.root.resolve():
            raise ValueError("批次保存位置无效。")
        return result

    @staticmethod
    def _write(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True,exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
        os.replace(temporary,path)

    def save(self, state: dict) -> None:
        self._write(self.directory(state["session_id"])/"state.json",state)
        self._write(self.root/"current.json",{"session_id":state["session_id"]})

    def load(self, session_id: str | None = None) -> dict | None:
        if session_id is None:
            pointer = self.root/"current.json"
            if not pointer.exists():
                return None
            session_id = json.loads(pointer.read_text(encoding="utf-8"))["session_id"]
        state = json.loads((self.directory(session_id)/"state.json").read_text(encoding="utf-8"))
        if state.get("schema_version") != 1 or state.get("session_id") != session_id:
            raise ValueError("批量草稿格式无效；原文件已保留。")
        return state

    def save_image(self, session_id: str, kind: str, image) -> None:
        path = self.image_path(session_id,kind)
        path.parent.mkdir(parents=True,exist_ok=True)
        temporary = path.with_suffix(".tmp")
        image.save(temporary,format="PNG")
        os.replace(temporary,path)

    def image_path(self, session_id: str, kind: str) -> Path:
        if kind not in {"warehouse","release"}:
            raise ValueError("无效图片类型。")
        return self.directory(session_id)/(kind+".png")

    def save_repair_backup(self, session_id: str, records: list[dict]) -> Path:
        path=self.directory(session_id)/("before-recognition-repair-"+str(uuid.uuid4())+".json")
        self._write(path,{"schema_version":1,"records":records})
        return path

    def previous(self, current: str) -> dict | None:
        paths = sorted(self.root.glob("*/state.json"),key=lambda path:path.stat().st_mtime,reverse=True)
        for path in paths:
            if path.parent.name != current:
                try:
                    return self.load(path.parent.name)
                except (OSError,ValueError,KeyError,TypeError):
                    continue
        return None

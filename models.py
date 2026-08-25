from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


STATS = ("HP", "攻击", "防御", "特攻", "特防", "速度")


def normalize_gender(value: str | None) -> str:
    value = (value or "").strip().lower()
    if value in {"m", "male", "♂", "雄", "雄性"}:
        return "M"
    if value in {"f", "female", "♀", "雌", "雌性"}:
        return "F"
    if value in {"n", "genderless", "无性别", "无"}:
        return "N"
    return ""


@dataclass
class Monster:
    id: str
    species: str = ""
    gender: str = ""
    nature: str = ""
    ivs: list[int | None] = field(default_factory=lambda: [None] * 6)
    ability: str = ""
    held_item: str = ""
    moves: list[str] = field(default_factory=list)
    egg_groups: list[str] = field(default_factory=list)
    is_alpha: bool = False
    page: str = ""
    slot: str = ""
    source: str = ""
    confidence: float | None = None
    notes: str = ""
    verified: bool = True
    scan_fingerprint: str = ""
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        self.gender = normalize_gender(self.gender)
        self.ivs = list(self.ivs[:6]) + [None] * max(0, 6 - len(self.ivs))
        self.ivs = [self._coerce_iv(v) for v in self.ivs[:6]]
        self.egg_groups = [x.strip() for x in self.egg_groups if x and x.strip()]
        self.moves = [x.strip() for x in self.moves if x and x.strip()]
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.created_at = self.created_at or now
        self.updated_at = self.updated_at or self.created_at

    @staticmethod
    def _coerce_iv(value: Any) -> int | None:
        if value is None or value == "":
            return None
        try:
            number = int(value)
        except (TypeError, ValueError):
            return None
        return number if 0 <= number <= 31 else None

    @property
    def iv_string(self) -> str:
        return "/".join("x" if value is None else str(value) for value in self.ivs)

    @property
    def group_string(self) -> str:
        return ", ".join(self.egg_groups)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Monster":
        return cls(
            id=str(value.get("id", "")),
            species=str(value.get("species", "")),
            gender=str(value.get("gender", "")),
            nature=str(value.get("nature", "")),
            ivs=value.get("ivs", [None] * 6),
            ability=str(value.get("ability", "")),
            held_item=str(value.get("held_item", "")),
            moves=value.get("moves", []),
            egg_groups=value.get("egg_groups", []),
            is_alpha=bool(value.get("is_alpha", False)),
            page=str(value.get("page", "")),
            slot=str(value.get("slot", "")),
            source=str(value.get("source", "")),
            confidence=value.get("confidence"),
            notes=str(value.get("notes", "")),
            verified=bool(value.get("verified", True)),
            scan_fingerprint=str(value.get("scan_fingerprint", "")),
            created_at=str(value.get("created_at", "")),
            updated_at=str(value.get("updated_at", "")),
        )

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


STATS = ("HP", "攻击", "防御", "特攻", "特防", "速度")
BOX_COLUMNS = 10


def format_box_position(page: str | int, slot: str | int, columns: int = BOX_COLUMNS) -> str:
    """Return the compact PokeMMO position label: page-row,column."""
    page_text = str(page or "").strip()
    slot_text = str(slot or "").strip()
    if not page_text or not slot_text:
        return ""
    try:
        slot_number = int(slot_text)
    except (TypeError, ValueError):
        return ""
    if slot_number < 1 or columns < 1:
        return ""
    row, column = divmod(slot_number - 1, columns)
    return f"{page_text}-{row + 1},{column + 1}"


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
    has_hidden_ability: bool = False
    account: str = "主账号"
    page: str = ""
    slot: str = ""
    source: str = ""
    confidence: float | None = None
    notes: str = ""
    # Internal breeding-planner progress metadata. These fields let a staged
    # nature-hand route survive inventory saves, automatic replans and app
    # restarts without exposing implementation markers in the visible notes.
    breeding_target_key: str = ""
    breeding_role: str = ""
    nature_attempt_level: int = 0
    nature_attempt_result: str = ""
    # A child that immediately breeds with Ditto does not need its sex during
    # the current route.  Keep that fact separate from ``gender``: the planner
    # still has a concrete proof-state gender, while future unrelated plans
    # must ask the user to confirm the real result before reusing it.
    gender_unconfirmed: bool = False
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
        self.account = self.account.strip() or "主账号"
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

    @property
    def position_label(self) -> str:
        return format_box_position(self.page, self.slot)

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
            # Old inventory rows predate an independent hidden-ability flag.
            # Treat legacy Alpha captures as HA-unlocked by default, while
            # allowing users to explicitly clear the flag after migration.
            has_hidden_ability=bool(value.get("has_hidden_ability", value.get("is_alpha", False))),
            account=str(value.get("account", "主账号")),
            page=str(value.get("page", "")),
            slot=str(value.get("slot", "")),
            source=str(value.get("source", "")),
            confidence=value.get("confidence"),
            notes=str(value.get("notes", "")),
            breeding_target_key=str(value.get("breeding_target_key", "")),
            breeding_role=str(value.get("breeding_role", "")),
            nature_attempt_level=int(value.get("nature_attempt_level", 0) or 0),
            nature_attempt_result=str(value.get("nature_attempt_result", "")),
            gender_unconfirmed=bool(value.get("gender_unconfirmed", False)),
            verified=bool(value.get("verified", True)),
            scan_fingerprint=str(value.get("scan_fingerprint", "")),
            created_at=str(value.get("created_at", "")),
            updated_at=str(value.get("updated_at", "")),
        )

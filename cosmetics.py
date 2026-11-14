"""Shared, deterministic cosmetic identities and breeding constraints.

Only ordinary particles stack. Shiny/Secret Shiny are catalogued for visual
identification, never treated as freely transferable ordinary particles.
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path
import re


PARTICLE_MODES = {"protect": "保护粒子素材", "target": "指定粒子", "ignore": "无视粒子", "unique": "同种粒子限一次"}
COSTUME_FAMILIES = {
    "royal": {4, 5, 6},
    "vampire": {215, 461},
    "pirate": {443, 444, 445},
    "pharaoh": {447, 448},
    "ninja": {52, 53},
}
COSTUME_NAMES = {"royal": "皇家", "vampire": "吸血鬼", "pirate": "海盗", "pharaoh": "法老", "ninja": "忍者"}


@lru_cache(maxsize=1)
def particle_catalog() -> tuple[dict, ...]:
    return tuple(json.loads((Path(__file__).resolve().parent / "data/particles.json").read_text(encoding="utf-8"))["particles"])


def _key(value: str) -> str:
    return re.sub(r"[\W_]+", "", str(value).casefold().replace("质子", "").replace("粒子", ""))


@lru_cache(maxsize=1)
def _particle_aliases() -> dict[str, str]:
    return {_key(alias): entry["id"] for entry in particle_catalog()
            for alias in (entry["id"], entry["name"], entry["english_name"], *entry["aliases"])
            if alias and _key(alias)}


def normalize_particles(values) -> list[str]:
    if isinstance(values, str):
        values = re.split(r"[、,，;；\n]+", values)
    aliases = _particle_aliases()
    return list(dict.fromkeys(aliases.get(_key(value), str(value).strip()) for value in (values or ()) if str(value).strip()))


def particle_names(values) -> str:
    names = {entry["id"]: entry["name"] for entry in particle_catalog()}
    return "、".join(names.get(value, value) for value in normalize_particles(values))


def costume_family(species: str) -> str:
    from species_data import get_species_database
    record = get_species_database().get(species, fuzzy=False)
    return next((name for name, ids in COSTUME_FAMILIES.items() if record and record.id in ids), "")


def monster_costume(monster) -> str:
    return (monster.costume_id or costume_family(monster.species)) if monster.is_costume else ""


@dataclass(frozen=True)
class CosmeticPolicy:
    particle_mode: str = "protect"
    target_particles: frozenset[str] = frozenset()
    target_costume: str = ""
    costume_lineage: str = ""

    @classmethod
    def from_options(cls, options: dict | None, species: str):
        options = options or {}
        mode = str(options.get("particle_mode", "protect"))
        if mode not in PARTICLE_MODES:
            raise ValueError("请选择有效的粒子使用方式。")
        selected = frozenset(normalize_particles(options.get("target_particles"))) if mode == "target" else frozenset()
        ordinary = {entry["id"] for entry in particle_catalog() if not entry["intrinsic"]}
        if mode == "target" and (not selected or not selected.issubset(ordinary)):
            raise ValueError("请选择至少一种已确认的普通粒子；闪光与秘密闪光不是普通粒子目标。")
        family = costume_family(species) if options.get("target_costume") else ""
        if options.get("target_costume") and not family:
            raise ValueError("当前时装规划支持小火龙、狃拉、圆陆鲨、利欧路、喵喵五个进化家族。")
        return cls(mode, selected, family, str(options.get("costume_lineage") or "") if family else "")

    @property
    def unique(self) -> bool:
        return self.particle_mode in {"target", "unique"}

    def allowed(self, monster) -> bool:
        particles = frozenset(normalize_particles(monster.particles))
        if particles & {"shiny", "secret_shiny"}:
            return False  # This planner does not manufacture shiny compatibility.
        known = {entry["id"] for entry in particle_catalog() if not entry["intrinsic"]}
        has_particles = monster.has_particles or bool(particles)
        if monster.is_costume:
            if not self.target_costume or monster_costume(monster) != self.target_costume:
                return False
            if self.costume_lineage and (monster.costume_lineage or monster.id) != self.costume_lineage:
                return False
        if self.particle_mode == "ignore":
            return True
        if self.unique and has_particles and (not particles or not particles.issubset(known)):
            return False
        if not has_particles or monster.is_costume:
            return True
        if self.particle_mode == "protect":
            return False
        return self.particle_mode == "unique" or bool(particles & self.target_particles)

    def accepts_goal(self, state) -> bool:
        return (self.target_particles.issubset(state.particles)
                and (not self.target_costume or (state.costume_id == self.target_costume
                     and (not self.costume_lineage or state.costume_lineage == self.costume_lineage))))

    def to_options(self, lineage: str = "") -> dict:
        return dict(particle_mode=self.particle_mode, target_particles=sorted(self.target_particles),
                    target_costume=bool(self.target_costume), costume_lineage=lineage or self.costume_lineage)


ACTIVE_COSMETICS: ContextVar[CosmeticPolicy] = ContextVar("breeding_cosmetics", default=CosmeticPolicy())


def cosmetic_signature(state) -> tuple:
    return state.particles, state.costume_id, state.costume_lineage, state.has_unknown_particles


def inherit_costume(a, b, species: str):
    """A rare costume remains the maternal spine; a male converts with Ditto."""
    if a.costume_id and b.costume_id:
        return None
    owner = a if a.costume_id else b if b.costume_id else None
    if owner is None:
        return "", ""
    other = b if owner is a else a
    ditto = other.species.casefold() in {"百变怪", "ditto"}
    if not ditto and owner.gender != "F":
        return None
    if costume_family(species) != owner.costume_id:
        return None
    return owner.costume_id, owner.costume_lineage

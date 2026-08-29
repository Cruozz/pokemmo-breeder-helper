from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Iterable


GROUP_ALIASES = {
    "monster": "怪兽",
    "怪兽": "怪兽",
    "water1": "水中1",
    "water 1": "水中1",
    "水中1": "水中1",
    "水中 1": "水中1",
    "bug": "虫",
    "虫": "虫",
    "flying": "飞行",
    "飞行": "飞行",
    "ground": "陆上",
    "field": "陆上",
    "陆上": "陆上",
    "fairy": "妖精",
    "妖精": "妖精",
    "plant": "植物",
    "grass": "植物",
    "植物": "植物",
    "humanshape": "人型",
    "human-like": "人型",
    "humanlike": "人型",
    "人型": "人型",
    "water3": "水中3",
    "water 3": "水中3",
    "水中3": "水中3",
    "mineral": "矿物",
    "矿物": "矿物",
    "indeterminate": "不定形",
    "amorphous": "不定形",
    "不定形": "不定形",
    "water2": "水中2",
    "water 2": "水中2",
    "水中2": "水中2",
    "ditto": "百变怪",
    "百变怪": "百变怪",
    "dragon": "龙",
    "龙": "龙",
    "no-eggs": "未发现",
    "undiscovered": "未发现",
    "未发现": "未发现",
}

# These babies require an incense to hatch in PokeMMO.  Without the incense,
# breeding their evolution line yields the immediate evolved form instead.
INCENSE_BABY_IDS = frozenset({298, 360, 406, 433, 438, 439, 440, 446, 458})

# Final evolutions whose requested form requires a particular gender.  Their
# hatch species may still have both genders, so the final breeding node must
# carry an explicit gender constraint even though the selected evolved form is
# itself single-gender.
GENDER_SENSITIVE_EVOLUTION_IDS = {
    31: "F",   # Nidoqueen
    34: "M",   # Nidoking
    413: "F",  # Wormadam
    414: "M",  # Mothim
    416: "F",  # Vespiquen
    475: "M",  # Gallade
    478: "F",  # Froslass
}

# PokeMMO treats the two Nidoran evolution lines as one gender-linked
# breeding family. A female child is Nidoran♀ while a male child is Nidoran♂,
# regardless of which side of the family supplied the parent.
GENDER_LINKED_BREEDING_FAMILIES = (
    (
        frozenset({29, 30, 31, 32, 33, 34}),
        (("F", 29), ("M", 32)),
    ),
)


def normalize_name(value: str) -> str:
    return re.sub(r"[^0-9a-z\u3400-\u9fff♀♂]", "", (value or "").strip().lower())


def normalize_group(value: str) -> str:
    raw = (value or "").strip().lower().replace("_", "-")
    compact = re.sub(r"\s+", " ", raw)
    return GROUP_ALIASES.get(compact, GROUP_ALIASES.get(normalize_name(raw), value.strip()))


def resource_path(*parts: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base.joinpath(*parts)


@dataclass(frozen=True)
class SpeciesRecord:
    id: int
    identifier: str
    names: tuple[str, ...]
    egg_groups: tuple[str, ...]
    gender_rate: int
    is_baby: bool = False
    evolves_from_species_id: int | None = None

    @property
    def display_name(self) -> str:
        chinese = next((name for name in self.names if re.search(r"[\u3400-\u9fff]", name)), "")
        return chinese or next(iter(self.names), self.identifier)

    @property
    def allowed_genders(self) -> tuple[str, ...]:
        if self.gender_rate < 0:
            return ("N",)
        if self.gender_rate == 0:
            return ("M",)
        if self.gender_rate >= 8:
            return ("F",)
        return ("F", "M")

    @property
    def female_percent(self) -> float | None:
        if self.gender_rate < 0:
            return None
        return self.gender_rate * 12.5


class SpeciesDatabase:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or resource_path("data", "species.json")
        self.records: list[SpeciesRecord] = []
        self.aliases: dict[str, SpeciesRecord] = {}
        self.by_id: dict[int, SpeciesRecord] = {}
        self.children_by_parent: dict[int, list[SpeciesRecord]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        data = json.loads(self.path.read_text(encoding="utf-8"))
        override_path = self.path.with_name("pokemmo_overrides.json")
        overrides: dict[int, dict] = {}
        if override_path.exists():
            try:
                override_data = json.loads(override_path.read_text(encoding="utf-8"))
                overrides = {
                    int(item["id"]): item
                    for item in override_data.get("species", [])
                    if isinstance(item, dict) and item.get("id") is not None
                }
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                overrides = {}
        for raw in data.get("species", []):
            override = overrides.get(int(raw["id"]), {})
            raw_groups = override.get("egg_groups", raw.get("egg_groups_zh", raw.get("egg_groups", [])))
            raw_names = [*raw.get("names", []), *override.get("aliases", [])]
            record = SpeciesRecord(
                id=int(raw["id"]),
                identifier=str(raw["identifier"]),
                names=tuple(str(name) for name in raw_names if str(name).strip()),
                egg_groups=tuple(normalize_group(str(group)) for group in raw_groups),
                gender_rate=int(override.get("gender_rate", raw.get("gender_rate", -1))),
                is_baby=bool(override.get("is_baby", raw.get("is_baby", False))),
                evolves_from_species_id=override.get("evolves_from_species_id", raw.get("evolves_from_species_id")),
            )
            self.records.append(record)
            self.by_id[record.id] = record
            for alias in (*record.names, record.identifier):
                key = normalize_name(alias)
                if key:
                    self.aliases[key] = record
        for record in self.records:
            if record.evolves_from_species_id is not None:
                self.children_by_parent.setdefault(record.evolves_from_species_id, []).append(record)
        for children in self.children_by_parent.values():
            children.sort(key=lambda item: item.id)

    def get_by_id(self, species_id: int | str) -> SpeciesRecord | None:
        try:
            return self.by_id.get(int(species_id))
        except (TypeError, ValueError):
            return None

    def search(self, query: str, limit: int = 20) -> list[SpeciesRecord]:
        """Search by exact Pokédex number or a Chinese/English name fragment."""
        raw = (query or "").strip()
        if not raw:
            return []
        if raw.isdigit():
            record = self.get_by_id(raw)
            return [record] if record else []

        key = normalize_name(raw)
        if not key:
            return []
        ranked: list[tuple[int, int, int, SpeciesRecord]] = []
        for record in self.records:
            aliases = {normalize_name(record.identifier), *(normalize_name(name) for name in record.names)}
            aliases.discard("")
            matching = [alias for alias in aliases if key in alias]
            if not matching:
                continue
            exact = 0 if key in aliases else 1
            prefix = 0 if any(alias.startswith(key) for alias in matching) else 1
            shortest = min(len(alias) for alias in matching)
            ranked.append((exact, prefix, shortest, record))
        ranked.sort(key=lambda item: (item[0], item[1], item[2], item[3].id))
        return [item[3] for item in ranked[: max(1, limit)]]

    def get(self, query: str, fuzzy: bool = False) -> SpeciesRecord | None:
        key = normalize_name(query)
        if not key:
            return None
        exact = self.aliases.get(key)
        if exact is not None or not fuzzy:
            return exact
        best: tuple[float, SpeciesRecord] | None = None
        for alias, record in self.aliases.items():
            if abs(len(alias) - len(key)) > 3:
                continue
            score = SequenceMatcher(None, key, alias).ratio()
            if best is None or score > best[0]:
                best = (score, record)
        return best[1] if best and best[0] >= 0.72 else None

    def evolution_root(self, value: SpeciesRecord | str | int) -> SpeciesRecord | None:
        record = value if isinstance(value, SpeciesRecord) else (
            self.get_by_id(value) if isinstance(value, int) or str(value).isdigit() else self.get(str(value), fuzzy=True)
        )
        if record is None:
            return None
        visited: set[int] = set()
        while record.evolves_from_species_id is not None and record.id not in visited:
            visited.add(record.id)
            parent = self.get_by_id(record.evolves_from_species_id)
            if parent is None:
                break
            record = parent
        return record

    def evolution_line(self, value: SpeciesRecord | str | int) -> tuple[SpeciesRecord, ...]:
        root = self.evolution_root(value)
        if root is None:
            return ()
        result: list[SpeciesRecord] = []
        pending = [root]
        visited: set[int] = set()
        while pending:
            record = pending.pop(0)
            if record.id in visited:
                continue
            visited.add(record.id)
            result.append(record)
            pending.extend(self.children_by_parent.get(record.id, ()))
        return tuple(result)

    def ancestry(self, value: SpeciesRecord | str | int) -> tuple[SpeciesRecord, ...]:
        """Return the direct root-to-target evolution path."""
        record = value if isinstance(value, SpeciesRecord) else (
            self.get_by_id(value) if isinstance(value, int) or str(value).isdigit() else self.get(str(value), fuzzy=True)
        )
        if record is None:
            return ()
        result = [record]
        visited: set[int] = set()
        while record.evolves_from_species_id is not None and record.id not in visited:
            visited.add(record.id)
            parent = self.get_by_id(record.evolves_from_species_id)
            if parent is None:
                break
            result.append(parent)
            record = parent
        result.reverse()
        return tuple(result)

    def breeding_parent(self, value: SpeciesRecord | str | int) -> SpeciesRecord | None:
        """Return the earliest member of the line that is allowed to breed."""
        line = self.evolution_line(value)
        return next((record for record in line if "未发现" not in record.egg_groups), None)

    def breeding_offspring(self, value: SpeciesRecord | str | int) -> SpeciesRecord | None:
        """Return the default hatch species when no incense is used."""
        root = self.evolution_root(value)
        if root is None:
            return None
        if root.id not in INCENSE_BABY_IDS:
            return root
        return self.breeding_parent(root)

    def linked_breeding_family(self, value: SpeciesRecord | str | int) -> tuple[SpeciesRecord, ...]:
        """Return every evolution form in a gender-linked breeding family."""
        record = value if isinstance(value, SpeciesRecord) else (
            self.get_by_id(value) if isinstance(value, int) or str(value).isdigit() else self.get(str(value), fuzzy=True)
        )
        if record is None:
            return ()
        for member_ids, _gender_offspring_ids in GENDER_LINKED_BREEDING_FAMILIES:
            if record.id in member_ids:
                return tuple(
                    member
                    for member_id in sorted(member_ids)
                    if (member := self.get_by_id(member_id)) is not None
                )
        return ()

    def breeding_offspring_by_gender(
        self,
        value: SpeciesRecord | str | int,
    ) -> tuple[tuple[str, SpeciesRecord], ...]:
        """Return the hatch species associated with each selectable gender."""
        record = value if isinstance(value, SpeciesRecord) else (
            self.get_by_id(value) if isinstance(value, int) or str(value).isdigit() else self.get(str(value), fuzzy=True)
        )
        if record is None:
            return ()
        for member_ids, gender_offspring_ids in GENDER_LINKED_BREEDING_FAMILIES:
            if record.id in member_ids:
                return tuple(
                    (gender, offspring)
                    for gender, offspring_id in gender_offspring_ids
                    if (offspring := self.get_by_id(offspring_id)) is not None
                )
        offspring = self.breeding_offspring(record)
        if offspring is None:
            return ()
        return tuple((gender, offspring) for gender in offspring.allowed_genders)

    def breeding_output_genders(self, value: SpeciesRecord | str | int) -> tuple[str, ...]:
        return tuple(gender for gender, _record in self.breeding_offspring_by_gender(value))

    def requires_incense_for_target(self, value: SpeciesRecord | str | int) -> bool:
        record = value if isinstance(value, SpeciesRecord) else (
            self.get_by_id(value) if isinstance(value, int) or str(value).isdigit() else self.get(str(value), fuzzy=True)
        )
        root = self.evolution_root(record) if record else None
        return bool(record and root and record.id == root.id and root.id in INCENSE_BABY_IDS)

    def required_evolution_gender(self, value: SpeciesRecord | str | int) -> str:
        record = value if isinstance(value, SpeciesRecord) else (
            self.get_by_id(value) if isinstance(value, int) or str(value).isdigit() else self.get(str(value), fuzzy=True)
        )
        return GENDER_SENSITIVE_EVOLUTION_IDS.get(record.id, "") if record else ""

    def find_in_text(self, text: str) -> SpeciesRecord | None:
        """Find a complete Chinese species alias inside a noisy OCR line."""
        key = normalize_name(text)
        if not key:
            return None
        matches: list[tuple[int, SpeciesRecord]] = []
        for alias, record in self.aliases.items():
            # Substring matching is deliberately restricted to Chinese names;
            # short English aliases create too many accidental OCR matches.
            if len(alias) >= 2 and re.search(r"[\u3400-\u9fff]", alias) and alias in key:
                matches.append((len(alias), record))
        return max(matches, default=(0, None), key=lambda item: item[0])[1]

    def resolve_from_lines(self, candidates: Iterable[str]) -> SpeciesRecord | None:
        values = [value.strip() for value in candidates if value and value.strip()]
        for value in values:
            exact = self.get(value)
            if exact:
                return exact
        for value in values:
            embedded = self.find_in_text(value)
            if embedded:
                return embedded
        scored: list[tuple[float, SpeciesRecord]] = []
        for value in values:
            key = normalize_name(value)
            if not key or len(key) > 30:
                continue
            record = self.get(value, fuzzy=True)
            if record:
                score = max(SequenceMatcher(None, key, normalize_name(alias)).ratio() for alias in (*record.names, record.identifier))
                scored.append((score, record))
        return max(scored, default=(0.0, None), key=lambda item: item[0])[1]

    @staticmethod
    def _ocr_name_variants(value: str, gender: str = "") -> tuple[str, ...]:
        """Build conservative variants for the noisy ``Lv. 名字 性别`` row."""
        raw = (value or "").strip()
        raw = re.sub(r"^.*?\blv\.?\s*\d+", "", raw, flags=re.IGNORECASE).strip(" ：:'\"`·|")
        variants = [raw]

        # RapidOCR often turns the tiny gender glyph into one trailing Han
        # character. These suffixes are not used by any bundled species name.
        gender_key = (gender or "").strip().upper()
        suffixes = ("早", "超") if not gender_key else (("早",) if gender_key == "F" else (("超",) if gender_key == "M" else ()))
        for suffix in suffixes:
            if raw.endswith(suffix):
                variants.append(raw[: -len(suffix)].rstrip(" ：:'\"`·|"))

        expanded = list(variants)
        for candidate in variants:
            # A stray 1/I/l frequently appears between Chinese glyphs when the
            # compact level row is anti-aliased. Keep legitimate suffixes such
            # as 多边兽Z intact by removing ASCII only when surrounded by Han.
            repaired = re.sub(
                r"(?<=[\u3400-\u9fff])[0-9a-z](?=[\u3400-\u9fff])",
                "",
                candidate,
                flags=re.IGNORECASE,
            )
            if repaired != candidate:
                expanded.append(repaired)

        normalized = [normalize_name(candidate) for candidate in expanded]
        return tuple(dict.fromkeys(candidate for candidate in normalized if candidate))

    def resolve_ocr_name(self, value: str, gender: str = "") -> tuple[SpeciesRecord | None, bool, float]:
        """Resolve one OCR name row and report whether the correction is safe.

        Exact aliases and complete embedded names are accepted immediately.
        Fuzzy correction is limited to Chinese aliases and requires both a
        useful score and separation from the runner-up species.
        """
        variants = self._ocr_name_variants(value, gender)
        if not variants:
            return None, False, 0.0

        for candidate in variants:
            record = self.aliases.get(candidate)
            if record is not None:
                return record, True, 1.0
            embedded = self.find_in_text(candidate)
            if embedded is not None:
                return embedded, True, 1.0

        per_record: dict[int, tuple[float, SpeciesRecord, int, int]] = {}
        for record in self.records:
            aliases = {
                normalize_name(alias)
                for alias in record.names
                if re.search(r"[\u3400-\u9fff]", alias)
            }
            for candidate in variants:
                for alias in aliases:
                    if not alias or abs(len(alias) - len(candidate)) > 3:
                        continue
                    score = SequenceMatcher(None, candidate, alias).ratio()
                    current = per_record.get(record.id)
                    if current is None or score > current[0]:
                        per_record[record.id] = (score, record, len(candidate), len(alias))

        ranked = sorted(per_record.values(), key=lambda item: (-item[0], abs(item[2] - item[3]), item[1].id))
        if not ranked:
            return None, False, 0.0
        best_score, best_record, query_length, alias_length = ranked[0]
        second_score = ranked[1][0] if len(ranked) > 1 else 0.0
        minimum_length = min(query_length, alias_length)
        threshold = 0.88 if minimum_length <= 2 else (0.78 if minimum_length == 3 else 0.72)
        margin = best_score - second_score
        if best_score < threshold or margin < 0.03:
            return None, False, best_score
        confident = best_score >= 0.82 and margin >= 0.06
        return best_record, confident, best_score


@lru_cache(maxsize=1)
def get_species_database() -> SpeciesDatabase:
    return SpeciesDatabase()


def enrich_species(species: str) -> SpeciesRecord | None:
    return get_species_database().get(species, fuzzy=True)

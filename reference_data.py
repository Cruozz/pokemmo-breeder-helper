from __future__ import annotations

import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache
from typing import Any

from species_data import SpeciesDatabase, get_species_database, resource_path


def normalize_move(value: str) -> str:
    return re.sub(r"[^0-9a-z\u3400-\u9fff]", "", (value or "").strip().lower())


@dataclass(frozen=True)
class EggMoveRouteStep:
    species_id: int
    species: str
    annotations: tuple[str, ...]


@dataclass(frozen=True)
class EggMoveRoute:
    """Workbook order: direct father first, original move source last.

    A route is reference data, not proof that a particular inventory monster
    knows the move. Level/BP/Sketch annotations must never grant moves for free.
    """

    move: str
    steps: tuple[EggMoveRouteStep, ...]
    raw: str

    @property
    def direct_donor(self) -> EggMoveRouteStep:
        return self.steps[0]


@dataclass(frozen=True)
class LocationRecord:
    region: str
    route: str
    species: str
    species_id: int | None
    encounter: str
    rarity: str
    notes: str
    ev_yield: str
    source_egg_groups: str
    held_items: str


class ReferenceDatabase:
    def __init__(self, species_database: SpeciesDatabase | None = None) -> None:
        self.species_database = species_database or get_species_database()
        self.location_records: list[LocationRecord] = []
        self.locations_by_species: dict[int, list[LocationRecord]] = {}
        self.egg_moves_by_species: dict[int, dict[str, tuple[str, ...]]] = {}
        self.move_aliases: dict[str, str] = {}
        self.location_source: dict[str, Any] = {}
        self.egg_move_source: dict[str, Any] = {}
        self.abilities_by_species: dict[int, dict[str, tuple[dict[str, Any], ...]]] = {}
        self.ability_aliases: dict[str, str] = {}
        self.ability_source: dict[str, Any] = {}
        self.move_names: set[str] = set()
        self._load()

    @staticmethod
    def _read_json(filename: str) -> dict[str, Any]:
        path = resource_path("data", filename)
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _load(self) -> None:
        move_dictionary = self._read_json("moves.json")
        for raw in move_dictionary.get("moves", []):
            names = [str(name).strip() for name in raw.get("names", []) if str(name).strip()]
            canonical = next((name for name in names if re.search(r"[\u3400-\u9fff]", name)), "")
            canonical = canonical or next(iter(names), "")
            if not canonical:
                continue
            self.move_names.add(canonical)
            for name in names:
                self.move_aliases[normalize_move(name)] = canonical

        abilities = self._read_json("abilities.json")
        self.ability_source = {
            key: abilities.get(key)
            for key in ("source", "source_url", "scope")
            if abilities.get(key)
        }
        for key, raw in abilities.get("species", {}).items():
            try:
                species_id = int(raw.get("species_id", key))
            except (TypeError, ValueError):
                continue
            record: dict[str, tuple[dict[str, Any], ...]] = {}
            for ability_type in ("normal", "hidden"):
                values: list[dict[str, Any]] = []
                for ability in raw.get(ability_type, []):
                    names = [str(name).strip() for name in ability.get("names", []) if str(name).strip()]
                    canonical = next((name for name in names if re.search(r"[\u3400-\u9fff]", name)), "")
                    canonical = canonical or next(iter(names), "")
                    if not canonical:
                        continue
                    for name in names:
                        self.ability_aliases[normalize_move(name)] = canonical
                    values.append({**ability, "canonical": canonical})
                record[ability_type] = tuple(values)
            self.abilities_by_species[species_id] = record

        locations = self._read_json("locations.json")
        self.location_source = dict(locations.get("source", {}))
        for region, rows in locations.get("regions", {}).items():
            for raw in rows:
                record = LocationRecord(
                    region=str(region),
                    route=str(raw.get("route", "")),
                    species=str(raw.get("species", "")),
                    species_id=int(raw["species_id"]) if raw.get("species_id") is not None else None,
                    encounter=str(raw.get("encounter", "")),
                    rarity=str(raw.get("rarity", "")),
                    notes=str(raw.get("notes", "")),
                    ev_yield=str(raw.get("ev_yield", "")),
                    source_egg_groups=str(raw.get("source_egg_groups", "")),
                    held_items=str(raw.get("held_items", "")),
                )
                self.location_records.append(record)
                if record.species_id is not None:
                    self.locations_by_species.setdefault(record.species_id, []).append(record)

        egg_moves = self._read_json("egg_moves.json")
        self.egg_move_source = dict(egg_moves.get("source", {}))
        for key, raw in egg_moves.get("species", {}).items():
            try:
                species_id = int(raw.get("species_id", key))
            except (TypeError, ValueError):
                continue
            moves: dict[str, tuple[str, ...]] = {}
            for move, routes in raw.get("moves", {}).items():
                canonical = str(move).strip()
                if not canonical:
                    continue
                moves[canonical] = tuple(str(route) for route in routes if str(route).strip())
                self.move_aliases.setdefault(normalize_move(canonical), canonical)
            self.egg_moves_by_species[species_id] = moves

        move_overrides = self._read_json("move_ocr_overrides.json")
        for alias, canonical in move_overrides.get("aliases", {}).items():
            if str(alias).strip() and str(canonical).strip():
                self.move_aliases[normalize_move(str(alias))] = str(canonical).strip()

    def _species_id(self, species: int | str) -> int | None:
        if isinstance(species, int) or str(species).strip().isdigit():
            record = self.species_database.get_by_id(species)
        else:
            record = self.species_database.get(str(species), fuzzy=True)
        return record.id if record else None

    def locations_for_species(self, species: int | str) -> tuple[LocationRecord, ...]:
        species_id = self._species_id(species)
        return tuple(self.locations_by_species.get(species_id or -1, ()))

    def egg_moves_for_species(self, species: int | str) -> dict[str, tuple[str, ...]]:
        species_id = self._species_id(species)
        moves = self.egg_moves_by_species.get(species_id or -1)
        if moves is None and species_id is not None:
            offspring = self.species_database.breeding_offspring(species_id)
            moves = self.egg_moves_by_species.get(offspring.id) if offspring else None
        return dict(moves or {})

    def normalize_egg_move_selection(
        self, species: int | str, moves: tuple[str, ...] | list[str] | None,
    ) -> tuple[str, ...]:
        if isinstance(moves, str):
            raise ValueError("遗传技能必须是技能名称列表，不能是一整段字符串。")
        selected = tuple(dict.fromkeys(
            self.canonical_move(str(move), fuzzy=False)
            for move in (moves or ()) if str(move).strip()
        ))
        if len(selected) > 4:
            raise ValueError("一只精灵最多保留 4 个遗传技能，请减少选择。")
        available = self.egg_moves_for_species(species)
        invalid = [move for move in selected if move not in available]
        if invalid:
            record = self.species_database.get_by_id(self._species_id(species))
            label = record.display_name if record else str(species)
            raise ValueError(
                f"{label} 的内置遗传技能资料不支持：{'、'.join(invalid)}。"
                "请从该孵出物种的遗传技能列表中选择；不会自动猜测或替换技能。"
            )
        return selected

    @lru_cache(maxsize=2048)
    def egg_move_routes(self, species: int | str, move: str) -> tuple[EggMoveRoute, ...]:
        canonical = self.canonical_move(move, fuzzy=False)
        result: list[EggMoveRoute] = []
        for raw in self.egg_moves_for_species(species).get(canonical, ()):
            steps: list[EggMoveRouteStep] = []
            for segment in re.split(r"<=|←", raw):
                name = re.split(r"[（(]", segment, maxsplit=1)[0].strip()
                # Do not turn an unrecognized workbook name into a different
                # species via OCR-style fuzzy matching.
                record = self.species_database.get(name)
                if record is None:
                    break
                annotations = tuple(re.findall(r"[（(]([^）)]*)[）)]", segment))
                steps.append(EggMoveRouteStep(record.id, record.display_name, annotations))
            else:
                if steps:
                    result.append(EggMoveRoute(canonical, tuple(steps), raw))
        return tuple(result)

    @lru_cache(maxsize=1024)
    def inheritable_moves(self, species: str) -> frozenset[str]:
        # Synthetic market egg-group placeholders have no known learnset.
        # Fail closed instead of leaking skills through an arbitrary species.
        record = self.species_database.get(species)
        if record is None:
            return frozenset()
        offspring = self.species_database.breeding_offspring(record)
        return frozenset(self.egg_moves_for_species((offspring or record).id))

    def abilities_for_species(self, species: int | str) -> dict[str, tuple[dict[str, Any], ...]]:
        species_id = self._species_id(species)
        raw = self.abilities_by_species.get(species_id or -1, {})
        return {
            "normal": tuple(dict(value) for value in raw.get("normal", ())),
            "hidden": tuple(dict(value) for value in raw.get("hidden", ())),
        }

    def hidden_ability_names(self, species: int | str) -> tuple[str, ...]:
        return tuple(
            str(value.get("canonical", ""))
            for value in self.abilities_for_species(species).get("hidden", ())
            if str(value.get("canonical", ""))
        )

    def canonical_ability(self, raw_text: str) -> str:
        key = normalize_move(raw_text)
        if not key:
            return ""
        return self.ability_aliases.get(key, raw_text.strip())

    def search_moves(self, query: str, limit: int = 30) -> tuple[str, ...]:
        key = normalize_move(query)
        if not key:
            return ()
        ranked: list[tuple[int, int, str]] = []
        for move in self.move_names:
            normalized = normalize_move(move)
            if key not in normalized:
                continue
            ranked.append((0 if normalized.startswith(key) else 1, len(normalized), move))
        ranked.sort(key=lambda item: (item[0], item[1], item[2]))
        return tuple(item[2] for item in ranked[: max(1, limit)])

    def canonical_move(self, raw_text: str, *, fuzzy: bool = True) -> str:
        key = normalize_move(raw_text)
        if not key:
            return ""
        exact = self.move_aliases.get(key)
        if exact:
            return exact
        if not fuzzy:
            return raw_text.strip()
        best: tuple[float, str] | None = None
        for alias, canonical in self.move_aliases.items():
            if abs(len(alias) - len(key)) > 2:
                continue
            score = SequenceMatcher(None, key, alias).ratio()
            if best is None or score > best[0]:
                best = (score, canonical)
        return best[1] if best and best[0] >= 0.78 else raw_text.strip()

    def is_egg_move(self, species: int | str, move: str) -> bool:
        moves = self.egg_moves_for_species(species)
        canonical = self.canonical_move(move)
        return canonical in moves


@lru_cache(maxsize=1)
def get_reference_database() -> ReferenceDatabase:
    return ReferenceDatabase()

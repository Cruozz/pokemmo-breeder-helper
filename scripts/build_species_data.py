from __future__ import annotations

import csv
import io
import json
import urllib.request
from collections import defaultdict
from pathlib import Path


BASE_URL = "https://raw.githubusercontent.com/PokeAPI/pokeapi/master/data/v2/csv"
MAX_SPECIES_ID = 649
LANGUAGES = {4, 9, 12}  # zh-Hant, English, zh-Hans

GROUP_NAMES_ZH = {
    "monster": "怪兽",
    "water1": "水中1",
    "bug": "虫",
    "flying": "飞行",
    "ground": "陆上",
    "fairy": "妖精",
    "plant": "植物",
    "humanshape": "人型",
    "water3": "水中3",
    "mineral": "矿物",
    "indeterminate": "不定形",
    "water2": "水中2",
    "ditto": "百变怪",
    "dragon": "龙",
    "no-eggs": "未发现",
}


def download_csv(name: str) -> list[dict[str, str]]:
    request = urllib.request.Request(
        f"{BASE_URL}/{name}",
        headers={"User-Agent": "pokemmo-breeder-helper-data-builder"},
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        text = response.read().decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text)))


def main() -> None:
    species_rows = download_csv("pokemon_species.csv")
    egg_map_rows = download_csv("pokemon_egg_groups.csv")
    egg_group_rows = download_csv("egg_groups.csv")
    name_rows = download_csv("pokemon_species_names.csv")

    group_identifiers = {int(row["id"]): row["identifier"] for row in egg_group_rows}
    species_groups: dict[int, list[str]] = defaultdict(list)
    for row in egg_map_rows:
        species_id = int(row["species_id"])
        if species_id <= MAX_SPECIES_ID:
            identifier = group_identifiers.get(int(row["egg_group_id"]))
            if identifier:
                species_groups[species_id].append(identifier)

    localized_names: dict[int, dict[int, str]] = defaultdict(dict)
    for row in name_rows:
        language_id = int(row["local_language_id"])
        species_id = int(row["pokemon_species_id"])
        if species_id <= MAX_SPECIES_ID and language_id in LANGUAGES:
            localized_names[species_id][language_id] = row["name"]

    records = []
    for row in species_rows:
        species_id = int(row["id"])
        if species_id > MAX_SPECIES_ID:
            continue
        groups = species_groups.get(species_id, [])
        names = localized_names.get(species_id, {})
        aliases = list(dict.fromkeys(filter(None, [row["identifier"], names.get(9), names.get(12), names.get(4)])))
        records.append(
            {
                "id": species_id,
                "identifier": row["identifier"],
                "names": aliases,
                "egg_groups": groups,
                "egg_groups_zh": [GROUP_NAMES_ZH.get(group, group) for group in groups],
                "gender_rate": int(row["gender_rate"]),
                "is_baby": row["is_baby"] == "1",
                "evolves_from_species_id": int(row["evolves_from_species_id"]) if row["evolves_from_species_id"] else None,
            }
        )

    project_dir = Path(__file__).resolve().parents[1]
    output_dir = project_dir / "data"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "species.json"
    payload = {
        "schema_version": 1,
        "scope": "Pokemon species 1-649; PokeMMO differences can be applied as local overrides",
        "source": "PokeAPI/pokeapi CSV data",
        "source_url": "https://github.com/PokeAPI/pokeapi/tree/master/data/v2/csv",
        "species": records,
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(records)} species to {output_path}")


if __name__ == "__main__":
    main()

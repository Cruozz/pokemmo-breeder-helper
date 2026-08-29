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


def download_csv(name: str) -> list[dict[str, str]]:
    request = urllib.request.Request(
        f"{BASE_URL}/{name}",
        headers={"User-Agent": "pokemmo-breeder-helper-data-builder"},
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        text = response.read().decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text)))


def main() -> None:
    pokemon_rows = download_csv("pokemon.csv")
    pokemon_ability_rows = download_csv("pokemon_abilities.csv")
    ability_rows = download_csv("abilities.csv")
    ability_name_rows = download_csv("ability_names.csv")

    pokemon_to_species = {
        int(row["id"]): int(row["species_id"])
        for row in pokemon_rows
        if row.get("is_default") == "1" and int(row["species_id"]) <= MAX_SPECIES_ID
    }
    ability_identifiers = {int(row["id"]): row["identifier"] for row in ability_rows}
    ability_names: dict[int, dict[int, str]] = defaultdict(dict)
    for row in ability_name_rows:
        language_id = int(row["local_language_id"])
        if language_id in LANGUAGES:
            ability_names[int(row["ability_id"])][language_id] = row["name"]

    by_species: dict[int, dict[str, list[dict[str, object]]]] = defaultdict(
        lambda: {"normal": [], "hidden": []}
    )
    for row in pokemon_ability_rows:
        species_id = pokemon_to_species.get(int(row["pokemon_id"]))
        if species_id is None:
            continue
        ability_id = int(row["ability_id"])
        localized = ability_names.get(ability_id, {})
        names = list(
            dict.fromkeys(
                filter(
                    None,
                    [
                        ability_identifiers.get(ability_id, ""),
                        localized.get(9),
                        localized.get(12),
                        localized.get(4),
                    ],
                )
            )
        )
        target = "hidden" if row.get("is_hidden") == "1" else "normal"
        by_species[species_id][target].append(
            {
                "id": ability_id,
                "slot": int(row.get("slot") or 0),
                "identifier": ability_identifiers.get(ability_id, ""),
                "names": names,
            }
        )

    records = {
        str(species_id): {
            "species_id": species_id,
            "normal": sorted(value["normal"], key=lambda item: int(item["slot"])),
            "hidden": sorted(value["hidden"], key=lambda item: int(item["slot"])),
        }
        for species_id, value in sorted(by_species.items())
    }
    project_dir = Path(__file__).resolve().parents[1]
    output_path = project_dir / "data" / "abilities.json"
    payload = {
        "schema_version": 1,
        "scope": (
            "Pokemon species 1-649 ability reference. PokeMMO release availability and "
            "special exceptions remain explicit planner/manual-review concerns."
        ),
        "source": "PokeAPI/pokeapi CSV data",
        "source_url": "https://github.com/PokeAPI/pokeapi/tree/master/data/v2/csv",
        "species": records,
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote ability references for {len(records)} species to {output_path}")


if __name__ == "__main__":
    main()

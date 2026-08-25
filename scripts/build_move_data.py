from __future__ import annotations

import csv
import io
import json
import urllib.request
from collections import defaultdict
from pathlib import Path


BASE_URL = "https://raw.githubusercontent.com/PokeAPI/pokeapi/master/data/v2/csv"
MAX_GENERATION_ID = 5
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
    move_rows = download_csv("moves.csv")
    name_rows = download_csv("move_names.csv")
    allowed = {
        int(row["id"]): row["identifier"]
        for row in move_rows
        if int(row["generation_id"]) <= MAX_GENERATION_ID
    }
    names: dict[int, dict[int, str]] = defaultdict(dict)
    for row in name_rows:
        move_id = int(row["move_id"])
        language_id = int(row["local_language_id"])
        if move_id in allowed and language_id in LANGUAGES:
            names[move_id][language_id] = row["name"]

    records = []
    for move_id, identifier in sorted(allowed.items()):
        localized = names.get(move_id, {})
        aliases = list(
            dict.fromkeys(
                filter(None, [identifier, localized.get(9), localized.get(12), localized.get(4)])
            )
        )
        records.append({"id": move_id, "identifier": identifier, "names": aliases})

    project_dir = Path(__file__).resolve().parents[1]
    output_path = project_dir / "data" / "moves.json"
    payload = {
        "schema_version": 1,
        "scope": "Moves introduced in generations 1-5; used only as an OCR name dictionary",
        "source": "PokeAPI/pokeapi CSV data",
        "source_url": "https://github.com/PokeAPI/pokeapi/tree/master/data/v2/csv",
        "moves": records,
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(records)} moves to {output_path}")


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen


SOURCE_URL = "https://tool.lzpoke.com/data/monsters.json"
FIELDS = (
    "id", "name", "types", "stats", "yields", "egg_groups", "abilities",
    "gender_ratio", "catch_rate", "obtainable", "evolutions", "moves", "locations",
)


def build(source: bytes, collected_at: str) -> dict:
    records = json.loads(source)
    if not isinstance(records, list):
        raise ValueError("Expected a monster list")
    species = [{key: record[key] for key in FIELDS} for record in records if 1 <= record["id"] <= 649]
    if len(species) != 649 or {record["id"] for record in species} != set(range(1, 650)):
        raise ValueError("Expected exactly the national species 1–649")
    for record in species:
        if not record["name"] or not record["stats"] or not record["yields"]:
            raise ValueError(f"Incomplete species {record['id']}")
        for location in record["locations"]:
            if location["season"] not in {"任意", "春", "夏", "秋", "冬"}:
                raise ValueError(f"Unrecognized season: {location['season']}")
    return {"schema_version": 1, "source": SOURCE_URL, "collected_at": collected_at,
            "source_sha256": hashlib.sha256(source).hexdigest(), "species": species}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the separate offline reference snapshot")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "data" / "guide.json.gz")
    options = parser.parse_args()
    if options.input:
        source = options.input.read_bytes()
        collected_at = datetime.fromtimestamp(options.input.stat().st_mtime, timezone.utc).isoformat()
    else:
        with urlopen(SOURCE_URL, timeout=60) as response:
            source = response.read()
        collected_at = datetime.now(timezone.utc).isoformat()
    result = build(source, collected_at)
    payload = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_bytes(gzip.compress(payload, mtime=0))
    print(json.dumps({key: value for key, value in result.items() if key != "species"}, ensure_ascii=False))
    print(f"Species: {len(result['species'])}; output: {options.output}")


if __name__ == "__main__":
    main()

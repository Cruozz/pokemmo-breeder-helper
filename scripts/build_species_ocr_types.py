"""Extract a small candidate-only type index from the bundled guide snapshot."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path


def build(source: bytes) -> dict:
    snapshot = json.loads(gzip.decompress(source))
    types = {str(record["id"]): list(record["types"]) for record in snapshot["species"]}
    if set(types) != {str(i) for i in range(1, 650)} or any(not value or len(value) > 2 for value in types.values()):
        raise ValueError("Expected types for exactly species 1-649")
    return {"schema_version": 1, "source": "guide.json.gz", "source_sha256": hashlib.sha256(source).hexdigest(), "types": types}


def main() -> None:
    root = Path(__file__).resolve().parents[1] / "data"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=root / "guide.json.gz")
    parser.add_argument("--output", type=Path, default=root / "species_ocr_types.json")
    options = parser.parse_args()
    payload = build(options.input.read_bytes())
    options.output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"Wrote {len(payload['types'])} candidate type entries to {options.output}")


if __name__ == "__main__":
    main()

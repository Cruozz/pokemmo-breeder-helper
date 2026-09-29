from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
import time

from build_ui_assets import POKEMON_CELL, POKEMON_COLUMNS, POKEMON_COUNT, PROJECT_ROOT, centered_rgba, download
from PIL import Image


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the offline shiny atlas without changing normal sprites")
    parser.add_argument("--revision", required=True)
    parser.add_argument("--cache", required=True, type=Path)
    parser.add_argument("--workers", default=8, type=int)
    args = parser.parse_args()
    if re.fullmatch(r"[0-9a-f]{40}", args.revision) is None:
        raise ValueError("Use a full PokeAPI/sprites commit SHA")
    cache = args.cache / args.revision
    cache.mkdir(parents=True, exist_ok=True)
    source_root = f"https://raw.githubusercontent.com/PokeAPI/sprites/{args.revision}/sprites/pokemon/shiny"

    def fetch(species_id: int) -> tuple[int, bytes]:
        path = cache / f"{species_id}.png"
        for attempt in range(3):
            try:
                raw = path.read_bytes() if path.exists() else download(f"{source_root}/{species_id}.png")
                with Image.open(BytesIO(raw)) as image:
                    image.verify()
                with Image.open(BytesIO(raw)) as image:
                    if image.size != (96, 96) or image.convert("RGBA").getchannel("A").getbbox() is None:
                        raise ValueError(f"Invalid sprite: {species_id}")
                if not path.exists():
                    path.write_bytes(raw)
                return species_id, raw
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(attempt + 1)
        raise RuntimeError("Sprite download failed")

    rows = (POKEMON_COUNT + POKEMON_COLUMNS - 1) // POKEMON_COLUMNS
    atlas = Image.new("RGBA", (POKEMON_COLUMNS * POKEMON_CELL, rows * POKEMON_CELL), (0, 0, 0, 0))
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        for completed, (species_id, raw) in enumerate(executor.map(fetch, range(1, POKEMON_COUNT + 1)), 1):
            column = (species_id - 1) % POKEMON_COLUMNS
            row = (species_id - 1) // POKEMON_COLUMNS
            atlas.alpha_composite(centered_rgba(raw, POKEMON_CELL), (column * POKEMON_CELL, row * POKEMON_CELL))
            if completed % 100 == 0:
                print(f"Validated {completed}/{POKEMON_COUNT} shiny sprites", flush=True)
    destination = PROJECT_ROOT / "assets" / "pokemon_shiny_atlas.png"
    atlas.save(destination, optimize=True)
    manifest = {"source_repository": "https://github.com/PokeAPI/sprites", "revision": args.revision,
                "source_path": "sprites/pokemon/shiny/{id}.png", "count": POKEMON_COUNT,
                "columns": POKEMON_COLUMNS, "cell": POKEMON_CELL,
                "sha256": hashlib.sha256(destination.read_bytes()).hexdigest()}
    (PROJECT_ROOT / "assets" / "pokemon_shiny_atlas.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest), flush=True)


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VENDOR_DIR = PROJECT_ROOT / "vendor"
if VENDOR_DIR.exists():
    sys.path.insert(0, str(VENDOR_DIR))

from PIL import Image


POKEMON_COUNT = 649
POKEMON_COLUMNS = 16
POKEMON_CELL = 96
ITEM_CELL = 32
ITEM_KEYS = (
    "power-weight",
    "power-bracer",
    "power-belt",
    "power-lens",
    "power-band",
    "power-anklet",
    "everstone",
)
RAW_ROOT = "https://raw.githubusercontent.com/PokeAPI/sprites/master"


def download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "PokeMMO-Breeder-Helper asset builder"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def fetch_many(jobs: dict[str, str], workers: int) -> dict[str, bytes]:
    results: dict[str, bytes] = {}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        pending = {executor.submit(download, url): key for key, url in jobs.items()}
        for future in as_completed(pending):
            key = pending[future]
            results[key] = future.result()
    return results


def centered_rgba(raw: bytes, cell_size: int) -> Image.Image:
    source = Image.open(BytesIO(raw)).convert("RGBA")
    if source.width > cell_size or source.height > cell_size:
        source.thumbnail((cell_size, cell_size), Image.Resampling.NEAREST)
    cell = Image.new("RGBA", (cell_size, cell_size), (0, 0, 0, 0))
    cell.alpha_composite(source, ((cell_size - source.width) // 2, (cell_size - source.height) // 2))
    return cell


def build(output_dir: Path, workers: int) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    jobs = {
        f"pokemon:{species_id}": f"{RAW_ROOT}/sprites/pokemon/{species_id}.png"
        for species_id in range(1, POKEMON_COUNT + 1)
    }
    jobs.update(
        {
            f"item:{key}": f"{RAW_ROOT}/sprites/items/{key}.png"
            for key in ITEM_KEYS
        }
    )
    blobs = fetch_many(jobs, workers)

    rows = (POKEMON_COUNT + POKEMON_COLUMNS - 1) // POKEMON_COLUMNS
    pokemon_atlas = Image.new(
        "RGBA",
        (POKEMON_COLUMNS * POKEMON_CELL, rows * POKEMON_CELL),
        (0, 0, 0, 0),
    )
    for species_id in range(1, POKEMON_COUNT + 1):
        cell = centered_rgba(blobs[f"pokemon:{species_id}"], POKEMON_CELL)
        column = (species_id - 1) % POKEMON_COLUMNS
        row = (species_id - 1) // POKEMON_COLUMNS
        pokemon_atlas.alpha_composite(cell, (column * POKEMON_CELL, row * POKEMON_CELL))
    pokemon_atlas.save(output_dir / "pokemon_atlas.png", optimize=True)

    item_atlas = Image.new("RGBA", (len(ITEM_KEYS) * ITEM_CELL, ITEM_CELL), (0, 0, 0, 0))
    for index, key in enumerate(ITEM_KEYS):
        item_atlas.alpha_composite(centered_rgba(blobs[f"item:{key}"], ITEM_CELL), (index * ITEM_CELL, 0))
    item_atlas.save(output_dir / "item_atlas.png", optimize=True)

    license_text = download(f"{RAW_ROOT}/LICENCE.txt").decode("utf-8")
    (output_dir / "POKEAPI_SPRITES_LICENSE.txt").write_text(license_text, encoding="utf-8")
    print(f"Built {output_dir / 'pokemon_atlas.png'} ({POKEMON_COUNT} sprites)")
    print(f"Built {output_dir / 'item_atlas.png'} ({len(ITEM_KEYS)} item icons)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build offline PokeAPI sprite atlases used by the mind map.")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "assets")
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args()
    build(args.output.resolve(), args.workers)


if __name__ == "__main__":
    main()

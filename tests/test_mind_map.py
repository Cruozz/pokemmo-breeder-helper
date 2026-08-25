from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

from mind_map import (
    BreedingMindMap,
    ITEM_ATLAS_CELL,
    ITEM_ATLAS_KEYS,
    MindMapNode,
    POKEMON_ATLAS_CELL,
    POKEMON_ATLAS_COLUMNS,
)
from PIL import Image


class FakeCanvas:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def focus_set(self) -> None:
        self.calls.append(("focus",))

    def configure(self, **kwargs) -> None:
        self.calls.append(("configure", kwargs))

    def scan_mark(self, x: int, y: int) -> None:
        self.calls.append(("mark", x, y))

    def scan_dragto(self, x: int, y: int, gain: int) -> None:
        self.calls.append(("drag", x, y, gain))


class MindMapInteractionTests(unittest.TestCase):
    def test_iv_cells_distinguish_perfect_any_and_custom_exact_values(self) -> None:
        self.assertEqual(BreedingMindMap._iv_value_kind("31"), "perfect")
        self.assertEqual(BreedingMindMap._iv_value_kind("X"), "any")
        self.assertEqual(BreedingMindMap._iv_value_kind("0"), "exact")
        self.assertEqual(BreedingMindMap._iv_value_kind("16"), "exact")

    def test_offline_sprite_atlases_cover_supported_species_and_items(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with Image.open(root / "assets" / "pokemon_atlas.png") as pokemon_atlas:
            self.assertEqual(pokemon_atlas.width, POKEMON_ATLAS_COLUMNS * POKEMON_ATLAS_CELL)
            self.assertGreaterEqual(pokemon_atlas.height, 41 * POKEMON_ATLAS_CELL)
        with Image.open(root / "assets" / "item_atlas.png") as item_atlas:
            self.assertEqual(item_atlas.size, (len(ITEM_ATLAS_KEYS) * ITEM_ATLAS_CELL, ITEM_ATLAS_CELL))

    def test_plain_mouse_wheel_zooms_around_pointer(self) -> None:
        view = BreedingMindMap.__new__(BreedingMindMap)
        view.zoom = 1.0
        calls: list[tuple[float, tuple[float, float]]] = []
        view.set_zoom = lambda value, anchor=None: calls.append((value, anchor))

        result = BreedingMindMap._on_mousewheel(
            view,
            SimpleNamespace(delta=120, x=180, y=95),
        )

        self.assertEqual(result, "break")
        self.assertEqual(calls, [(1.1, (180, 95))])

    def test_middle_button_pans_and_restores_cursor(self) -> None:
        view = BreedingMindMap.__new__(BreedingMindMap)
        view.canvas = FakeCanvas()

        self.assertEqual(
            BreedingMindMap._start_pan(view, SimpleNamespace(x=30, y=40)),
            "break",
        )
        self.assertEqual(
            BreedingMindMap._drag_pan(view, SimpleNamespace(x=70, y=90)),
            "break",
        )
        self.assertEqual(BreedingMindMap._stop_pan(view), "break")
        self.assertIn(("mark", 30, 40), view.canvas.calls)
        self.assertIn(("drag", 70, 90, 1), view.canvas.calls)
        self.assertEqual(view.canvas.calls[-1], ("configure", {"cursor": ""}))

    def test_inventory_leaf_exclusion_invokes_material_callback(self) -> None:
        view = BreedingMindMap.__new__(BreedingMindMap)
        view.nodes_by_key = {
            "leaf": MindMapNode(
                key="leaf",
                title="库存素材",
                exclude_material_id="rare-alpha-id",
            )
        }
        excluded: list[str] = []
        view.on_material_exclude = excluded.append

        self.assertEqual(BreedingMindMap._exclude_key(view, "leaf"), "break")
        self.assertEqual(excluded, ["rare-alpha-id"])


if __name__ == "__main__":
    unittest.main()

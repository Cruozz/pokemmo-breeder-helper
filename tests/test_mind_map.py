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


class TaggedCanvas(FakeCanvas):
    def find_withtag(self, _tag: str):
        return (1,)

    def gettags(self, _item: int):
        return ("node:done",)


class MindMapInteractionTests(unittest.TestCase):
    def test_node_detail_uses_numeric_v_badge_instead_of_roman_iv_label(self) -> None:
        view = BreedingMindMap.__new__(BreedingMindMap)
        captured: list[str] = []
        view.detail_var = SimpleNamespace(set=captured.append)

        BreedingMindMap._show_node_detail(
            view,
            MindMapNode(
                key="four-v",
                title="性格手",
                iv_text="4V",
                iv_values=("31", "31", "X", "31", "31", "X"),
            ),
        )

        self.assertIn("4V 31/31/X/31/31/X", captured[0])
        self.assertNotIn("IV ", captured[0])

    def test_iv_cells_distinguish_perfect_any_and_custom_exact_values(self) -> None:
        self.assertEqual(BreedingMindMap._iv_value_kind("31"), "perfect")
        self.assertEqual(BreedingMindMap._iv_value_kind("X"), "any")
        self.assertEqual(BreedingMindMap._iv_value_kind("0"), "exact")
        self.assertEqual(BreedingMindMap._iv_value_kind("16"), "exact")

    def test_zoomed_out_status_and_nature_chips_fit_without_overlap(self) -> None:
        view = BreedingMindMap.__new__(BreedingMindMap)
        view.zoom = 0.6
        status_width = view._chip_width("启用后执行", 7)
        nature_width = view._chip_width("爆性格：待确认", 7)
        left = view._scaled(12)
        gap = view._scaled(6)
        media_left = view._scaled(view.BASE_NODE_WIDTH - 72)

        self.assertLess(left + status_width + gap + nature_width, media_left)
        self.assertLess(
            view._scaled(120 + 16),
            view._scaled(view.BASE_NODE_HEIGHT),
        )

    def test_offline_sprite_atlases_cover_supported_species_and_items(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with Image.open(root / "assets" / "pokemon_atlas.png") as pokemon_atlas:
            self.assertEqual(pokemon_atlas.width, POKEMON_ATLAS_COLUMNS * POKEMON_ATLAS_CELL)
            self.assertGreaterEqual(pokemon_atlas.height, 41 * POKEMON_ATLAS_CELL)
        with Image.open(root / "assets" / "item_atlas.png") as item_atlas:
            self.assertEqual(item_atlas.size, (len(ITEM_ATLAS_KEYS) * ITEM_ATLAS_CELL, ITEM_ATLAS_CELL))

    def test_author_payment_qr_assets_are_packaged_as_readable_images(self) -> None:
        root = Path(__file__).resolve().parents[1]
        for name in ("donation-alipay.jpg", "donation-wechat.png"):
            with Image.open(root / "assets" / name) as payment_image:
                self.assertGreater(payment_image.width, 800)
                self.assertGreater(payment_image.height, 1000)

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

    def test_selected_ready_node_can_toggle_non_destructive_progress(self) -> None:
        view = BreedingMindMap.__new__(BreedingMindMap)
        view.selected_key = "step-2"
        view.nodes_by_key = {
            "step-2": MindMapNode(
                key="step-2",
                title="步骤 2",
                step_number=2,
                actionable=True,
            )
        }
        toggled: list[int] = []
        view.on_step_progress_toggle = toggled.append

        self.assertEqual(BreedingMindMap._toggle_progress_selected(view), "break")
        self.assertEqual(toggled, [2])

    def test_double_click_completed_node_toggles_collapsed_sources(self) -> None:
        view = BreedingMindMap.__new__(BreedingMindMap)
        view.canvas = TaggedCanvas()
        view.selected_key = ""
        view.nodes_by_key = {
            "done": MindMapNode(
                key="done",
                title="已完成步骤",
                step_number=3,
                completed=True,
                history_toggleable=True,
                sources_collapsed=True,
            )
        }
        view.detail_var = SimpleNamespace(set=lambda _value: None)
        toggled: list[int] = []
        view.on_completed_sources_toggle = toggled.append
        view.on_step_progress_toggle = None

        self.assertEqual(BreedingMindMap._on_double_click(view), "break")
        self.assertEqual(toggled, [3])


if __name__ == "__main__":
    unittest.main()

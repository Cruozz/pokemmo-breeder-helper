from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import tkinter as tk
import unittest

from guide_data import get_guide_database
from guide_views import QueryPage
from pokedex_portrait import PokedexPortrait, PortraitAtlas
from species_data import resource_path


class PortraitAssetTests(unittest.TestCase):
    def test_all_species_have_both_images(self):
        atlas = PortraitAtlas()
        try:
            for species_id in range(1, 650):
                for shiny in (False, True):
                    with self.subTest(species_id=species_id, shiny=shiny):
                        image = atlas.crop(species_id, shiny)
                        self.assertEqual(image.size, (96, 96))
                        self.assertIsNotNone(image.getchannel("A").getbbox())
        finally:
            atlas.close()

    def test_representative_shiny_images_are_not_normal_images(self):
        atlas = PortraitAtlas()
        try:
            for species_id in (1, 6, 25, 130, 150, 649):
                self.assertNotEqual(atlas.crop(species_id).tobytes(), atlas.crop(species_id, True).tobytes())
        finally:
            atlas.close()

    def test_shiny_manifest_matches_asset(self):
        manifest = json.loads(resource_path("assets", "pokemon_shiny_atlas.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["count"], 649)
        self.assertEqual(len(manifest["revision"]), 40)
        self.assertEqual(manifest["sha256"], hashlib.sha256(resource_path("assets", "pokemon_shiny_atlas.png").read_bytes()).hexdigest())

    def test_invalid_species_id_does_not_crop_wrong_image(self):
        atlas = PortraitAtlas()
        for species_id in (0, -1, 650):
            with self.assertRaises(ValueError):
                atlas.crop(species_id)


class PortraitInteractionTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()

    def tearDown(self):
        self.root.destroy()

    def test_click_twice_returns_to_normal(self):
        portrait = PokedexPortrait(self.root)
        portrait.set_species(25, "皮卡丘")
        normal = portrait.photo
        self.assertIsNotNone(normal)
        self.assertFalse(portrait.shiny)
        portrait.button.invoke()
        self.assertTrue(portrait.shiny)
        self.assertIsNot(portrait.photo, normal)
        self.assertIn("闪光", str(portrait.button["text"]))
        portrait.button.invoke()
        self.assertFalse(portrait.shiny)
        self.assertIs(portrait.photo, normal)

    def test_species_change_resets_to_normal_but_same_selection_does_not(self):
        portrait = PokedexPortrait(self.root)
        portrait.set_species(6, "喷火龙")
        portrait.toggle()
        portrait.set_species(6, "喷火龙")
        self.assertTrue(portrait.shiny)
        portrait.set_species(25, "皮卡丘")
        self.assertFalse(portrait.shiny)
        self.assertEqual(portrait.species_id, 25)
        self.assertEqual(len(portrait.photos), 1)

    def test_empty_selection_removes_old_picture(self):
        portrait = PokedexPortrait(self.root)
        portrait.set_species(25, "皮卡丘")
        portrait.set_species(None)
        self.assertIsNone(portrait.photo)
        self.assertTrue(portrait.button.instate(["disabled"]))
        self.assertEqual(portrait.photos, {})

    def test_keyboard_toggle_stops_other_shortcuts(self):
        portrait = PokedexPortrait(self.root)
        portrait.set_species(25, "皮卡丘")
        self.assertEqual(portrait._keyboard_toggle(), "break")
        self.assertTrue(portrait.shiny)

    def test_portrait_resizes_without_resetting_shiny(self):
        portrait = PokedexPortrait(self.root)
        portrait.set_species(25, "皮卡丘")
        portrait.toggle()
        portrait._resize(SimpleNamespace(width=184, height=170))
        self.assertLess(portrait.picture_size, 144)
        self.assertTrue(portrait.shiny)
        portrait._resize(SimpleNamespace(width=184, height=320))
        self.assertEqual(portrait.picture_size, 144)
        self.assertTrue(portrait.shiny)

    def test_missing_asset_has_readable_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            portrait = PokedexPortrait(self.root, PortraitAtlas(Path(directory)))
            portrait.set_species(25, "皮卡丘")
            self.assertTrue(portrait.error)
            self.assertIsNone(portrait.photo)
            self.assertTrue(portrait.button.instate(["disabled"]))
            self.assertIn("不可用", str(portrait.button["text"]))

    def test_pokedex_selection_updates_the_portrait(self):
        page = QueryPage(self.root, get_guide_database(), "pokedex", lambda *_args: None)
        page.query.set("皮卡丘")
        page.refresh()
        self.root.update()
        self.assertEqual(page.portrait.species_id, 25)
        page.portrait.button.invoke()
        self.assertTrue(page.portrait.shiny)
        page.query.set("妙蛙种子")
        page.refresh()
        self.root.update()
        self.assertEqual(page.portrait.species_id, 1)
        self.assertFalse(page.portrait.shiny)
        page.query.set("没有这只精灵")
        page.refresh()
        self.root.update()
        self.assertIsNone(page.portrait.photo)


if __name__ == "__main__":
    unittest.main()

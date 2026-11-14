from pathlib import Path
from PIL import Image, ImageDraw
import pytest
from cosmetics import particle_catalog
from ocr_engine import OCRItem
from particle_vision import detect_particle


ROOT = Path(__file__).resolve().parents[1] / "data"


def summary(scale=1, name_right=280):
    image = Image.new("RGB", (400 * scale, 380 * scale), (29, 36, 39))
    ImageDraw.Draw(image).rectangle((397 * scale, 0, 400 * scale, 380 * scale), fill=(0, 0, 0))
    lines = [OCRItem("Lv.100 伊布", .99, [[90 * scale, 300 * scale], [name_right * scale, 300 * scale],
                                        [name_right * scale, 320 * scale], [90 * scale, 320 * scale]])]
    return image, lines


def paste_icon(image, particle, position, size=24, resample=Image.Resampling.NEAREST):
    entry = next(e for e in particle_catalog() if e["id"] == particle)
    with Image.open(ROOT / entry["icon"]) as original:
        icon = original.convert("RGBA").resize((size, size), resample)
    image.paste(icon, position, icon)


@pytest.mark.parametrize("scale", [1, 2])
@pytest.mark.parametrize("resample", [Image.Resampling.NEAREST, Image.Resampling.BILINEAR])
def test_all_catalogue_icons_match_at_desktop_and_mobile_scales(scale, resample):
    for entry in particle_catalog():
        image, lines = summary(scale)
        paste_icon(image, entry["id"], (360 * scale, 289 * scale), 24 * scale, resample)
        assert detect_particle(image, lines) == (True, [entry["id"]]), (entry["id"], scale, resample)


def test_missing_anchor_and_empty_band_do_not_guess_names():
    image, lines = summary()
    assert detect_particle(image, []) == (False, [])
    assert detect_particle(image, lines) == (False, [])
    assert detect_particle(None, lines) == (False, [])


@pytest.mark.parametrize("particle", ["bats", "phantom", "sarcophagus", "lotus_field"])
@pytest.mark.parametrize("position", [(275, 220), (365, 180), (280, 294), (365, 345), (410, 289)])
def test_icons_in_sprite_background_gender_stats_or_neighbor_are_ignored(particle, position):
    panel, lines = summary()
    image = Image.new("RGB", (650, 400), (29, 36, 39))
    image.paste(panel, (0, 0))
    paste_icon(image, particle, position)
    assert detect_particle(image, lines) == (False, [])


@pytest.mark.parametrize("scale", [1, 1.25, 1.5, 2])
def test_scaled_offset_panel_and_short_name_keep_the_right_corner(scale):
    panel, lines = summary(name_right=220)
    paste_icon(panel, "sarcophagus", (360, 289))
    image = Image.new("RGB", (700, 500), (90, 100, 110))
    image.paste(panel, (63, 41))
    image = image.resize((round(700 * scale), round(500 * scale)), Image.Resampling.BILINEAR)
    lines = [OCRItem(i.text, i.score, [[round((x + 63) * scale), round((y + 41) * scale)] for x, y in i.box]) for i in lines]
    assert detect_particle(image, lines) == (True, ["sarcophagus"])


def test_missing_panel_edge_in_large_frame_does_not_scan_other_columns():
    image, lines = summary(name_right=220)
    image = Image.new("RGB", (700, 500), (29, 36, 39))
    paste_icon(image, "lotus_field", (400, 289))
    assert detect_particle(image, lines) == (False, [])


@pytest.mark.parametrize("kind", ["noise", "stripes", "partial", "wrong_color"])
def test_unconfirmed_graphics_do_not_set_has_particles(kind):
    import numpy as np
    image, lines = summary()
    if kind == "noise":
        pixels = np.random.default_rng(17).integers(0, 256, (35, 56, 3), dtype=np.uint8)
        image.paste(Image.fromarray(pixels), (341, 288))
    elif kind == "stripes":
        draw = ImageDraw.Draw(image)
        for x in range(342, 395, 6):
            draw.rectangle((x, 290, x + 2, 315), fill=(50, 150, 220))
    elif kind == "partial":
        paste_icon(image, "sarcophagus", (388, 289))
    else:
        paste_icon(image, "lotus_field", (360, 289))
        image.paste(Image.eval(image.crop((360, 289, 384, 313)), lambda p: 255 - p), (360, 289))
    assert detect_particle(image, lines) == (False, [])

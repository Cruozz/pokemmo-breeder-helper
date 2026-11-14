from pathlib import Path
from PIL import Image
import pytest
from cosmetics import particle_catalog
from ocr_engine import OCRItem
from particle_vision import detect_particle


@pytest.mark.parametrize("size", [24,48])
def test_all_catalogue_icons_match_at_desktop_and_mobile_scales(size):
    root=Path(__file__).resolve().parents[1]/"data"
    lines=[OCRItem("Lv.100 伊布",.99,[[25,120],[220,120],[220,140],[25,140]])]
    for entry in particle_catalog():
        image=Image.new("RGB",(290,190),(75,84,92))
        icon=Image.open(root/entry["icon"]).convert("RGBA").resize((size,size),Image.Resampling.NEAREST)
        image.paste(icon,(220,100-size//2),icon)
        assert detect_particle(image,lines)==(True,[entry["id"]]),(entry["id"],size)


def test_missing_anchor_and_empty_band_do_not_guess_names():
    image=Image.new("RGB",(290,190),(75,84,92))
    assert detect_particle(image,[])==(False,[])
    lines=[OCRItem("Lv.100 伊布",.99,[[25,120],[220,120],[220,140],[25,140]])]
    assert detect_particle(image,lines)==(False,[])

from pathlib import Path

from PIL import Image,ImageDraw
import pytest

from bulk_ocr import BulkRow,combine,read_warehouse
from warehouse_vision import classify_alpha_icon


def thumbnail(alpha=False):
    tile=Image.new("RGB",(80,68),(47,50,53))
    draw=ImageDraw.Draw(tile)
    draw.ellipse((30,14,60,44),fill=(90,170,95),outline=(191,20,29) if alpha else (30,30,30),width=2)
    draw.rectangle((40,24,43,27),fill=(240,240,240))
    return tile


@pytest.mark.parametrize("scale",[.75,1,1.25,2])
def test_whole_red_contour_identifies_alpha_at_multiple_sizes(scale):
    tile=thumbnail(True)
    tile=tile.resize((round(tile.width*scale),round(tile.height*scale)),Image.Resampling.LANCZOS)
    assert classify_alpha_icon(tile) is True


def test_body_red_patch_is_not_an_alpha_outline():
    tile=thumbnail()
    ImageDraw.Draw(tile).ellipse((32,16,58,42),fill=(191,20,29))
    assert classify_alpha_icon(tile) is not True


def test_ui_red_marks_and_cell_frame_cannot_turn_a_normal_sprite_into_alpha():
    tile=thumbnail()
    draw=ImageDraw.Draw(tile)
    draw.ellipse((14,53,22,62),outline=(191,20,29),width=2)
    draw.text((47,54),"100",fill=(191,20,29))
    assert classify_alpha_icon(tile) is False
    draw.rectangle((0,0,79,67),outline=(191,20,29),width=3)
    assert classify_alpha_icon(tile) is not True


def test_blank_tiny_and_obscured_icons_remain_unknown():
    assert classify_alpha_icon(Image.new("RGB",(80,68),(47,50,53))) is None
    assert classify_alpha_icon(thumbnail(True).resize((32,27))) is None
    tile=thumbnail(True)
    ImageDraw.Draw(tile).rectangle((0,0,45,67),fill=(47,50,53))
    assert classify_alpha_icon(tile) is None


def test_red_frame_without_a_sprite_is_not_alpha():
    tile=Image.new("RGB",(80,68),(47,50,53))
    ImageDraw.Draw(tile).ellipse((30,14,60,44),outline=(191,20,29),width=2)
    assert classify_alpha_icon(tile) is None


def test_neighbor_alpha_is_confined_to_its_own_slot_and_result_row():
    grid=Image.new("RGB",(800,408),(47,50,53))
    grid.paste(thumbnail(),(0,0));grid.paste(thumbnail(True),(80,0))
    class EmptyOCR:
        def recognize(self,_image):return []
    cells=read_warehouse(grid,EmptyOCR(),[1,2])
    assert [cell["is_alpha"] for cell in cells]==[False,True]
    result=combine([BulkRow(1),BulkRow(2)],cells,3,1,2)
    assert [row.is_alpha for row in result.rows]==[False,True]


@pytest.mark.parametrize("filename",["pokemon_atlas.png","pokemon_shiny_atlas.png"])
@pytest.mark.parametrize("size",[24,32,40])
def test_normal_and_shiny_red_bodies_never_supply_an_alpha_halo(filename,size):
    with Image.open(Path(__file__).resolve().parents[1]/"assets"/filename) as image:
        atlas=image.convert("RGBA")
    for identifier in range(649):
        row,column=divmod(identifier,16)
        sprite=atlas.crop((column*96,row*96,(column+1)*96,(row+1)*96))
        sprite=sprite.crop(sprite.getbbox());sprite.thumbnail((size,size),Image.Resampling.LANCZOS)
        tile=Image.new("RGB",(80,68),(47,50,53))
        tile.paste(sprite,(44-sprite.width//2,29-sprite.height//2),sprite)
        assert classify_alpha_icon(tile) is not True,(filename,size,identifier+1)

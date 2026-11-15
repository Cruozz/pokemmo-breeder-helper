from pathlib import Path

from PIL import Image,ImageDraw
import pytest

from bulk_vision import gender_from_tile,hidden_ability_from_header


def symbol_tile(gender,frame=False):
    tile=Image.new("RGB",(80,68),(35,43,48))
    draw=ImageDraw.Draw(tile)
    draw.ellipse((32,12,60,35),fill=(200,140,180))
    if frame:draw.rectangle((9,1,78,66),outline=(20,170,245),width=2)
    color=(235,113,154) if gender=="F" else (20,150,240)
    draw.ellipse((14,48,20,54),outline=color,width=1)
    if gender=="F":
        draw.line((17,54,17,60),fill=color)
        draw.line((14,57,20,57),fill=color)
    else:
        draw.line((19,49,24,44),fill=color)
        draw.line((21,44,24,44,24,47),fill=color)
    return tile


@pytest.mark.parametrize("gender",["F","M"])
@pytest.mark.parametrize("scale",[.75,1,1.25,2])
def test_sex_symbol_remains_distinct_from_a_blue_selection_frame(gender,scale):
    tile=symbol_tile(gender,frame=True)
    tile=tile.resize((round(80*scale),round(68*scale)),Image.Resampling.LANCZOS)
    assert gender_from_tile(tile)==gender


def test_frames_blue_blocks_and_missing_symbols_do_not_invent_gender():
    tile=Image.new("RGB",(80,68),(35,43,48));draw=ImageDraw.Draw(tile)
    draw.rectangle((10,0,12,67),fill=(20,150,240))
    draw.rectangle((15,44,21,54),fill=(20,150,240))
    assert gender_from_tile(tile)==""
    assert gender_from_tile(Image.new("RGB",(80,68),(35,43,48)))==""
    assert gender_from_tile(symbol_tile("F").resize((30,26)))==""


def header(color=(40,200,250)):
    image=Image.new("RGB",(700,180),(50,60,65))
    ImageDraw.Draw(image).polygon([(233,47),(244,47),(249,53),(238,64),(228,53)],fill=color)
    return image


@pytest.mark.parametrize("height",[14,17,20])
def test_blue_gem_can_be_wider_than_the_ocr_text_height(height):
    box=[[70,50],[214,50],[214,50+height],[70,50+height]]
    assert hidden_ability_from_header(header(),box,310) is True


def test_blue_gem_can_overlap_the_end_of_an_ocr_box():
    box=[[70,50],[250,50],[250,67],[70,67]]
    assert hidden_ability_from_header(header(),box,310) is True


def test_green_star_neighbor_sprite_and_blue_blocks_are_not_hidden_ability_gems():
    box=[[70,50],[214,50],[214,67],[70,67]]
    assert hidden_ability_from_header(header((80,230,150)),box,310) is False
    image=Image.new("RGB",(700,180),(50,60,65))
    ImageDraw.Draw(image).rectangle((320,47,342,65),fill=(40,200,250))
    assert hidden_ability_from_header(image,box,310) is False
    ImageDraw.Draw(image).rectangle((229,47,248,64),fill=(40,200,250))
    assert hidden_ability_from_header(image,box,310) is False
    assert hidden_ability_from_header(header(),box,245) is None


@pytest.mark.parametrize("filename",["pokemon_atlas.png","pokemon_shiny_atlas.png"])
@pytest.mark.parametrize("size",[24,32,40])
def test_colored_pokemon_bodies_without_a_sex_symbol_do_not_supply_gender(filename,size):
    with Image.open(Path(__file__).resolve().parents[1]/"assets"/filename) as image:atlas=image.convert("RGBA")
    for identifier in range(649):
        row,column=divmod(identifier,16)
        sprite=atlas.crop((column*96,row*96,(column+1)*96,(row+1)*96))
        sprite=sprite.crop(sprite.getbbox());sprite.thumbnail((size,size),Image.Resampling.LANCZOS)
        tile=Image.new("RGB",(80,68),(47,50,53))
        tile.paste(sprite,(44-sprite.width//2,29-sprite.height//2),sprite)
        assert gender_from_tile(tile)=="",(filename,size,identifier+1)

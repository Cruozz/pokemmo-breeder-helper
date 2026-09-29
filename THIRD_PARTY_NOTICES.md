# Third-party notices

## Alphapedia live information (V0.2.17)

The optional live-information workspace reads the public pages at
https://alpha.pokemmotools.org/ and https://alpha.pokemmotools.org/rotations
when opened. It displays the latest community-reported Alpha and current
Altering Cave encounter slots. Remote scripts are not executed or bundled.
Only the most recent parsed public facts are cached locally; the application
does not send inventory, account names, screenshots or game information.
Species names and portraits use the existing bundled PokeAPI-derived resources.
Alphapedia is credited in the workspace, with links to the original pages.
Reports and approximate despawn times may be delayed or incomplete.

## PokeAPI data

The generated `data/species.json`, `data/moves.json` and `data/abilities.json` files use source data from
[PokeAPI/pokeapi](https://github.com/PokeAPI/pokeapi), including species names,
egg groups, gender rates, baby flags, move names and ability names. PokeAPI is distributed under the BSD
3-Clause license. The upstream license is available at:

https://github.com/PokeAPI/pokeapi/blob/master/LICENSE.md

A copy is bundled at `data/POKEAPI_LICENSE.md`.

No PokeMMO client memory, network traffic, ROM data or unsupported client dump
is used to build this file.

## PokeAPI sprite assets

`assets/pokemon_atlas.png`, `assets/pokemon_shiny_atlas.png` and `assets/item_atlas.png` are mechanically packed
from the public [PokeAPI/sprites](https://github.com/PokeAPI/sprites) repository.
They provide offline visual references for species and breeding items in the
planning mind map and Pokédex; the application does not download them at runtime and does
not read or unpack the PokeMMO client. The upstream notice states that image
contents are Copyright The Pokémon Company and that the repository is
distributed under CC0 1.0 Universal. A copy is bundled at
`assets/POKEAPI_SPRITES_LICENSE.txt`.

The shiny atlas covers national species 1–649, using the front sprites from
PokeAPI/sprites commit `fb3512817b9c3f46952b3f89e82645e77bdcaf49`.
The build manifest at `assets/pokemon_shiny_atlas.json` records the source and
atlas hash. `scripts/build_shiny_assets.py` builds this asset independently;
the pre-existing normal and item atlases are unchanged.

## Reviewed PokeMMO-specific mechanics

The explicit Nidoran breeding overrides in `data/pokemmo_overrides.json` were
reviewed against the public PokeMMO Wiki pages for
[Nidoran♂](https://pokemmo.shoutwiki.com/wiki/Nidoran%E2%99%82) and
[Breeding](https://pokemmo.shoutwiki.com/wiki/Breeding). Only short factual
mechanics are encoded; no page text or media is redistributed.

## User-provided reference workbooks

`data/locations.json` and `data/egg_moves.json` were mechanically generated
from the user-provided workbooks `全地区精灵分布.xlsx` and `技能遗传链.xlsx`.
The workbooks did not include an explicit redistribution license. Confirm the
original authors' permission before publishing these derived datasets in a
public release.

## V0.2.14 原生查询资料

新增 `data/guide.json.gz` 为露珠 PokeMMO 工具站公开事实资料的只读快照。
来源：https://tool.lzpoke.com/data/monsters.json （2026-09-29）。
仅提取物种、属性、数值、招式、进化与遭遇条件，不包含网站界面代码。
数据、名称等权利属于各自权利人；不将本项目代码许可套用于第三方资料，
不宣称获得官方背书或原站接口授权。来源与原始文件哈希记录在快照元信息中。
此来源未附明确的再分发许可；公开发布含此快照的源码或发行包前，应先确认原作者授权。

# Third-party notices

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

`assets/pokemon_atlas.png` and `assets/item_atlas.png` are mechanically packed
from the public [PokeAPI/sprites](https://github.com/PokeAPI/sprites) repository.
They provide offline visual references for species and breeding items in the
planning mind map; the application does not download them at runtime and does
not read or unpack the PokeMMO client. The upstream notice states that image
contents are Copyright The Pokémon Company and that the repository is
distributed under CC0 1.0 Universal. A copy is bundled at
`assets/POKEAPI_SPRITES_LICENSE.txt`.

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

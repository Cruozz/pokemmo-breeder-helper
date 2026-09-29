from __future__ import annotations

from pathlib import Path
import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageTk

from species_data import resource_path


SPRITE_COUNT = 649
SPRITE_COLUMNS = 16
SPRITE_CELL = 96
PORTRAIT_SIZE = 144


class PortraitAtlas:
    def __init__(self, asset_root: Path | None = None) -> None:
        self.asset_root = asset_root if asset_root is not None else resource_path("assets")
        self.images = {}

    def crop(self, species_id: int, shiny: bool = False) -> Image.Image:
        if not 1 <= species_id <= SPRITE_COUNT:
            raise ValueError("没有该精灵的图片")
        if shiny not in self.images:
            filename = "pokemon_shiny_atlas.png" if shiny else "pokemon_atlas.png"
            with Image.open(self.asset_root / filename) as image:
                expected = (SPRITE_COLUMNS * SPRITE_CELL, ((SPRITE_COUNT + SPRITE_COLUMNS - 1) // SPRITE_COLUMNS) * SPRITE_CELL)
                if image.size != expected:
                    raise ValueError("精灵图片资源尺寸不正确")
                self.images[shiny] = image.convert("RGBA")
        column = (species_id - 1) % SPRITE_COLUMNS
        row = (species_id - 1) // SPRITE_COLUMNS
        image = self.images[shiny].crop((column * SPRITE_CELL, row * SPRITE_CELL, (column + 1) * SPRITE_CELL, (row + 1) * SPRITE_CELL))
        if image.getchannel("A").getbbox() is None:
            raise ValueError("该精灵的图片资源为空")
        return image

    def close(self) -> None:
        for image in self.images.values():
            image.close()
        self.images.clear()


class PokedexPortrait(ttk.Frame):
    def __init__(self, parent, atlas: PortraitAtlas | None = None) -> None:
        super().__init__(parent, padding=(6, 6, 10, 6))
        self.configure(width=184, height=220)
        self.pack_propagate(False)
        self.atlas = atlas if atlas is not None else PortraitAtlas()
        self.species_id = None
        self.species_name = ""
        self.shiny = False
        self.photo = None
        self.photos = {}
        self.error = ""
        self.picture_size = PORTRAIT_SIZE
        self.caption = tk.StringVar(self, value="选择精灵查看图片")
        self.button = ttk.Button(self, text="暂无图片", command=self.toggle, compound="top", takefocus=True, state="disabled")
        self.button.pack(fill="both", expand=True)
        self.button.bind("<Return>", self._keyboard_toggle)
        self.button.bind("<space>", self._keyboard_toggle)
        self.caption_label = ttk.Label(self, textvariable=self.caption, anchor="center", justify="center", wraplength=165, style="Muted.TLabel")
        self.bind("<Configure>", self._resize)

    def _resize(self, event) -> None:
        if event.width < 50 or event.height < 60:
            return
        available = min(event.width - 24, event.height - 46)
        size = min(PORTRAIT_SIZE, max(48, available // 24 * 24))
        if size != self.picture_size:
            self.picture_size = size
            self.photos.clear()
            self.render()

    def set_species(self, species_id: int | None, name: str = "") -> None:
        if species_id != self.species_id:
            self.species_id = species_id
            self.shiny = False
            self.photos.clear()
        self.species_name = name
        self.render()

    def toggle(self) -> None:
        if self.species_id is None or self.button.instate(["disabled"]):
            return
        self.shiny = not self.shiny
        self.render()

    def _keyboard_toggle(self, _event=None) -> str:
        self.toggle()
        return "break"

    def render(self) -> None:
        if self.species_id is None:
            self.photo = None
            self.button.configure(image="", text="暂无图片", state="disabled")
            self.caption.set("选择精灵查看图片")
            return
        try:
            if self.shiny not in self.photos:
                source = self.atlas.crop(self.species_id, self.shiny)
                enlarged = source.resize((self.picture_size, self.picture_size), Image.Resampling.NEAREST)
                self.photos[self.shiny] = ImageTk.PhotoImage(enlarged, master=self)
            self.photo = self.photos[self.shiny]
        except (OSError, ValueError) as error:
            self.error = str(error)
            self.photo = None
            self.button.configure(image="", text="图片暂不可用", state="disabled")
            self.caption.set("请使用完整发行包")
            return
        self.error = ""
        mode = "闪光" if self.shiny else "普通"
        self.button.configure(image=self.photo, text=f"{self.species_name} · {mode}", state="normal")
        self.caption.set("")

    def destroy(self) -> None:
        self.photos.clear()
        self.photo = None
        self.atlas.close()
        super().destroy()

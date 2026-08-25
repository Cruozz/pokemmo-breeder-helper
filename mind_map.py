from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import BOTH, LEFT, RIGHT, X, Y, Canvas
from tkinter import ttk
from typing import Callable

MODULE_DIR = Path(__file__).resolve().parent
VENDOR_DIR = MODULE_DIR / "vendor"
if VENDOR_DIR.exists():
    sys.path.insert(0, str(VENDOR_DIR))

from PIL import Image, ImageTk


POKEMON_ATLAS_COLUMNS = 16
POKEMON_ATLAS_CELL = 96
ITEM_ATLAS_CELL = 32
ITEM_ATLAS_KEYS = (
    "power-weight",
    "power-bracer",
    "power-belt",
    "power-lens",
    "power-band",
    "power-anklet",
    "everstone",
)


@dataclass
class MindMapNode:
    key: str
    title: str
    iv_text: str = ""
    detail: str = ""
    item_text: str = ""
    status_text: str = ""
    nature_text: str = ""
    kind: str = "pending"
    step_number: int | None = None
    completed: bool = False
    actionable: bool = False
    show_checkbox: bool = False
    species_id: int | None = None
    item_keys: tuple[str, ...] = ()
    iv_values: tuple[str, ...] = ()
    exclude_material_id: str = ""
    children: list["MindMapNode"] = field(default_factory=list)


class BreedingMindMap(ttk.Frame):
    """Scrollable, zoomable dependency map built with native Tk Canvas items."""

    BASE_NODE_WIDTH = 300
    BASE_NODE_HEIGHT = 140
    BASE_HORIZONTAL_GAP = 28
    BASE_VERTICAL_GAP = 78
    BASE_MARGIN = 34

    def __init__(
        self,
        parent,
        *,
        colors: dict[str, str],
        font_family: str,
        on_step_activate: Callable[[int], object],
        on_material_exclude: Callable[[str], object] | None = None,
        asset_root: Path | None = None,
    ) -> None:
        super().__init__(parent)
        self.colors = colors
        self.font_family = font_family
        self.on_step_activate = on_step_activate
        self.on_material_exclude = on_material_exclude
        self.root_node: MindMapNode | None = None
        self.nodes_by_key: dict[str, MindMapNode] = {}
        self.positions: dict[str, tuple[float, float]] = {}
        self.subtree_widths: dict[str, float] = {}
        self.zoom = 1.0
        self.selected_key = ""
        self._center_after_id = None
        resource_base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
        self.asset_root = asset_root or resource_base / "assets"
        self._pokemon_atlas = self._load_atlas(self.asset_root / "pokemon_atlas.png")
        self._item_atlas = self._load_atlas(self.asset_root / "item_atlas.png")
        self._photo_images: list[ImageTk.PhotoImage] = []

        toolbar = ttk.Frame(self, style="Toolbar.TFrame", padding=(8, 5))
        toolbar.pack(fill=X)
        ttk.Label(
            toolbar,
            text="路线思维导图 · 滚轮缩放 · 中键拖动 · 库存叶节点可本次禁用",
            style="Muted.TLabel",
        ).pack(side=LEFT)
        ttk.Button(toolbar, text="−", width=3, style="Compact.TButton", command=lambda: self.set_zoom(self.zoom - 0.1)).pack(side=RIGHT, padx=(3, 0))
        ttk.Button(toolbar, text="100%", width=6, style="Compact.TButton", command=lambda: self.set_zoom(1.0)).pack(side=RIGHT, padx=(3, 0))
        ttk.Button(toolbar, text="+", width=3, style="Compact.TButton", command=lambda: self.set_zoom(self.zoom + 0.1)).pack(side=RIGHT, padx=(3, 0))

        surface = ttk.Frame(self)
        surface.pack(fill=BOTH, expand=True)
        self.canvas = Canvas(
            surface,
            background=colors["surface_alt"],
            highlightthickness=1,
            highlightbackground=colors["border_blue"],
            takefocus=True,
        )
        vertical = ttk.Scrollbar(surface, orient="vertical", command=self.canvas.yview)
        horizontal = ttk.Scrollbar(surface, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        surface.rowconfigure(0, weight=1)
        surface.columnconfigure(0, weight=1)

        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind("<Shift-MouseWheel>", self._on_shift_mousewheel)
        self.canvas.bind("<Control-MouseWheel>", self._on_ctrl_mousewheel)
        self.canvas.bind("<ButtonPress-2>", self._start_pan)
        self.canvas.bind("<B2-Motion>", self._drag_pan)
        self.canvas.bind("<ButtonRelease-2>", self._stop_pan)
        self.canvas.bind("<Shift-ButtonPress-1>", self._start_pan)
        self.canvas.bind("<Shift-B1-Motion>", self._drag_pan)
        self.canvas.bind("<Shift-ButtonRelease-1>", self._stop_pan)
        self.canvas.bind("<space>", self._activate_selected)
        self.canvas.bind("<Return>", self._activate_selected)
        self.canvas.bind("<e>", self._exclude_selected)

    @property
    def node_count(self) -> int:
        return len(self.nodes_by_key)

    def set_root(self, root: MindMapNode | None, empty_message: str = "暂无可显示的路线") -> None:
        same_tree = bool(self.root_node and root and self.root_node.key == root.key)
        old_x = self.canvas.xview()[0] if same_tree else 0.0
        old_y = self.canvas.yview()[0] if same_tree else 0.0
        self.root_node = root
        if not same_tree:
            self.selected_key = ""
        self.nodes_by_key.clear()
        if root is not None:
            self._index(root)
        self.render(empty_message, center=not same_tree)
        if same_tree:
            self.canvas.xview_moveto(old_x)
            self.canvas.yview_moveto(old_y)

    def _index(self, node: MindMapNode) -> None:
        self.nodes_by_key[node.key] = node
        for child in node.children:
            self._index(child)

    def set_zoom(self, value: float, anchor: tuple[float, float] | None = None) -> None:
        next_zoom = max(0.6, min(1.8, round(value, 1)))
        if next_zoom == self.zoom:
            return
        if self._center_after_id is not None:
            try:
                self.after_cancel(self._center_after_id)
            except Exception:
                pass
            self._center_after_id = None

        self.update_idletasks()
        anchor_x, anchor_y = anchor or (
            max(1, self.canvas.winfo_width()) / 2,
            max(1, self.canvas.winfo_height()) / 2,
        )
        logical_x = self.canvas.canvasx(anchor_x) / self.zoom
        logical_y = self.canvas.canvasy(anchor_y) / self.zoom
        self.zoom = next_zoom
        self.render(center=False)
        self.update_idletasks()

        region = self.canvas.bbox("all")
        if region:
            width = max(1, region[2] - region[0])
            height = max(1, region[3] - region[1])
            desired_left = logical_x * self.zoom - anchor_x
            desired_top = logical_y * self.zoom - anchor_y
            self.canvas.xview_moveto(max(0.0, (desired_left - region[0]) / width))
            self.canvas.yview_moveto(max(0.0, (desired_top - region[1]) / height))

    def _scaled(self, value: float) -> float:
        return value * self.zoom

    def _measure(self, node: MindMapNode) -> float:
        node_width = self._scaled(self.BASE_NODE_WIDTH)
        if not node.children:
            width = node_width
        else:
            children_width = sum(self._measure(child) for child in node.children)
            children_width += self._scaled(self.BASE_HORIZONTAL_GAP) * max(0, len(node.children) - 1)
            width = max(node_width, children_width)
        self.subtree_widths[node.key] = width
        return width

    def _place(self, node: MindMapNode, left: float, depth: int) -> None:
        width = self.subtree_widths[node.key]
        node_width = self._scaled(self.BASE_NODE_WIDTH)
        x = left + width / 2 - node_width / 2
        y = self._scaled(self.BASE_MARGIN + depth * (self.BASE_NODE_HEIGHT + self.BASE_VERTICAL_GAP))
        self.positions[node.key] = (x, y)
        child_left = left
        for child in node.children:
            self._place(child, child_left, depth + 1)
            child_left += self.subtree_widths[child.key] + self._scaled(self.BASE_HORIZONTAL_GAP)

    def render(self, empty_message: str = "暂无可显示的路线", *, center: bool = True) -> None:
        self.canvas.delete("all")
        self._photo_images.clear()
        self.positions.clear()
        self.subtree_widths.clear()
        root = self.root_node
        if root is None:
            self.canvas.create_text(
                28,
                30,
                anchor="nw",
                text=empty_message,
                fill=self.colors["muted"],
                font=(self.font_family, 10),
            )
            self.canvas.configure(scrollregion=(0, 0, 640, 260))
            return

        tree_width = self._measure(root)
        self._place(root, self._scaled(self.BASE_MARGIN), 0)
        max_depth = self._depth(root)
        total_width = tree_width + self._scaled(self.BASE_MARGIN * 2)
        total_height = self._scaled(
            self.BASE_MARGIN * 2
            + (max_depth + 1) * self.BASE_NODE_HEIGHT
            + max_depth * self.BASE_VERTICAL_GAP
        )
        self._draw_edges(root)
        self._draw_nodes(root)
        self.canvas.configure(scrollregion=(0, 0, total_width, total_height))
        if center:
            self._schedule_center_on_root()

    def _depth(self, node: MindMapNode) -> int:
        if not node.children:
            return 0
        return 1 + max(self._depth(child) for child in node.children)

    def _draw_edges(self, node: MindMapNode) -> None:
        x, y = self.positions[node.key]
        node_width = self._scaled(self.BASE_NODE_WIDTH)
        node_height = self._scaled(self.BASE_NODE_HEIGHT)
        start_x = x + node_width / 2
        start_y = y + node_height
        for child in node.children:
            child_x, child_y = self.positions[child.key]
            end_x = child_x + node_width / 2
            middle_y = start_y + (child_y - start_y) / 2
            self.canvas.create_line(
                start_x,
                start_y,
                start_x,
                middle_y,
                end_x,
                middle_y,
                end_x,
                child_y,
                fill=self.colors["border_blue"],
                width=max(2, round(2 * self.zoom)),
                joinstyle="round",
            )
            self._draw_edges(child)

    def _node_palette(self, node: MindMapNode) -> tuple[str, str, str]:
        palettes = {
            "target": (self.colors["selected"], self.colors["accent"], self.colors["ink_blue"]),
            "current": (self.colors["accent_soft"], self.colors["action"], self.colors["ink_blue"]),
            "completed": (self.colors["success_soft"], self.colors["success"], self.colors["success_text"]),
            "purchase": (self.colors["warning_soft"], self.colors["warning"], self.colors["warning_text"]),
            "inventory": (self.colors["surface"], self.colors["success"], self.colors["ink"]),
            "pending": (self.colors["surface"], self.colors["border_blue"], self.colors["ink"]),
        }
        return palettes.get(node.kind, palettes["pending"])

    def _draw_nodes(self, node: MindMapNode) -> None:
        self._draw_node(node)
        for child in node.children:
            self._draw_nodes(child)

    def _draw_node(self, node: MindMapNode) -> None:
        x, y = self.positions[node.key]
        width = self._scaled(self.BASE_NODE_WIDTH)
        height = self._scaled(self.BASE_NODE_HEIGHT)
        fill, border, text_color = self._node_palette(node)
        outline = self.colors["accent"] if node.key == self.selected_key else border
        outline_width = 3 if node.key == self.selected_key else 2
        common_tags = (f"node:{node.key}", "mind-node")
        self.canvas.create_rectangle(
            x,
            y,
            x + width,
            y + height,
            fill=fill,
            outline=outline,
            width=max(1, round(outline_width * self.zoom)),
            tags=common_tags + (f"card:{node.key}", "mind-card"),
        )

        left = x + self._scaled(12)
        title_left = left
        if node.show_checkbox or node.step_number is not None:
            box = self._scaled(18)
            checkbox_tags = (f"node:{node.key}", "mind-check-hitbox")
            if node.step_number is not None:
                checkbox_tags += (f"check:{node.key}",)
            self.canvas.create_rectangle(
                left - self._scaled(5),
                y + self._scaled(7),
                left + self._scaled(23),
                y + self._scaled(35),
                fill=fill,
                outline="",
                tags=checkbox_tags,
            )
            self.canvas.create_rectangle(
                left,
                y + self._scaled(12),
                left + box,
                y + self._scaled(12) + box,
                fill=self.colors["success"] if node.completed else self.colors["surface"],
                outline=self.colors["success"] if node.completed else border,
                width=max(1, round(2 * self.zoom)),
                tags=checkbox_tags + ("mind-check",),
            )
            if node.completed:
                self.canvas.create_line(
                    left + self._scaled(4),
                    y + self._scaled(21),
                    left + self._scaled(8),
                    y + self._scaled(25),
                    left + self._scaled(15),
                    y + self._scaled(16),
                    fill="#FFFFFF",
                    width=max(2, round(2 * self.zoom)),
                    tags=checkbox_tags + ("mind-check",),
                )
            title_left += self._scaled(28)

        self.canvas.create_text(
            title_left,
            y + self._scaled(11),
            anchor="nw",
            text=self._short(node.title, 21),
            fill=text_color,
            font=(self.font_family, max(8, round(9 * self.zoom)), "bold"),
            tags=common_tags,
        )
        self._draw_iv_row(node, left, y + self._scaled(39), common_tags)
        self.canvas.create_text(
            left,
            y + self._scaled(66),
            anchor="nw",
            text=self._short(node.detail, 29),
            fill=self.colors["muted"],
            font=(self.font_family, max(7, round(8 * self.zoom))),
            tags=common_tags,
        )
        self.canvas.create_text(
            left,
            y + self._scaled(86),
            anchor="nw",
            text=self._short(node.item_text, 29),
            fill=self.colors["muted"],
            font=(self.font_family, max(7, round(8 * self.zoom))),
            tags=common_tags,
        )
        self._draw_node_media(node, x, y, width, common_tags)
        self._draw_chip(node, left, y + self._scaled(116), node.status_text, border, fill)
        if node.nature_text:
            nature_width = min(self._scaled(104), max(self._scaled(58), self._scaled(10 + len(node.nature_text) * 7)))
            self._draw_chip(
                node,
                left + self._scaled(54),
                y + self._scaled(116),
                node.nature_text,
                self.colors["action"],
                self.colors["accent_soft"],
                forced_width=nature_width,
            )
        if node.exclude_material_id:
            self._draw_exclude_action(node, x, y, width)

    @staticmethod
    def _load_atlas(path: Path) -> Image.Image | None:
        try:
            with Image.open(path) as source:
                return source.convert("RGBA")
        except (FileNotFoundError, OSError):
            return None

    def _draw_iv_row(
        self,
        node: MindMapNode,
        x: float,
        y: float,
        tags: tuple[str, ...],
    ) -> None:
        if not node.iv_values:
            self.canvas.create_text(
                x,
                y,
                anchor="nw",
                text=self._short(node.iv_text, 29),
                fill=self.colors["ink_blue"],
                font=(self.font_family, max(8, round(9 * self.zoom)), "bold"),
                tags=tags,
            )
            return

        label_width = self._scaled(30)
        self.canvas.create_text(
            x,
            y + self._scaled(2),
            anchor="nw",
            text=self._short(node.iv_text, 5),
            fill=self.colors["ink_blue"],
            font=(self.font_family, max(8, round(8 * self.zoom)), "bold"),
            tags=tags,
        )
        cell_width = self._scaled(22)
        cell_height = self._scaled(19)
        gap = self._scaled(2)
        start_x = x + label_width
        for index, raw in enumerate(node.iv_values[:6]):
            value = str(raw or "X").upper()
            value_kind = self._iv_value_kind(value)
            if value_kind == "perfect":
                cell_fill = self.colors["success_soft"]
                cell_text = self.colors["success_text"]
                cell_border = self.colors["success"]
            elif value_kind == "any":
                cell_fill = self.colors["surface_alt"]
                cell_text = self.colors["muted"]
                cell_border = self.colors["border"]
                value = "X"
            else:
                cell_fill = self.colors["accent_soft"]
                cell_text = self.colors["ink_blue"]
                cell_border = self.colors["action"]
            cell_x = start_x + index * (cell_width + gap)
            self.canvas.create_rectangle(
                cell_x,
                y,
                cell_x + cell_width,
                y + cell_height,
                fill=cell_fill,
                outline=cell_border,
                width=1,
                tags=tags,
            )
            self.canvas.create_text(
                cell_x + cell_width / 2,
                y + cell_height / 2,
                text=value,
                fill=cell_text,
                font=(self.font_family, max(7, round(8 * self.zoom)), "bold"),
                tags=tags,
            )

    @staticmethod
    def _iv_value_kind(value: str) -> str:
        normalized = str(value or "X").strip().upper()
        if normalized == "31":
            return "perfect"
        if normalized in {"X", "-", "任意", "NONE"}:
            return "any"
        return "exact"

    def _draw_node_media(
        self,
        node: MindMapNode,
        x: float,
        y: float,
        width: float,
        tags: tuple[str, ...],
    ) -> None:
        panel_left = x + width - self._scaled(72)
        panel_right = x + width - self._scaled(8)
        if node.species_id and self._pokemon_atlas is not None:
            self.canvas.create_rectangle(
                panel_left,
                y + self._scaled(8),
                panel_right,
                y + self._scaled(78),
                fill=self.colors["surface_alt"],
                outline=self.colors["border_blue"],
                width=1,
                tags=tags,
            )
            photo = self._pokemon_photo(node.species_id, max(24, round(62 * self.zoom)))
            if photo is not None:
                self.canvas.create_image(
                    (panel_left + panel_right) / 2,
                    y + self._scaled(43),
                    image=photo,
                    anchor="center",
                    tags=tags,
                )

        item_keys = tuple(key for key in node.item_keys if key in ITEM_ATLAS_KEYS)[:2]
        if item_keys and self._item_atlas is not None:
            item_top = y + self._scaled(84)
            item_bottom = y + self._scaled(113)
            self.canvas.create_rectangle(
                panel_left,
                item_top,
                panel_right,
                item_bottom,
                fill=self.colors["accent_soft"],
                outline=self.colors["action"],
                width=1,
                tags=tags,
            )
            icon_size = max(14, round(24 * self.zoom))
            spacing = self._scaled(26)
            first_x = (panel_left + panel_right) / 2 - spacing * (len(item_keys) - 1) / 2
            for index, key in enumerate(item_keys):
                photo = self._item_photo(key, icon_size)
                if photo is not None:
                    self.canvas.create_image(
                        first_x + index * spacing,
                        (item_top + item_bottom) / 2,
                        image=photo,
                        anchor="center",
                        tags=tags,
                    )

    def _pokemon_photo(self, species_id: int, size: int) -> ImageTk.PhotoImage | None:
        if self._pokemon_atlas is None or not 1 <= species_id <= 649:
            return None
        column = (species_id - 1) % POKEMON_ATLAS_COLUMNS
        row = (species_id - 1) // POKEMON_ATLAS_COLUMNS
        box = (
            column * POKEMON_ATLAS_CELL,
            row * POKEMON_ATLAS_CELL,
            (column + 1) * POKEMON_ATLAS_CELL,
            (row + 1) * POKEMON_ATLAS_CELL,
        )
        source = self._pokemon_atlas.crop(box).resize((size, size), Image.Resampling.NEAREST)
        photo = ImageTk.PhotoImage(source)
        self._photo_images.append(photo)
        return photo

    def _item_photo(self, key: str, size: int) -> ImageTk.PhotoImage | None:
        if self._item_atlas is None or key not in ITEM_ATLAS_KEYS:
            return None
        index = ITEM_ATLAS_KEYS.index(key)
        box = (index * ITEM_ATLAS_CELL, 0, (index + 1) * ITEM_ATLAS_CELL, ITEM_ATLAS_CELL)
        source = self._item_atlas.crop(box).resize((size, size), Image.Resampling.NEAREST)
        photo = ImageTk.PhotoImage(source)
        self._photo_images.append(photo)
        return photo

    def _draw_chip(
        self,
        node: MindMapNode,
        x: float,
        y: float,
        text: str,
        border: str,
        fill: str,
        *,
        forced_width: float | None = None,
    ) -> None:
        if not text:
            return
        width = forced_width or min(self._scaled(94), max(self._scaled(46), self._scaled(12 + len(text) * 7)))
        height = self._scaled(16)
        tags = (f"node:{node.key}", "mind-chip")
        self.canvas.create_rectangle(x, y, x + width, y + height, fill=fill, outline=border, width=1, tags=tags)
        self.canvas.create_text(
            x + width / 2,
            y + height / 2,
            text=self._short(text, 12),
            fill=border,
            font=(self.font_family, max(7, round(7 * self.zoom)), "bold"),
            tags=tags,
        )

    def _draw_exclude_action(self, node: MindMapNode, x: float, y: float, width: float) -> None:
        button_width = self._scaled(64)
        button_height = self._scaled(18)
        button_x = x + width - self._scaled(72)
        button_y = y + self._scaled(116)
        tags = (
            f"node:{node.key}",
            f"exclude:{node.key}",
            "exclude-action",
        )
        self.canvas.create_rectangle(
            button_x,
            y + self._scaled(112),
            button_x + button_width,
            y + self._scaled(138),
            fill="",
            outline="",
            tags=tags,
        )
        self.canvas.create_rectangle(
            button_x,
            button_y,
            button_x + button_width,
            button_y + button_height,
            fill=self.colors["danger_soft"],
            outline=self.colors["danger"],
            width=1,
            tags=tags,
        )
        self.canvas.create_text(
            button_x + button_width / 2,
            button_y + button_height / 2,
            text="本次禁用",
            fill=self.colors["danger_text"],
            font=(self.font_family, max(7, round(7 * self.zoom)), "bold"),
            tags=tags,
        )

    @staticmethod
    def _short(value: str, length: int) -> str:
        value = (value or "").strip()
        return value if len(value) <= length else value[: max(1, length - 1)] + "…"

    def _on_click(self, _event=None):
        current = self.canvas.find_withtag("current")
        if not current:
            return None
        tags = self.canvas.gettags(current[0])
        node_tag = next((tag for tag in tags if tag.startswith("node:")), "")
        if not node_tag:
            self.selected_key = ""
            self._refresh_selection()
            return None
        key = node_tag.split(":", 1)[1]
        self.selected_key = key
        self.canvas.focus_set()
        if any(tag.startswith("exclude:") for tag in tags):
            return self._exclude_key(key)
        if any(tag.startswith("check:") for tag in tags):
            return self._activate_key(key)
        self._refresh_selection()
        return "break"

    def _refresh_selection(self) -> None:
        for key, node in self.nodes_by_key.items():
            _fill, border, _text = self._node_palette(node)
            selected = key == self.selected_key
            self.canvas.itemconfigure(
                f"card:{key}",
                outline=self.colors["accent"] if selected else border,
                width=max(1, round((3 if selected else 2) * self.zoom)),
            )

    def _activate_selected(self, _event=None):
        return self._activate_key(self.selected_key)

    def _exclude_selected(self, _event=None):
        return self._exclude_key(self.selected_key)

    def _exclude_key(self, key: str):
        node = self.nodes_by_key.get(key)
        if node is None or not node.exclude_material_id or self.on_material_exclude is None:
            return "break"
        self.on_material_exclude(node.exclude_material_id)
        return "break"

    def _activate_key(self, key: str):
        node = self.nodes_by_key.get(key)
        if node is None or node.step_number is None:
            return "break"
        self.on_step_activate(node.step_number)
        return "break"

    def _on_mousewheel(self, event):
        if event.delta:
            self.set_zoom(
                self.zoom + (0.1 if event.delta > 0 else -0.1),
                (event.x, event.y),
            )
        return "break"

    def _on_shift_mousewheel(self, event):
        self.canvas.xview_scroll(-1 if event.delta > 0 else 1, "units")
        return "break"

    def _on_ctrl_mousewheel(self, event):
        return self._on_mousewheel(event)

    def _start_pan(self, event):
        self.canvas.focus_set()
        self.canvas.configure(cursor="fleur")
        self.canvas.scan_mark(event.x, event.y)
        return "break"

    def _drag_pan(self, event):
        self.canvas.scan_dragto(event.x, event.y, gain=1)
        return "break"

    def _stop_pan(self, _event=None):
        self.canvas.configure(cursor="")
        return "break"

    def _schedule_center_on_root(self) -> None:
        if self._center_after_id is not None:
            try:
                self.after_cancel(self._center_after_id)
            except Exception:
                pass
        self._center_after_id = self.after_idle(self._center_on_root)

    def _center_on_root(self) -> None:
        self._center_after_id = None
        root = self.root_node
        if root is None or root.key not in self.positions:
            return
        self.update_idletasks()
        scrollregion = self.canvas.bbox("all")
        if not scrollregion:
            return
        total_width = max(1, scrollregion[2] - scrollregion[0])
        viewport = max(1, self.canvas.winfo_width())
        x, _y = self.positions[root.key]
        root_center = x + self._scaled(self.BASE_NODE_WIDTH) / 2
        fraction = max(0.0, min(1.0, (root_center - viewport / 2) / max(1, total_width - viewport)))
        self.canvas.xview_moveto(fraction)
        self.canvas.yview_moveto(0.0)

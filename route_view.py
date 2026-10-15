"""Two presentations of the same route. Changing presentation never edits a plan."""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from tkinter import BOTH, LEFT, X, Canvas, StringVar, ttk

from mind_map import BreedingMindMap, MindMapNode


GENDER_FILLS = {"M": "#DBEAFE", "F": "#FCE7F3"}
STAT_NAMES = ("HP", "攻击", "防御", "特攻", "特防", "速度")


@dataclass(frozen=True)
class TextStep:
    stage: int
    node: MindMapNode


def text_steps(root: MindMapNode | None) -> list[TextStep]:
    """Group executable steps by dependency depth, retaining their original numbers.

    Unnumbered explanation/context nodes are not additional breeding operations.
    """
    result: dict[str, TextStep] = {}

    def visit(node: MindMapNode) -> int:
        if node.key in result:
            return result[node.key].stage
        previous = max((visit(child) for child in node.children), default=0)
        if node.step_number is None:
            return previous
        stage = previous + 1
        result[node.key] = TextStep(stage, node)
        return stage

    if root:
        visit(root)
    return sorted(result.values(), key=lambda step: (step.stage, step.node.step_number))


def held_item(node: MindMapNode) -> str:
    return node.item_text.removeprefix("本只携带：").strip() or "无需道具"


class BreedingTextSteps(ttk.Frame):
    """A responsive, vertically scrollable list; only visible cards are drawn."""

    ROW_HEIGHT = 110
    HEADER_HEIGHT = 38
    GAP = 14

    def __init__(self, parent, *, colors, font_family, pokemon_photo, on_step_select=None):
        super().__init__(parent)
        self.colors, self.font_family = colors, font_family
        self.pokemon_photo = pokemon_photo
        self.on_step_select = on_step_select
        self.root_node = None
        self.steps: list[TextStep] = []
        self.selected_key = ""
        self.empty_message = "暂无可显示的路线"
        self._draw_after = None
        self._layouts = []
        self._starts = []
        self._height = 1
        self.canvas = Canvas(self, width=1, height=1, background=colors["surface_alt"],
                             highlightthickness=1, highlightbackground=colors["border_blue"], takefocus=True)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self._yview)
        self.canvas.configure(yscrollcommand=self._scrolled)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.canvas.bind("<Configure>", self._resize)
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.canvas.bind("<Button-4>", lambda _event: self._scroll(-3))
        self.canvas.bind("<Button-5>", lambda _event: self._scroll(3))
        self.canvas.bind("<Button-1>", self._click)
        for key, amount in (("Up", -1), ("Down", 1), ("Prior", -1), ("Next", 1)):
            self.canvas.bind(f"<{key}>", lambda _event, n=amount, unit="pages" if key in {"Prior", "Next"} else "units": self._scroll(n, unit))
        self.canvas.bind("<Home>", lambda _event: self._yview("moveto", 0))
        self.canvas.bind("<End>", lambda _event: self._yview("moveto", 1))

    def destroy(self):
        if self._draw_after is not None:
            self.after_cancel(self._draw_after)
        super().destroy()

    def set_root(self, root, empty_message="暂无可显示的路线"):
        same = bool(self.root_node and root and self.root_node.key == root.key)
        self.root_node, self.empty_message = root, empty_message
        self.steps = text_steps(root)
        if not same:
            self.selected_key = ""
            self.canvas.yview_moveto(0)
        self._layout()
        self._schedule_draw()

    def _layout(self):
        y, stage = 12, 0
        self._layouts = []
        for step in self.steps:
            if step.stage != stage:
                count = sum(item.stage == step.stage for item in self.steps)
                self._layouts.append((y, y + 42, "stage", (step.stage, count)))
                y += 42
                stage = step.stage
            height = self.HEADER_HEIGHT + sum(self._row_height(node) for node in [*step.node.children, step.node]) + 8
            self._layouts.append((y, y + height, "step", step.node))
            y += height + self.GAP
        # A ready-made inventory result has no breeding steps, but must stay visible.
        if not self.steps and self.root_node:
            height = self._row_height(self.root_node)
            self._layouts.append((y, y + height + 8, "result", self.root_node))
            y += height + 20
        self._starts = [item[0] for item in self._layouts]
        self._height = max(1, y + 12)
        self.canvas.configure(scrollregion=(0, 0, max(1, self.canvas.winfo_width() - 2), self._height))

    def _resize(self, _event):
        self._layout()
        self._schedule_draw()

    def _scrolled(self, first, last):
        self.scrollbar.set(first, last)
        self._schedule_draw()

    def _schedule_draw(self):
        if self._draw_after is None:
            self._draw_after = self.after_idle(self._draw)

    def _yview(self, *args):
        self.canvas.yview(*args)
        self._schedule_draw()
        return "break"

    def _scroll(self, amount, unit="units"):
        return self._yview("scroll", amount, unit)

    def _wheel(self, event):
        return self._scroll(-max(1, abs(event.delta) // 120) * (1 if event.delta > 0 else -1) * 3)

    def _text(self, x, y, text, *, tags=(), size=10, bold=False, fill=None, width=0, anchor="nw"):
        return self.canvas.create_text(x, y, text=text, anchor=anchor, width=width,
                                       fill=fill or self.colors["ink"],
                                       font=(self.font_family, size, "bold" if bold else "normal"), tags=tags)

    def _draw(self):
        self._draw_after = None
        self.canvas.delete("all")
        width = self.canvas.winfo_width()
        if width < 10:
            return
        if not self._layouts:
            self._text(16, 18, self.empty_message, width=max(1, width - 32), fill=self.colors["muted"])
            return
        top = self.canvas.canvasy(0)
        bottom = top + self.canvas.winfo_height()
        first = max(0, bisect_right(self._starts, top) - 1)
        left, right = 12, width - 14
        for y, end, kind, data in self._layouts[first:]:
            if y > bottom:
                break
            if end < top:
                continue
            if kind == "stage":
                stage, count = data
                self._text(left + 2, y + 7, f"第 {stage} 阶段", size=12, bold=True)
                self._text(right - 4, y + 9, f"{count} 次", anchor="ne", fill=self.colors["muted"])
            elif kind == "result":
                self._monster_row(data, left, y, right, "成品", show_item=False)
            else:
                self._step_card(data, left, y, right, end)

    def _step_card(self, node, left, y, right, bottom):
        tags = (f"step:{node.key}", "text-step")
        selected = node.key == self.selected_key
        self.canvas.create_rectangle(left, y, right, bottom, fill=self.colors["surface"],
                                     outline=self.colors["action"] if selected else self.colors["border_blue"],
                                     width=2 if selected else 1, tags=tags)
        self._text(left + 12, y + 9, f"步骤 {node.step_number}", bold=True, fill=self.colors["ink_blue"], tags=tags)
        state = "已完成" if node.completed else "孵化中" if node.in_progress else "可执行" if node.actionable else ""
        if state:
            self._text(right - 12, y + 9, state, anchor="ne", fill=self.colors["muted"], tags=tags)
        row_y = y + self.HEADER_HEIGHT
        for index, parent in enumerate(node.children):
            label = f"亲本 {chr(65 + index)}"
            reference = f"步骤 {parent.step_number} 产物" if parent.step_number is not None else ""
            self._monster_row(parent, left + 8, row_y,
                              right - 8, label, reference, tags=tags)
            row_y += self._row_height(parent)
        self._monster_row(node, left + 8, row_y,
                          right - 8, "得到", show_item=False, tags=tags)

    def _skill_lines(self, node):
        return (["技能：" + "、".join(node.route_moves)] if node.route_moves else []) + [
            "配种前须准备：" + text for text in node.preparation_text
        ]

    def _row_height(self, node):
        height = self.ROW_HEIGHT
        width = max(80, self.canvas.winfo_width() - 70)
        for text in self._skill_lines(node):
            item = self._text(0, 0, text, size=9, width=width)
            bounds = self.canvas.bbox(item)
            self.canvas.delete(item)
            height += (bounds[3] - bounds[1] if bounds else 18) + 5
        return height

    def _monster_row(self, node, left, top, right, label, reference="", *, show_item=True, tags=()):
        fill = GENDER_FILLS.get(node.gender, "#F8FAFC")
        self.canvas.create_rectangle(left, top, right, top + self._row_height(node) - 6, fill=fill, outline="", tags=tags + ("text-monster",))
        self._text(left + 10, top + 10, label, bold=True, size=9, tags=tags)
        if reference:
            self._text(left + 10, top + 34, reference.replace(" 产物", "\n产物"), size=8, tags=tags)
        sprite_x = left + 94
        if node.species_id:
            photo = self.pokemon_photo(node.species_id, 56)
            if photo is not None:
                self.canvas.create_image(sprite_x, top + 31, image=photo, tags=tags + ("text-sprite",))
        name_x = left + 130
        gender = {"M": " ♂", "F": " ♀", "N": " 无性别"}.get(node.gender, " 未锁性别")
        self._text(name_x, top + 8, (node.species_name or node.title) + gender,
                   bold=True, width=max(30, right - name_x - 10), tags=tags + ("text-species",))
        if show_item:
            self._text(name_x, top + 37, held_item(node), size=9,
                       width=max(30, right - name_x - 10), tags=tags + ("text-held-item",))
        values = node.iv_values
        count = sum(value == "31" for value in values) if values else None
        self._text(left + 12, top + 77, f"{count}V" if count is not None else node.iv_text, bold=True, size=9, tags=tags)
        stat_left = left + 65
        cell = max(1, (right - stat_left - 8) / 6)
        for index, stat in enumerate(STAT_NAMES):
            value = values[index] if index < len(values) else "X"
            x = stat_left + index * cell
            self.canvas.create_rectangle(x + 2, top + 66, x + cell - 2, top + 99,
                                         fill="#F0FDF4" if value == "31" else "#FFFFFF", outline="#CBD5E1", tags=tags)
            self._text(x + cell / 2, top + 69, stat, size=8, anchor="n", tags=tags)
            self._text(x + cell / 2, top + 83, value, size=9, bold=value == "31", anchor="n", tags=tags + ("text-iv",))
        extra_y = top + 106
        for text in self._skill_lines(node):
            item = self._text(left + 10, extra_y, text, size=9, width=max(80, right - left - 20),
                              tags=tags + ("text-skill",), fill=self.colors["ink_blue"])
            bounds = self.canvas.bbox(item)
            extra_y += (bounds[3] - bounds[1] if bounds else 18) + 5

    def _click(self, event):
        self.canvas.focus_set()
        x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        for item in reversed(self.canvas.find_overlapping(x, y, x, y)):
            key = next((tag[5:] for tag in self.canvas.gettags(item) if tag.startswith("step:")), "")
            if not key:
                continue
            self.selected_key = key
            step = next(entry.node for entry in self.steps if entry.node.key == key)
            self._schedule_draw()
            if self.on_step_select:
                self.on_step_select(step.step_number)
            break


class BreedingRouteView(ttk.Frame):
    """Own the view switch while preserving the original map and its viewport."""

    def __init__(self, parent, **map_options):
        super().__init__(parent)
        self.mode = StringVar(self, "map")
        self.root_node = None
        self.text_root = None
        self.empty_message = "暂无可显示的路线"
        bar = ttk.Frame(self, style="Toolbar.TFrame", padding=(8, 5))
        bar.pack(fill=X)
        ttk.Radiobutton(bar, text="思维导图", variable=self.mode, value="map", command=self._show_mode).pack(side=LEFT, padx=(0, 16))
        ttk.Radiobutton(bar, text="文字步骤", variable=self.mode, value="text", command=self._show_mode).pack(side=LEFT)
        self.map = BreedingMindMap(self, **map_options)
        self.text = BreedingTextSteps(self, colors=map_options["colors"], font_family=map_options["font_family"],
                                      pokemon_photo=self.map._pokemon_photo,
                                      on_step_select=map_options.get("on_step_select"))
        self._map_dirty = self._text_dirty = False
        self.map.pack(fill=BOTH, expand=True)

    @property
    def nodes_by_key(self):
        return self.map.nodes_by_key

    @property
    def node_count(self):
        return self.map.node_count

    def set_zoom(self, value, anchor=None):
        self.map.set_zoom(value, anchor)

    def set_mode(self, mode):
        if mode not in {"map", "text"}:
            raise ValueError("Unknown route presentation")
        self.mode.set(mode)
        self._show_mode()

    def _show_mode(self):
        if self.mode.get() == "text":
            self.map.pack_forget()
            self.text.pack(fill=BOTH, expand=True)
            if self._text_dirty:
                self.text.set_root(self.text_root, self.empty_message)
                self._text_dirty = False
        else:
            self.text.pack_forget()
            self.map.pack(fill=BOTH, expand=True)
            if self._map_dirty:
                self.map.set_root(self.root_node, self.empty_message)
                self._map_dirty = False

    def set_root(self, root, empty_message="暂无可显示的路线", *, text_root=None):
        self.root_node = root
        self.text_root = text_root if text_root is not None else root
        self.empty_message = empty_message
        self._map_dirty = self._text_dirty = True
        self._show_mode()

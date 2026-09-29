from __future__ import annotations

import math
import queue
import threading
import tkinter as tk
from tkinter import ttk

from pokedex_portrait import PokedexPortrait

from guide_data import (
    PERIOD_KEYS, REGIONS, SEASONS, STAT_LABELS, TYPE_LABELS,
    GuideDatabase, ev_text, ev_values, get_guide_database, group_hordes, horde_locations_text,
)


PAGE_SIZE = 150
PAGE_TITLES = {"hordes": "群怪分布", "pokedex": "精灵图鉴", "effort": "努力值"}


def readonly_text(parent: ttk.Frame, height: int = 6) -> tk.Text:
    holder = ttk.Frame(parent)
    holder.pack(fill="both", expand=True)
    text = tk.Text(holder, height=height, wrap="word", relief="flat", borderwidth=0,
                   padx=12, pady=8, font="TkDefaultFont", background="#FFFFFF", foreground="#0F172A",
                   selectbackground="#DBEAFE", selectforeground="#0F172A", state="disabled")
    scrollbar = ttk.Scrollbar(holder, orient="vertical", command=text.yview)
    text.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    text.pack(fill="both", expand=True)
    return text


def set_text(widget: tk.Text, content: str) -> None:
    widget.configure(state="normal")
    widget.delete("1.0", "end")
    widget.insert("1.0", content)
    widget.configure(state="disabled")
    widget.yview_moveto(0)


class ResultTable(ttk.Frame):
    def __init__(self, parent, columns: list[tuple[str, str, int]], selected, *, paginated=True) -> None:
        super().__init__(parent)
        self.paginated = paginated
        self.column_keys = [key for key, _label, _width in columns]
        self.rows: list[tuple[object, tuple]] = []
        self.page = 0
        self.sort_key = ""
        self.descending = False
        self.selected = selected
        self.tree = ttk.Treeview(self, columns=self.column_keys, show="headings", selectmode="browse", height=7)
        for key, label, width in columns:
            self.tree.heading(key, text=label, command=lambda column=key: self.sort(column))
            self.tree.column(key, width=width, minwidth=55, stretch=key in {"name", "location", "groups"})
        vertical = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        horizontal = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        controls = ttk.Frame(self, padding=(0, 5))
        controls.grid(row=2, column=0, columnspan=2, sticky="ew")
        self.count = tk.StringVar(self)
        ttk.Label(controls, textvariable=self.count, style="Muted.TLabel").pack(side="left")
        self.next_button = ttk.Button(controls, text="下一页", command=lambda: self.change_page(1))
        if paginated:
            self.next_button.pack(side="right")
        self.previous_button = ttk.Button(controls, text="上一页", command=lambda: self.change_page(-1))
        if paginated:
            self.previous_button.pack(side="right", padx=5)
        self.tree.bind("<<TreeviewSelect>>", self._select)

    def set_rows(self, rows: list[tuple[object, tuple]]) -> None:
        self.rows = rows
        self.page = 0
        if self.sort_key:
            self._sort_rows()
        self.render()

    def _sort_rows(self) -> None:
        index = self.column_keys.index(self.sort_key)
        self.rows.sort(key=lambda item: item[1][index], reverse=self.descending)

    def sort(self, key: str) -> None:
        self.descending = not self.descending if key == self.sort_key else False
        self.sort_key = key
        self._sort_rows()
        self.page = 0
        self.render()

    def change_page(self, offset: int) -> None:
        if not self.paginated:
            return
        self.page = max(0, min(self.page + offset, max(0, (len(self.rows) - 1) // PAGE_SIZE)))
        self.render()

    def render(self) -> None:
        children = self.tree.get_children()
        if children:
            self.tree.delete(*children)
        start = self.page * PAGE_SIZE if self.paginated else 0
        visible_rows = self.rows[start:start + PAGE_SIZE] if self.paginated else self.rows
        for index, (_record, values) in enumerate(visible_rows, start):
            self.tree.insert("", "end", iid=str(index), values=values)
        pages = max(1, math.ceil(len(self.rows) / PAGE_SIZE))
        show_pages = self.paginated and pages > 1
        if show_pages:
            self.next_button.pack(side="right")
            self.previous_button.pack(side="right", padx=5)
        else:
            self.next_button.pack_forget()
            self.previous_button.pack_forget()
        self.count.set((f"{len(self.rows):,} 条结果 · 第 {self.page + 1}/{pages} 页" if show_pages else f"{len(self.rows):,} 条结果")
                       if self.rows else "没有匹配结果；请清空关键词或放宽季节、地区筛选。")
        if self.rows and not self.paginated:
            self.count.set(f"{len(self.rows):,} 只精灵")
        self.previous_button.configure(state="normal" if self.page else "disabled")
        self.next_button.configure(state="normal" if self.page + 1 < pages else "disabled")
        if self.rows:
            self.tree.selection_set(str(start))
            self.tree.focus(str(start))
        else:
            self.selected(None)

    def _select(self, _event=None) -> None:
        selection = self.tree.selection()
        if selection:
            self.selected(self.rows[int(selection[0])][0])


class QueryPage(ttk.Frame):
    def __init__(self, parent, database: GuideDatabase, mode: str, navigate) -> None:
        super().__init__(parent, style="Panel.TFrame", padding=12)
        self.database = database
        self.mode = mode
        self.navigate = navigate
        self.pending = None
        self.selected_record = None
        self.variables = {}
        self.defaults = {}
        self.filter_cells = []
        self.filter_columns = 0
        heading = ttk.Frame(self)
        heading.pack(fill="x")
        ttk.Label(heading, text=PAGE_TITLES[mode], style="Title.TLabel").pack(side="left")
        search = ttk.Frame(self, padding=(0, 10, 0, 5))
        search.pack(fill="x")
        ttk.Label(search, text="搜索").pack(side="left", padx=(0, 8))
        self.query = tk.StringVar(self)
        self.entry = ttk.Entry(search, textvariable=self.query)
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<Return>", self._query_now)
        ttk.Button(search, text="清空筛选", command=self.reset).pack(side="left", padx=(8, 0))
        self.query.trace_add("write", self.schedule)
        self.filters = ttk.Frame(self)
        self.filters.pack(fill="x")
        self.filters.bind("<Configure>", self._layout_filters)
        if mode == "pokedex":
            self.add_filter("type", "属性", ("全部属性", *TYPE_LABELS.values()))
            groups = sorted({value for record in database.species for value in record["egg_groups"]})
            self.add_filter("egg_group", "蛋组", ("全部蛋组", *groups))
            self.add_filter("ability", "特性关键词", ("",), editable=True)
        else:
            self.add_filter("region", "地区", REGIONS)
            self.add_filter("season", "游戏季节", SEASONS)
            self.add_filter("period", "游戏时段", ("全部时段", *PERIOD_KEYS))
            self.add_filter("quantity", "群怪数量", ("全部群怪", "3只", "5只"))
            if mode == "effort":
                self.add_filter("stat", "努力项", tuple(STAT_LABELS.values()))
                self.add_filter("single", "收益类型", ("全部收益", "仅单一努力项精灵"))
            else:
                methods = sorted({row.method for row in database.hordes})
                self.add_filter("method", "遭遇方式", ("全部方式", *methods))
        hint = (
            "支持中文名、英文名与编号；选择精灵查看种族值、特性、招式和野外分布。"
            if mode == "pokedex" else
            "选择精灵查看各地群怪分布。" if mode == "hordes" else
            "选择游戏内季节，不按现实月份推断。可搜索精灵或地点；不同季节、时段单独列出。"
        )
        self.hint = ttk.Label(self, text=hint, style="Muted.TLabel", wraplength=650)
        if mode != "hordes":
            self.hint.pack(fill="x", pady=(6, 8))
        self.bind("<Configure>", lambda event: self.hint.configure(wraplength=max(250, event.width - 30)))
        if mode == "pokedex":
            columns = [("id", "编号", 65), ("name", "精灵", 125), ("types", "属性", 100),
                       ("total", "种族值合计", 95), ("groups", "蛋组", 150)]
        elif mode == "hordes":
            columns = [("id", "编号", 65), ("name", "精灵", 125), ("region", "分布地区", 220),
                       ("locations", "地点数", 70), ("quantity", "群怪数量", 100)]
        else:
            columns = [("name", "精灵", 105), ("region", "地区", 65), ("location", "地点", 230),
                       ("season", "季节", 100), ("period", "时段", 140), ("quantity", "数量", 60),
                       ("level", "等级", 75), ("method", "方式", 90)]
            if mode == "effort":
                columns.insert(2, ("ev", "整群基础值", 100))
        self.body = ttk.Panedwindow(self, orient="vertical")
        self.body.pack(fill="both", expand=True)
        self.table = ResultTable(self.body, columns, self.show_details, paginated=mode != "pokedex")
        if mode == "hordes":
            self.table.tree.configure(height=3)
        self.body.add(self.table, weight=3)
        detail_frame = ttk.Frame(self.body)
        actions = ttk.Frame(detail_frame, padding=(0, 4))
        actions.pack(fill="x")
        self.detail_title = tk.StringVar(self, value="选择一条记录查看详情")
        ttk.Label(actions, textvariable=self.detail_title, style="Field.TLabel").pack(side="left")
        self.jump = ttk.Button(actions, text="查看群怪分布" if mode == "pokedex" else "查看精灵图鉴", command=self.jump_to_related)
        self.jump.pack(side="right")
        if mode == "pokedex":
            detail_content = ttk.Frame(detail_frame)
            detail_content.pack(fill="both", expand=True)
            self.portrait = PokedexPortrait(detail_content)
            self.portrait.pack(side="left", fill="y")
            self.detail_tabs = ttk.Notebook(detail_content)
            self.detail_tabs.pack(fill="both", expand=True)
            self.details = {}
            for key, title in (("base", "基本资料"), ("moves", "招式"), ("locations", "野外分布")):
                panel = ttk.Frame(self.detail_tabs)
                self.detail_tabs.add(panel, text=title)
                self.details[key] = readonly_text(panel)
        else:
            self.details = {"base": readonly_text(detail_frame, height=5)}
        self.body.add(detail_frame, weight=2)
        if mode == "hordes":
            self.horde_split_ready = False
            self.body.bind("<Configure>", self._initialize_horde_split)
        self.refresh()

    def _initialize_horde_split(self, event) -> None:
        if not self.horde_split_ready and event.height >= 160:
            self.horde_split_ready = True
            self.body.sashpos(0, max(125, int(event.height * 0.45)))

    def add_filter(self, key, label, values, editable=False) -> None:
        cell = ttk.Frame(self.filters, padding=(0, 3, 8, 3))
        ttk.Label(cell, text=label).pack(anchor="w")
        variable = tk.StringVar(self, value=values[0])
        self.variables[key] = variable
        self.defaults[key] = values[0]
        combo = ttk.Combobox(cell, textvariable=variable, values=values, state="normal" if editable else "readonly", width=15)
        combo.pack(fill="x", pady=(3, 0))
        combo.bind("<Return>", self._query_now)
        variable.trace_add("write", self.schedule)
        self.filter_cells.append(cell)

    def _layout_filters(self, event) -> None:
        columns = 3 if event.width < 950 else 6
        if columns == self.filter_columns:
            return
        self.filter_columns = columns
        for index in range(6):
            self.filters.columnconfigure(index, weight=1 if index < columns else 0)
        for index, cell in enumerate(self.filter_cells):
            cell.grid(row=index // columns, column=index % columns, sticky="ew")

    def schedule(self, *_args) -> None:
        if self.pending is not None:
            self.after_cancel(self.pending)
        self.pending = self.after(180, self.refresh)

    def destroy(self) -> None:
        if self.pending is not None:
            self.after_cancel(self.pending)
            self.pending = None
        super().destroy()

    def _query_now(self, _event=None) -> str:
        self.refresh()
        return "break"

    def reset(self) -> None:
        self.query.set("")
        for key, value in self.defaults.items():
            self.variables[key].set(value)
        self.table.sort_key = ""
        self.refresh()

    def refresh(self) -> None:
        if self.pending is not None:
            self.after_cancel(self.pending)
            self.pending = None
        values = {key: value.get() for key, value in self.variables.items()}
        if self.mode == "pokedex":
            records = self.database.find_species(self.query.get(), values["type"], values["egg_group"], values["ability"])
            rows = [(record, (record["id"], record["name"], "/".join(TYPE_LABELS.get(value, value) for value in record["types"]),
                              sum(record["stats"].values()), "/".join(record["egg_groups"]))) for record in records]
        else:
            stat = next((key for key, label in STAT_LABELS.items() if label == values.get("stat")), "")
            records = self.database.find_encounters(
                self.query.get(), region=values["region"], season=values["season"], period=values["period"],
                quantity=values["quantity"], method=values.get("method", "全部方式"), stat=stat,
                single_stat=values.get("single") == "仅单一努力项精灵",
            )
            rows = []
            if self.mode == "hordes":
                rows = [(record, (record.species_id, record.name, record.regions, record.location_count, record.quantities))
                        for record in group_hordes(records)]
            else:
                for record in records:
                    display = [record.name, record.region, record.location, record.season_label, record.periods,
                               record.quantity, record.level, record.method]
                    if stat:
                        display.insert(2, ev_values(self.database.by_id[record.species_id])[stat] * record.quantity)
                    rows.append((record, tuple(display)))
        self.table.set_rows(rows)

    def show_details(self, record) -> None:
        self.selected_record = record
        self.jump.configure(state="normal" if record else "disabled")
        if record is None:
            if self.mode == "pokedex":
                self.portrait.set_species(None)
            self.detail_title.set("没有匹配记录")
            for text in self.details.values():
                set_text(text, "请清空关键词，或尝试其他地区、季节与时段。")
            return
        if self.mode == "pokedex":
            self.portrait.set_species(record["id"], record["name"])
            self.detail_title.set(f"#{record['id']:03}  {record['name']}")
            stats = "    ".join(f"{label} {record['stats'].get(key, 0)}" for key, label in STAT_LABELS.items())
            abilities = list(dict.fromkeys(value["name"] for value in record["abilities"][:2]))
            hidden = record["abilities"][2]["name"] if len(record["abilities"]) > 2 else "未标注"
            gender = record["gender_ratio"]
            gender_text = "无性别" if gender == 255 else "仅雌性" if gender == 254 else "仅雄性" if gender == 0 else f"雌性约 {round((gender + 1) / 256 * 100, 1)}%"
            content = f"属性：{' / '.join(TYPE_LABELS.get(value, value) for value in record['types'])}\n种族值：{stats}\n"
            content += f"蛋组：{' / '.join(record['egg_groups'])}    性别：{gender_text}\n普通特性：{' / '.join(abilities)}    隐藏特性：{hidden}\n"
            content += f"捕获度：{record['catch_rate']}    单只努力值：{ev_text(record)}\n"
            content += "进化：" + ("；".join(f"{value['name']}（{self.evolution_condition(value)}）" for value in record["evolutions"]) or "无后续进化记录")
            set_text(self.details["base"], content)
            moves = list(dict.fromkeys((value.get("type", "未标注"), value.get("level"), value["name"]) for value in record["moves"]))
            moves_text = "\n".join(f"{kind}{' Lv.' + str(level) if level is not None else ''}    {name}" for kind, level, name in moves)
            set_text(self.details["moves"], moves_text or "暂无招式记录")
            locations = self.database.find_encounters(quantity="全部遭遇", species_id=record["id"])
            lines = [f"{row.region} · {row.location} | {row.method} | {row.quantity}只 | Lv.{row.level} | {row.season_label} | {row.periods}" for row in locations]
            set_text(self.details["locations"], "\n".join(lines) or "暂无普通野外遭遇记录；不代表无法通过其他方式获取。")
        elif self.mode == "hordes":
            self.detail_title.set(f"#{record.species_id:03}  {record.name} · {record.location_count} 个地点")
            set_text(self.details["base"], horde_locations_text(record))
        else:
            species = self.database.by_id[record.species_id]
            self.detail_title.set(f"{record.name} · {record.region}")
            chance = "；".join(f"{period} {value}" for period, value in record.chances) or "未标注"
            content = f"地点：{record.location}\n方式：{record.method}    数量：{record.quantity}只    等级：{record.level}\n"
            content += f"季节：{record.season_label}    时段：{record.periods}\n源标遭遇权重/概率：{chance}（不作为甜甜香气成功率）\n"
            content += f"单只努力值：{ev_text(species)}    同种整群基础值：{ev_text(species, record.quantity)}"
            set_text(self.details["base"], content)

    @staticmethod
    def evolution_condition(value: dict) -> str:
        kind = value.get("type", "未标注")
        amount = value.get("val")
        if kind == "LEVEL":
            return f"等级 {amount}"
        return f"{kind} / {amount}" if amount is not None else str(kind)

    def jump_to_related(self) -> None:
        if self.selected_record is None:
            return
        species_id = self.selected_record["id"] if self.mode == "pokedex" else self.selected_record.species_id
        self.navigate("hordes" if self.mode == "pokedex" else "pokedex", species_id)


class GuideWorkspace(ttk.Frame):
    def __init__(self, parent, navigate) -> None:
        super().__init__(parent, style="Panel.TFrame")
        self.navigate = navigate
        self.pages = {}
        self.database = None
        self.mode = "hordes"
        self.pending_species = None
        self.result_queue = queue.Queue()
        self.loading = ttk.Label(self, text="正在读取本地查询资料…", padding=20)
        self.loading.pack(fill="both", expand=True)
        threading.Thread(target=self._load, daemon=True).start()
        self.poll_after = self.after(60, self._poll)

    def _load(self) -> None:
        try:
            self.result_queue.put((get_guide_database(), None))
        except Exception as error:
            self.result_queue.put((None, error))

    def _poll(self) -> None:
        self.poll_after = None
        try:
            self.database, error = self.result_queue.get_nowait()
        except queue.Empty:
            self.poll_after = self.after(60, self._poll)
            return
        if error:
            self.loading.configure(text=f"本地资料读取失败：{error}\n请使用完整发行包。库存与孵蛋功能不受影响。", wraplength=600)
            return
        self.loading.pack_forget()
        self.show(self.mode, self.pending_species)

    def destroy(self) -> None:
        if self.poll_after is not None:
            self.after_cancel(self.poll_after)
            self.poll_after = None
        super().destroy()

    def show(self, mode: str, species_id: int | None = None) -> None:
        self.mode = mode
        self.pending_species = species_id
        if self.database is None:
            return
        for page in self.pages.values():
            page.pack_forget()
        if mode not in self.pages:
            self.pages[mode] = QueryPage(self, self.database, mode, self.navigate)
        page = self.pages[mode]
        page.pack(fill="both", expand=True)
        if species_id is not None:
            page.reset()
            page.query.set(self.database.by_id[species_id]["name"])
            page.refresh()
        page.entry.focus_set()

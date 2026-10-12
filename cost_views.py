"""Native route cost details, local valuations and editable breeding fees."""
from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
from tkinter import ttk

from breeding_cost import PriceBook, amount, material_record, save_price_book
from market_data import MarketClient, load_cache, save_cache


class CostDialog(tk.Toplevel):
    def __init__(self, parent, *, book, path, inventory, candidates=(), on_saved=None, client=None, active_snapshot=False):
        super().__init__(parent)
        self.title("孵蛋成本与报价")
        self.geometry("980x680")
        self.minsize(660, 480)
        self.transient(parent)
        self.path, self.on_saved = path, on_saved
        self.book = PriceBook(book.to_dict(), book.snapshot)
        self.candidates = list(candidates)
        self.active_snapshot = active_snapshot
        self.client = client or MarketClient()
        self.cache_path = path.with_name("market_cache.json")
        self.in_flight = False
        self.last_refresh = -1000
        self.retry_until = 0
        self.result_queue = queue.Queue()
        self.poll_id = None
        self.closed = False
        self.protocol("WM_DELETE_WINDOW", self.close)
        for monster in inventory:
            row = material_record(monster)
            self.book.materials[row["key"]] = row
        for candidate in candidates:
            self.book.materials.update({row["key"]: row for row in candidate.cost_materials})
        cached = load_cache(self.cache_path)
        if self.book.snapshot is None and cached:
            self.book = PriceBook(self.book.to_dict(), cached[0])

        shell = ttk.Frame(self, padding=12)
        shell.pack(fill="both", expand=True)
        top = ttk.Frame(shell)
        top.pack(fill="x")
        ttk.Label(top, text="孵蛋成本", font=("Microsoft YaHei UI", 14, "bold")).pack(side="left")
        self.refresh_button = ttk.Button(top, text="刷新行情", command=self.refresh_market)
        self.refresh_button.pack(side="right")
        self.status_var = tk.StringVar(self, "优先比较总消耗价值；金额均为游戏币。")
        self.status_label = ttk.Label(shell, textvariable=self.status_var, wraplength=900)
        self.status_label.pack(fill="x", pady=(8, 8))
        self.tabs = ttk.Notebook(shell)
        self.tabs.pack(fill="both", expand=True)
        detail = ttk.Frame(self.tabs, padding=10)
        materials = ttk.Frame(self.tabs, padding=10)
        fees = ttk.Frame(self.tabs, padding=10)
        self.tabs.add(detail, text="路线成本")
        self.tabs.add(materials, text="素材估值")
        self.tabs.add(fees, text="费用设置")
        self.summary_var = tk.StringVar(self)
        ttk.Label(detail, textvariable=self.summary_var, wraplength=900).pack(fill="x", pady=(0, 8))
        choices = [("正在执行（原报价）" if active_snapshot and i == 0 else f"建议 {i if active_snapshot else i+1}") for i in range(len(candidates))]
        self.candidate_var = tk.StringVar(self, choices[0] if choices else "暂无路线")
        self.candidate_combo = ttk.Combobox(detail, textvariable=self.candidate_var,
                                          values=choices, state="readonly", width=22)
        self.candidate_combo.pack(anchor="w", pady=(0, 6))
        self.candidate_combo.bind("<<ComboboxSelected>>", lambda _e: self.render_report())
        self.details_tree = self.tree(detail, ("item", "kind", "qty", "unit", "sum", "source"),
                                      ("项目", "类别", "数量", "单价", "金额", "报价来源"), (350, 65, 55, 90, 95, 160))
        ttk.Label(detail, text="步骤金额为该子代的累计投入，已知金额后的 +? 表示仍有待报价项；整条路线按原始素材统计一次。",
                  wraplength=900).pack(fill="x", pady=(8, 0))

        filters = ttk.Frame(materials)
        filters.pack(fill="x", pady=(0, 8))
        ttk.Label(filters, text="搜索素材").pack(side="left")
        self.search_var = tk.StringVar(self)
        ttk.Entry(filters, textvariable=self.search_var, width=25).pack(side="left", fill="x", expand=True, padx=8)
        self.filter_var = tk.StringVar(self, "全部")
        ttk.Combobox(filters, textvariable=self.filter_var, values=("全部", "库存", "采购", "待报价"), state="readonly", width=9).pack(side="right")
        self.material_tree = self.tree(materials, ("label", "value", "reference", "location"),
                                       ("素材条件", "手动估值", "行情参考", "来源 / 位置"), (530, 100, 110, 155))
        self.material_tree.bind("<<TreeviewSelect>>", self.select_material)
        editor = ttk.Frame(materials)
        editor.pack(fill="x", pady=8)
        ttk.Label(editor, text="所选素材估值").pack(side="left")
        self.price_var = tk.StringVar(self)
        self.price_entry = ttk.Entry(editor, textvariable=self.price_var, width=14)
        self.price_entry.pack(side="left", padx=8)
        self.price_entry.bind("<FocusOut>", lambda _e: self.validate_price())
        ttk.Button(editor, text="设置估值", command=self.set_material_price).pack(side="left")
        ttk.Button(editor, text="填入参考价", command=self.fill_reference).pack(side="left", padx=8)
        ttk.Button(editor, text="清除估值", command=self.clear_material_price).pack(side="left")
        self.edit_error = tk.StringVar(self)
        ttk.Label(materials, textvariable=self.edit_error, foreground="#b91c1c", wraplength=900).pack(fill="x")
        ttk.Label(materials, text="行情参考只提供蛋组单 V 等公开最低挂牌价，不含完整性格、多 V 和技能条件。确认相符后填写估值；空白表示待报价，0 表示你明确估值为零。",
                  wraplength=900).pack(fill="x", pady=(4, 0))
        self.search_var.trace_add("write", lambda *_: self.render_materials())
        self.filter_var.trace_add("write", lambda *_: self.render_materials())

        fields = ttk.Frame(fees)
        fields.pack(fill="x")
        self.fee_vars = {}
        for i, (key, label, value) in enumerate((("brace", "护腕单价", self.book.brace),
                                                ("everstone", "不变之石单价（留空使用行情）", self.book.everstone),
                                                ("gender", "默认指定性别费", self.book.gender))):
            ttk.Label(fields, text=label).grid(row=i, column=0, sticky="w", pady=6)
            var = self.fee_vars[key] = tk.StringVar(self, "" if value is None else str(value))
            ttk.Entry(fields, textvariable=var, width=18).grid(row=i, column=1, sticky="w", padx=12)
        ttk.Label(fees, text="默认指定性别费 5,000。特殊性别比例需要按实际费用单独填写；固定性别无需付指定费用。",
                  wraplength=900).pack(fill="x", pady=10)
        self.gender_tree = self.tree(fees, ("label", "price"), ("路线中的指定性别项目", "特殊费用"), (570, 140))
        gender_editor = ttk.Frame(fees)
        gender_editor.pack(fill="x", pady=8)
        ttk.Label(gender_editor, text="特殊指定费用").pack(side="left")
        self.gender_price_var = tk.StringVar(self)
        ttk.Entry(gender_editor, textvariable=self.gender_price_var, width=14).pack(side="left", padx=8)
        ttk.Button(gender_editor, text="设置（空白恢复默认）", command=self.set_gender_price).pack(side="left")
        self.gender_tree.bind("<<TreeviewSelect>>", self.select_gender)

        bottom = ttk.Frame(shell)
        bottom.pack(fill="x", pady=(10, 0))
        ttk.Button(bottom, text="关闭", command=self.close).pack(side="right")
        ttk.Button(bottom, text="保存报价", command=self.save).pack(side="right", padx=8)
        self.render_materials()
        self.render_report()

        self.bind("<Configure>", self.resize_labels)

    @staticmethod
    def tree(parent, columns, labels, widths):
        area = ttk.Frame(parent)
        area.pack(fill="both", expand=True)
        tree = ttk.Treeview(area, columns=columns, show="headings", selectmode="browse")
        for column, label, width in zip(columns, labels, widths):
            tree.heading(column, text=label)
            tree.column(column, width=width, minwidth=45, stretch=column == columns[0])
        y = ttk.Scrollbar(area, orient="vertical", command=tree.yview)
        x = ttk.Scrollbar(area, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=y.set, xscrollcommand=x.set)
        tree.grid(row=0, column=0, sticky="nsew")
        y.grid(row=0, column=1, sticky="ns")
        x.grid(row=1, column=0, sticky="ew")
        area.rowconfigure(0, weight=1)
        area.columnconfigure(0, weight=1)
        return tree

    def resize_labels(self, event):
        if event.widget is self:
            for widget in self.winfo_children():
                self._wrap(widget, max(300, event.width - 70))

    def _wrap(self, widget, width):
        if isinstance(widget, ttk.Label) and "wraplength" in widget.keys() and int(widget.cget("wraplength") or 0):
            widget.configure(wraplength=width)
        for child in widget.winfo_children():
            self._wrap(child, width)

    def render_materials(self):
        selected = self.material_tree.selection()
        self.material_tree.delete(*self.material_tree.get_children())
        query, mode = self.search_var.get().casefold(), self.filter_var.get()
        for key, row in self.book.materials.items():
            if query not in (row["label"] + row.get("location", "")).casefold():
                continue
            if mode == "库存" and row["virtual"] or mode == "采购" and not row["virtual"] or mode == "待报价" and key in self.book.prices:
                continue
            reference = self.book.reference(row)
            self.material_tree.insert("", "end", iid=key, values=(row["label"], f'{self.book.prices[key]:,}' if key in self.book.prices else "待报价",
                                                                  f"{reference:,}（参考）" if reference is not None else "无匹配参考", row.get("location", "")))
        if selected and self.material_tree.exists(selected[0]):
            self.material_tree.selection_set(selected)

    def select_material(self, _event=None):
        selected = self.material_tree.selection()
        if selected:
            self.price_var.set(str(self.book.prices.get(selected[0], "")))
            self.edit_error.set("")

    def validate_price(self):
        try:
            amount(self.price_var.get(), optional=True)
            self.edit_error.set("")
            return True
        except ValueError as error:
            self.edit_error.set(str(error))
            return False

    def set_material_price(self):
        selected = self.material_tree.selection()
        if not selected:
            self.edit_error.set("请先选择一项素材。")
            return
        if not self.validate_price():
            return
        value = amount(self.price_var.get(), optional=True)
        if value is None:
            self.book.prices.pop(selected[0], None)
        else:
            self.book.prices[selected[0]] = value
        self.render_materials()
        self.render_report()
        self.status_var.set("估值已修改，点“保存报价”写入本地并用于下次规划。")

    def clear_material_price(self):
        self.price_var.set("")
        self.set_material_price()

    def fill_reference(self):
        selected = self.material_tree.selection()
        value = self.book.reference(self.book.materials[selected[0]]) if selected else None
        if value is None:
            self.edit_error.set("所选素材没有匹配参考价，请手动填写。")
        else:
            self.price_var.set(str(value))
            self.edit_error.set("请核对完整素材条件，再点“设置估值”。")

    def select_gender(self, _event=None):
        selected = self.gender_tree.selection()
        if selected:
            self.gender_price_var.set(str(self.book.gender_overrides.get(selected[0], "")))

    def set_gender_price(self):
        selected = self.gender_tree.selection()
        if not selected:
            self.status_var.set("请先选择一项指定性别项目。")
            return
        try:
            price = amount(self.gender_price_var.get(), optional=True)
            if price is None:
                self.book.gender_overrides.pop(selected[0], None)
            else:
                self.book.gender_overrides[selected[0]] = price
            self.render_report()
            self.status_var.set("特殊费用已修改，点“保存报价”写入本地。")
        except ValueError as error:
            self.status_var.set(str(error))

    def render_report(self):
        self.details_tree.delete(*self.details_tree.get_children())
        self.gender_tree.delete(*self.gender_tree.get_children())
        if not self.candidates:
            self.summary_var.set("先生成规划，再查看路线成本和采购报价模板。已有库存可直接填写估值。")
            return
        index = self.candidate_combo.current()
        candidate = self.candidates[max(0, index)]
        report = candidate.cost_report() if self.active_snapshot and index <= 0 else self.book.report(candidate.root, candidate.working_gender or candidate.target_gender, candidate.gender_strategy)
        self.summary_var.set(report.summary() + "\n按可行候选比较估算成本；不保证全市场最低。保存报价后重新生成路线，正在执行的方案保留原报价快照。")
        if candidate.nature_phase in {"maternal", "gamble_upper", "gamble_lower", "promote", "guarantee"}:
            self.summary_var.set(self.summary_var.get() + "\n当前为分阶段性格路线：这里只统计当前阶段，未包含后续阶段的费用。")
        for line in report.lines:
            self.details_tree.insert("", "end", values=(line.label, line.kind, line.quantity,
                                                         f"{line.unit_price:,}" if line.unit_price is not None else "待报价",
                                                         f"{line.subtotal:,}" if line.subtotal is not None else "待报价", line.source))
            if line.kind == "性别" and line.key:
                key = line.key.removeprefix("gender:")
                if not self.gender_tree.exists(key):
                    self.gender_tree.insert("", "end", iid=key, values=(line.label, f'{self.book.gender_overrides[key]:,}' if key in self.book.gender_overrides else line.source))
        for step in report.steps:
            self.details_tree.insert("", "end", values=(f'步骤 {step["number"]} · {step["label"]}', "累计", "—", "—",
                                                         f'{step["total"]:,}' + (" +?" if step["missing"] else ""),
                                                         f'本步费用 {step["fees"]:,}' + (" +?" if step["fee_missing"] else "")))

    def apply_fees(self):
        values = {key: amount(var.get(), optional=key == "everstone") for key, var in self.fee_vars.items()}
        for key, value in values.items():
            setattr(self.book, key, value)

    def save(self):
        try:
            self.apply_fees()
            save_price_book(self.path, self.book)
        except (ValueError, OSError) as error:
            self.status_var.set(f"保存失败：{error}")
            return
        self.render_report()
        self.status_var.set("报价已保存。重新生成规划后按新报价比较路线。")
        if self.on_saved:
            self.on_saved(self.book)

    def refresh_market(self):
        now = time.time()
        interval = self.book.snapshot.minimum_interval if self.book.snapshot else 60
        if self.in_flight or now < max(self.retry_until, self.last_refresh + interval):
            self.status_var.set("行情正在刷新或处于刷新间隔，请稍后再试。")
            return
        self.in_flight = True
        self.last_refresh = now
        self.refresh_button.configure(state="disabled")
        self.status_var.set("正在读取公开行情，库存数据仅保存在本地……")
        def worker():
            try:
                self.result_queue.put((self.client.snapshot(), None))
            except Exception as error:
                self.result_queue.put((None, error))
        threading.Thread(target=worker, daemon=True, name="breeding-cost-market").start()
        self.poll_id = self.after(100, self.poll_market)

    def poll_market(self):
        self.poll_id = None
        if self.closed:
            return
        try:
            snapshot, error = self.result_queue.get_nowait()
        except queue.Empty:
            self.poll_id = self.after(100, self.poll_market)
            return
        self.in_flight = False
        self.refresh_button.configure(state="normal")
        if error:
            self.retry_until = time.time() + getattr(error, "retry_after", 0)
            self.status_var.set(f"刷新失败，保留已有报价：{error}")
            return
        self.book = PriceBook(self.book.to_dict(), snapshot)
        try:
            save_cache(self.cache_path, snapshot, time.time())
            self.status_var.set("行情已更新；不变之石可自动报价，素材参考价需核对完整条件。点“保存报价”用于下次规划。")
        except OSError:
            self.status_var.set("行情已更新，但缓存保存失败；请检查本地目录权限。")
        self.render_materials()
        self.render_report()

    def close(self):
        self.closed = True
        if self.poll_id:
            self.after_cancel(self.poll_id)
        self.destroy()

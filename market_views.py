from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
from tkinter import ttk
import webbrowser

from market_data import (MarketClient, MarketError, SOURCE_URLS, EGG_GROUPS, load_catalog,
                         item_rows, pokemon_rows, sorted_rows, quote_state, format_price,
                         format_time, candles, load_cache, save_cache)
from storage import data_dir


class PriceChart(tk.Canvas):
    def __init__(self, parent):
        super().__init__(parent, height=145, background='white', highlightthickness=1,
                         highlightbackground='#d7dee8')
        self.points = ()
        self.period = 30
        self.kind = '价格折线'
        self.interval = 86400
        self.message = '选择一项查看历史走势'
        self.positions = []
        self.bind('<Configure>', lambda event: self.redraw())
        self.bind('<Motion>', self.hover)
        self.bind('<Leave>', lambda event: self.delete('hover'))

    def show(self, points=(), message=''):
        self.points = points
        self.message = message
        self.redraw()

    def redraw(self):
        self.delete('all')
        self.positions = []
        width = max(160, self.winfo_width())
        height = self.winfo_height() if self.winfo_ismapped() else max(100, self.winfo_height())
        if height < 65:
            self.create_text(width / 2, max(10, height / 2), text='拖动上方分隔条展开走势图', fill='#65748b')
            return
        points = self.points
        if points and self.period:
            cutoff = time.time() - self.period * 86400
            points = tuple(point for point in points if point.at >= cutoff)
        priced = [point for point in points if point.price is not None]
        if not priced:
            self.create_text(width / 2, height / 2, text=self.message or '所选时间范围暂无历史报价',
                             fill='#65748b', font=('Microsoft YaHei UI', 10))
            return
        left, right, top, bottom = 75, width - 20, 15, height - 30
        if right <= left or bottom <= top:
            return
        values = [point.price for point in priced]
        low, high = min(values), max(values)
        margin = max(1, (high - low) * .08)
        low, high = max(0, low - margin), high + margin
        t0, t1 = priced[0].at, max(priced[0].at + 1, priced[-1].at)
        x = lambda at: left + (at - t0) / (t1 - t0) * (right - left)
        y = lambda value: bottom - (value - low) / max(1, high - low) * (bottom - top)
        for index in range(3):
            value = low + (high - low) * index / 2
            yy = y(value)
            self.create_line(left, yy, right, yy, fill='#e7edf5')
            self.create_text(left - 8, yy, text=f'{value:,.0f}', anchor='e', fill='#65748b', font=('Arial', 8))
        self.create_text(left, height - 10, text=format_time(t0), anchor='w', fill='#65748b', font=('Arial', 8))
        self.create_text(right, height - 10, text=format_time(t1), anchor='e', fill='#65748b', font=('Arial', 8))
        if self.kind == 'K线':
            records = candles(priced, self.interval)
            half = max(1, min(5, (right - left) / max(1, len(records)) / 3))
            for at, opening, highest, lowest, closing in records:
                xx = x(max(t0, min(t1, at)))
                color = '#b82e39' if closing >= opening else '#137d61'
                self.create_line(xx, y(highest), xx, y(lowest), fill=color)
                yy1, yy2 = y(opening), y(closing)
                self.create_rectangle(xx - half, min(yy1, yy2), xx + half, max(yy1, yy2) + 1,
                                      fill=color, outline=color)
        else:
            coordinates = [value for point in priced for value in (x(point.at), y(point.price))]
            if len(coordinates) > 2:
                self.create_line(*coordinates, fill='#2853d7', width=2)
            else:
                xx, yy = coordinates
                self.create_oval(xx - 3, yy - 3, xx + 3, yy + 3, fill='#2853d7', outline='')
        self.positions = [(x(point.at), y(point.price), point) for point in priced]

    def hover(self, event):
        self.delete('hover')
        if not self.positions:
            return
        xx, yy, point = min(self.positions, key=lambda item: abs(item[0] - event.x))
        self.create_line(xx, 12, xx, self.winfo_height() - 28, fill='#8a9cb4', dash=(3, 3), tags='hover')
        text = f'{format_time(point.at)}  挂牌价 {format_price(point.price)}  数量 {format_price(point.quantity)}'
        self.create_text(self.winfo_width() / 2, 10, text=text, anchor='n', fill='#263850',
                         font=('Microsoft YaHei UI', 9), tags='hover')


class MarketPage(ttk.Frame):
    def __init__(self, parent, owner, kind):
        super().__init__(parent, padding=(4, 6))
        self.owner, self.kind = owner, kind
        self.rows = {}
        self.sort_column, self.descending = 'price', False
        self.search = tk.StringVar(self)
        self.category = tk.StringVar(self, '全部分类')
        self.mode = tk.StringVar(self, '进化族群')
        self.variant = tk.StringVar(self, '全部')
        self.gender = tk.StringVar(self, '不限性别')
        self.group = tk.StringVar(self, '全部蛋组')
        self.tier = tk.StringVar(self, '全部分级')
        self.count = tk.StringVar(self, '尚未加载')
        controls = ttk.Frame(self)
        controls.pack(fill='x', pady=(0, 5))
        controls.columnconfigure(1, weight=1)
        ttk.Label(controls, text='搜索').grid(row=0, column=0, padx=(0, 5))
        ttk.Entry(controls, textvariable=self.search).grid(row=0, column=1, sticky='ew')
        if kind == 'items':
            ttk.Label(controls, text='分类').grid(row=0, column=2, padx=(10, 4))
            self.combo(controls, self.category, ('全部分类', '培育道具', '捕捉球', '树果', '时装', '礼盒', '其他'), 10).grid(row=0, column=3)
        else:
            ttk.Label(controls, text='查询').grid(row=0, column=2, padx=(10, 4))
            self.mode_combo = self.combo(controls, self.mode, ('进化族群', '单种宝可梦', '蛋组1V', '粒子'), 11)
            self.mode_combo.grid(row=0, column=3)
            self.mode_combo.bind('<<ComboboxSelected>>', self._mode_changed)
            filters = ttk.Frame(self)
            filters.pack(fill='x', pady=(0, 6))
            self.filter_combos = {}
            for col, (label, var, values, width, key) in enumerate((
                ('蛋组', self.group, ('全部蛋组', *EGG_GROUPS.values()), 10, 'group'),
                ('种类', self.variant, ('全部', '头目', '闪光', '头目闪光'), 9, 'variant'),
                ('性别', self.gender, ('不限性别', '雄性', '雌性'), 9, 'gender'),
                ('分级', self.tier, ('全部分级', 'OU', 'UU', 'NU', 'Uber', 'LC', 'Untiered'), 9, 'tier'),
            )):
                ttk.Label(filters, text=label).grid(row=0, column=col * 2, padx=(6 if col else 0, 3))
                combo = self.combo(filters, var, values, width)
                combo.grid(row=0, column=col * 2 + 1, sticky='ew')
                filters.columnconfigure(col * 2 + 1, weight=1)
                self.filter_combos[key] = combo
        for var in (self.search, self.category, self.mode, self.variant, self.gender, self.group, self.tier):
            var.trace_add('write', lambda *args: owner.schedule_render())
        result = ttk.Frame(self)
        result.pack(fill='both', expand=True)
        result.columnconfigure(0, weight=1)
        result.rowconfigure(0, weight=1)
        columns = ('name', 'category', 'price', 'quantity', 'at', 'state')
        self.tree = ttk.Treeview(result, columns=columns, show='headings', height=7, selectmode='browse')
        for key, label, width in zip(columns, ('名称', '分类／蛋组', '最低挂牌价', '上架数量', '采集时间', '状态'), (205, 125, 110, 90, 115, 110)):
            self.tree.heading(key, text=label, command=lambda key=key: self.sort(key))
            self.tree.column(key, width=width, minwidth=70, anchor='e' if key in ('price', 'quantity') else 'w', stretch=key=='name')
        self.tree.grid(row=0, column=0, sticky='nsew')
        vertical = ttk.Scrollbar(result, orient='vertical', command=self.tree.yview)
        vertical.grid(row=0, column=1, sticky='ns')
        horizontal = ttk.Scrollbar(result, orient='horizontal', command=self.tree.xview)
        horizontal.grid(row=1, column=0, sticky='ew')
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.tree.tag_configure('old', foreground='#9a6500')
        self.tree.bind('<<TreeviewSelect>>', lambda event: owner.select_row(self))
        ttk.Label(self, textvariable=self.count, style='Muted.TLabel').pack(anchor='w', pady=(3, 0))

    def combo(self, parent, var, values, width):
        return ttk.Combobox(parent, textvariable=var, values=values, state='readonly', width=width)

    def _mode_changed(self, event=None):
        mode = self.mode.get()
        allowed = {'group': mode != '粒子', 'variant': mode in ('进化族群', '粒子'),
                   'gender': mode in ('进化族群', '蛋组1V'), 'tier': mode in ('进化族群', '单种宝可梦')}
        for key, combo in self.filter_combos.items():
            combo.configure(state='readonly' if allowed[key] else 'disabled')
        self.owner.clear_history()

    def sort(self, column):
        if column == 'state':
            return
        self.descending = not self.descending if self.sort_column == column else column in ('quantity', 'at')
        self.sort_column = column
        self.owner.render(self.kind)

    def render(self, snapshot, catalog):
        selected = self.tree.selection()
        position = self.tree.yview()[0]
        if self.kind == 'items':
            rows = item_rows(snapshot, catalog, self.search.get(), self.category.get())
        else:
            rows = pokemon_rows(snapshot, catalog, mode=self.mode.get(), search=self.search.get(),
                                variant=self.variant.get(), gender=self.gender.get(), egg_group=self.group.get(), tier=self.tier.get())
        rows = sorted_rows(rows, self.sort_column, self.descending)
        self.rows = {row.key: row for row in rows}
        children = self.tree.get_children()
        if children:
            self.tree.delete(*children)
        for row in rows:
            state = quote_state(row.quote)
            self.tree.insert('', 'end', iid=row.key, values=(row.name, row.category, format_price(row.quote.price),
                             format_price(row.quote.quantity), format_time(row.quote.at), state), tags=('old',) if state == '旧数据' else ())
        self.tree.yview_moveto(position)
        if selected and selected[0] in self.rows:
            self.tree.selection_set(selected[0])
        elif self.owner.current_kind() == self.kind:
            self.owner.clear_history()
        if rows:
            self.count.set(f'{len(rows)} 项 · 点击列标题排序，选中一行查看走势 · 金额单位：游戏币')
        else:
            self.count.set('没有符合当前筛选条件的行情')


class MarketWorkspace(ttk.Frame):
    def __init__(self, parent, *, client=None, cache_path=None, autostart=True):
        super().__init__(parent, padding=6)
        self.client = client if client is not None else MarketClient()
        self.cache_path = cache_path or data_dir() / 'market_cache.json'
        self.catalog = load_catalog()
        self.network_enabled = autostart
        self.closed = False
        self.activated = False
        self.snapshot = None
        self.fetched_at = 0
        self.in_flight = False
        self.last_request = -10000
        self.minimum_interval = 15
        self.next_due = 0
        self.retry_until = 0
        self.queue = queue.Queue()
        self.history_in_flight = False
        self.history_target = None
        self.history_pending_at = 0
        self.history_cache = {}
        self.selected_row = None
        self.render_id = None
        self.poll_id = None
        self.auto_var = tk.BooleanVar(self, True)
        self.status = tk.StringVar(self, '尚未读取行情 · 数据来自 PokeMMO 工具站')
        self.selection_title = tk.StringVar(self, '选择一项查看历史走势')
        self.history_status = tk.StringVar(self, '行情来自 GTL 挂牌快照，价格及数量以游戏内当前市场为准。')
        self.series_var = tk.StringVar(self)
        self.chart_kind = tk.StringVar(self, '价格折线')
        self.period_var = tk.StringVar(self, '30天')
        self.candle_interval = tk.StringVar(self, '日')
        bar = ttk.Frame(self)
        bar.pack(fill='x', pady=(0, 6))
        ttk.Label(bar, text='GTL 行情查询', font=('Microsoft YaHei UI', 11, 'bold')).pack(side='left')
        self.refresh_button = ttk.Button(bar, text='刷新行情', command=self.refresh)
        self.refresh_button.pack(side='right')
        self.auto_check = ttk.Checkbutton(bar, text='自动刷新（10分钟）', variable=self.auto_var)
        self.auto_check.pack(side='right', padx=10)
        panes = ttk.Panedwindow(self, orient='vertical')
        panes.pack(fill='both', expand=True)
        self.tabs = ttk.Notebook(panes)
        panes.add(self.tabs, weight=3)
        self.pages = {kind: MarketPage(self.tabs, self, kind) for kind in ('items', 'pokemon')}
        for kind, label in (('items', '道具市场'), ('pokemon', '宝可梦市场')):
            self.tabs.add(self.pages[kind], text=label)
        details = ttk.Frame(panes, padding=(4, 4))
        panes.add(details, weight=2)
        self.title_label = ttk.Label(details, textvariable=self.selection_title, wraplength=650)
        self.title_label.pack(anchor='w', fill='x', pady=(0, 4))
        details.bind('<Configure>', lambda event: self.title_label.configure(wraplength=max(180, event.width - 10)))
        options = ttk.Frame(details)
        options.pack(fill='x', pady=(0, 4))
        ttk.Label(options, text='走势条件').pack(side='left')
        self.series_combo = ttk.Combobox(options, textvariable=self.series_var, state='readonly', width=19)
        self.series_combo.pack(side='left', padx=(4, 10))
        self.series_combo.bind('<<ComboboxSelected>>', lambda event: self.request_history())
        for var, values, width in ((self.chart_kind, ('价格折线', 'K线'), 9), (self.period_var, ('30天', '90天', '全部'), 7),
                                    (self.candle_interval, ('4小时', '日', '周'), 6)):
            combo = ttk.Combobox(options, textvariable=var, values=values, state='readonly', width=width)
            combo.pack(side='left', padx=3)
            combo.bind('<<ComboboxSelected>>', lambda event: self.redraw_chart())
        self.chart = PriceChart(details)
        self.chart.pack(fill='both', expand=True)
        ttk.Label(details, textvariable=self.history_status, style='Muted.TLabel', wraplength=650).pack(fill='x', pady=(3, 0))
        footer = ttk.Frame(self)
        footer.pack(fill='x', pady=(5, 0))
        self.status_label = ttk.Label(footer, textvariable=self.status, style='Muted.TLabel', wraplength=540)
        self.status_label.pack(side='left', fill='x', expand=True)
        ttk.Button(footer, text='来源网页', command=lambda: webbrowser.open(SOURCE_URLS[self.current_kind()])).pack(side='right')
        footer.bind('<Configure>', lambda event: self.status_label.configure(wraplength=max(150, event.width - 100)))
        self.tabs.bind('<<NotebookTabChanged>>', self._tab_changed)
        self.bind('<Map>', self._on_map, add='+')
        cached = load_cache(self.cache_path)
        if cached:
            self.snapshot, self.fetched_at = cached
            self.apply_snapshot(self.snapshot, cached=True)
        self.poll_id = self.after(150, self._tick)

    def current_kind(self):
        return 'pokemon' if self.tabs.select() == str(self.pages['pokemon']) else 'items'

    def _on_map(self, event):
        if event.widget is self and self.network_enabled and not self.activated:
            self.activated = True
            self.refresh()

    def _tab_changed(self, event=None):
        self.clear_history()
        self.select_row(self.pages[self.current_kind()])

    def schedule_render(self):
        if self.render_id is not None:
            self.after_cancel(self.render_id)
        self.render_id = self.after(180, self._render_all)

    def _render_all(self):
        self.render_id = None
        for kind in self.pages:
            self.render(kind)

    def render(self, kind):
        if self.snapshot is not None:
            self.pages[kind].render(self.snapshot, self.catalog)

    def refresh(self):
        now = time.monotonic()
        if self.closed or self.in_flight or now < self.retry_until or now - self.last_request < self.minimum_interval:
            return
        self.in_flight = True
        self.last_request = now
        self.status.set('正在读取道具与宝可梦行情…')
        self.refresh_button.configure(state='disabled')
        threading.Thread(target=self._fetch_snapshot, args=(self.client, self.queue), daemon=True, name='pokemmo-market').start()

    @staticmethod
    def _fetch_snapshot(client, results):
        try:
            results.put(('snapshot', client.snapshot(), None))
        except Exception as error:
            results.put(('snapshot', None, error if isinstance(error, MarketError) else MarketError('行情读取失败，请稍后刷新。')))

    def apply_snapshot(self, snapshot, *, cached=False):
        self.history_target = None
        self.history_pending = None
        self.snapshot = snapshot
        self.minimum_interval = snapshot.minimum_interval
        self.next_due = time.monotonic() + snapshot.interval
        self.auto_check.configure(text=f'自动刷新（{snapshot.interval // 60}分钟）')
        self.status.set(f"{'本机缓存' if cached else '来源旧快照' if snapshot.stale else '已更新'} · 网站更新 {format_time(snapshot.updated_at)} · 采集 {format_time(snapshot.source_at)}（北京时间）")
        if not cached:
            self.fetched_at = time.time()
            try:
                save_cache(self.cache_path, snapshot, self.fetched_at)
            except OSError:
                self.status.set(self.status.get() + ' · 缓存保存失败')
        self._render_all()

    def select_row(self, page):
        if self.current_kind() != page.kind:
            return
        selected = page.tree.selection()
        row = page.rows.get(selected[0]) if selected else None
        if row is None:
            self.clear_history()
            return
        same = self.selected_row is not None and row.key == self.selected_row.key
        self.selected_row = row
        self.selection_title.set(f'{row.name} · 挂牌价 {format_price(row.quote.price)} · 数量 {format_price(row.quote.quantity)} · {quote_state(row.quote)}')
        self.series_combo.configure(values=tuple(row.series_choices.values()))
        if not same or self.series_var.get() not in row.series_choices.values():
            self.series_var.set(row.series_choices.get(row.series, next(iter(row.series_choices.values()))))
        self.request_history()

    def clear_history(self):
        self.selected_row = None
        self.history_target = None
        self.history_pending = None
        self.series_var.set('')
        self.series_combo.configure(values=())
        self.selection_title.set('选择一项查看历史走势')
        self.history_status.set('行情来自 GTL 挂牌快照，价格及数量以游戏内当前市场为准。')
        self.chart.show(message='选择一项查看历史走势')

    def request_history(self):
        row = self.selected_row
        if row is None:
            return
        series = next((key for key, label in row.series_choices.items() if label == self.series_var.get()), row.series)
        target = (row.key, series)
        if target == self.history_target:
            return
        self.history_target = target
        self.history_pending = None
        self.history_pending_at = time.monotonic() + .3
        cache_key = (row.item_id, row.chart, series)
        cached = self.history_cache.get(cache_key)
        if cached:
            self.show_history(cached[1])
            if time.monotonic() - cached[0] < 300:
                return
            self.history_status.set(self.history_status.get() + ' · 正在更新')
        else:
            self.chart.show(message='正在读取历史走势…')
            self.history_status.set('正在读取历史报价')
        self.history_pending = target

    @staticmethod
    def _fetch_history(client, results, row, series, target):
        try:
            results.put(('history', (target, row, series, client.history(row, series)), None))
        except Exception as error:
            safe = error if isinstance(error, MarketError) else MarketError('历史行情读取失败，请稍后刷新。')
            results.put(('history', (target, row, series, None), safe))

    def show_history(self, points):
        self.chart.show(points, '暂无历史报价')
        prices = [point.price for point in points if point.price is not None]
        if prices:
            self.history_status.set(f'全部历史 {len(points)} 个采集点 · 最低 {min(prices):,} / 最高 {max(prices):,} · 末次 {format_time(points[-1].at)}（北京时间）')
        else:
            self.history_status.set('来源网站尚无该条件的历史报价')
        self.redraw_chart()

    def redraw_chart(self):
        self.chart.period = {'30天': 30, '90天': 90, '全部': 0}[self.period_var.get()]
        self.chart.kind = self.chart_kind.get()
        self.chart.interval = {'4小时': 14400, '日': 86400, '周': 604800}[self.candle_interval.get()]
        self.chart.redraw()

    def _tick(self):
        self.poll_id = None
        if self.closed:
            return
        while True:
            try:
                kind, value, error = self.queue.get_nowait()
            except queue.Empty:
                break
            if error and error.retry_after:
                self.retry_until = max(self.retry_until, time.monotonic() + error.retry_after)
            if kind == 'snapshot':
                self.in_flight = False
                if error:
                    self.status.set(str(error) + (' · 保留上次成功的数据（缓存）' if self.snapshot else ' · 尚无行情数据'))
                    self.next_due = time.monotonic() + max(60, error.retry_after)
                else:
                    self.apply_snapshot(value)
            else:
                self.history_in_flight = False
                target, row, series, points = value
                if not error:
                    self.history_cache[(row.item_id, row.chart, series)] = (time.monotonic(), points)
                    if len(self.history_cache) > 32:
                        self.history_cache.pop(next(iter(self.history_cache)))
                if self.history_target == target:
                    if error:
                        cached = self.history_cache.get((row.item_id, row.chart, series))
                        if cached:
                            self.show_history(cached[1])
                            self.history_status.set(str(error) + ' · 显示上次历史数据（缓存）')
                        else:
                            self.chart.show(message=str(error))
                            self.history_status.set(str(error))
                    else:
                        self.show_history(points)
        now = time.monotonic()
        pending = getattr(self, 'history_pending', None)
        if pending and pending == self.history_target and not self.history_in_flight and now >= self.history_pending_at and now >= self.retry_until:
            self.history_pending = None
            row = self.selected_row
            if row is not None:
                self.history_in_flight = True
                threading.Thread(target=self._fetch_history, args=(self.client, self.queue, row, pending[1], pending), daemon=True,
                                 name='pokemmo-market-history').start()
        if self.network_enabled and self.auto_var.get() and self.winfo_viewable() and now >= self.next_due:
            self.refresh()
        wait = max(0, self.retry_until - now, self.minimum_interval - (now - self.last_request))
        self.refresh_button.configure(state='disabled' if self.in_flight or wait > 0 else 'normal',
                                      text='读取中…' if self.in_flight else f'刷新行情（{int(wait) + 1}s）' if wait > 0 else '刷新行情')
        self.poll_id = self.after(150, self._tick)

    def destroy(self):
        self.closed = True
        for callback in (self.poll_id, self.render_id):
            if callback is not None:
                self.after_cancel(callback)
        self.poll_id = self.render_id = None
        super().destroy()

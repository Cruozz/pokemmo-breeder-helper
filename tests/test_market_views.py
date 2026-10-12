import os
from pathlib import Path
import tempfile
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

from market_data import HistoryPoint, MarketError, parse_snapshot
from market_views import MarketWorkspace
from tests.test_market_data import fixture


class MarketViewTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / 'market.json'
        self.client = Mock()
        self.snapshot = parse_snapshot(fixture())
        self.client.snapshot.return_value = self.snapshot
        self.client.history.return_value = (HistoryPoint(time.time() - 3600, 5000, 2), HistoryPoint(time.time(), 6000, 3))
        self.page = MarketWorkspace(self.root, client=self.client, cache_path=self.path, autostart=False)

    def tearDown(self):
        self.page.destroy()
        for callback in self.root.tk.call('after', 'info'):
            self.root.after_cancel(callback)
        self.root.destroy()
        self.directory.cleanup()

    def tick(self):
        if self.page.poll_id is not None:
            self.page.after_cancel(self.page.poll_id)
        self.page._tick()

    def pump(self, predicate, timeout=3):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.02)
        self.assertTrue(predicate())

    def select(self, kind, key):
        self.page.tabs.select(self.page.pages[kind])
        self.root.update()
        tree = self.page.pages[kind].tree
        tree.selection_set(key)
        self.root.update()

    def test_tabs_filters_selection_and_chart_are_native(self):
        self.page.apply_snapshot(self.snapshot)
        self.assertEqual([self.page.tabs.tab(tab, 'text') for tab in self.page.tabs.tabs()], ['道具市场', '宝可梦市场'])
        self.select('items', 'item:5229')
        self.pump(lambda: bool(self.page.chart.points))
        self.assertIn('不变之石', self.page.selection_title.get())
        self.assertIn('6000', self.page.selection_title.get().replace(',', ''))
        self.page.chart_kind.set('K线')
        self.page.redraw_chart()
        self.assertTrue(self.page.chart.find_all())

    def test_snapshot_request_is_single_flight_and_ui_stays_responsive(self):
        gate = threading.Event()
        self.client.snapshot.side_effect = lambda: (gate.wait(3), self.snapshot)[1]
        try:
            self.page.refresh()
            self.page.refresh()
            marker = []
            self.root.after(0, lambda: marker.append(True))
            self.root.update()
            self.assertEqual(marker, [True])
            gate.set()
            self.pump(lambda: not self.page.in_flight)
            self.client.snapshot.assert_called_once()
        finally:
            gate.set()

    def test_failed_refresh_keeps_previous_quote_and_respects_retry_after(self):
        self.page.apply_snapshot(self.snapshot)
        self.page.queue.put(('snapshot', None, MarketError('请求过于频繁', 120)))
        self.tick()
        self.assertEqual(self.page.snapshot.items[5229].price, 6000)
        self.assertIn('缓存', self.page.status.get())
        self.assertGreater(self.page.retry_until, time.monotonic() + 119)
        self.page.refresh()
        self.client.snapshot.assert_not_called()

    def test_restored_cache_is_labelled_and_does_not_start_network(self):
        self.page.apply_snapshot(self.snapshot)
        restored = MarketWorkspace(self.root, client=self.client, cache_path=self.path, autostart=False)
        try:
            self.assertIn('本机缓存', restored.status.get())
            self.assertEqual(restored.snapshot.items[5229].price, 6000)
            self.client.snapshot.assert_not_called()
        finally:
            restored.destroy()

    def test_filters_survive_switching_tabs_and_null_price_is_not_zero(self):
        self.page.apply_snapshot(self.snapshot)
        items = self.page.pages['items']
        items.search.set('橙色邮件')
        self.page._render_all()
        self.assertEqual(len(items.rows), 1)
        values = items.tree.item('item:121', 'values')
        self.assertEqual(values[2], '—')
        self.page.tabs.select(self.page.pages['pokemon'])
        self.page.tabs.select(items)
        self.assertEqual(items.search.get(), '橙色邮件')

    def test_late_history_cannot_overwrite_new_selection(self):
        self.page.apply_snapshot(self.snapshot)
        first = self.page.pages['items'].rows['item:5229']
        second = self.page.pages['items'].rows['item:121']
        self.page.selected_row = second
        self.page.history_target = (second.key, '')
        self.page.queue.put(('history', ((first.key, ''), first, '', self.client.history.return_value), None))
        self.tick()
        self.assertEqual(self.page.chart.points, ())

    def test_cached_history_switch_does_not_send_an_extra_request(self):
        self.page.apply_snapshot(self.snapshot)
        row = self.page.pages['items'].rows['item:5229']
        self.page.selected_row = row
        self.page.series_var.set('当前报价')
        self.page.history_cache[(5229, '', '')] = (time.monotonic(), self.client.history.return_value)
        self.page.history_pending = (row.key, '')
        self.page.request_history()
        self.tick()
        self.assertEqual(self.page.chart.points, self.client.history.return_value)
        self.client.history.assert_not_called()

    def test_mode_disables_filters_that_the_source_does_not_provide(self):
        pokemon = self.page.pages['pokemon']
        pokemon.mode.set('单种宝可梦')
        pokemon._mode_changed()
        self.assertEqual(str(pokemon.filter_combos['variant'].cget('state')), 'disabled')
        self.assertEqual(str(pokemon.filter_combos['gender'].cget('state')), 'disabled')
        pokemon.mode.set('蛋组1V')
        pokemon._mode_changed()
        self.assertEqual(str(pokemon.filter_combos['gender'].cget('state')), 'readonly')

    def test_market_controls_fit_full_app_minimum_window(self):
        from app import App
        from live_views import LiveWorkspace
        with patch.dict(os.environ, {'LOCALAPPDATA': self.directory.name}), \
                patch('app.LiveWorkspace', side_effect=lambda parent: LiveWorkspace(parent, cache_path=self.path.with_name('live.json'), autostart=False)):
            app = App(self.root)
            self.root.update()
            app._select_workspace_mode('live')
            self.root.update()
            live = app.live_workspace
            live.tabs.select(live.market_page)
            live._tab_changed()
            market = live.market_workspace
            market.client = self.client
            market.apply_snapshot(self.snapshot)
            market.show_history(self.client.history.return_value)
            for geometry in ('700x600', '1000x800'):
                self.root.geometry(geometry)
                self.root.deiconify()
                self.root.update()
                for button in (market.refresh_button, market.auto_check, market.series_combo):
                    self.assertLessEqual(button.winfo_rootx() + button.winfo_width(), self.root.winfo_rootx() + self.root.winfo_width())
                self.assertLessEqual(market.status_label.winfo_rooty() + market.status_label.winfo_height(), self.root.winfo_rooty() + self.root.winfo_height())
                self.assertGreater(market.chart.winfo_width(), 200)
                self.assertTrue(market.chart.find_all())
            live.destroy()

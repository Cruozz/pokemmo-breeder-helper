from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from PIL import Image

from app import App
from preview_dialog import PreviewZoomWindow
from preview_geometry import fit_scale, image_point, normalized_roi, rescale_roi


class Value:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class GeometryTests(TestCase):
    def test_fit_fills_one_dimension_without_cropping(self):
        for size, viewport in [((1288, 822), (987, 540)), ((400, 300), (1600, 1000))]:
            scale = fit_scale(size, viewport)
            rendered = [size[i] * scale for i in (0, 1)]
            self.assertTrue(all(rendered[i] <= viewport[i] for i in (0, 1)))
            self.assertTrue(any(abs(rendered[i] - viewport[i]) < 1e-6 for i in (0, 1)))

    def test_fit_small_image_can_enlarge_above_two_times(self):
        self.assertEqual(fit_scale((100, 100), (800, 600)), 6)

    def test_mapping_uses_both_rounded_dimensions_and_offset(self):
        self.assertEqual(image_point((345, 217), (12, 5), (333, 212), (1288, 822)), (1288, 822))

    def test_reverse_drag_clamps_all_edges(self):
        self.assertEqual(normalized_roi((700, 900), (-5, -2), (640, 480)), (0, 0, 640, 480))

    def test_rescale_none_and_rectangle(self):
        self.assertIsNone(rescale_roi(None, (100, 100), (200, 300)))
        self.assertEqual(rescale_roi((10, 20, 90, 80), (100, 100), (200, 300)), (20, 60, 180, 240))


class DetachedPreviewTests(TestCase):
    def setUp(self):
        self.preview = p = PreviewZoomWindow.__new__(PreviewZoomWindow)
        p.image = Image.new("RGB", (1000, 800))
        p.roi = (0, 0, 320, 800)
        p.window = Mock()
        p.window.winfo_exists.return_value = True
        p.closed = p.dirty = p.fields_pending = p.syncing_fields = False
        p.drag_start = p.draft_roi = p.pending_frame = p.resize_after_id = None
        p.offset, p.rendered_size = (10, 20), (500, 400)
        p.canvas = Mock()
        p.canvas.canvasx.side_effect = lambda x: x
        p.canvas.canvasy.side_effect = lambda y: y
        p.status_var = Value()
        p.coord_vars = [Value() for _ in range(4)]
        p.close_button = Mock()
        p._render = Mock()
        p._draw_roi = Mock()
        p.on_apply = Mock()
        p.on_close = Mock()
        p._sync_fields()

    def drag(self):
        p = self.preview
        p._roi_start(SimpleNamespace(x=60, y=70))
        p._roi_drag(SimpleNamespace(x=310, y=320))
        p._roi_finish(SimpleNamespace(x=310, y=320))

    def test_new_selection_survives_many_live_frames(self):
        self.drag()
        p = self.preview
        for _ in range(12):
            p.update_image(Image.new("RGB", (1000, 800)), (0, 0, 320, 800))
        self.assertEqual(p.roi, (100, 100, 600, 600))
        self.assertTrue(p.dirty)

    def test_live_frame_is_queued_until_drag_finishes(self):
        p = self.preview
        p._roi_start(SimpleNamespace(x=60, y=70))
        p._roi_drag(SimpleNamespace(x=310, y=320))
        p.update_image(Image.new("RGB", (2000, 1600)), (0, 0, 640, 1600))
        self.assertEqual(p.image.size, (1000, 800))
        p._render.assert_not_called()
        p._roi_finish(SimpleNamespace(x=310, y=320))
        self.assertEqual(p.image.size, (2000, 1600))
        self.assertEqual(p.roi, (200, 200, 1200, 1200))

    def test_clean_selection_follows_parent(self):
        self.preview.update_image(self.preview.image, (20, 30, 400, 500))
        self.assertEqual(self.preview.roi, (20, 30, 400, 500))

    def test_clear_stays_cleared_after_refresh(self):
        p = self.preview
        p.clear_roi()
        p.update_image(p.image, (0, 0, 320, 800))
        self.assertIsNone(p.roi)

    def test_click_without_drag_keeps_original(self):
        p = self.preview
        p._roi_start(SimpleNamespace(x=60, y=70))
        p._roi_finish(SimpleNamespace(x=60, y=70))
        self.assertEqual(p.roi, (0, 0, 320, 800))
        self.assertFalse(p.dirty)

    def test_letterbox_click_does_not_start_selection(self):
        self.preview._roi_start(SimpleNamespace(x=0, y=0))
        self.assertIsNone(self.preview.drag_start)

    def test_numeric_edit_is_not_overwritten_by_refresh(self):
        p = self.preview
        for v, text in zip(p.coord_vars, ("100", "120", "200", "240")):
            v.set(text)
        p._fields_changed()
        p.update_image(Image.new("RGB", (1000, 800)), (0, 0, 320, 800))
        self.assertEqual(p.coord_vars[0].get(), "100")
        p._commit_coordinates()
        self.assertEqual(p.roi, (100, 120, 300, 360))
        self.assertIsNone(p.pending_frame)

    def test_invalid_coordinates_block_apply(self):
        p = self.preview
        for invalid in ("bad", "-10", "99999"):
            p.coord_vars[0].set(invalid)
            p._fields_changed()
            p.apply()
            p.on_apply.assert_not_called()
            self.assertFalse(p.closed)

    def test_apply_valid_pending_coordinates_and_close(self):
        p = self.preview
        p.coord_vars[2].set("250")
        p._fields_changed()
        p.apply()
        p.on_apply.assert_called_once_with((0, 0, 250, 800))
        self.assertTrue(p.closed)

    def test_cancel_never_applies_draft(self):
        self.drag()
        self.preview.close()
        self.preview.on_apply.assert_not_called()

    def test_resize_does_not_render_mid_gesture(self):
        p = self.preview
        p.drag_start = (100, 100)
        p._resize()
        p._render.assert_not_called()
        p.drag_start = None
        p._resize()
        p._render.assert_called_once()

    def test_scroll_offset_is_included_in_source_coordinates(self):
        p = self.preview
        p.canvas.canvasx.side_effect = lambda x: x + 100
        p.canvas.canvasy.side_effect = lambda y: y + 50
        self.assertEqual(p._image_point(60, 70), (300, 200))


class EmbeddedPreviewTests(TestCase):
    def setUp(self):
        self.app = a = App.__new__(App)
        a.current_image = Image.new("RGB", (1000, 800))
        a.preview_offset = (10, 20)
        a.preview_render_size = (500, 400)
        a.drag_start = None
        a.roi = (0, 0, 320, 800)
        a.preview_roi_item = 1
        a.canvas = Mock()
        a.status_var = Value()
        a._update_detached_preview = Mock()

    def test_refresh_does_not_repaint_committed_roi_during_drag(self):
        a = self.app
        a.start_roi(SimpleNamespace(x=60, y=70))
        a.drag_roi(SimpleNamespace(x=310, y=320))
        a.canvas.reset_mock()
        a.show_preview()
        a.draw_roi()
        a.canvas.coords.assert_not_called()
        a.canvas.itemconfigure.assert_not_called()

    def test_main_selection_rescales_if_live_source_resizes_mid_drag(self):
        a = self.app
        a.start_roi(SimpleNamespace(x=60, y=70))
        a.current_image = Image.new("RGB", (2000, 1600))
        a.draw_roi = Mock()
        a.finish_roi(SimpleNamespace(x=310, y=320))
        self.assertEqual(a.roi, (200, 200, 1200, 1200))
        self.assertIsNone(a.drag_start)
        a.draw_roi.assert_called_once()

    def test_tiny_gesture_restores_prior_selection(self):
        a = self.app
        a.start_roi(SimpleNamespace(x=60, y=70))
        a.draw_roi = Mock()
        a.finish_roi(SimpleNamespace(x=60, y=70))
        self.assertEqual(a.roi, (0, 0, 320, 800))
        a.draw_roi.assert_called_once()

    def test_double_click_cancels_embedded_gesture(self):
        a = self.app
        a.start_roi(SimpleNamespace(x=60, y=70))
        a.preview_zoom_window = None
        a.root = Mock()
        a.draw_roi = Mock()
        with patch("app.PreviewZoomWindow"):
            a.open_preview_zoom()
        self.assertIsNone(a.drag_start)
        a.draw_roi.assert_called_once()

    def test_new_source_closes_detached_draft(self):
        a = self.app
        a.preview_zoom_window = Mock()
        a.source_var = Value()
        a.show_preview = Mock()
        a._cancel_live_preview_tick = Mock()
        a.set_image(Image.new("RGB", (800, 600)), "other.png")
        a.preview_zoom_window.close.assert_called_once()
        self.assertIsNone(a.roi)

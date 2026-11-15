import os
from pathlib import Path
import tempfile
import threading
import time
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import Mock, patch

from PIL import Image,ImageDraw

from app import App
from bulk_ocr import BulkResult,BulkRow
from ocr_engine import OCRItem
from storage import load_inventory,save_inventory


def ready_row():
    return BulkRow(1,species="玛狃拉",raw_name="玛狃拉'恶冰",level=40,warehouse_level=40,slot=8,gender="M",
                   ivs=[31,1,2,3,4,5],hidden_ability=False,nature="",is_alpha=False,has_particles=False,
                   is_costume=False,reviewed=True)


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


class BulkWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.environment=patch.dict(os.environ,{"LOCALAPPDATA":self.directory.name})
        self.environment.start()
        self.root=tk.Tk()
        self.root.attributes("-alpha",0)
        self.app=App(self.root)
        self.root.geometry("720x600")
        self.root.update()

    def tearDown(self):
        if self.app.bulk_workspace is not None:
            self.app.bulk_workspace.shutdown()
        for callback in self.root.tk.call("after","info"):
            self.root.after_cancel(callback)
        self.root.destroy()
        self.environment.stop()
        self.directory.cleanup()

    def bulk(self):
        self.app._set_scan_method("bulk")
        self.root.update()
        self.app._apply_responsive_layout()
        self.root.update_idletasks()
        return self.app.bulk_workspace

    def test_modes_pause_capture_and_preserve_separate_fields_regions_and_progress(self):
        app=self.app
        app.species_var.set("伊布")
        app.iv_var.set("31/1/2/3/4/5")
        app.roi=(10,20,100,200)
        app.batch_page_var.set("2");app.batch_slot_var.set("3")
        app.live_preview_running=True
        bulk=self.bulk()
        self.assertFalse(app.live_preview_running)
        self.assertFalse(app.scan_controls_panel.winfo_manager())
        self.assertTrue(bulk.winfo_ismapped())
        bulk.page.set("6");bulk.start.set("8");bulk.count.set("20")
        bulk.set_source("warehouse",Image.new("RGB",(800,400)))
        bulk.rois["warehouse"]=(0,0,800,400)
        app._set_scan_method("continuous")
        self.root.update()
        self.assertFalse(bulk.winfo_manager())
        self.assertEqual((app.species_var.get(),app.iv_var.get(),app.roi),("伊布","31/1/2/3/4/5",(10,20,100,200)))
        self.assertEqual((app.batch_page_var.get(),app.batch_slot_var.get()),("2","3"))
        self.bulk()
        self.assertEqual((bulk.page.get(),bulk.start.get(),bulk.count.get()),("6","8","20"))
        self.assertEqual(bulk.rois["warehouse"],(0,0,800,400))
        self.assertIsNone(app._handle_batch_enter())

    def test_batch_controls_fit_small_and_large_windows(self):
        bulk=self.bulk()
        for geometry in ("720x600","1200x800"):
            self.root.geometry(geometry);self.root.update();self.app._apply_responsive_layout();self.root.update_idletasks()
            for page,button in ((bulk.input_page,bulk.recognize_button),(bulk.review_page,bulk.import_button)):
                bulk.tabs.select(page);self.root.update_idletasks()
                self.assertTrue(button.winfo_ismapped())
                self.assertLessEqual(button.winfo_rooty()+button.winfo_height(),self.root.winfo_rooty()+self.root.winfo_height())
                self.assertLessEqual(button.winfo_rootx()+button.winfo_width(),self.root.winfo_rootx()+self.root.winfo_width())

    def test_unreviewed_rows_import_without_filling_fields_or_advancing_continuous(self):
        bulk=self.bulk()
        bulk.page.set("6");bulk.start.set("8");bulk.count.set("1")
        row=ready_row()
        row.has_particles=row.is_costume=row.is_alpha=row.nature=None
        row.reviewed=False
        bulk.result=BulkResult([row])
        continuous_account=self.app.account_var.get()
        bulk.account.set("批量账号")
        bulk.stale=False
        self.assertFalse(bulk.order_confirmed.get())
        bulk._refresh(select=True)
        with patch("app.save_inventory",side_effect=OSError("test write failure")),patch("bulk_views.messagebox.showwarning"):
            bulk.import_selected()
        self.assertEqual(self.app.inventory,[])
        self.assertFalse(row.imported)
        bulk.import_selected()
        self.assertEqual(len(self.app.inventory),1)
        self.assertEqual(len(load_inventory()),1)
        self.assertEqual((self.app.inventory[0].page,self.app.inventory[0].slot),("6","8"))
        self.assertTrue(row.imported)
        self.assertFalse(self.app.inventory[0].verified)
        self.assertTrue(self.app.inventory[0].planner_usable)
        self.assertIn("nature",self.app.inventory[0].unreviewed_fields)
        self.assertIn("未审核",bulk.tree.item("1","values")[-1])
        self.assertEqual(self.app.account_var.get(),continuous_account)
        row.imported=False  # Replay after an inventory write but before a draft-save crash.
        bulk.sync_inventory()
        self.assertTrue(row.imported)
        bulk._refresh(select=True);bulk.import_selected()
        self.assertEqual(len(load_inventory()),1)
        self.assertEqual(self.app.batch_slot_var.get(),"1")

    def test_changed_inputs_and_old_worker_result_cannot_import_or_replace_the_draft(self):
        bulk=self.bulk()
        row=ready_row()
        bulk.result=BulkResult([row]);bulk._refresh(select=True)
        bulk.count.set("1")
        self.assertTrue(bulk.stale)
        bulk.on_import=Mock()
        bulk.import_selected()
        bulk.on_import.assert_not_called()
        request=bulk.request
        bulk.pause()
        bulk.messages.put((request,BulkResult([BulkRow(1,species="伊布")]),None))
        if bulk.poll_id is not None:
            bulk.after_cancel(bulk.poll_id)
        bulk._poll()
        self.assertIs(bulk.result.rows[0],row)

    def test_saved_draft_restores_pending_fields_and_source_images(self):
        bulk=self.bulk()
        bulk.page.set("6");bulk.start.set("8");bulk.count.set("1")
        bulk.set_source("warehouse",Image.new("RGB",(800,400)))
        bulk.rois["warehouse"]=(0,0,800,400)
        row=ready_row();row.has_particles=None;row.nature=None;row.reviewed=False
        bulk.result=BulkResult([row]);bulk.stale=False;bulk._save()
        capture=bulk.result.capture_id
        bulk.shutdown();bulk.destroy();self.app.bulk_workspace=None
        restored=self.bulk()
        self.assertEqual(restored.result.capture_id,capture)
        self.assertIsNone(restored.result.rows[0].has_particles)
        self.assertIsNone(restored.result.rows[0].nature)
        self.assertFalse(restored.result.rows[0].reviewed)
        self.assertEqual(restored.images["warehouse"].size,(800,400))

    def test_empty_scan_can_be_saved_and_edited_in_inventory_without_filling_anything(self):
        bulk=self.bulk()
        bulk.auto_import.set(False)
        bulk.page.set("6");bulk.start.set("8");bulk.count.set("1")
        row=BulkRow(1,slot=8)
        bulk.result=BulkResult([row]);bulk.stale=False;bulk._refresh(select=True)
        with patch("bulk_views.messagebox.showwarning") as warning:
            bulk.import_selected()
        warning.assert_not_called()
        self.assertEqual(len(load_inventory()),1)
        identifier=self.app.inventory[0].id
        self.app.inventory_tree.selection_set(identifier)
        self.app.edit_inventory_selected();self.root.update()
        with patch("app.messagebox.showwarning") as warning:
            self.app.save_current_monster()
        warning.assert_not_called()
        stored=load_inventory()
        self.assertEqual(len(stored),1)
        self.assertEqual(stored[0].id,identifier)
        self.assertFalse(stored[0].verified)
        self.assertEqual(stored[0].ivs,[None]*6)
        self.app.inventory_tree.selection_set(identifier)
        self.app.mark_selected_inventory_reviewed()
        self.app.inventory_tree.selection_set(identifier)
        self.app.edit_inventory_selected();self.root.update()
        with patch("app.messagebox.showwarning") as warning:
            self.app.save_current_monster()
        warning.assert_not_called()
        self.assertTrue(load_inventory()[0].verified)
        self.assertFalse(load_inventory()[0].planner_usable)

    def test_editor_can_save_or_mark_reviewed_without_filling_unknown_fields(self):
        bulk=self.bulk()
        row=ready_row();row.nature=None;row.is_alpha=None;row.is_costume=None;row.has_particles=None;row.reviewed=False
        bulk.result=BulkResult([row]);bulk._refresh(select=True)
        bulk.edit_selected()
        window=bulk.editor
        next(widget for widget in descendants(window) if isinstance(widget,ttk.Button) and widget.cget("text")=="保存资料").invoke()
        self.assertIsNone(bulk.editor)
        self.assertFalse(row.reviewed)
        self.assertIsNone(row.nature)
        self.assertIsNone(row.has_particles)
        bulk.edit_selected()
        next(widget for widget in descendants(bulk.editor) if isinstance(widget,ttk.Button) and widget.cget("text")=="标为已审核 / 下一只").invoke()
        self.assertIsNone(bulk.editor)
        self.assertTrue(row.reviewed)
        self.assertIsNone(row.nature)

    def test_supplementing_imported_row_updates_existing_stock_and_preserves_traits(self):
        bulk=self.bulk()
        bulk.page.set("6");bulk.start.set("8");bulk.count.set("1")
        row=ready_row();row.reviewed=False;row.nature=None;row.has_particles=True;row.particles=["bats"];row.is_costume=True
        bulk.result=BulkResult([row]);bulk.stale=False;bulk._refresh(select=True)
        bulk.import_selected()
        original_id=self.app.inventory[0].id
        bulk.edit_selected()
        combo=next(widget for widget in descendants(bulk.editor) if isinstance(widget,ttk.Combobox) and "固执" in tuple(widget.cget("values")))
        combo.set("固执")
        next(widget for widget in descendants(bulk.editor) if isinstance(widget,ttk.Button) and widget.cget("text")=="保存资料").invoke()
        stored=load_inventory()
        self.assertEqual(len(stored),1)
        self.assertEqual((stored[0].id,stored[0].nature),(original_id,"固执"))
        self.assertFalse(stored[0].verified)
        self.assertEqual(stored[0].particles,["bats"])
        self.assertTrue(stored[0].is_costume)
        self.app.inventory=[];save_inventory([])
        with patch("bulk_views.messagebox.showwarning") as warning:
            bulk.apply_to_selected("nature","胆小")
        warning.assert_called_once()
        self.assertEqual(load_inventory(),[])
        self.assertEqual(row.nature,"固执")

    def test_inventory_editor_supplements_pending_batch_without_forcing_review(self):
        bulk=self.bulk()
        bulk.page.set("6");bulk.start.set("8");bulk.count.set("1")
        row=ready_row();row.reviewed=False;row.nature=None;row.has_particles=True;row.particles=["bats"];row.is_costume=None
        bulk.result=BulkResult([row]);bulk.stale=False;bulk._refresh(select=True)
        bulk.import_selected()
        identifier=self.app.inventory[0].id
        self.app.inventory_tree.selection_set(identifier)
        self.app.edit_inventory_selected()
        self.root.update()
        self.app.nature_var.set("内敛")
        with patch("app.messagebox.showwarning") as warning:
            self.app.save_current_monster()
        warning.assert_not_called()
        stored=load_inventory()
        self.assertEqual(len(stored),1)
        self.assertEqual((stored[0].id,stored[0].nature),(identifier,"内敛"))
        self.assertFalse(stored[0].verified)
        self.assertEqual(stored[0].particles,["bats"])
        self.assertIn("is_costume",stored[0].unreviewed_fields)
        self.bulk()
        self.assertEqual(row.nature,"内敛")
        self.assertFalse(row.reviewed)
        self.app.inventory_tree.selection_set(identifier)
        self.app.mark_selected_inventory_reviewed()
        self.assertTrue(load_inventory()[0].verified)

    def test_recognition_thread_reads_only_its_two_regions_and_keeps_unknown_review_fields(self):
        bulk=self.bulk()
        bulk.page.set("6");bulk.start.set("8");bulk.count.set("1")
        warehouse=Image.new("RGB",(800,400),(30,35,40))
        ImageDraw.Draw(warehouse).rectangle((567,42,573,53),fill=(20,150,240))
        bulk.set_source("warehouse",warehouse)
        bulk.set_source("release",Image.new("RGB",(700,180),(50,60,65)))
        bulk.rois={"warehouse":(0,0,800,400),"release":(0,0,700,180)}
        class FakeOCR:
            def recognize(self,image):
                def entry(text,x,y,width):return OCRItem(text,.99,[[x,y],[x+width,y],[x+width,y+20],[x,y+20]])
                return [entry("40",20,20,25)] if image.size==(720,112) else [entry("Lv.40 玛狃拉'恶冰",70,50,168),entry("31/1/2/3/4/5",75,75,150)]
        bulk.get_processor=lambda:FakeOCR()
        bulk.recognize()
        deadline=time.monotonic()+4
        while bulk.busy and time.monotonic()<deadline:
            self.root.update();time.sleep(.01)
        self.assertFalse(bulk.busy)
        self.assertEqual(bulk.result.blockers,[])
        row=bulk.result.rows[0]
        self.assertEqual((row.species,row.slot,row.gender,row.warehouse_level),("玛狃拉",8,"M",40))
        self.assertIsNone(row.has_particles)
        self.assertIsNone(row.nature)
        self.assertFalse(row.reviewed)
        self.assertTrue(bulk.auto_import.get())
        self.assertTrue(row.imported)
        self.assertEqual(len(load_inventory()),1)
        self.assertFalse(load_inventory()[0].verified)
        self.assertTrue(load_inventory()[0].planner_usable)

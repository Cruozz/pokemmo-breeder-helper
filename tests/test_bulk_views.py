import os
from dataclasses import replace
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

    def single_row_sources(self,bulk,gender="M",diamond=False):
        bulk.page.set("6");bulk.start.set("8");bulk.count.set("1")
        warehouse=Image.new("RGB",(800,400),(30,35,40))
        draw=ImageDraw.Draw(warehouse)
        color=(235,113,154) if gender=="F" else (20,150,240)
        draw.ellipse((568,45,574,51),outline=color,width=1)
        if gender=="F":
            draw.line((571,51,571,57),fill=color)
            draw.line((568,54,574,54),fill=color)
        else:
            draw.line((573,46,577,42),fill=color)
            draw.line((574,42,577,42,577,45),fill=color)
        bulk.set_source("warehouse",warehouse)
        release=Image.new("RGB",(700,180),(50,60,65))
        if diamond:ImageDraw.Draw(release).polygon([(258,49),(268,49),(273,55),(263,67),(253,55)],fill=(40,200,250))
        bulk.set_source("release",release)
        bulk.rois={"warehouse":(0,0,800,400),"release":(0,0,700,180)}
        class FakeOCR:
            def recognize(self,image):
                def entry(text,x,y,width):return OCRItem(text,.99,[[x,y],[x+width,y],[x+width,y+20],[x,y+20]])
                return [entry("40",20,20,25)] if image.size==(720,112) else [entry("Lv.40 玛狃拉'恶冰",70,50,168),entry("31/1/2/3/4/5",75,75,150)]
        bulk.get_processor=lambda:FakeOCR()

    def finish_recognition(self,bulk):
        deadline=time.monotonic()+4
        while bulk.busy and time.monotonic()<deadline:
            self.root.update();time.sleep(.01)
        self.assertFalse(bulk.busy)

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
        bulk.result.warnings=["仓库高亮仅供参考；已按设置的第 21～40 格对应，不影响入库。"]
        bulk._refresh()
        for geometry in ("720x600","1200x800"):
            self.root.geometry(geometry);self.root.update();self.app._apply_responsive_layout();self.root.update_idletasks()
            for page,button in ((bulk.input_page,bulk.recognize_button),(bulk.review_page,bulk.import_button),(bulk.review_page,bulk.retry_button)):
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

    def test_completed_batches_advance_twenty_slots_then_to_the_next_page(self):
        bulk=self.bulk()
        bulk.page.set("3");bulk.start.set("1");bulk.count.set("20")
        first_session=bulk.session_id
        for start,expected in ((1,("3","21","20")),(21,("3","41","20")),(41,("4","1","20"))):
            bulk.result=BulkResult([replace(ready_row(),index=i+1,slot=start+i,reviewed=False) for i in range(20)])
            bulk.stale=False;bulk._refresh(select=True);bulk.import_selected()
            self.assertTrue(all(row.imported for row in bulk.result.rows))
            bulk.new_batch()
            self.assertEqual((bulk.page.get(),bulk.start.get(),bulk.count.get()),expected)
            self.assertEqual(bulk.preferred_count,20)
        self.assertEqual(len(load_inventory()),60)
        self.assertNotEqual(bulk.session_id,first_session)
        empty_session=bulk.session_id
        bulk.new_batch()
        self.assertEqual(bulk.session_id,empty_session)
        bulk.restore_previous()
        self.assertEqual((bulk.page.get(),bulk.start.get(),bulk.count.get()),("3","41","20"))
        self.assertTrue(all(row.imported for row in bulk.result.rows))

    def test_short_last_batch_remembers_twenty_after_restore_and_page_change(self):
        bulk=self.bulk()
        bulk.page.set("3");bulk.start.set("31");bulk.count.set("20")
        bulk.result=BulkResult([replace(ready_row(),index=i+1,slot=31+i,imported=True) for i in range(20)])
        bulk.stale=False;bulk.new_batch()
        self.assertEqual((bulk.page.get(),bulk.start.get(),bulk.count.get()),("3","51","10"))
        bulk.shutdown();bulk.destroy();self.app.bulk_workspace=None
        restored=self.bulk()
        self.assertEqual(restored.preferred_count,20)
        restored.result=BulkResult([replace(ready_row(),index=i+1,slot=51+i,imported=True) for i in range(10)])
        restored.stale=False;restored.new_batch()
        self.assertEqual((restored.page.get(),restored.start.get(),restored.count.get()),("4","1","20"))

    def test_new_batch_does_not_skip_unsaved_partial_invalid_or_stale_results(self):
        bulk=self.bulk()
        bulk.page.set("3");bulk.start.set("1");bulk.count.set("2")
        for imported,stale,blockers in (((False,False),False,[]),((True,False),False,[]),((True,True),True,[]),((True,True),False,["数量不符"])):
            bulk.result=BulkResult([replace(ready_row(),index=i+1,slot=i+1,imported=imported[i]) for i in range(2)],blockers)
            bulk.stale=stale;bulk.new_batch()
            self.assertEqual((bulk.page.get(),bulk.start.get()),("3","1"))
        bulk.new_batch()
        self.assertEqual(bulk.start.get(),"1")

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
        self.single_row_sources(bulk)
        with patch("bulk_ocr.selected_slots",return_value=[1]):
            bulk.recognize()
            self.finish_recognition(bulk)
        self.assertEqual(bulk.result.blockers,[])
        self.assertTrue(bulk.result.warnings)
        self.assertIn("高亮仅供参考",bulk.summary.get())
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

    def test_legacy_highlight_blocked_batch_can_retry_saved_images_and_enter_inventory(self):
        bulk=self.bulk()
        self.single_row_sources(bulk)
        processor=bulk.get_processor
        row=replace(ready_row(),slot=None,gender="",warehouse_level=None,reviewed=False)
        bulk.result=BulkResult([row],["仓库高亮格位与设置范围不一致，请核对起始格、数量和截图。"],[1])
        bulk.stale=False
        state=bulk._state();state["result"].pop("warnings")
        bulk.shutdown();bulk.destroy();self.app.bulk_workspace=None
        bulk.store.save(state)
        restored=self.bulk()
        self.assertIn("重新识别这一批",restored.status.get())
        self.assertEqual(str(restored.import_button.cget("state")),"disabled")
        restored.get_processor=processor
        with patch("bulk_ocr.selected_slots",return_value=[1]):
            restored.retry_button.invoke()
            self.finish_recognition(restored)
        self.assertFalse(restored.result.blockers)
        self.assertEqual((restored.result.rows[0].slot,restored.result.rows[0].gender),(8,"M"))
        self.assertTrue(restored.result.rows[0].imported)
        self.assertEqual(len(load_inventory()),1)
        self.assertFalse(load_inventory()[0].verified)

    def test_rerecognition_corrects_same_unreviewed_stock_and_never_restores_consumed_records(self):
        bulk=self.bulk()
        self.single_row_sources(bulk,gender="F",diamond=True)
        row=replace(ready_row(),gender="M",hidden_ability=False,reviewed=False,nature=None)
        bulk.result=BulkResult([row]);bulk.stale=False;bulk._refresh(select=True)
        bulk.import_selected()
        identifier=self.app.inventory[0].id
        self.app._patch_bulk_inventory([identifier],{"nature":"固执","has_particles":True,"particles":["bats"]})
        original_capture=bulk.result.capture_id
        bulk.retry_button.invoke();self.finish_recognition(bulk)
        material=load_inventory()[0]
        self.assertEqual((material.id,material.gender,material.has_hidden_ability),(identifier,"F",True))
        self.assertEqual(len(load_inventory()),1)
        self.assertEqual((material.nature,material.particles),("固执",["bats"]))
        self.assertFalse(material.verified)
        self.assertEqual(bulk.result.capture_id,original_capture)
        self.assertTrue(list(bulk.store.directory(bulk.session_id).glob("before-recognition-repair-*.json")))
        self.app.inventory=[];save_inventory([])
        bulk.retry_button.invoke();self.finish_recognition(bulk)
        self.assertEqual(load_inventory(),[])
        self.assertTrue(bulk.result.rows[0].imported)
        self.assertEqual(bulk.tree.item("1","values")[-1],"已离库")

    def test_failed_retry_or_backup_keeps_original_batch_and_inventory(self):
        bulk=self.bulk()
        self.single_row_sources(bulk,gender="F",diamond=True)
        row=replace(ready_row(),gender="M",hidden_ability=False,reviewed=False,nature=None)
        bulk.result=BulkResult([row]);bulk.stale=False;bulk._refresh(select=True)
        bulk.import_selected()
        original_capture=bulk.result.capture_id
        original_stock=[monster.to_dict() for monster in load_inventory()]
        with patch("bulk_session.BulkSessionStore.save_repair_backup",side_effect=OSError("backup unavailable")):
            bulk.retry_button.invoke();self.finish_recognition(bulk)
        self.assertIn("校正未保存",bulk.status.get())
        self.assertEqual([monster.to_dict() for monster in load_inventory()],original_stock)
        self.assertEqual((bulk.result.capture_id,bulk.result.rows[0].gender),(original_capture,"M"))
        self.assertTrue(bulk.result.rows[0].imported)
        with patch("bulk_views.recognize_bulk",return_value=BulkResult(blockers=["数量不符"])):
            bulk.retry_button.invoke();self.finish_recognition(bulk)
        self.assertIn("原库存和批次保留",bulk.status.get())
        self.assertEqual([monster.to_dict() for monster in load_inventory()],original_stock)
        self.assertEqual(bulk.result.capture_id,original_capture)
        bulk.retry_button.invoke();self.finish_recognition(bulk)
        self.assertEqual((load_inventory()[0].gender,load_inventory()[0].has_hidden_ability),("F",True))

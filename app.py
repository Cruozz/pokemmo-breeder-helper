from __future__ import annotations

import sys
import uuid
import hashlib
import json
import queue
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
VENDOR_DIR = BASE_DIR / "vendor"
APP_TITLE = "Pokemmo孵蛋助手——作者：晨若 QQ1052495869 有问题反馈哦"
LIVE_PREVIEW_INTERVAL_MS = 300
BATCH_SCAN_INTERVAL_MS = 350
BATCH_STABLE_FRAMES = 3
BATCH_STABLE_DIFFERENCE = 6.0
BATCH_CHANGE_DIFFERENCE = 7.0
BATCH_NEXT_COUNTDOWN_SECONDS = 3.0
BATCH_COUNTDOWN_TICK_MS = 10
UI_COLORS = {
    "app_bg": "#F8FAFC",
    "surface": "#FFFFFF",
    "surface_alt": "#F8FAFC",
    "ink": "#0F172A",
    "ink_blue": "#1E3A8A",
    "muted": "#64748B",
    "border": "#E2E8F0",
    "border_blue": "#DBEAFE",
    "accent": "#1E40AF",
    "accent_hover": "#1E3A8A",
    "action": "#2563EB",
    "action_hover": "#1D4ED8",
    "accent_soft": "#EFF6FF",
    "selected": "#DBEAFE",
    "teal": "#2563EB",
    "teal_soft": "#EFF6FF",
    "success": "#16A34A",
    "success_text": "#166534",
    "success_soft": "#F0FDF4",
    "warning": "#D97706",
    "warning_text": "#92400E",
    "warning_soft": "#FFF7ED",
    "danger": "#DC2626",
    "danger_text": "#991B1B",
    "danger_soft": "#FEF2F2",
    "disabled": "#94A3B8",
    "preview": "#0F172A",
}
PLAN_ITEM_ASSET_KEYS = {
    "HP护腕": "power-weight",
    "攻击护腕": "power-bracer",
    "防御护腕": "power-belt",
    "特攻护腕": "power-lens",
    "特防护腕": "power-band",
    "速度护腕": "power-anklet",
    "不变之石": "everstone",
}
if VENDOR_DIR.exists():
    sys.path.insert(0, str(VENDOR_DIR))

from tkinter import END, BOTH, LEFT, RIGHT, X, Y, BooleanVar, Canvas, Listbox, PanedWindow, StringVar, Toplevel, filedialog, messagebox
from tkinter import font as tkfont
from tkinter import ttk

from PIL import Image, ImageFilter, ImageGrab, ImageTk

from capture import WindowInfo, capture_window, list_windows
from chain_planner import ChainCandidate, ChainState, gender_name, is_ditto
from execution import ExecutionPlan, ExecutionStep, build_execution_plan
from mind_map import BreedingMindMap, MindMapNode
from models import STATS, Monster, format_box_position, normalize_gender
from autocomplete import AutocompletePopup
from nature_data import (
    NATURES,
    NEUTRAL_TARGET_NAME,
    filter_planner_natures,
    find_nature,
    is_neutral_nature,
    planner_nature_display_name,
)
from ocr_engine import OCRProcessor
from planner import make_report_with_candidates
from preview_dialog import PreviewZoomWindow
from reference_data import get_reference_database
from species_data import SpeciesRecord, get_species_database
from storage import (
    are_high_confidence_duplicates,
    consume_parents_and_add_child,
    delete_inventory_records,
    find_high_confidence_duplicate_groups,
    load_accounts,
    load_active_plan,
    load_inventory,
    save_accounts,
    save_active_plan,
    save_inventory,
    undo_last_inventory_deletion,
    undo_last_consumption,
)


class App:
    def __init__(self, root: ttk.Frame | object) -> None:
        self.root = root
        self.root.title(APP_TITLE)
        self.app_icon_photo = None
        self.author_alipay_photo = None
        self.author_wechat_photo = None
        app_icon_path = BASE_DIR / "assets" / "app-icon.png"
        if app_icon_path.exists():
            try:
                self.app_icon_photo = ImageTk.PhotoImage(Image.open(app_icon_path).convert("RGBA"))
                self.root.iconphoto(True, self.app_icon_photo)
            except Exception:
                self.app_icon_photo = None
        self.root.geometry("880x920")
        self.root.minsize(700, 600)
        self.layout_orientation = ""
        self.applied_workspace_mode = ""
        self.applied_layout_density = ""
        self.compact_scan_view = "result"
        self.source_collapsed = False
        self.current_form_expanded = False
        self.layout_after_id = None
        self.preview_after_id = None
        self.window_suspended = False
        self._last_left_wraplength = 0
        self._last_right_wraplength = 0
        self._last_scan_wraplength = 0
        self._batch_layout_narrow: bool | None = None
        self._last_status_wraplengths: tuple[int, int] = (0, 0)

        self.current_image: Image.Image | None = None
        self.current_source = ""
        self.preview_scale = 1.0
        self.preview_offset = (0, 0)
        self.roi: tuple[int, int, int, int] | None = None
        self.drag_start: tuple[int, int] | None = None
        self.drag_rectangle = None
        self.preview_photo = None
        self.preview_image_item = None
        self.preview_roi_item = None
        self.preview_render_size: tuple[int, int] | None = None
        self.preview_render_key: tuple[int, tuple[int, int]] | None = None
        self.preview_zoom_window: PreviewZoomWindow | None = None
        self.plan_map_window: Toplevel | None = None
        self.detached_plan_map: BreedingMindMap | None = None
        self.planner_details_collapsed = False
        self.selected_plan_step_number: int | None = None
        self.auto_activate_replan_pending = False
        self.auto_replan_reason = ""
        self.auto_replan_progress_keys: set[tuple[str, str]] = set()
        self.auto_replan_preferred_material_ids: set[str] = set()
        self.expanded_completed_sources: set[tuple[str, int]] = set()
        self.plan_candidate_cache: dict[str, ChainCandidate] = {}
        self.autocomplete_popups: list[AutocompletePopup] = []
        self.windows: list[WindowInfo] = []
        self.inventory = load_inventory()
        self.accounts = list(dict.fromkeys([*load_accounts(), *(item.account for item in self.inventory if item.account)]))
        self.species_db = get_species_database()
        self.reference_db = get_reference_database()
        self.ocr: OCRProcessor | None = None
        self.editing_monster_id: str | None = None
        self.current_candidates = []
        self.target_species_results: list[SpeciesRecord] = []
        self.selected_target_species_id: int | None = None
        self.nature_picker_window: Toplevel | None = None
        self.proposed_plan: ExecutionPlan | None = None
        self.plan_worker_busy = False
        self.plan_result_queue: queue.Queue = queue.Queue()
        self.plan_excluded_ids: set[str] = set()
        self.plan_exclusion_history: list[str] = []
        self.plan_exclusion_scope_id: int | None = None
        self.active_plan: ExecutionPlan | None = None
        stored_plan = load_active_plan()
        if stored_plan:
            try:
                self.active_plan = ExecutionPlan.from_dict(stored_plan)
            except Exception:
                self.active_plan = None
        self._reconcile_active_plan()

        self.batch_running = False
        self.batch_after_id = None
        self.batch_countdown_after_id = None
        self.batch_countdown_deadline = 0.0
        self.batch_countdown_active = False
        self.batch_worker_busy = False
        self.batch_pending_fingerprint: bytes | None = None
        self.batch_pending_count = 0
        self.batch_last_processed: bytes | None = None
        self.batch_last_confirmed_fingerprint: bytes | None = None
        self.batch_last_confirmed_signature: tuple | None = None
        self.batch_latest_fingerprint: bytes | None = None
        self.batch_current_fingerprint: bytes | None = None
        self.batch_current_confidence: float | None = None
        self.batch_waiting_confirmation = False
        self.batch_awaiting_visual_change = False
        self.batch_result_queue: queue.Queue = queue.Queue()
        self.batch_session = 0
        self.batch_saved_count = 0
        self.live_preview_running = False
        self.live_preview_after_id = None
        self.live_window: WindowInfo | None = None

        self.page_var = StringVar()
        self.slot_var = StringVar()
        self.account_var = StringVar(value="主账号")
        self.species_var = StringVar()
        self.gender_var = StringVar()
        self.nature_var = StringVar()
        self.iv_var = StringVar()
        self.ability_var = StringVar()
        self.item_var = StringVar()
        self.moves_var = StringVar()
        self.alpha_var = StringVar(value="普通")
        self.hidden_ability_var = BooleanVar(value=False)
        self.groups_var = StringVar()
        self.source_var = StringVar()
        self.source_summary_var = StringVar(value="未连接 · 请选择 PokeMMO 窗口或载入截图")
        self.status_var = StringVar(value="准备就绪。")
        self.target_species_var = StringVar()
        self.target_gender_var = StringVar(value="雌性")
        self.target_alpha_var = StringVar(value="普通")
        self.target_hidden_ability_var = BooleanVar(value=False)
        self.target_hidden_ability_hint_var = StringVar(value="不要求保留梦特潜力")
        self.selected_egg_moves: list[str] = []
        self.target_egg_moves_var = StringVar(value="不需要遗传技能")
        self.target_nature_var = StringVar()
        self.target_nature_info_var = StringVar(value="不指定性格")
        self.target_lock_nature_var = BooleanVar(value=False)
        self.target_lock_gender_var = BooleanVar(value=True)
        self.target_allow_ditto_var = BooleanVar(value=False)
        self.target_convert_mother_with_ditto_var = BooleanVar(value=False)
        self.target_allow_alpha_materials_var = BooleanVar(value=False)
        self.target_alpha_material_hint_var = StringVar(
            value="关闭＝仅普通素材；开启＝普通与头目均可用，最终仍为普通。"
        )
        self.target_strategy_var = StringVar(value="库存优先")
        self.target_intermediate_gender_strategy_var = StringVar(value="智能锁定")
        self.target_gender_strategy_hint_var = StringVar(
            value="低 V 首支不锁；记录实际性别后，只锁配对所需的另一支。5V 与成品约束保持确定。"
        )
        self.next_step_gender_var = StringVar(value="自动")
        self.next_step_gender_hint_var = StringVar(value="")
        self.planner_rules_visible = False
        self.target_iv_var = StringVar(value="x/x/x/x/x/x")
        self.target_iv_vars = [StringVar(value="X") for _stat in STATS]
        self.target_groups_var = StringVar(value="待选择")
        self.target_info_var = StringVar(value="输入图鉴编号或名字片段，再从下方结果中双击选择。")
        self.inventory_filter_var = StringVar()
        self.batch_page_var = StringVar(value="1")
        self.batch_slot_var = StringVar(value="1")
        self.batch_slots_per_page_var = StringVar(value="60")
        self.batch_delay_var = StringVar(value=f"{BATCH_NEXT_COUNTDOWN_SECONDS:g}")
        self.ocr_performance_var = StringVar(value="平衡")
        self.plan_status_var = StringVar(value="尚未启用执行方案。")
        self.plan_summary_var = StringVar(value="尚未生成规划。")
        self.plan_purchase_var = StringVar(value="生成方案后将在这里显示库存利用与补购信息。")
        self.plan_exclusion_var = StringVar(value="本次规划没有排除库存素材。")
        self.recent_scan_var = StringVar(value="最近识别：—")
        self.ocr_confidence_var = StringVar(value="OCR 置信度：—")
        self.batch_cycle_title_var = StringVar(value="连续录入节奏")
        self.batch_cycle_value_var = StringVar(value="未启动")
        self.batch_cycle_hint_var = StringVar(value="启动连续扫描后，这里会显示下一只精灵的操作提示。")
        self.inventory_summary_var = StringVar(value="库存 0 条")
        self.inventory_selection_var = StringVar(value="未选择素材")
        self.plan_compact_summary_var = StringVar(value="尚未生成规划")
        self.inventory_status_filter_var = StringVar(value="全部状态")
        self.inventory_type_filter_var = StringVar(value="全部类别")
        self.inventory_account_filter_var = StringVar(value="全部账号")
        self.workspace_mode_var = StringVar(value="扫描素材")

        if self._enrich_inventory():
            save_inventory(self.inventory)

        self.build_ui()
        self.status_var.trace_add("write", self._update_status_appearance)
        self.plan_status_var.trace_add("write", self._update_plan_status_appearance)
        self.refresh_windows()
        self.refresh_inventory_tree()
        self.refresh_plan_status()
        self._update_status_appearance()
        self._update_plan_status_appearance()
        self.root.bind("<Configure>", self._schedule_responsive_layout, add="+")
        self.root.bind("<Unmap>", self._on_root_unmap, add="+")
        self.root.bind("<Map>", self._on_root_map, add="+")
        self.root.bind("<Return>", self._handle_batch_enter, add="+")
        self.root.bind("<KP_Enter>", self._handle_batch_enter, add="+")
        self.root.bind("<space>", self._handle_batch_space, add="+")
        self.root.bind("<F8>", self._handle_batch_retry_hotkey, add="+")
        self.root.after_idle(self._apply_responsive_layout)

    def build_ui(self) -> None:
        self._configure_styles()
        try:
            self.root.configure(background=UI_COLORS["app_bg"])
        except Exception:
            pass

        workspace_bar = ttk.Frame(self.root, style="App.TFrame", padding=(12, 8, 12, 0))
        workspace_bar.pack(fill=X)
        ttk.Label(workspace_bar, text="工作区", style="Field.TLabel").pack(side=LEFT, padx=(0, 8))
        self.scan_mode_button = ttk.Button(
            workspace_bar,
            text="扫描素材",
            style="Primary.TButton",
            command=lambda: self._select_workspace_mode("scan"),
        )
        self.scan_mode_button.pack(side=LEFT, padx=(0, 5))
        self.planner_mode_button = ttk.Button(
            workspace_bar,
            text="孵蛋规划",
            command=lambda: self._select_workspace_mode("planner"),
        )
        self.planner_mode_button.pack(side=LEFT, padx=(0, 5))
        self.author_mode_button = ttk.Button(
            workspace_bar,
            text="作者的话",
            command=lambda: self._select_workspace_mode("author"),
        )
        self.author_mode_button.pack(side=RIGHT)

        self.scan_status_frame = ttk.Frame(self.root, style="StatusBar.TFrame", padding=(8, 6))
        self.scan_status_frame.pack(fill=X, padx=12, pady=(6, 4))
        self.build_scan_status_bar(self.scan_status_frame)

        self.scan_controls_panel = ttk.Frame(self.root, style="Panel.TFrame", padding=(8, 7))
        self.scan_controls_panel.pack(fill=X, padx=12, pady=(0, 4))
        self.build_scan_controls(self.scan_controls_panel)

        self.main_pane = self._create_paned_window(
            self.root,
            orient="horizontal",
            background=UI_COLORS["app_bg"],
        )
        self.main_pane.pack(fill=BOTH, expand=True, padx=12, pady=(0, 10))

        self.left_panel = ttk.Frame(self.main_pane, style="Panel.TFrame", padding=8)
        self.right_panel = ttk.Frame(self.main_pane, style="Panel.TFrame", padding=8)
        self.build_capture_panel(self.left_panel)
        self.build_right_panel(self.right_panel)
        self.left_panel.bind("<Configure>", self._resize_left_content, add="+")
        self.right_panel.bind("<Configure>", self._resize_right_content, add="+")

    def _select_workspace_mode(self, mode: str) -> None:
        mode = mode if mode in {"planner", "author"} else "scan"
        labels = {"scan": "扫描素材", "planner": "孵蛋规划", "author": "作者的话"}
        self.workspace_mode_var.set(labels[mode])
        if hasattr(self, "right_tabs"):
            self._set_author_workspace_visible(mode == "author")
            if mode != "author":
                target_tab = self.planner_tab if mode == "planner" else self.current_tab
                self.right_tabs.select(target_tab)
        if mode == "scan":
            self.compact_scan_view = "result"
        self._schedule_responsive_layout(immediate=True)

    def _set_author_workspace_visible(self, visible: bool) -> None:
        if not hasattr(self, "right_tabs") or not hasattr(self, "author_page"):
            return
        if visible:
            self.right_tabs.pack_forget()
            if not self.author_page.winfo_manager():
                self.author_page.pack(fill=BOTH, expand=True)
            return
        self.author_page.pack_forget()
        if not self.right_tabs.winfo_manager():
            self.right_tabs.pack(fill=BOTH, expand=True)

    def _on_right_tab_changed(self, _event=None) -> None:
        if not hasattr(self, "right_tabs"):
            return
        selected = self.right_tabs.nametowidget(self.right_tabs.select())
        if selected is self.planner_tab:
            label = "孵蛋规划"
        elif selected is self.inventory_tab:
            label = "素材库存"
        else:
            label = "扫描素材"
        self.workspace_mode_var.set(label)
        self._schedule_responsive_layout(immediate=True)

    def _update_workspace_buttons(self, mode: str) -> None:
        if not hasattr(self, "scan_mode_button"):
            return
        self.scan_mode_button.configure(style="Primary.TButton" if mode == "scan" else "TButton")
        self.planner_mode_button.configure(style="Primary.TButton" if mode == "planner" else "TButton")
        self.author_mode_button.configure(style="Primary.TButton" if mode == "author" else "TButton")

    def build_scan_status_bar(self, parent: ttk.Frame) -> None:
        primary = ttk.Frame(parent)
        primary.pack(fill=X)
        self.status_label = ttk.Label(
            primary,
            textvariable=self.status_var,
            style="StatusInfo.TLabel",
            padding=(8, 5),
            anchor="w",
            justify="left",
        )
        self.status_label.pack(side=LEFT, fill=X, expand=True)
        ttk.Label(
            primary,
            textvariable=self.ocr_confidence_var,
            style="OCRConfidence.TLabel",
            padding=(8, 5),
        ).pack(side=RIGHT, padx=(6, 0))

        secondary = ttk.Frame(parent)
        secondary.pack(fill=X, pady=(5, 0))
        self.scan_recent_label = ttk.Label(
            secondary,
            textvariable=self.recent_scan_var,
            style="RecentScan.TLabel",
            padding=(9, 5),
            anchor="w",
            justify="left",
        )
        self.scan_recent_label.pack(side=LEFT, fill=X, expand=True)
        self.compact_view_controls = ttk.Frame(secondary)
        self.compact_view_controls.pack(side=RIGHT, padx=(6, 0))
        self.preview_view_button = ttk.Button(
            self.compact_view_controls,
            text="实时预览",
            style="Compact.TButton",
            command=lambda: self._set_compact_scan_view("preview"),
        )
        self.preview_view_button.pack(side=LEFT, padx=(0, 3))
        self.result_view_button = ttk.Button(
            self.compact_view_controls,
            text="识别结果",
            style="Primary.TButton",
            command=lambda: self._set_compact_scan_view("result"),
        )
        self.result_view_button.pack(side=LEFT)
        parent.bind("<Configure>", self._resize_scan_status, add="+")

    def _resize_scan_status(self, event) -> None:
        status_wrap = max(260, event.width - 160)
        reserved = 190 if self._layout_for_width(max(1, self.root.winfo_width())) == "compact" else 30
        recent_wrap = max(260, event.width - reserved)
        previous_status, previous_recent = self._last_status_wraplengths
        if abs(status_wrap - previous_status) < 8 and abs(recent_wrap - previous_recent) < 8:
            return
        self._last_status_wraplengths = (status_wrap, recent_wrap)
        self.status_label.configure(wraplength=status_wrap)
        self.scan_recent_label.configure(wraplength=recent_wrap)

    def _set_compact_scan_view(self, view: str) -> None:
        self.compact_scan_view = "preview" if view == "preview" else "result"
        if self.compact_scan_view == "result" and hasattr(self, "right_tabs"):
            selected = self.right_tabs.nametowidget(self.right_tabs.select())
            if selected is self.planner_tab:
                self.right_tabs.select(self.current_tab)
        self.layout_orientation = ""
        if hasattr(self, "root") and hasattr(self, "main_pane"):
            self._schedule_responsive_layout(immediate=True)

    def _update_compact_view_buttons(self) -> None:
        if not hasattr(self, "preview_view_button"):
            return
        self.preview_view_button.configure(
            style="Primary.TButton" if self.compact_scan_view == "preview" else "Compact.TButton"
        )
        self.result_view_button.configure(
            style="Primary.TButton" if self.compact_scan_view == "result" else "Compact.TButton"
        )

    @staticmethod
    def _create_paned_window(parent, *, orient: str, background: str | None = None) -> PanedWindow:
        return PanedWindow(
            parent,
            orient=orient,
            background=background or UI_COLORS["border"],
            borderwidth=0,
            sashwidth=8,
            sashpad=2,
            sashrelief="flat",
            showhandle=False,
            opaqueresize=True,
        )

    @staticmethod
    def _bind_popup_escape(window: Toplevel, close=None) -> None:
        """Give every child window the same predictable Escape-to-close behavior."""
        close_action = close or window.destroy

        def close_on_escape(_event=None) -> str:
            try:
                if window.winfo_exists():
                    close_action()
            except Exception:
                pass
            return "break"

        window.bind("<Escape>", close_on_escape)

    def _new_child_window(self) -> Toplevel:
        window = Toplevel(self.root)
        self._bind_popup_escape(window)
        if self.app_icon_photo is not None:
            try:
                window.iconphoto(True, self.app_icon_photo)
            except Exception:
                pass
        return window

    def _configure_styles(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        c = UI_COLORS
        family = self._select_ui_font_family()
        base_font = (family, 9)
        small_font = (family, 8)
        semibold = (family, 9, "bold")
        section_font = (family, 10, "bold")
        timer_font = (family, 16, "bold")
        self.ui_font = base_font
        self.ui_font_small = small_font
        self.ui_font_semibold = semibold
        self.ui_font_section = section_font
        self._configure_named_fonts(family)

        style.configure(".", font=base_font, foreground=c["ink"])
        style.configure("TFrame", background=c["surface"])
        style.configure("App.TFrame", background=c["app_bg"])
        style.configure(
            "Panel.TFrame",
            background=c["surface"],
            bordercolor=c["border"],
            lightcolor=c["border"],
            darkcolor=c["border"],
            relief="solid",
            borderwidth=1,
        )
        style.configure("Toolbar.TFrame", background=c["surface_alt"])
        style.configure(
            "StatusBar.TFrame",
            background=c["surface"],
            bordercolor=c["border"],
            lightcolor=c["border"],
            darkcolor=c["border"],
            relief="solid",
            borderwidth=1,
        )
        style.configure("TLabel", background=c["surface"], foreground=c["ink"], font=base_font)
        style.configure("Muted.TLabel", background=c["surface"], foreground=c["muted"], font=small_font)
        style.configure("Section.TLabel", background=c["surface"], foreground=c["ink"], font=section_font)
        style.configure("Field.TLabel", background=c["surface"], foreground=c["ink_blue"], font=semibold)
        style.configure("Meta.TLabel", background=c["surface_alt"], foreground=c["muted"], font=small_font)
        style.configure(
            "AuthorMessage.TLabel",
            background=c["surface_alt"],
            foreground=c["ink_blue"],
            font=section_font,
        )
        style.configure("Status.TLabel", background=c["accent_soft"], foreground=c["ink_blue"], font=semibold)
        style.configure("StatusInfo.TLabel", background=c["accent_soft"], foreground=c["ink_blue"], font=semibold)
        style.configure("StatusSuccess.TLabel", background=c["success_soft"], foreground=c["success_text"], font=semibold)
        style.configure("StatusWarning.TLabel", background=c["warning_soft"], foreground=c["warning_text"], font=semibold)
        style.configure("StatusDanger.TLabel", background=c["danger_soft"], foreground=c["danger_text"], font=semibold)
        style.configure("Mode.TLabel", background=c["accent_soft"], foreground=c["accent"], font=semibold)
        style.configure("Success.TLabel", background=c["success_soft"], foreground=c["success_text"], font=semibold)
        style.configure("Warning.TLabel", background=c["warning_soft"], foreground=c["warning_text"], font=semibold)
        style.configure("Danger.TLabel", background=c["danger_soft"], foreground=c["danger_text"], font=semibold)
        style.configure("InfoBanner.TLabel", background=c["accent_soft"], foreground=c["ink_blue"], font=semibold)
        style.configure("OCRConfidence.TLabel", background=c["surface"], foreground=c["ink_blue"], font=semibold)
        style.configure(
            "RecentScan.TLabel",
            background=c["accent"],
            foreground="#FFFFFF",
            font=section_font,
            bordercolor=c["action"],
            lightcolor=c["action"],
            darkcolor=c["action"],
            relief="solid",
            borderwidth=1,
        )
        cycle_styles = {
            "Info": (c["accent_soft"], c["action"], c["ink_blue"]),
            "Success": (c["success_soft"], c["success"], c["success_text"]),
            "Warning": (c["warning_soft"], c["warning"], c["warning_text"]),
        }
        for name, (background, border, foreground) in cycle_styles.items():
            style.configure(
                f"BatchCycle{name}.TFrame",
                background=background,
                bordercolor=border,
                lightcolor=border,
                darkcolor=border,
                relief="solid",
                borderwidth=1,
            )
            style.configure(
                f"BatchCycle{name}Title.TLabel",
                background=background,
                foreground=foreground,
                font=semibold,
            )
            style.configure(
                f"BatchCycle{name}Value.TLabel",
                background=background,
                foreground=foreground,
                font=timer_font,
            )
            style.configure(
                f"BatchCycle{name}Hint.TLabel",
                background=background,
                foreground=foreground,
                font=small_font,
            )
        style.configure("TCheckbutton", background=c["surface"], foreground=c["ink"], font=base_font)
        style.map(
            "TCheckbutton",
            background=[("active", c["surface"]), ("disabled", c["surface"])],
            foreground=[("disabled", c["disabled"])],
            indicatorcolor=[("selected", c["action"]), ("disabled", c["border"])],
        )

        style.configure(
            "TLabelframe",
            background=c["surface"],
            bordercolor=c["border_blue"],
            lightcolor=c["border_blue"],
            darkcolor=c["border_blue"],
            relief="solid",
            borderwidth=1,
        )
        style.configure("TLabelframe.Label", background=c["surface"], foreground=c["ink_blue"], font=section_font)

        style.configure(
            "TButton",
            background=c["surface"],
            foreground=c["ink_blue"],
            bordercolor=c["border_blue"],
            lightcolor=c["border_blue"],
            darkcolor=c["border_blue"],
            padding=(8, 4),
            relief="solid",
            borderwidth=1,
            font=semibold,
        )
        style.configure("Compact.TButton", padding=(4, 1), font=small_font)
        style.map(
            "TButton",
            background=[("pressed", c["selected"]), ("active", c["accent_soft"]), ("disabled", c["surface_alt"])],
            foreground=[("disabled", c["disabled"])],
            bordercolor=[("focus", c["action"]), ("active", c["action"]), ("disabled", c["border"])],
        )
        style.configure("Primary.TButton", background=c["accent"], foreground="#FFFFFF", bordercolor=c["accent"], padding=(8, 4))
        style.map(
            "Primary.TButton",
            background=[("pressed", c["ink_blue"]), ("active", c["accent_hover"]), ("disabled", "#93A4C7")],
            foreground=[("disabled", "#F8FAFC")],
            bordercolor=[("focus", c["action"]), ("disabled", "#93A4C7")],
        )
        style.configure("Teal.TButton", background=c["teal"], foreground="#FFFFFF", bordercolor=c["teal"], padding=(8, 4))
        style.map(
            "Teal.TButton",
            background=[("pressed", c["accent"]), ("active", c["action_hover"]), ("disabled", "#9DB7E9")],
            foreground=[("disabled", "#F8FAFC")],
            bordercolor=[("focus", c["accent"]), ("disabled", "#9DB7E9")],
        )
        style.configure("Danger.TButton", background=c["surface"], foreground=c["danger_text"], bordercolor="#FECACA")
        style.map(
            "Danger.TButton",
            background=[("active", c["danger_soft"]), ("pressed", "#FEE2E2"), ("disabled", c["surface_alt"])],
            foreground=[("disabled", c["disabled"])],
            bordercolor=[("focus", c["danger"]), ("disabled", c["border"])],
        )

        style.configure(
            "TEntry",
            fieldbackground=c["surface"],
            foreground=c["ink"],
            bordercolor=c["border"],
            lightcolor=c["border"],
            darkcolor=c["border"],
            padding=(8, 6),
            font=base_font,
        )
        style.map(
            "TEntry",
            fieldbackground=[("disabled", c["surface_alt"]), ("readonly", c["surface_alt"])],
            foreground=[("disabled", c["disabled"])],
            bordercolor=[("focus", c["action"]), ("invalid", c["danger"]), ("disabled", c["border"])],
            lightcolor=[("focus", c["action"])],
            darkcolor=[("focus", c["action"])],
        )
        style.configure(
            "TCombobox",
            fieldbackground=c["surface"],
            background=c["surface"],
            foreground=c["ink"],
            bordercolor=c["border"],
            lightcolor=c["border"],
            darkcolor=c["border"],
            padding=(7, 5),
            font=base_font,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", c["surface"]), ("disabled", c["surface_alt"])],
            foreground=[("disabled", c["disabled"])],
            bordercolor=[("focus", c["action"]), ("disabled", c["border"])],
            arrowcolor=[("disabled", c["disabled"]), ("readonly", c["ink_blue"])],
        )
        style.configure("TNotebook", background=c["surface"], borderwidth=0, tabmargins=(0, 0, 0, 0))
        style.configure("TNotebook.Tab", background=c["surface_alt"], foreground=c["muted"], padding=(15, 8), font=semibold)
        style.map(
            "TNotebook.Tab",
            background=[("selected", c["accent_soft"]), ("active", c["accent_soft"])],
            foreground=[("selected", c["accent"]), ("active", c["ink_blue"])],
        )
        style.configure(
            "Treeview",
            background=c["surface"],
            fieldbackground=c["surface"],
            foreground=c["ink"],
            rowheight=29,
            bordercolor=c["border"],
            lightcolor=c["border"],
            darkcolor=c["border"],
            font=base_font,
        )
        style.configure("Treeview.Heading", background=c["accent_soft"], foreground=c["ink_blue"], font=semibold, padding=(7, 7))
        style.map(
            "Treeview",
            background=[("selected", c["selected"])],
            foreground=[("selected", c["ink_blue"])],
            bordercolor=[("focus", c["action"])],
        )
        style.configure("Vertical.TScrollbar", background=c["border"], troughcolor=c["surface_alt"], bordercolor=c["surface_alt"], arrowcolor=c["muted"])
        style.configure("Horizontal.TScrollbar", background=c["border"], troughcolor=c["surface_alt"], bordercolor=c["surface_alt"], arrowcolor=c["muted"])
        style.configure("Blue.Horizontal.TProgressbar", background=c["action"], troughcolor=c["accent_soft"], bordercolor=c["accent_soft"])

    @staticmethod
    def _status_style_for_text(text: str) -> str:
        normalized = text.strip().lower()
        if any(word in normalized for word in ("失败", "错误", "异常", "无效")):
            return "StatusDanger.TLabel"
        if any(word in normalized for word in ("缺料", "待核对", "需核对", "请先", "等待", "正在", "尚未")):
            return "StatusWarning.TLabel"
        if any(word in normalized for word in ("已保存", "已完成", "已连接", "已载入", "已撤销", "成功", "准备就绪")):
            return "StatusSuccess.TLabel"
        return "StatusInfo.TLabel"

    def _update_status_appearance(self, *_args) -> None:
        if hasattr(self, "status_label"):
            self.status_label.configure(style=self._status_style_for_text(self.status_var.get()))

    def _update_plan_status_appearance(self, *_args) -> None:
        if hasattr(self, "plan_status_label"):
            self.plan_status_label.configure(style=self._status_style_for_text(self.plan_status_var.get()))

    def _select_ui_font_family(self) -> str:
        """Choose one CJK-capable family so Latin and Chinese glyphs share a visual system."""
        candidates = (
            "Microsoft YaHei UI",
            "Microsoft YaHei",
            "Noto Sans CJK SC",
            "Source Han Sans SC",
            "SimHei",
            "Arial Unicode MS",
            "Segoe UI",
        )
        try:
            installed = set(tkfont.families(self.root))
        except Exception:
            installed = set()
        return next((name for name in candidates if name in installed), candidates[-1])

    def _configure_named_fonts(self, family: str) -> None:
        """Keep native Tk widgets on the same family as ttk widgets."""
        sizes = {
            "TkDefaultFont": 9,
            "TkTextFont": 9,
            "TkMenuFont": 9,
            "TkHeadingFont": 9,
            "TkCaptionFont": 9,
            "TkSmallCaptionFont": 8,
            "TkIconFont": 9,
            "TkTooltipFont": 8,
        }
        for name, size in sizes.items():
            try:
                tkfont.nametofont(name, root=self.root).configure(family=family, size=size)
            except Exception:
                continue

    def _schedule_responsive_layout(self, event=None, *, immediate: bool = False) -> None:
        if event is not None and event.widget is not self.root:
            return
        if self.window_suspended:
            return
        if self.layout_after_id is not None:
            try:
                self.root.after_cancel(self.layout_after_id)
            except Exception:
                pass
        self.layout_after_id = self.root.after(0 if immediate else 40, self._apply_responsive_layout)

    def _on_root_unmap(self, event=None) -> None:
        if event is not None and event.widget is not self.root:
            return
        self.window_suspended = True
        if self.layout_after_id is not None:
            try:
                self.root.after_cancel(self.layout_after_id)
            except Exception:
                pass
            self.layout_after_id = None
        if self.preview_after_id is not None:
            try:
                self.root.after_cancel(self.preview_after_id)
            except Exception:
                pass
            self.preview_after_id = None

    def _on_root_map(self, event=None) -> None:
        if event is not None and event.widget is not self.root:
            return
        self.window_suspended = False
        self._schedule_responsive_layout(immediate=True)
        if self._embedded_preview_visible():
            self._schedule_preview_redraw()

    def _embedded_preview_visible(self) -> bool:
        if self.window_suspended or self.workspace_mode_var.get() != "扫描素材":
            return False
        if self.layout_orientation == "compact" and self.compact_scan_view != "preview":
            return False
        return True

    def _apply_responsive_layout(self) -> None:
        self.layout_after_id = None
        width = max(1, self.root.winfo_width())
        height = max(1, self.root.winfo_height())
        desired = self._layout_for_width(width)
        density = "tight" if desired == "compact" and height < 780 else "normal"
        workspace_label = self.workspace_mode_var.get()
        mode = (
            "planner"
            if workspace_label == "孵蛋规划"
            else "inventory"
            if workspace_label == "素材库存"
            else "author"
            if workspace_label == "作者的话"
            else "scan"
        )
        if (
            desired == self.layout_orientation
            and mode == self.applied_workspace_mode
            and density == self.applied_layout_density
        ):
            return

        if mode != "scan":
            self.scan_status_frame.pack_forget()
            self.scan_controls_panel.pack_forget()
        else:
            if not self.scan_status_frame.winfo_manager():
                self.scan_status_frame.pack(fill=X, padx=12, pady=(6, 4), before=self.main_pane)
            if not self.scan_controls_panel.winfo_manager():
                self.scan_controls_panel.pack(fill=X, padx=12, pady=(0, 4), before=self.main_pane)

        for panel in (self.left_panel, self.right_panel):
            try:
                self.main_pane.forget(panel)
            except Exception:
                pass
        if mode != "scan":
            self.main_pane.configure(orient="horizontal")
            self.main_pane.add(self.right_panel, minsize=520, stretch="always")
            self.compact_view_controls.pack_forget()
        elif desired == "split":
            self.main_pane.configure(orient="horizontal")
            self.main_pane.add(self.left_panel, minsize=320, stretch="always")
            self.main_pane.add(self.right_panel, minsize=480, stretch="always")
            self.compact_view_controls.pack_forget()
        else:
            self.main_pane.configure(orient="horizontal")
            panel = self.left_panel if self.compact_scan_view == "preview" else self.right_panel
            self.main_pane.add(panel, minsize=300, stretch="always")
            if not self.compact_view_controls.winfo_manager():
                self.compact_view_controls.pack(side=RIGHT, padx=(6, 0))
            self._update_compact_view_buttons()
        self._apply_current_result_density(desired == "compact", density == "tight")
        self.layout_orientation = desired
        self.applied_workspace_mode = mode
        self.applied_layout_density = density
        self._update_workspace_buttons(mode)
        if mode == "scan":
            self.root.after_idle(lambda orientation=desired: self._place_initial_main_sash(orientation))
            if self._embedded_preview_visible():
                self.root.after_idle(self._redraw_preview)

    def _place_initial_main_sash(self, orientation: str) -> None:
        if orientation != self.layout_orientation:
            return
        try:
            if orientation != "split" or len(self.main_pane.panes()) < 2:
                return
            available = max(800, self.main_pane.winfo_width())
            position = min(max(320, round(available * 0.42)), max(320, available - 480))
            self.main_pane.sash_place(0, position, 0)
        except Exception:
            return

    def _adjust_preview_height(self, amount: int) -> None:
        """Keyboard/button alternative to dragging the wide-layout divider."""
        if self.layout_orientation == "split":
            try:
                x, y = self.main_pane.sash_coord(0)
                self.main_pane.sash_place(0, x + amount, y)
            except Exception:
                pass
        self._schedule_preview_redraw()

    @staticmethod
    def _layout_for_width(width: int) -> str:
        return "split" if width >= 980 else "compact"

    def _resize_left_content(self, event) -> None:
        wraplength = max(240, event.width - 34)
        if abs(wraplength - self._last_left_wraplength) < 8:
            return
        self._last_left_wraplength = wraplength
        for widget_name in ("capture_tip",):
            widget = getattr(self, widget_name, None)
            if widget is not None:
                widget.configure(wraplength=wraplength)

    def _resize_scan_controls(self, event) -> None:
        wraplength = max(300, event.width - 42)
        narrow = event.width < 760
        if self._batch_layout_narrow != narrow:
            self._apply_batch_responsive_layout(narrow)
        if abs(wraplength - self._last_scan_wraplength) < 8:
            return
        self._last_scan_wraplength = wraplength
        if hasattr(self, "batch_help_label"):
            self.batch_help_label.configure(wraplength=wraplength)

    def _resize_right_content(self, event) -> None:
        wraplength = max(300, event.width - 42)
        if abs(wraplength - self._last_right_wraplength) < 8:
            return
        self._last_right_wraplength = wraplength
        if hasattr(self, "target_info_label"):
            self.target_info_label.configure(wraplength=max(180, round(event.width * 0.38)))
        for widget_name in ("plan_status_label", "plan_summary_label", "plan_purchase_label"):
            widget = getattr(self, widget_name, None)
            if widget is not None:
                widget.configure(wraplength=wraplength)

    def _apply_current_result_density(self, compact: bool, tight: bool = False) -> None:
        helper = getattr(self, "current_form_help_label", None)
        if helper is not None:
            if compact:
                helper.grid_remove()
            else:
                helper.grid()
        raw_box = getattr(self, "raw_text_box", None)
        if raw_box is not None:
            raw_box.configure(height=4 if compact else 5)
        header = getattr(self, "current_form_header", None)
        form = getattr(self, "current_form", None)
        actions = getattr(self, "current_actions", None)
        if header is None or form is None or actions is None:
            return
        if tight:
            if not header.winfo_manager():
                if form.winfo_manager():
                    header.pack(fill=X, pady=(0, 4), before=form)
                else:
                    header.pack(fill=X, pady=(0, 4), before=actions)
            if self.current_form_expanded:
                if not form.winfo_manager():
                    form.pack(fill=X, before=actions)
            else:
                form.pack_forget()
            self.current_form_toggle_button.configure(
                text="收起编辑字段" if self.current_form_expanded else "展开编辑字段"
            )
        else:
            header.pack_forget()
            if not form.winfo_manager():
                form.pack(fill=X, before=actions)

    def toggle_current_form(self) -> None:
        self.current_form_expanded = not self.current_form_expanded
        tight = self.layout_orientation == "compact" and max(1, self.root.winfo_height()) < 780
        self._apply_current_result_density(self.layout_orientation == "compact", tight)

    def _schedule_preview_redraw(self, _event=None) -> None:
        if self.current_image is None or not self._embedded_preview_visible():
            return
        if self.preview_after_id is not None:
            try:
                self.root.after_cancel(self.preview_after_id)
            except Exception:
                pass
        self.preview_after_id = self.root.after(60, self._redraw_preview)

    def _redraw_preview(self) -> None:
        self.preview_after_id = None
        if not self._embedded_preview_visible():
            return
        if self.roi:
            self.draw_roi()
        else:
            self.show_preview()

    def build_scan_controls(self, parent: ttk.Frame) -> None:
        self.source_frame = ttk.LabelFrame(parent, text="画面来源", padding=(8, 6))
        self.source_frame.pack(fill=X, pady=(0, 6))
        source_header = ttk.Frame(self.source_frame)
        source_header.pack(fill=X)
        ttk.Label(
            source_header,
            textvariable=self.source_summary_var,
            style="Field.TLabel",
            anchor="w",
        ).pack(side=LEFT, fill=X, expand=True)
        self.source_toggle_button = ttk.Button(
            source_header,
            text="收起",
            style="Compact.TButton",
            command=self.toggle_source_controls,
        )
        self.source_toggle_button.pack(side=RIGHT, padx=(8, 0))

        self.source_details = ttk.Frame(self.source_frame)
        self.source_details.pack(fill=X, pady=(5, 0))
        ttk.Button(self.source_details, text="刷新窗口", command=self.refresh_windows).grid(row=0, column=0, padx=3, pady=3)
        self.window_combo = ttk.Combobox(self.source_details, state="readonly", width=43)
        self.window_combo.grid(row=0, column=1, columnspan=2, sticky="ew", padx=3, pady=3)
        ttk.Button(self.source_details, text="连接实时预览", command=self.capture_selected_window).grid(row=0, column=3, padx=3, pady=3)
        ttk.Button(self.source_details, text="加载截图", command=self.load_image).grid(row=1, column=0, padx=3, pady=3)
        ttk.Button(self.source_details, text="读取剪贴板", command=self.load_clipboard).grid(row=1, column=1, padx=3, pady=3)
        ttk.Button(self.source_details, text="默认左侧信息区", command=self.set_default_roi).grid(row=1, column=2, padx=3, pady=3)
        ttk.Button(self.source_details, text="清除框选", command=self.clear_roi).grid(row=1, column=3, padx=3, pady=3)
        self.source_details.columnconfigure(1, weight=1)
        self.source_details.columnconfigure(2, weight=1)

        batch = ttk.LabelFrame(parent, text="OCR 连续扫描", padding=(8, 6))
        self.batch_frame = batch
        batch.pack(fill=X)
        self.batch_page_label = ttk.Label(batch, text="起始箱", style="Field.TLabel")
        self.batch_page_entry = ttk.Entry(batch, textvariable=self.batch_page_var, width=6)
        self.batch_slot_label = ttk.Label(batch, text="起始格", style="Field.TLabel")
        self.batch_slot_entry = ttk.Entry(batch, textvariable=self.batch_slot_var, width=6)
        self.batch_count_label = ttk.Label(batch, text="每箱格数", style="Field.TLabel")
        self.batch_count_entry = ttk.Entry(batch, textvariable=self.batch_slots_per_page_var, width=6)
        self.batch_delay_label = ttk.Label(batch, text="切换等待", style="Field.TLabel")
        self.batch_delay_spinbox = ttk.Spinbox(
            batch,
            textvariable=self.batch_delay_var,
            from_=1.5,
            to=8.0,
            increment=0.5,
            width=5,
        )
        self.batch_seconds_label = ttk.Label(batch, text="秒", style="Muted.TLabel")
        self.batch_load_label = ttk.Label(batch, text="OCR 负载", style="Field.TLabel")
        self.ocr_performance_combo = ttk.Combobox(
            batch,
            textvariable=self.ocr_performance_var,
            values=("省资源", "平衡", "快速"),
            state="readonly",
            width=7,
        )
        self.ocr_performance_combo.bind("<<ComboboxSelected>>", self._on_ocr_performance_changed)
        self.batch_start_button = ttk.Button(batch, text="开始连续扫描", style="Primary.TButton", command=self.start_batch_scan)
        self.batch_stop_button = ttk.Button(batch, text="停止", style="Danger.TButton", command=self.stop_batch_scan, state="disabled")
        self.batch_identify_button = ttk.Button(batch, text="识别当前精灵", command=self.force_scan_current_slot)
        self.batch_account_label = ttk.Label(batch, text="当前账号", style="Field.TLabel")
        self.batch_account_combo = ttk.Combobox(
            batch,
            textvariable=self.account_var,
            values=("主账号",),
            state="normal",
            width=12,
        )
        self.batch_add_account_button = ttk.Button(
            batch,
            text="+",
            width=3,
            style="Compact.TButton",
            command=self.open_add_account_dialog,
        )
        self.batch_parameters_button = ttk.Button(
            batch,
            text="收起参数",
            style="Compact.TButton",
            command=self.toggle_batch_parameters,
        )
        self.batch_help_label = ttk.Label(
            batch,
            style="Muted.TLabel",
            text="首次画面稳定后自动 OCR；按回车保存。保存后的下一格为空时，可在录入节奏卡按 Space 跳过；到点强制 OCR，未切换时按 F8 重新计时。",
            wraplength=455,
            justify="left",
        )
        self.batch_parameter_widgets = (
            self.batch_page_label,
            self.batch_page_entry,
            self.batch_slot_label,
            self.batch_slot_entry,
            self.batch_count_label,
            self.batch_count_entry,
            self.batch_delay_label,
            self.batch_delay_spinbox,
            self.batch_seconds_label,
            self.batch_load_label,
            self.ocr_performance_combo,
            self.batch_help_label,
        )
        self.batch_parameters_compact = False
        self._apply_batch_responsive_layout(False)
        parent.bind("<Configure>", self._resize_scan_controls, add="+")

    def _apply_batch_responsive_layout(self, narrow: bool) -> None:
        """Reflow OCR controls instead of clipping them in narrow windows."""
        batch = getattr(self, "batch_frame", None)
        if batch is None:
            return
        self._batch_layout_narrow = bool(narrow)
        for column in range(11):
            batch.columnconfigure(column, weight=0)
        common = {"padx": 2, "pady": 2}
        if narrow:
            placements = (
                (self.batch_page_label, 0, 0, 1, ""),
                (self.batch_page_entry, 0, 1, 1, ""),
                (self.batch_slot_label, 0, 2, 1, ""),
                (self.batch_slot_entry, 0, 3, 1, ""),
                (self.batch_count_label, 0, 4, 1, ""),
                (self.batch_count_entry, 0, 5, 1, ""),
                (self.batch_delay_label, 0, 6, 1, ""),
                (self.batch_delay_spinbox, 0, 7, 1, ""),
                (self.batch_seconds_label, 0, 8, 1, ""),
                (self.batch_load_label, 1, 0, 1, ""),
                (self.ocr_performance_combo, 1, 1, 1, ""),
                (self.batch_account_label, 1, 2, 1, ""),
                (self.batch_account_combo, 1, 3, 3, "ew"),
                (self.batch_add_account_button, 1, 6, 1, ""),
                (self.batch_parameters_button, 1, 8, 1, "e"),
                (self.batch_start_button, 2, 0, 2, "ew"),
                (self.batch_stop_button, 2, 2, 1, "ew"),
                (self.batch_identify_button, 2, 3, 6, "ew"),
                (self.batch_help_label, 3, 0, 9, "w"),
            )
            batch.columnconfigure(5, weight=1)
            help_padding = (4, 0)
        else:
            placements = (
                (self.batch_page_label, 0, 0, 1, ""),
                (self.batch_page_entry, 0, 1, 1, ""),
                (self.batch_slot_label, 0, 2, 1, ""),
                (self.batch_slot_entry, 0, 3, 1, ""),
                (self.batch_count_label, 0, 4, 1, ""),
                (self.batch_count_entry, 0, 5, 1, ""),
                (self.batch_delay_label, 0, 6, 1, ""),
                (self.batch_delay_spinbox, 0, 7, 1, ""),
                (self.batch_seconds_label, 0, 8, 1, ""),
                (self.batch_load_label, 0, 9, 1, ""),
                (self.ocr_performance_combo, 0, 10, 1, ""),
                (self.batch_start_button, 1, 0, 2, "ew"),
                (self.batch_stop_button, 1, 2, 1, "ew"),
                (self.batch_identify_button, 1, 3, 3, "ew"),
                (self.batch_account_label, 1, 6, 1, ""),
                (self.batch_account_combo, 1, 7, 2, "ew"),
                (self.batch_add_account_button, 1, 9, 1, ""),
                (self.batch_parameters_button, 1, 10, 1, "w"),
                (self.batch_help_label, 2, 0, 11, "w"),
            )
            batch.columnconfigure(5, weight=1)
            help_padding = (4, 0)
        for widget, row, column, columnspan, sticky in placements:
            widget.grid_configure(
                row=row,
                column=column,
                columnspan=columnspan,
                sticky=sticky,
                **common,
            )
        self.batch_help_label.grid_configure(pady=help_padding)
        if self.batch_parameters_compact:
            for widget in self.batch_parameter_widgets:
                widget.grid_remove()

    def toggle_batch_parameters(self) -> None:
        self._set_batch_parameters_compact(not self.batch_parameters_compact)

    def _set_batch_parameters_compact(self, compact: bool) -> None:
        self.batch_parameters_compact = bool(compact)
        for widget in getattr(self, "batch_parameter_widgets", ()):
            if self.batch_parameters_compact:
                widget.grid_remove()
            else:
                widget.grid()
        if hasattr(self, "batch_parameters_button"):
            self.batch_parameters_button.configure(text="展开参数" if compact else "收起参数")

    def toggle_source_controls(self) -> None:
        self._set_source_collapsed(not self.source_collapsed)

    def _set_source_collapsed(self, collapsed: bool) -> None:
        self.source_collapsed = bool(collapsed)
        if not hasattr(self, "source_details"):
            return
        if self.source_collapsed:
            self.source_details.pack_forget()
            self.source_toggle_button.configure(text="展开")
        else:
            self.source_details.pack(fill=X, pady=(5, 0))
            self.source_toggle_button.configure(text="收起")

    def build_capture_panel(self, parent: ttk.Frame) -> None:
        preview_area = ttk.Frame(parent)
        preview_area.pack(fill=BOTH, expand=True)

        preview_header = ttk.Frame(preview_area)
        ttk.Label(preview_header, text="实时预览 · 双击或弹出后放大框选", style="Field.TLabel").pack(side=LEFT)
        ttk.Button(
            preview_header,
            text="弹出预览",
            style="Compact.TButton",
            command=self.open_preview_zoom,
        ).pack(side=RIGHT, padx=(6, 0))
        ttk.Button(
            preview_header,
            text="+",
            width=3,
            style="Compact.TButton",
            command=lambda: self._adjust_preview_height(60),
        ).pack(side=RIGHT, padx=(2, 0))
        ttk.Button(
            preview_header,
            text="−",
            width=3,
            style="Compact.TButton",
            command=lambda: self._adjust_preview_height(-60),
        ).pack(side=RIGHT)
        preview = ttk.LabelFrame(preview_area, labelwidget=preview_header, padding=6)
        preview.pack(fill=BOTH, expand=True)
        self.canvas = Canvas(preview, background=UI_COLORS["preview"], highlightthickness=0)
        self.canvas.pack(fill=BOTH, expand=True)
        self.canvas.bind("<ButtonPress-1>", self.start_roi)
        self.canvas.bind("<B1-Motion>", self.drag_roi)
        self.canvas.bind("<ButtonRelease-1>", self.finish_roi)
        self.canvas.bind("<Double-Button-1>", self.open_preview_zoom)
        self.canvas.bind("<Configure>", self._schedule_preview_redraw, add="+")

    def build_right_panel(self, parent: ttk.Frame) -> None:
        tabs = ttk.Notebook(parent)
        tabs.pack(fill=BOTH, expand=True)
        self.right_tabs = tabs

        current_tab = ttk.Frame(tabs, padding=8)
        self.current_tab = current_tab
        inventory_tab = ttk.Frame(tabs, padding=8)
        planner_tab = ttk.Frame(tabs, padding=8)
        self.inventory_tab = inventory_tab
        self.planner_tab = planner_tab
        tabs.add(current_tab, text="识别当前")
        tabs.add(inventory_tab, text="素材库存")
        tabs.add(planner_tab, text="孵蛋规划")
        self.build_current_tab(current_tab)
        self.build_inventory_tab(inventory_tab)
        self.build_planner_tab(planner_tab)
        tabs.bind("<<NotebookTabChanged>>", self._on_right_tab_changed, add="+")

        self.author_page = ttk.Frame(parent, style="Panel.TFrame", padding=8)
        self.build_author_tab(self.author_page)

    def build_author_tab(self, parent: ttk.Frame) -> None:
        strip = ttk.Frame(parent, style="Toolbar.TFrame", padding=(14, 10))
        strip.pack(fill=X, anchor="n")
        strip.columnconfigure(0, weight=1)

        ttk.Label(
            strip,
            text="制作不易，请作者喝杯咖啡\n量力而行，有问题请反馈。",
            style="AuthorMessage.TLabel",
            justify="left",
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=(2, 18))

        def payment_button(
            column: int,
            title: str,
            asset_name: str,
            photo_attr: str,
            button_attr: str,
        ) -> None:
            asset_path = BASE_DIR / "assets" / asset_name
            try:
                with Image.open(asset_path) as source:
                    image = source.convert("RGB")
                    image.thumbnail((96, 120), Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(image)
                setattr(self, photo_attr, photo)
                button = ttk.Button(
                    strip,
                    text=title,
                    image=photo,
                    compound="top",
                    style="Compact.TButton",
                    command=lambda name=asset_name, label=title: self.open_donation_qr(name, label),
                )
                button.grid(row=0, column=column, sticky="e", padx=(0, 8) if column == 1 else (0, 2))
                setattr(self, button_attr, button)
            except (FileNotFoundError, OSError):
                ttk.Label(
                    strip,
                    text=f"{title}缺失",
                    style="Warning.TLabel",
                    anchor="center",
                ).grid(row=0, column=column, sticky="e", padx=(0, 8) if column == 1 else (0, 2))

        payment_button(1, "微信码", "donation-wechat.png", "author_wechat_photo", "author_wechat_button")
        payment_button(2, "支付宝码", "donation-alipay.jpg", "author_alipay_photo", "author_alipay_button")

    def open_donation_qr(self, asset_name: str, title: str) -> None:
        asset_path = BASE_DIR / "assets" / asset_name
        try:
            with Image.open(asset_path) as source:
                image = source.convert("RGB")
                max_height = max(420, min(720, self.root.winfo_screenheight() - 160))
                image.thumbnail((560, max_height), Image.Resampling.LANCZOS)
        except (FileNotFoundError, OSError):
            messagebox.showerror("收款码缺失", "收款码资源未找到，请重新下载完整发布包。")
            return

        window = self._new_child_window()
        window.title(f"{title}收款码")
        window.resizable(False, False)
        photo = ImageTk.PhotoImage(image)
        window.payment_photo = photo
        ttk.Label(window, image=photo, anchor="center").pack(padx=12, pady=(12, 8))
        ttk.Button(window, text="关闭", command=window.destroy).pack(pady=(8, 12))
        self._bind_popup_escape(window)

    def build_current_tab(self, parent: ttk.Frame) -> None:
        self.current_form_header = ttk.Frame(parent, style="Toolbar.TFrame", padding=(8, 5))
        ttk.Label(
            self.current_form_header,
            text="识别字段已收起 · 摘要、保存状态和 OCR 置信度保持可见",
            style="Field.TLabel",
        ).pack(side=LEFT, fill=X, expand=True)
        self.current_form_toggle_button = ttk.Button(
            self.current_form_header,
            text="展开编辑字段",
            style="Compact.TButton",
            command=self.toggle_current_form,
        )
        self.current_form_toggle_button.pack(side=RIGHT, padx=(8, 0))

        form = ttk.LabelFrame(parent, text="当前识别结果", padding=(8, 6))
        self.current_form = form
        form.pack(fill=X)

        field_padx = (3, 4)
        field_pady = 2
        ttk.Label(form, text="账号/角色", style="Field.TLabel").grid(row=0, column=0, sticky="e", padx=field_padx, pady=field_pady)
        self.account_combo = ttk.Combobox(form, textvariable=self.account_var, width=14, state="normal")
        self.account_combo.grid(row=0, column=1, sticky="w", padx=field_padx, pady=field_pady)
        ttk.Label(form, text="仓库页", style="Field.TLabel").grid(row=0, column=2, sticky="e", padx=field_padx, pady=field_pady)
        ttk.Entry(form, textvariable=self.page_var, width=6).grid(row=0, column=3, sticky="w", padx=field_padx, pady=field_pady)
        ttk.Label(form, text="格子", style="Field.TLabel").grid(row=0, column=4, sticky="e", padx=field_padx, pady=field_pady)
        ttk.Entry(form, textvariable=self.slot_var, width=6).grid(row=0, column=5, sticky="w", padx=field_padx, pady=field_pady)

        ttk.Label(form, text="精灵名字", style="Field.TLabel").grid(row=1, column=0, sticky="e", padx=field_padx, pady=field_pady)
        self.current_species_entry = ttk.Entry(form, textvariable=self.species_var, width=20)
        self.current_species_entry.grid(row=1, column=1, columnspan=2, sticky="ew", padx=field_padx, pady=field_pady)
        ttk.Label(form, text="性别", style="Field.TLabel").grid(row=1, column=3, sticky="e", padx=field_padx, pady=field_pady)
        ttk.Combobox(
            form,
            textvariable=self.gender_var,
            values=("F", "M", "N"),
            state="readonly",
            width=6,
        ).grid(row=1, column=4, columnspan=2, sticky="w", padx=field_padx, pady=field_pady)

        ttk.Label(form, text="个体值", style="Field.TLabel").grid(row=2, column=0, sticky="e", padx=field_padx, pady=field_pady)
        ttk.Entry(form, textvariable=self.iv_var, width=20).grid(row=2, column=1, columnspan=2, sticky="ew", padx=field_padx, pady=field_pady)
        ttk.Label(form, text="素材类别", style="Field.TLabel").grid(row=2, column=3, sticky="e", padx=field_padx, pady=field_pady)
        self.material_alpha_combo = ttk.Combobox(
            form,
            textvariable=self.alpha_var,
            values=("普通", "头目"),
            state="readonly",
            width=7,
        )
        self.material_alpha_combo.grid(row=2, column=4, columnspan=2, sticky="w", padx=field_padx, pady=field_pady)
        self.material_alpha_combo.bind("<<ComboboxSelected>>", self._on_material_alpha_changed)
        ttk.Label(form, text="性格", style="Field.TLabel").grid(row=3, column=0, sticky="e", padx=field_padx, pady=field_pady)
        self.current_nature_entry = ttk.Entry(form, textvariable=self.nature_var, width=20)
        self.current_nature_entry.grid(row=3, column=1, columnspan=2, sticky="ew", padx=field_padx, pady=field_pady)
        ttk.Checkbutton(
            form,
            text="梦特潜力已解锁",
            variable=self.hidden_ability_var,
        ).grid(row=3, column=3, columnspan=3, sticky="w", padx=field_padx, pady=field_pady)
        ttk.Label(form, text="当前特性", style="Field.TLabel").grid(row=4, column=0, sticky="e", padx=field_padx, pady=field_pady)
        self.current_ability_entry = ttk.Entry(form, textvariable=self.ability_var, width=20)
        self.current_ability_entry.grid(row=4, column=1, columnspan=2, sticky="ew", padx=field_padx, pady=field_pady)
        ttk.Label(form, text="技能", style="Field.TLabel").grid(row=4, column=3, sticky="e", padx=field_padx, pady=field_pady)
        self.current_moves_entry = ttk.Entry(form, textvariable=self.moves_var, width=20)
        self.current_moves_entry.grid(row=4, column=4, columnspan=2, sticky="ew", padx=field_padx, pady=field_pady)
        self.current_form_help_label = ttk.Label(
            form,
            text="F=母，M=公，N=无性别；蛋组会根据名字自动填写。",
            style="Muted.TLabel",
        )
        self.current_form_help_label.grid(
            row=5, column=0, columnspan=6, sticky="w", padx=3, pady=(2, 0)
        )
        form.columnconfigure(1, weight=2)
        form.columnconfigure(2, weight=1)
        form.columnconfigure(4, weight=1)
        form.columnconfigure(5, weight=1)
        self._install_inventory_autocomplete()

        actions = ttk.Frame(parent)
        self.current_actions = actions
        actions.pack(fill=X, pady=6)
        ttk.Button(actions, text="识别当前截图", style="Primary.TButton", command=self.ocr_current).pack(side=LEFT, padx=(0, 6))
        self.save_monster_button = ttk.Button(actions, text="保存/更新并标记已核对", style="Teal.TButton", command=self.save_current_monster)
        self.save_monster_button.pack(side=LEFT, padx=(0, 6))
        ttk.Button(actions, text="清空结果", command=self.clear_current).pack(side=LEFT)
        self.ocr_confidence_label = ttk.Label(
            actions,
            textvariable=self.ocr_confidence_var,
            style="OCRConfidence.TLabel",
        )
        self.ocr_confidence_label.pack(side=RIGHT, padx=(8, 2))

        self.raw_text = ttk.LabelFrame(parent, text="识别摘要", padding=6)
        self.raw_text.pack(fill=X)
        summary_body = ttk.Frame(self.raw_text)
        summary_body.pack(fill=X)
        summary_body.columnconfigure(0, weight=3)
        summary_body.columnconfigure(1, weight=2, minsize=220)
        self.raw_text_box = __import__("tkinter").Text(
            summary_body,
            height=4,
            wrap="word",
            background=UI_COLORS["surface"],
            foreground=UI_COLORS["ink"],
            insertbackground=UI_COLORS["accent"],
            relief="flat",
            borderwidth=0,
            highlightthickness=1,
            highlightbackground=UI_COLORS["border"],
            highlightcolor=UI_COLORS["accent"],
            padx=9,
            pady=7,
            font=self.ui_font,
        )
        self.raw_text_box.grid(row=0, column=0, sticky="nsew", padx=(0, 6))

        self.batch_cycle_panel = ttk.Frame(summary_body, style="BatchCycleInfo.TFrame", padding=(10, 8))
        self.batch_cycle_panel.grid(row=0, column=1, sticky="nsew")
        self.batch_cycle_title_label = ttk.Label(
            self.batch_cycle_panel,
            textvariable=self.batch_cycle_title_var,
            style="BatchCycleInfoTitle.TLabel",
        )
        self.batch_cycle_title_label.pack(anchor="w")
        self.batch_cycle_value_label = ttk.Label(
            self.batch_cycle_panel,
            textvariable=self.batch_cycle_value_var,
            style="BatchCycleInfoValue.TLabel",
        )
        self.batch_cycle_value_label.pack(anchor="w", pady=(2, 1))
        self.batch_cycle_hint_label = ttk.Label(
            self.batch_cycle_panel,
            textvariable=self.batch_cycle_hint_var,
            style="BatchCycleInfoHint.TLabel",
            justify="left",
            wraplength=210,
        )
        self.batch_cycle_hint_label.pack(anchor="w", fill=X)
        self.batch_retry_button = ttk.Button(
            self.batch_cycle_panel,
            text="重新开始倒计时（F8）",
            style="Compact.TButton",
            command=self.restart_batch_countdown,
            state="disabled",
        )
        self.batch_retry_button.pack(anchor="w", pady=(5, 0))
        self.batch_skip_button = ttk.Button(
            self.batch_cycle_panel,
            text="下一格为空：跳过（Space）",
            style="Compact.TButton",
            command=self.skip_batch_location,
            state="disabled",
        )
        self.batch_skip_button.pack(anchor="w", fill=X, pady=(5, 0))
        self.batch_skip_button.bind("<space>", self._handle_batch_space)

    def _install_inventory_autocomplete(self) -> None:
        def species_provider(query: str) -> list[str]:
            return [record.display_name for record in self.species_db.search(query, limit=30)]

        def nature_provider(query: str) -> list[str]:
            key = query.strip().lower()
            return [
                nature.chinese
                for nature in NATURES
                if key in nature.chinese or key in nature.english.lower()
            ]

        def ability_provider(query: str) -> list[str]:
            record = self.species_db.get(self.species_var.get(), fuzzy=True)
            if record is None:
                return []
            key = query.strip().lower()
            abilities = self.reference_db.abilities_for_species(record.id)
            values = [
                str(ability.get("canonical", ""))
                for ability_type in ("normal", "hidden")
                for ability in abilities.get(ability_type, ())
                if str(ability.get("canonical", ""))
            ]
            return [value for value in dict.fromkeys(values) if key in value.lower()]

        self.autocomplete_popups.extend(
            (
                AutocompletePopup(
                    self.root,
                    self.current_species_entry,
                    species_provider,
                    on_selected=self._on_current_species_autocomplete,
                ),
                AutocompletePopup(self.root, self.current_nature_entry, nature_provider),
                AutocompletePopup(self.root, self.current_ability_entry, ability_provider),
                AutocompletePopup(
                    self.root,
                    self.current_moves_entry,
                    lambda query: self.reference_db.search_moves(query, limit=30),
                    token_mode=True,
                ),
            )
        )

    def _on_current_species_autocomplete(self, species: str) -> None:
        record = self.species_db.get(species, fuzzy=False)
        if record is None:
            return
        self.species_var.set(record.display_name)
        self.groups_var.set(", ".join(record.egg_groups))
        if record.allowed_genders == ("N",):
            self.gender_var.set("N")

    def _on_material_alpha_changed(self, _event=None) -> None:
        if self.alpha_var.get() == "头目":
            # Captured Alphas normally expose HA potential. Bred exceptions can
            # still be corrected manually by clearing this checkbox afterwards.
            self.hidden_ability_var.set(True)

    def build_inventory_tab(self, parent: ttk.Frame) -> None:
        actions = ttk.LabelFrame(parent, text="库存检索与操作", padding=8)
        actions.pack(fill=X, pady=(0, 8))
        ttk.Label(actions, text="搜索", style="Field.TLabel").grid(row=0, column=0, sticky="e", padx=(0, 4), pady=(0, 6))
        filter_entry = ttk.Entry(actions, textvariable=self.inventory_filter_var, width=24)
        filter_entry.grid(row=0, column=1, sticky="ew", padx=(0, 10), pady=(0, 6))
        filter_entry.bind("<KeyRelease>", lambda _event: self.refresh_inventory_tree())
        ttk.Label(actions, text="核对状态", style="Field.TLabel").grid(row=0, column=2, sticky="e", padx=(0, 4), pady=(0, 6))
        status_filter = ttk.Combobox(
            actions,
            textvariable=self.inventory_status_filter_var,
            values=("全部状态", "已确认", "待核对"),
            state="readonly",
            width=9,
        )
        status_filter.grid(row=0, column=3, sticky="w", padx=(0, 10), pady=(0, 6))
        status_filter.bind("<<ComboboxSelected>>", lambda _event: self.refresh_inventory_tree())
        ttk.Label(actions, text="类别", style="Field.TLabel").grid(row=0, column=4, sticky="e", padx=(0, 4), pady=(0, 6))
        type_filter = ttk.Combobox(
            actions,
            textvariable=self.inventory_type_filter_var,
            values=("全部类别", "普通", "头目"),
            state="readonly",
            width=9,
        )
        type_filter.grid(row=0, column=5, sticky="w", pady=(0, 6))
        type_filter.bind("<<ComboboxSelected>>", lambda _event: self.refresh_inventory_tree())
        ttk.Label(actions, text="账号", style="Field.TLabel").grid(row=0, column=6, sticky="e", padx=(10, 4), pady=(0, 6))
        self.inventory_account_filter = ttk.Combobox(
            actions,
            textvariable=self.inventory_account_filter_var,
            values=("全部账号",),
            state="readonly",
            width=12,
        )
        self.inventory_account_filter.grid(row=0, column=7, sticky="w", pady=(0, 6))
        self.inventory_account_filter.bind("<<ComboboxSelected>>", lambda _event: self.refresh_inventory_tree())

        self.inventory_action_bar = ttk.Frame(actions)
        self.inventory_action_bar.grid(row=1, column=0, columnspan=8, sticky="ew")
        self.inventory_refresh_button = ttk.Button(
            self.inventory_action_bar, text="刷新列表", command=self.refresh_inventory_tree
        )
        self.inventory_select_all_button = ttk.Button(
            self.inventory_action_bar, text="全选当前结果", command=self.select_all_inventory
        )
        self.inventory_duplicate_button = ttk.Button(
            self.inventory_action_bar,
            text="重复检查",
            style="Primary.TButton",
            command=self.check_inventory_duplicates,
        )
        self.inventory_export_button = ttk.Button(
            self.inventory_action_bar, text="导出 JSON", command=self.export_inventory
        )
        self.inventory_import_button = ttk.Button(
            self.inventory_action_bar, text="导入 JSON", command=self.import_inventory
        )
        self.inventory_undo_button = ttk.Button(
            self.inventory_action_bar, text="撤销删除", command=self.undo_last_inventory_delete
        )
        self.inventory_summary_label = ttk.Label(
            self.inventory_action_bar,
            textvariable=self.inventory_summary_var,
            style="Muted.TLabel",
            justify="left",
        )
        self.inventory_selection_label = ttk.Label(
            self.inventory_action_bar,
            textvariable=self.inventory_selection_var,
            style="InfoBanner.TLabel",
            padding=(6, 3),
        )
        self.inventory_delete_button = ttk.Button(
            self.inventory_action_bar,
            text="删除选中",
            style="Danger.TButton",
            command=self.delete_selected_inventory,
        )
        self._inventory_action_layout = ""
        self._apply_inventory_action_layout("wide")
        self.inventory_action_bar.bind("<Configure>", self._resize_inventory_action_bar, add="+")
        actions.columnconfigure(1, weight=1)

        columns = ("account", "position", "status", "species", "gender", "alpha", "hidden", "nature", "ivs", "groups", "moves", "confidence")
        tree_frame = ttk.Frame(parent)
        tree_frame.pack(fill=BOTH, expand=True)
        self.inventory_tree = ttk.Treeview(tree_frame, columns=columns, show="headings", selectmode="extended", height=7)
        headings = {
            "account": "账号",
            "position": "位置（页-行,列）",
            "status": "状态",
            "species": "种类",
            "gender": "性别",
            "alpha": "类别",
            "hidden": "梦特",
            "nature": "性格",
            "ivs": "个体值",
            "groups": "蛋组",
            "moves": "技能",
            "confidence": "OCR",
        }
        widths = {
            "account": 82, "position": 108, "status": 56, "species": 95, "gender": 45,
            "alpha": 50, "hidden": 52, "nature": 58, "ivs": 115, "groups": 100, "moves": 150, "confidence": 48,
        }
        for column in columns:
            self.inventory_tree.heading(column, text=headings[column])
            self.inventory_tree.column(column, width=widths[column], anchor="center")
        vertical_scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.inventory_tree.yview)
        horizontal_scrollbar = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.inventory_tree.xview)
        self.inventory_tree.configure(
            yscrollcommand=vertical_scrollbar.set,
            xscrollcommand=horizontal_scrollbar.set,
        )
        self.inventory_tree.grid(row=0, column=0, sticky="nsew")
        vertical_scrollbar.grid(row=0, column=1, sticky="ns")
        horizontal_scrollbar.grid(row=1, column=0, sticky="ew")
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)
        self.inventory_tree.tag_configure("pending", background=UI_COLORS["warning_soft"], foreground=UI_COLORS["warning_text"])
        self.inventory_tree.tag_configure("verified", background=UI_COLORS["surface"], foreground=UI_COLORS["ink"])
        self.inventory_tree.bind("<Double-Button-1>", self.edit_inventory_selected)
        self.inventory_tree.bind("<<TreeviewSelect>>", self._on_inventory_selection_changed)
        self.inventory_tree.bind("<Control-a>", self.select_all_inventory)

    def _resize_inventory_action_bar(self, event=None) -> None:
        width = max(1, int(getattr(event, "width", self.inventory_action_bar.winfo_width())))
        mode = "narrow" if width < 720 else "medium" if width < 1120 else "wide"
        self._apply_inventory_action_layout(mode)

    def _apply_inventory_action_layout(self, mode: str) -> None:
        if mode == self._inventory_action_layout:
            return
        widgets = (
            self.inventory_refresh_button,
            self.inventory_select_all_button,
            self.inventory_duplicate_button,
            self.inventory_export_button,
            self.inventory_import_button,
            self.inventory_undo_button,
            self.inventory_summary_label,
            self.inventory_selection_label,
            self.inventory_delete_button,
        )
        for widget in widgets:
            widget.grid_forget()
        for column in range(9):
            self.inventory_action_bar.columnconfigure(column, weight=0)

        if mode == "wide":
            placements = tuple((widget, 0, index, 1, "w") for index, widget in enumerate(widgets[:6])) + (
                (self.inventory_summary_label, 0, 6, 1, "e"),
                (self.inventory_selection_label, 0, 7, 1, "e"),
                (self.inventory_delete_button, 0, 8, 1, "e"),
            )
            self.inventory_action_bar.columnconfigure(6, weight=1)
        elif mode == "medium":
            placements = tuple((widget, 0, index, 1, "w") for index, widget in enumerate(widgets[:6])) + (
                (self.inventory_summary_label, 1, 0, 4, "w"),
                (self.inventory_selection_label, 1, 4, 1, "e"),
                (self.inventory_delete_button, 1, 5, 1, "e"),
            )
            self.inventory_action_bar.columnconfigure(3, weight=1)
        else:
            placements = (
                (self.inventory_refresh_button, 0, 0, 1, "ew"),
                (self.inventory_select_all_button, 0, 1, 1, "ew"),
                (self.inventory_duplicate_button, 0, 2, 1, "ew"),
                (self.inventory_export_button, 1, 0, 1, "ew"),
                (self.inventory_import_button, 1, 1, 1, "ew"),
                (self.inventory_undo_button, 1, 2, 1, "ew"),
                (self.inventory_summary_label, 2, 0, 1, "w"),
                (self.inventory_selection_label, 2, 1, 1, "e"),
                (self.inventory_delete_button, 2, 2, 1, "e"),
            )
            for column in range(3):
                self.inventory_action_bar.columnconfigure(column, weight=1)

        for widget, row, column, columnspan, sticky in placements:
            widget.grid(
                row=row,
                column=column,
                columnspan=columnspan,
                sticky=sticky,
                padx=(0, 5),
                pady=2,
            )
        self._inventory_action_layout = mode

    def build_planner_tab(self, parent: ttk.Frame) -> None:
        form = ttk.LabelFrame(parent, text="目标与约束", padding=10)
        self.planner_form = form
        form.pack(fill=X)
        ttk.Label(form, text="目标精灵", style="Field.TLabel").grid(row=0, column=0, sticky="e", padx=4, pady=4)
        species_entry = ttk.Entry(form, textvariable=self.target_species_var, width=38)
        species_entry.grid(row=0, column=1, columnspan=4, sticky="ew", padx=4, pady=4)
        species_entry.bind("<KeyRelease>", self.search_target_species)
        species_entry.bind("<Return>", self.confirm_first_species_result)
        self.target_info_label = ttk.Label(
            form,
            textvariable=self.target_info_var,
            style="Muted.TLabel",
            wraplength=330,
            justify="left",
        )
        self.target_info_label.grid(row=0, column=5, columnspan=3, sticky="w", padx=4, pady=4)

        self.target_species_list = Listbox(
            form,
            height=5,
            exportselection=False,
            background=UI_COLORS["surface"],
            foreground=UI_COLORS["ink"],
            selectbackground=UI_COLORS["selected"],
            selectforeground=UI_COLORS["ink_blue"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=UI_COLORS["border"],
            highlightcolor=UI_COLORS["accent"],
            font=self.ui_font,
        )
        self.target_species_list.grid(row=1, column=1, columnspan=7, sticky="ew", padx=4, pady=(0, 4))
        self.target_species_list.bind("<Double-Button-1>", self.confirm_species_result)
        self.target_species_list.bind("<Return>", self.confirm_species_result)
        self.target_species_hint = ttk.Label(form, text="双击一项确认目标精灵", style="Warning.TLabel")
        self.target_species_hint.grid(
            row=1, column=0, sticky="ne", padx=4, pady=4
        )
        self.target_species_list.grid_remove()
        self.target_species_hint.grid_remove()

        ttk.Label(form, text="目标性格", style="Field.TLabel").grid(row=2, column=0, sticky="e", padx=4, pady=4)
        ttk.Entry(form, textvariable=self.target_nature_var, state="readonly", width=16).grid(
            row=2, column=1, sticky="ew", padx=4, pady=4
        )
        ttk.Button(form, text="选择性格…", command=self.open_nature_picker).grid(
            row=2, column=2, sticky="ew", padx=4, pady=4
        )
        ttk.Label(form, textvariable=self.target_nature_info_var, style="Muted.TLabel").grid(
            row=2, column=3, columnspan=5, sticky="w", padx=4, pady=4
        )

        ttk.Label(form, text="目标个体值", style="Field.TLabel").grid(row=3, column=0, sticky="e", padx=4, pady=4)
        iv_frame = ttk.Frame(form)
        iv_frame.grid(row=3, column=1, columnspan=7, sticky="w", padx=4, pady=4)
        for index, (stat, variable) in enumerate(zip(STATS, self.target_iv_vars)):
            cell = ttk.Frame(iv_frame)
            cell.grid(row=0, column=index, padx=(0, 8))
            ttk.Label(cell, text=stat, style="Field.TLabel").pack()
            entry = ttk.Entry(cell, textvariable=variable, width=5, justify="center")
            entry.pack()
            entry.bind(
                "<FocusOut>",
                lambda _event, target=variable: target.set(self._clamp_target_iv_text(target.get())),
            )
        ttk.Label(iv_frame, text="留空或 X = 任意", style="Muted.TLabel").grid(
            row=0, column=len(STATS), sticky="s", padx=(4, 0), pady=(0, 2)
        )

        ttk.Label(form, text="目标类别", style="Field.TLabel").grid(row=4, column=0, sticky="e", padx=4, pady=4)
        self.target_alpha_combo = ttk.Combobox(
            form,
            textvariable=self.target_alpha_var,
            values=("普通", "头目"),
            state="readonly",
            width=10,
        )
        self.target_alpha_combo.grid(row=4, column=1, sticky="w", padx=4, pady=4)
        self.target_alpha_combo.bind("<<ComboboxSelected>>", self._on_target_alpha_changed)
        ttk.Label(form, text="自动蛋组", style="Field.TLabel").grid(row=4, column=2, sticky="e", padx=4, pady=4)
        ttk.Label(form, textvariable=self.target_groups_var, style="InfoBanner.TLabel", padding=(7, 4)).grid(
            row=4, column=3, columnspan=3, sticky="w", padx=4, pady=4
        )
        ttk.Button(form, text="查看分布与遗传技能", command=self.open_species_reference).grid(
            row=4, column=6, columnspan=2, sticky="ew", padx=4, pady=4
        )

        special_rules = ttk.Frame(form, style="Toolbar.TFrame", padding=(8, 5))
        special_rules.grid(row=5, column=0, columnspan=8, sticky="ew", padx=4, pady=(4, 2))
        self.target_hidden_ability_check = ttk.Checkbutton(
            special_rules,
            text="成品保留梦特",
            variable=self.target_hidden_ability_var,
            command=self._on_target_hidden_ability_changed,
        )
        self.target_hidden_ability_check.pack(side=LEFT)
        ttk.Label(
            special_rules,
            textvariable=self.target_hidden_ability_hint_var,
            style="Muted.TLabel",
        ).pack(side=LEFT, padx=(8, 18))
        ttk.Button(
            special_rules,
            text="选择遗传技能…",
            command=self.open_egg_move_picker,
        ).pack(side=LEFT)
        ttk.Label(
            special_rules,
            textvariable=self.target_egg_moves_var,
            style="InfoBanner.TLabel",
            padding=(7, 3),
        ).pack(side=LEFT, padx=(8, 0), fill=X, expand=True)

        rules = ttk.LabelFrame(form, text="高级规划规则", padding=(8, 5))
        self.planner_rules_frame = rules
        rules.grid(row=6, column=0, columnspan=8, sticky="ew", padx=4, pady=(5, 2))
        ttk.Checkbutton(
            rules,
            text="全程锁性格（不变石链）",
            variable=self.target_lock_nature_var,
            command=self._on_nature_lock_changed,
        ).grid(row=0, column=0, sticky="w", padx=(0, 12), pady=3)
        self.target_gender_lock_check = ttk.Checkbutton(
            rules,
            text="锁定成品性别",
            variable=self.target_lock_gender_var,
            command=self._on_gender_lock_changed,
        )
        self.target_gender_lock_check.grid(row=0, column=1, sticky="w", padx=(0, 4), pady=3)
        self.target_gender_combo = ttk.Combobox(
            rules,
            textvariable=self.target_gender_var,
            values=("雌性", "雄性"),
            state="readonly",
            width=7,
        )
        self.target_gender_combo.grid(row=0, column=2, sticky="w", padx=(0, 12), pady=3)
        ttk.Checkbutton(
            rules,
            text="优先使用库存百变怪",
            variable=self.target_allow_ditto_var,
        ).grid(row=0, column=3, sticky="w", padx=(0, 12), pady=3)
        ttk.Label(rules, text="计算策略", style="Field.TLabel").grid(row=0, column=4, sticky="e", padx=(0, 4), pady=3)
        ttk.Combobox(
            rules,
            textvariable=self.target_strategy_var,
            values=("库存优先", "步骤优先"),
            state="readonly",
            width=10,
        ).grid(row=0, column=5, sticky="w", pady=3)
        self.target_allow_alpha_materials_check = ttk.Checkbutton(
            rules,
            text="普通目标允许使用头目素材",
            variable=self.target_allow_alpha_materials_var,
        )
        self.target_allow_alpha_materials_check.grid(
            row=1, column=0, columnspan=2, sticky="w", padx=(0, 12), pady=3
        )
        ttk.Label(
            rules,
            textvariable=self.target_alpha_material_hint_var,
            style="Muted.TLabel",
        ).grid(row=1, column=2, columnspan=4, sticky="w", pady=3)
        ttk.Checkbutton(
            rules,
            text="仅用百变怪转换母体",
            variable=self.target_convert_mother_with_ditto_var,
        ).grid(row=2, column=0, columnspan=2, sticky="w", padx=(0, 12), pady=3)
        ttk.Label(
            rules,
            text="无目标母体时，可用目标公体＋百变怪只转换一次；其余支线仍遵守上方百变怪开关。",
            style="Muted.TLabel",
        ).grid(row=2, column=2, columnspan=4, sticky="w", pady=3)
        ttk.Label(rules, text="中间性别", style="Field.TLabel").grid(
            row=3, column=0, sticky="w", padx=(0, 4), pady=3
        )
        self.target_intermediate_gender_combo = ttk.Combobox(
            rules,
            textvariable=self.target_intermediate_gender_strategy_var,
            values=("智能锁定", "全程锁定", "尽量不锁"),
            state="readonly",
            width=10,
        )
        self.target_intermediate_gender_combo.grid(row=3, column=1, sticky="w", padx=(0, 12), pady=3)
        self.target_intermediate_gender_combo.bind(
            "<<ComboboxSelected>>", self._on_intermediate_gender_strategy_changed
        )
        ttk.Label(
            rules,
            textvariable=self.target_gender_strategy_hint_var,
            style="Muted.TLabel",
        ).grid(row=3, column=2, columnspan=4, sticky="w", pady=3)
        ttk.Label(
            rules,
            text="库存优先＝少补素材；步骤优先＝少孵化次数。中间性别策略不会改变成品性别要求。",
            style="Muted.TLabel",
        ).grid(row=4, column=0, columnspan=6, sticky="w", pady=(0, 2))
        rules.columnconfigure(5, weight=1)
        self._on_target_alpha_changed()
        rules.grid_remove()
        form.columnconfigure(1, weight=1)
        form.columnconfigure(3, weight=1)
        form.columnconfigure(4, weight=1)

        self.planner_collapsed_bar = ttk.Frame(parent, style="Toolbar.TFrame", padding=(9, 6))
        ttk.Label(
            self.planner_collapsed_bar,
            textvariable=self.plan_compact_summary_var,
            style="InfoBanner.TLabel",
        ).pack(side=LEFT, fill=X, expand=True)
        self.planner_details_toggle_button = ttk.Button(
            self.planner_collapsed_bar,
            text="收起目标与说明",
            style="Compact.TButton",
            command=self._toggle_planner_details,
        )
        self.planner_details_toggle_button.pack(side=RIGHT, padx=(8, 0))
        self.planner_collapsed_bar.pack(fill=X, pady=(0, 6), before=self.planner_form)

        actions = ttk.Frame(parent)
        self.planner_actions = actions
        actions.pack(fill=X, pady=8)
        self.generate_plan_button = ttk.Button(actions, text="生成规划方案", style="Primary.TButton", command=self.generate_plan)
        self.generate_plan_button.pack(side=LEFT, padx=(0, 6))
        self.activate_plan_button = ttk.Button(actions, text="启用最佳方案", style="Teal.TButton", command=self.activate_best_plan)
        self.activate_plan_button.pack(side=LEFT, padx=(0, 6))
        self.complete_step_button = ttk.Button(actions, text="完成下一步并核销父母", style="Teal.TButton", command=self.complete_next_step)
        self.complete_step_button.pack(side=LEFT, padx=(0, 6))
        self.undo_step_button = ttk.Button(actions, text="撤销上一次核销", style="Danger.TButton", command=self.undo_last_step)
        self.undo_step_button.pack(side=LEFT)
        self.detach_plan_map_button = ttk.Button(
            actions,
            text="独立查看路线",
            command=self.open_detached_plan_map,
        )
        self.detach_plan_map_button.pack(side=RIGHT, padx=(6, 0))
        self.planner_rules_button = ttk.Button(
            actions,
            text="高级规则",
            command=self._toggle_planner_rules,
        )
        self.planner_rules_button.pack(side=RIGHT, padx=(6, 0))
        self.plan_progress = ttk.Progressbar(actions, mode="indeterminate", length=92, style="Blue.Horizontal.TProgressbar")
        self.plan_progress.pack(side=RIGHT, padx=(8, 2))
        self.plan_progress.pack_forget()
        self.next_step_gender_frame = ttk.Frame(parent, style="Toolbar.TFrame", padding=(8, 5))
        ttk.Label(self.next_step_gender_frame, text="下一步性别", style="Field.TLabel").pack(side=LEFT)
        self.next_step_gender_combo = ttk.Combobox(
            self.next_step_gender_frame,
            textvariable=self.next_step_gender_var,
            values=("自动", "不锁", "锁母", "锁公"),
            state="readonly",
            width=8,
        )
        self.next_step_gender_combo.pack(side=LEFT, padx=(7, 10))
        self.next_step_gender_combo.bind("<<ComboboxSelected>>", self._on_next_step_gender_override)
        ttk.Label(
            self.next_step_gender_frame,
            textvariable=self.next_step_gender_hint_var,
            style="Muted.TLabel",
        ).pack(side=LEFT, fill=X, expand=True)
        self.mark_step_progress_button = ttk.Button(
            self.next_step_gender_frame,
            text="标记孵化中",
            style="Compact.TButton",
            command=self._toggle_selected_plan_step_in_progress,
        )
        self.mark_step_progress_button.pack(side=RIGHT, padx=(8, 0))
        self.plan_status_label = ttk.Label(
            parent,
            textvariable=self.plan_status_var,
            style="StatusInfo.TLabel",
            wraplength=760,
            justify="left",
            padding=(9, 6),
        )
        self.plan_status_label.pack(fill=X, pady=(0, 6))
        route_summary = ttk.Frame(parent, style="Toolbar.TFrame", padding=(9, 7))
        self.plan_route_summary = route_summary
        route_summary.pack(fill=X, pady=(0, 6))
        self.plan_summary_label = ttk.Label(
            route_summary,
            textvariable=self.plan_summary_var,
            style="InfoBanner.TLabel",
            wraplength=760,
            justify="left",
        )
        self.plan_summary_label.pack(fill=X)
        self.plan_purchase_label = ttk.Label(
            route_summary,
            textvariable=self.plan_purchase_var,
            style="Muted.TLabel",
            wraplength=760,
            justify="left",
        )
        self.plan_purchase_label.pack(fill=X, pady=(5, 0))
        self.plan_exclusion_frame = ttk.Frame(route_summary, style="Toolbar.TFrame")
        ttk.Label(
            self.plan_exclusion_frame,
            textvariable=self.plan_exclusion_var,
            style="Warning.TLabel",
        ).pack(side=LEFT, fill=X, expand=True)
        self.undo_plan_exclusion_button = ttk.Button(
            self.plan_exclusion_frame,
            text="撤销上一次本次禁用",
            style="Compact.TButton",
            command=self.undo_last_plan_exclusion,
        )
        self.undo_plan_exclusion_button.pack(side=RIGHT, padx=(8, 0))
        self.clear_plan_exclusions_button = ttk.Button(
            self.plan_exclusion_frame,
            text="恢复全部并重算",
            style="Compact.TButton",
            command=self.clear_plan_exclusions,
        )
        self.clear_plan_exclusions_button.pack(side=RIGHT, padx=(8, 0))

        self.plan_map = BreedingMindMap(
            parent,
            colors=UI_COLORS,
            font_family=self.ui_font[0],
            on_step_activate=self._activate_plan_step_number,
            on_step_select=self._select_plan_step_number,
            on_step_progress_toggle=self._toggle_plan_step_in_progress,
            on_completed_sources_toggle=self._toggle_completed_step_sources,
            on_material_exclude=self.exclude_plan_material,
        )
        self.plan_map.pack(fill=BOTH, expand=True)
        self._update_plan_action_states()

    def _set_planner_details_collapsed(self, collapsed: bool) -> None:
        if not hasattr(self, "planner_form"):
            return
        self.planner_details_collapsed = bool(collapsed)
        self.planner_collapsed_bar.pack_forget()
        if collapsed:
            self.planner_form.pack_forget()
            self.plan_status_label.pack_forget()
            self.plan_route_summary.pack_forget()
            self.planner_collapsed_bar.pack(fill=X, pady=(0, 6), before=self.planner_actions)
            self.planner_details_toggle_button.configure(text="修改目标与查看说明")
        else:
            if not self.planner_form.winfo_manager():
                self.planner_form.pack(fill=X, before=self.planner_actions)
            if not self.plan_route_summary.winfo_manager():
                self.plan_route_summary.pack(fill=X, pady=(0, 6), before=self.plan_map)
            if not self.plan_status_label.winfo_manager():
                self.plan_status_label.pack(fill=X, pady=(0, 6), before=self.plan_route_summary)
            self.planner_collapsed_bar.pack(fill=X, pady=(0, 6), before=self.planner_form)
            self.planner_details_toggle_button.configure(text="收起目标与说明")

    def _toggle_planner_details(self) -> None:
        self._set_planner_details_collapsed(not self.planner_details_collapsed)

    def _update_plan_compact_summary(self) -> None:
        target = self.target_species_var.get().strip() or "未选择目标"
        iv_text = self.target_iv_var.get().upper()
        nature = self.target_nature_var.get().strip() or "任意性格"
        plan = self.active_plan or self.proposed_plan
        if plan and plan.steps:
            completed = sum(step.completed for step in plan.steps)
            ready = len(plan.ready_steps)
            state = f"已完成 {completed}/{len(plan.steps)} · 可并行执行 {ready} 个"
        else:
            state = "尚无可执行路线"
        self.plan_compact_summary_var.set(
            f"目标：{target} · {iv_text} · {nature} · {self.target_alpha_var.get()}｜{state}"
        )

    def open_detached_plan_map(self) -> None:
        existing = self.plan_map_window
        if existing is not None:
            try:
                if existing.winfo_exists():
                    existing.deiconify()
                    existing.lift()
                    existing.focus_force()
                    return
            except Exception:
                pass
        window = self._new_child_window()
        self.plan_map_window = window
        window.title("孵蛋路线思维导图")
        window.geometry("1400x900")
        window.minsize(820, 560)
        if self.app_icon_photo is not None:
            try:
                window.iconphoto(True, self.app_icon_photo)
            except Exception:
                pass
        detached = BreedingMindMap(
            window,
            colors=UI_COLORS,
            font_family=self.ui_font[0],
            on_step_activate=self._activate_plan_step_number,
            on_step_select=self._select_plan_step_number,
            on_step_progress_toggle=self._toggle_plan_step_in_progress,
            on_completed_sources_toggle=self._toggle_completed_step_sources,
            on_material_exclude=self.exclude_plan_material,
        )
        self.detached_plan_map = detached
        detached.pack(fill=BOTH, expand=True, padx=8, pady=8)
        detached.set_root(self.plan_map.root_node, "暂无可执行路线｜请先在主窗口生成规划")

        def close_window() -> None:
            self.detached_plan_map = None
            self.plan_map_window = None
            window.destroy()

        window.protocol("WM_DELETE_WINDOW", close_window)
        self._bind_popup_escape(window, close_window)
        try:
            window.state("zoomed")
        except Exception:
            pass

    def _toggle_planner_rules(self) -> None:
        if self.planner_details_collapsed:
            self._set_planner_details_collapsed(False)
        self.planner_rules_visible = not self.planner_rules_visible
        if self.planner_rules_visible:
            self.planner_rules_frame.grid()
            self.planner_rules_button.configure(text="收起规则")
        else:
            self.planner_rules_frame.grid_remove()
            self.planner_rules_button.configure(text="高级规则")

    def _set_planner_busy(self, busy: bool) -> None:
        self.plan_worker_busy = busy
        if not hasattr(self, "generate_plan_button"):
            return
        if busy:
            self.generate_plan_button.configure(state="disabled", text="正在计算…")
            self.plan_progress.pack(side=RIGHT, padx=(8, 2))
            self.plan_progress.start(12)
            self._update_plan_action_states()
        else:
            self.plan_progress.stop()
            self.plan_progress.pack_forget()
            self.generate_plan_button.configure(text="生成规划方案")
            self._update_plan_action_states()

    def _update_plan_action_states(self) -> None:
        if not hasattr(self, "generate_plan_button"):
            return
        self.generate_plan_button.configure(state="disabled" if self.plan_worker_busy else "normal")
        can_activate = bool(
            self.proposed_plan
            and self.proposed_plan.steps
            and not self.plan_worker_busy
        )
        self.activate_plan_button.configure(state="normal" if can_activate else "disabled")
        selected_step = self._selected_ready_step()
        can_complete = bool(selected_step and not self.plan_worker_busy)
        self.complete_step_button.configure(state="normal" if can_complete else "disabled")
        if selected_step is not None:
            parallel_count = len(self.active_plan.ready_steps) if self.active_plan else 0
            if selected_step.requires_purchase:
                button_text = f"确认已采购并完成步骤 {selected_step.number}"
            elif parallel_count > 1 or self.selected_plan_step_number:
                button_text = f"完成步骤 {selected_step.number} 并核销"
            else:
                button_text = "完成当前节点并核销父母"
            self.complete_step_button.configure(text=button_text)
        else:
            self.complete_step_button.configure(text="完成当前节点并核销父母")
        if hasattr(self, "next_step_gender_frame"):
            step = selected_step
            if step is None:
                self.next_step_gender_frame.pack_forget()
            else:
                override_labels = {"": "自动", "random": "不锁", "F": "锁母", "M": "锁公"}
                self.next_step_gender_var.set(override_labels.get(step.gender_override, "自动"))
                self.next_step_gender_hint_var.set(
                    f"当前：{step.gender_instruction}。仅覆盖这一节点；随机结果保存后会自动重算剩余路线。"
                )
                self.next_step_gender_combo.configure(state="readonly" if can_complete else "disabled")
                self.mark_step_progress_button.configure(
                    text="取消孵化中" if step.in_progress else "标记孵化中",
                    state="normal" if can_complete else "disabled",
                )
                if not self.next_step_gender_frame.winfo_manager():
                    before_widget = self.plan_map if self.planner_details_collapsed else self.plan_status_label
                    self.next_step_gender_frame.pack(fill=X, pady=(0, 6), before=before_widget)
        self._update_plan_compact_summary()
        if hasattr(self, "clear_plan_exclusions_button"):
            self.clear_plan_exclusions_button.configure(
                state="normal" if self.plan_excluded_ids and not self.plan_worker_busy else "disabled"
            )
        if hasattr(self, "undo_plan_exclusion_button"):
            self.undo_plan_exclusion_button.configure(
                state="normal"
                if getattr(self, "plan_exclusion_history", []) and not self.plan_worker_busy
                else "disabled"
            )

    def _selected_ready_step(self) -> ExecutionStep | None:
        plan = self.active_plan
        if plan is None:
            return None
        if self.selected_plan_step_number is not None:
            selected = next(
                (step for step in plan.steps if step.number == self.selected_plan_step_number),
                None,
            )
            if selected is not None and plan.is_step_ready(selected):
                return selected
        return plan.next_actionable_step

    def _select_plan_step_number(self, step_number: int) -> None:
        self.selected_plan_step_number = step_number
        self._update_plan_action_states()

    @staticmethod
    def _plan_step_progress_key(step: ExecutionStep) -> tuple[str, str]:
        return tuple(sorted((step.parent_a_id, step.parent_b_id)))

    def _capture_plan_progress_keys(self, plan: ExecutionPlan | None) -> set[tuple[str, str]]:
        if plan is None:
            return set()
        return {
            self._plan_step_progress_key(step)
            for step in plan.steps
            if step.in_progress and not step.completed
        }

    def _toggle_selected_plan_step_in_progress(self) -> None:
        step = self._selected_ready_step()
        if step is not None:
            self._toggle_plan_step_in_progress(step.number)

    def _toggle_plan_step_in_progress(self, step_number: int):
        plan = self.active_plan
        if plan is None:
            messagebox.showinfo("先启用方案", "请先启用最佳方案，再标记正在孵化的节点。")
            return "break"
        step = next((item for item in plan.steps if item.number == step_number), None)
        if step is None:
            return "break"
        if not plan.is_step_ready(step):
            messagebox.showwarning("尚不可执行", "只有当前可执行的并行节点才能标记为“孵化中”。")
            return "break"
        step.in_progress = not step.in_progress
        self.selected_plan_step_number = step.number
        save_active_plan(plan.to_dict())
        action_text = "标记为孵化中" if step.in_progress else "取消孵化中标记"
        self.status_var.set(
            f"步骤 {step.number} 已{action_text}。"
            "这只是备忘，不会核销素材或解锁上层。"
        )
        self.refresh_plan_status()
        return "break"

    def _toggle_completed_step_sources(self, step_number: int):
        plan = self.active_plan or self.proposed_plan
        if plan is None:
            return "break"
        step = next((item for item in plan.steps if item.number == step_number), None)
        if step is None or not step.completed:
            return "break"
        key = (plan.id, step_number)
        if key in self.expanded_completed_sources:
            self.expanded_completed_sources.remove(key)
        else:
            self.expanded_completed_sources.add(key)
        if self.current_candidates:
            self._render_plan_tree(self.current_candidates[0])
        return "break"

    @staticmethod
    def _species_option_text(record: SpeciesRecord) -> str:
        english = record.identifier.replace("-", " ").title()
        groups = " / ".join(record.egg_groups)
        return f"#{record.id:03d}  {record.display_name}  ({english})  ｜蛋组 {groups}"

    def search_target_species(self, _event=None) -> None:
        self.selected_target_species_id = None
        self.target_groups_var.set("待选择")
        query = self.target_species_var.get().strip().lstrip("#").strip()
        self.target_species_results = self.species_db.search(query, limit=30)
        self.target_species_list.delete(0, END)
        if not query:
            self.target_species_list.grid_remove()
            self.target_species_hint.grid_remove()
            self.target_info_var.set("输入图鉴编号或名字片段，再从下方结果中双击选择。")
            return
        self.target_species_list.grid()
        self.target_species_hint.grid()
        if not self.target_species_results:
            self.target_species_list.insert(END, "没有找到匹配的精灵")
            self.target_info_var.set("没有匹配结果；可尝试完整编号、简体中文名或英文名。")
            return
        for record in self.target_species_results:
            self.target_species_list.insert(END, self._species_option_text(record))
        self.target_species_list.selection_set(0)
        self.target_info_var.set(f"找到 {len(self.target_species_results)} 项；双击正确的精灵确认。")

    def confirm_first_species_result(self, _event=None) -> str:
        if self.target_species_results:
            self.target_species_list.selection_clear(0, END)
            self.target_species_list.selection_set(0)
            self.confirm_species_result()
        return "break"

    def confirm_species_result(self, _event=None) -> str:
        selection = self.target_species_list.curselection()
        if not selection or not self.target_species_results:
            return "break"
        index = int(selection[0])
        if 0 <= index < len(self.target_species_results):
            self._apply_target_species(self.target_species_results[index])
        return "break"

    def _apply_target_species(self, record: SpeciesRecord) -> SpeciesRecord:
        target_changed = self.selected_target_species_id != record.id
        if target_changed:
            self.selected_egg_moves.clear()
            self.target_egg_moves_var.set("不需要遗传技能")
        self.selected_target_species_id = record.id
        self.target_species_var.set(record.display_name)
        breeding_parent = self.species_db.breeding_parent(record)
        offspring = self.species_db.breeding_offspring(record)
        self._sync_plan_exclusion_scope(record)
        effective_groups = breeding_parent.egg_groups if breeding_parent else record.egg_groups
        self.target_groups_var.set(" / ".join(effective_groups))
        self.target_species_results = []
        self.target_species_list.delete(0, END)
        self.target_species_list.grid_remove()
        self.target_species_hint.grid_remove()
        forced_gender = self.species_db.required_evolution_gender(record)
        selected_gender, lock_gender = self._resolved_target_gender_controls(
            record,
            forced_gender,
            target_changed,
            self.target_gender_var.get(),
            bool(self.target_lock_gender_var.get()),
        )
        self.target_gender_var.set(selected_gender)
        self.target_lock_gender_var.set(lock_gender)
        if forced_gender:
            forced_label = "雄性" if forced_gender == "M" else "雌性"
            ratio = f"最终进化要求{forced_label}，已自动锁定成品性别"
        elif record.female_percent is None:
            ratio = "无性别，可与同进化线无性别精灵或百变怪孵化"
        elif record.female_percent == 0:
            ratio = "仅雄性"
        elif record.female_percent == 100:
            ratio = "仅雌性"
        else:
            ratio = f"雌性比例 {record.female_percent:g}%"
        self._sync_gender_controls(record)
        baby = "｜幼体物种" if record.is_baby else ""
        hatch = f"｜孵蛋目标 {offspring.display_name}" if offspring else ""
        reuse = (
            f"｜中间代先养成 {breeding_parent.display_name}"
            if offspring and breeding_parent and offspring.id != breeding_parent.id
            else ""
        )
        incense = "｜需要熏香（暂不生成严格路线）" if self.species_db.requires_incense_for_target(record) else ""
        location_count = len(self.reference_db.locations_for_species(record.id))
        egg_move_count = len(self.reference_db.egg_moves_for_species((offspring or record).id))
        hidden_names = self.reference_db.hidden_ability_names(record.id)
        self.target_hidden_ability_hint_var.set(
            f"对应梦特：{' / '.join(hidden_names)}" if hidden_names else "该物种没有独立梦特名称；仍可记录梦特潜力标记"
        )
        self.target_info_var.set(
            f"已选择 #{record.id} {record.display_name}｜蛋组 {' / '.join(effective_groups)}｜{ratio}{baby}{hatch}{reuse}{incense}｜"
            f"分布 {location_count} 条｜可遗传技能 {egg_move_count} 种"
        )
        return record

    def _on_target_hidden_ability_changed(self) -> None:
        record = self.species_db.by_id.get(self.selected_target_species_id) if self.selected_target_species_id else None
        hidden_names = self.reference_db.hidden_ability_names(record.id) if record else ()
        if self.target_hidden_ability_var.get():
            label = " / ".join(hidden_names) if hidden_names else "梦特潜力"
            self.target_hidden_ability_hint_var.set(f"严格保留：{label}；同进化线梦特父母会贯穿路线")
        else:
            self.target_hidden_ability_hint_var.set(
                f"不要求保留梦特潜力" + (f"（该物种梦特：{' / '.join(hidden_names)}）" if hidden_names else "")
            )

    def open_egg_move_picker(self) -> None:
        record = self.lookup_target_species(silent=False)
        if record is None:
            return
        offspring = self.species_db.breeding_offspring(record) or record
        egg_moves = self.reference_db.egg_moves_for_species(offspring.id)
        if not egg_moves:
            messagebox.showinfo("没有遗传技能资料", f"#{offspring.id} {offspring.display_name} 暂无内置遗传技能链。")
            return

        window = self._new_child_window()
        window.title(f"选择遗传技能｜{offspring.display_name}")
        window.geometry("860x560")
        window.minsize(680, 430)
        window.transient(self.root)
        ttk.Label(
            window,
            text="最多选择 4 个；右侧会显示工作簿中的可行传递链。若库存没有携带技能的同进化线素材，规划会列为交易行/前置制作缺料。",
            style="Muted.TLabel",
            padding=(10, 10, 10, 5),
        ).pack(fill=X)
        body = self._create_paned_window(window, orient="horizontal")
        body.pack(fill=BOTH, expand=True, padx=10, pady=6)
        move_frame = ttk.LabelFrame(body, text="可遗传技能", padding=6)
        route_frame = ttk.LabelFrame(body, text="遗传链明细", padding=6)
        body.add(move_frame, minsize=220, stretch="never")
        body.add(route_frame, minsize=380, stretch="always")
        move_list = Listbox(move_frame, selectmode="multiple", exportselection=False, font=self.ui_font)
        move_scroll = ttk.Scrollbar(move_frame, orient="vertical", command=move_list.yview)
        move_list.configure(yscrollcommand=move_scroll.set)
        move_list.pack(side=LEFT, fill=BOTH, expand=True)
        move_scroll.pack(side=RIGHT, fill=Y)
        move_names = sorted(egg_moves)
        for index, move in enumerate(move_names):
            move_list.insert(END, move)
            if move in self.selected_egg_moves:
                move_list.selection_set(index)
        route_text = __import__("tkinter").Text(
            route_frame,
            wrap="word",
            font=self.ui_font,
            padx=9,
            pady=8,
            relief="flat",
            highlightthickness=1,
            highlightbackground=UI_COLORS["border"],
        )
        route_text.pack(fill=BOTH, expand=True)

        def refresh_routes(_event=None) -> None:
            selected = [move_names[int(index)] for index in move_list.curselection()]
            route_text.delete("1.0", END)
            if not selected:
                route_text.insert("1.0", "选择一个或多个技能后，这里显示每条可行遗传链。")
                return
            lines: list[str] = []
            for move in selected:
                lines.append(f"【{move}】")
                lines.extend(f"  {index}. {route}" for index, route in enumerate(egg_moves.get(move, ()), 1))
                lines.append("")
            route_text.insert("1.0", "\n".join(lines).strip())

        def confirm() -> None:
            selected = [move_names[int(index)] for index in move_list.curselection()]
            if len(selected) > 4:
                messagebox.showwarning("技能过多", "一只精灵最多保留 4 个技能，请减少选择。")
                return
            self.selected_egg_moves = selected
            self.target_egg_moves_var.set("、".join(selected) if selected else "不需要遗传技能")
            window.destroy()

        move_list.bind("<<ListboxSelect>>", refresh_routes)
        refresh_routes()
        buttons = ttk.Frame(window, padding=(10, 4, 10, 10))
        buttons.pack(fill=X)
        ttk.Button(buttons, text="确认选择", style="Primary.TButton", command=confirm).pack(side=RIGHT, padx=4)
        ttk.Button(buttons, text="取消", command=window.destroy).pack(side=RIGHT, padx=4)

    def _sync_plan_exclusion_scope(self, record: SpeciesRecord) -> None:
        offspring = self.species_db.breeding_offspring(record)
        scope_id = offspring.id if offspring is not None else record.id
        if self.plan_exclusion_scope_id is None:
            self.plan_exclusion_scope_id = scope_id
        elif self.plan_exclusion_scope_id != scope_id:
            self.plan_exclusion_scope_id = scope_id
            self.plan_excluded_ids.clear()
            self.plan_exclusion_history = []
        inventory_ids = {monster.id for monster in self.inventory}
        self.plan_excluded_ids.intersection_update(inventory_ids)
        self.plan_exclusion_history = [
            material_id
            for material_id in getattr(self, "plan_exclusion_history", [])
            if material_id in self.plan_excluded_ids
        ]
        self._update_plan_exclusion_ui()

    def _update_plan_exclusion_ui(self) -> None:
        if not hasattr(self, "plan_exclusion_frame"):
            return
        excluded = [monster for monster in self.inventory if monster.id in self.plan_excluded_ids]
        if not excluded:
            self.plan_exclusion_var.set("本次规划没有排除库存素材。")
            self.plan_exclusion_frame.pack_forget()
            return
        preview = "、".join(monster.species for monster in excluded[:3])
        if len(excluded) > 3:
            preview += f" 等 {len(excluded)} 只"
        self.plan_exclusion_var.set(
            f"本次规划已保护 {len(excluded)} 只库存素材：{preview}（库存记录仍保留）"
        )
        if not self.plan_exclusion_frame.winfo_manager():
            self.plan_exclusion_frame.pack(fill=X, pady=(6, 0))

    def _active_plan_uses_material(self, material_id: str) -> bool:
        if self.active_plan is None or self.active_plan.completed:
            return False
        return any(
            not step.completed and material_id in {step.parent_a_id, step.parent_b_id}
            for step in self.active_plan.steps
        )

    def exclude_plan_material(self, material_id: str) -> str:
        if self.plan_worker_busy:
            self.plan_status_var.set("规划正在计算；完成后再禁用其他素材。")
            return "break"
        monster = next((item for item in self.inventory if item.id == material_id), None)
        if monster is None:
            self.plan_status_var.set("该素材已不在库存中，正在刷新规划。")
            self.generate_plan()
            return "break"
        if material_id in self.plan_excluded_ids:
            self.plan_status_var.set(f"{monster.species} 已在本次规划的保护列表中。")
            return "break"
        if self._active_plan_uses_material(material_id):
            if not messagebox.askyesno(
                "放弃当前执行路线？",
                f"{monster.species} 正被当前已启用路线使用。\n\n"
                "将它设为本次禁用会放弃当前未完成路线并重新规划；已经完成的核销不会恢复，"
                "本地库存记录不会因本次禁用而删除。是否继续？",
            ):
                return "break"
            self.active_plan = None
            save_active_plan(None)
        self.plan_excluded_ids.add(material_id)
        self.plan_exclusion_history.append(material_id)
        self.proposed_plan = None
        self._update_plan_exclusion_ui()
        self.plan_status_var.set(f"已保护 {monster.species}；正在从本次路线中排除并重新规划……")
        self.generate_plan()
        return "break"

    def undo_last_plan_exclusion(self) -> None:
        if self.plan_worker_busy:
            return
        while self.plan_exclusion_history:
            material_id = self.plan_exclusion_history.pop()
            if material_id not in self.plan_excluded_ids:
                continue
            self.plan_excluded_ids.remove(material_id)
            monster = next((item for item in self.inventory if item.id == material_id), None)
            label = monster.species if monster is not None else "最近禁用的素材"
            self.proposed_plan = None
            self._update_plan_exclusion_ui()
            self.plan_status_var.set(f"已撤销 {label} 的本次禁用；正在重新规划……")
            self.generate_plan()
            return
        self._update_plan_exclusion_ui()

    def clear_plan_exclusions(self) -> None:
        if self.plan_worker_busy or not self.plan_excluded_ids:
            return
        restored = len(self.plan_excluded_ids)
        self.plan_excluded_ids.clear()
        self.plan_exclusion_history.clear()
        self.proposed_plan = None
        self._update_plan_exclusion_ui()
        self.plan_status_var.set(f"已恢复 {restored} 只受保护素材，正在重新规划……")
        self.generate_plan()

    def _sync_gender_controls(self, record: SpeciesRecord | None = None) -> None:
        forced_gender = self.species_db.required_evolution_gender(record) if record is not None else ""
        selectable = record is None or record.allowed_genders == ("F", "M")
        self.target_gender_lock_check.configure(
            state="disabled" if forced_gender else ("normal" if selectable else "disabled")
        )
        if forced_gender:
            self.target_lock_gender_var.set(True)
            self.target_gender_var.set("雄性" if forced_gender == "M" else "雌性")
            self.target_gender_combo.configure(state="disabled")
            return
        if selectable and self.target_lock_gender_var.get():
            if self.target_gender_var.get() not in {"雌性", "雄性"}:
                self.target_gender_var.set("雌性")
            self.target_gender_combo.configure(state="readonly")
        else:
            self.target_gender_combo.configure(state="disabled")

    def _on_gender_lock_changed(self) -> None:
        record = self.species_db.by_id.get(self.selected_target_species_id) if self.selected_target_species_id else None
        self._sync_gender_controls(record)

    def _on_intermediate_gender_strategy_changed(self, _event=None) -> None:
        strategy = self.target_intermediate_gender_strategy_var.get()
        hints = {
            "智能锁定": "低 V 首支不锁；记录实际性别后，只锁配对所需的另一支。5V 与成品约束保持确定。",
            "全程锁定": "所有可选性别的中间子代都按规划指定，路线稳定，但性别费最高。",
            "尽量不锁": "中间代尽量随机；每次记录实际性别后重算，性别费最低，但路线变化更多。",
        }
        self.target_gender_strategy_hint_var.set(hints.get(strategy, hints["智能锁定"]))
        if self.selected_target_species_id and self.current_candidates and not self.plan_worker_busy:
            self.plan_status_var.set(f"已切换为{strategy}，正在重新规划候选路线……")
            self.root.after_idle(self.generate_plan)

    def _on_next_step_gender_override(self, _event=None) -> None:
        plan = self.active_plan
        step = self._selected_ready_step()
        if step is None:
            return
        mapping = {"自动": "", "不锁": "random", "锁母": "F", "锁公": "M"}
        requested = mapping.get(self.next_step_gender_var.get(), "")
        record = self.species_db.get(step.child.species, fuzzy=True)
        allowed = record.allowed_genders if record is not None else ("F", "M")
        if requested in {"F", "M"} and requested not in allowed:
            messagebox.showwarning("性别不可用", f"{step.child.species} 不能孵出所选性别。")
            self.next_step_gender_var.set("自动")
            return
        is_final = step.number == len(plan.steps)
        if is_final and plan.target_gender:
            if requested == "random" or (requested in {"F", "M"} and requested != plan.target_gender):
                messagebox.showwarning("成品性别约束", "最后一步必须满足已设置的成品性别，不能在此改为随机或相反性别。")
                self.next_step_gender_var.set("自动")
                return
        if allowed != ("F", "M") and requested == "random":
            messagebox.showinfo("固定性别", f"{step.child.species} 的性别固定，无需设置为随机。")
            self.next_step_gender_var.set("自动")
            return
        step.gender_override = requested
        if requested in {"F", "M"}:
            step.child.gender = requested
        else:
            step.child.gender = step.planned_gender
        save_active_plan(plan.to_dict())
        self.refresh_plan_status()

    def _on_target_alpha_changed(self, _event=None) -> None:
        if self.target_alpha_var.get() == "头目":
            self.target_allow_alpha_materials_check.configure(state="disabled")
            self.target_alpha_material_hint_var.set("头目目标必须使用头目素材，此选项不适用。")
            hidden_var = getattr(self, "target_hidden_ability_var", None)
            if hidden_var is not None:
                hidden_var.set(True)
            hidden_check = getattr(self, "target_hidden_ability_check", None)
            if hidden_check is not None:
                hidden_check.configure(state="disabled")
            if hidden_var is not None:
                self._on_target_hidden_ability_changed()
            return
        self.target_allow_alpha_materials_check.configure(state="normal")
        hidden_check = getattr(self, "target_hidden_ability_check", None)
        if hidden_check is not None:
            hidden_check.configure(state="normal")
        self.target_alpha_material_hint_var.set("关闭＝仅普通素材；开启＝普通与头目均可用，最终仍为普通。")
        if getattr(self, "target_hidden_ability_var", None) is not None:
            self._on_target_hidden_ability_changed()

    def _on_nature_lock_changed(self) -> None:
        selected = self.target_nature_var.get().strip()
        if not selected:
            self.target_nature_info_var.set("请先选择性格" if self.target_lock_nature_var.get() else "不指定性格")
            return
        if not self.target_lock_nature_var.get():
            self.target_nature_info_var.set(
                f"母体优先：仅从成品低一档起记录 {selected}；满 V 未中后逐级赌性格手，最后才保底购买"
            )
            return
        if is_neutral_nature(selected):
            self.target_nature_info_var.set("全程不变石链；五种无修正性格任意一种均可")
            return
        nature = find_nature(selected)
        effect = nature.effect if nature else selected
        self.target_nature_info_var.set(f"{effect}；沿性格支线全程使用不变石")

    @staticmethod
    def _resolved_target_gender_controls(
        record: SpeciesRecord,
        forced_gender: str,
        target_changed: bool,
        selected: str,
        lock_gender: bool,
    ) -> tuple[str, bool]:
        """Resolve the visible gender controls without erasing user intent.

        ``lookup_target_species`` revalidates the selected species whenever a
        plan is generated.  That validation must not reset an explicitly
        unchecked gender lock for an unchanged, ordinary dual-gender target.
        A newly selected target keeps the established female-lock default;
        genuinely gender-dependent forms remain mandatory.
        """
        if forced_gender in {"F", "M"}:
            return ("雌性" if forced_gender == "F" else "雄性"), True
        if record.allowed_genders == ("N",):
            return "任意", False
        if record.allowed_genders == ("M",):
            return "雄性", False
        if record.allowed_genders == ("F",):
            return "雌性", False
        if target_changed:
            return "雌性", True
        return (selected if selected in {"雌性", "雄性"} else "雌性"), bool(lock_gender)

    @staticmethod
    def _requested_target_gender(
        record: SpeciesRecord,
        lock_gender: bool,
        selected: str,
        forced_gender: str = "",
    ) -> str:
        if forced_gender in {"F", "M"}:
            return forced_gender
        if record.allowed_genders != ("F", "M") or not lock_gender:
            return ""
        return {"雄性": "M", "雌性": "F"}.get(selected, "F")

    @staticmethod
    def _requested_target_nature(selected: str, full_chain: bool) -> tuple[str, str]:
        return selected.strip(), "chain" if full_chain else "late"

    @staticmethod
    def _plan_material_scope_counts(
        inventory: list[Monster],
        family_names: set[str],
        egg_groups: set[str],
        allow_ditto: bool,
    ) -> tuple[int, int, int]:
        """Count relevant normal/alpha materials before category filtering."""
        normalized_family = {"".join(value.lower().split()) for value in family_names if value}
        normalized_groups = {"".join(value.lower().split()) for value in egg_groups if value}
        normal_count = 0
        alpha_count = 0
        alpha_ditto_count = 0
        for monster in inventory:
            if not monster.verified:
                continue
            species_key = "".join((monster.species or "").lower().split())
            is_ditto_material = species_key in {"百变怪", "ditto"}
            monster_groups = {"".join(value.lower().split()) for value in monster.egg_groups if value}
            if not (
                species_key in normalized_family
                or (allow_ditto and is_ditto_material)
                or bool(normalized_groups & monster_groups)
            ):
                continue
            if monster.is_alpha:
                alpha_count += 1
                alpha_ditto_count += int(is_ditto_material)
            else:
                normal_count += 1
        return normal_count, alpha_count, alpha_ditto_count

    def open_species_reference(self) -> None:
        record = self.lookup_target_species(silent=False)
        if record is None:
            return
        locations = self.reference_db.locations_for_species(record.id)
        egg_moves = self.reference_db.egg_moves_for_species(record.id)
        window = self._new_child_window()
        window.title(f"#{record.id} {record.display_name}｜分布与遗传技能")
        window.geometry("980x650")
        window.minsize(780, 520)
        window.transient(self.root)

        ttk.Label(
            window,
            text=f"#{record.id} {record.display_name}｜{len(locations)} 条分布记录｜{len(egg_moves)} 种可遗传技能",
            padding=10,
        ).pack(fill=X)
        tabs = ttk.Notebook(window)
        tabs.pack(fill=BOTH, expand=True, padx=10, pady=(0, 10))
        location_tab = ttk.Frame(tabs, padding=6)
        move_tab = ttk.Frame(tabs, padding=6)
        tabs.add(location_tab, text=f"出现地点（{len(locations)}）")
        tabs.add(move_tab, text=f"遗传技能（{len(egg_moves)}）")

        location_columns = ("region", "route", "encounter", "rarity", "notes", "held")
        location_tree = ttk.Treeview(location_tab, columns=location_columns, show="headings")
        location_headings = {
            "region": "地区", "route": "路线", "encounter": "出现方式",
            "rarity": "稀有度", "notes": "备注", "held": "可能携带",
        }
        location_widths = {"region": 60, "route": 130, "encounter": 105, "rarity": 80, "notes": 320, "held": 180}
        for column in location_columns:
            location_tree.heading(column, text=location_headings[column])
            location_tree.column(column, width=location_widths[column], anchor="w")
        for location in locations:
            location_tree.insert(
                "",
                END,
                values=(location.region, location.route, location.encounter, location.rarity, location.notes, location.held_items),
            )
        location_tree.pack(fill=BOTH, expand=True)

        move_columns = ("move", "chain")
        move_tree = ttk.Treeview(move_tab, columns=move_columns, show="headings")
        move_tree.heading("move", text="遗传技能")
        move_tree.heading("chain", text="可行遗传链路")
        move_tree.column("move", width=130, anchor="w")
        move_tree.column("chain", width=760, anchor="w")
        for move, routes in egg_moves.items():
            for route in routes:
                move_tree.insert("", END, values=(move, route))
        move_tree.pack(fill=BOTH, expand=True)

    def open_nature_picker(self) -> None:
        if self.nature_picker_window is not None and self.nature_picker_window.winfo_exists():
            self.nature_picker_window.lift()
            self.nature_picker_window.focus_force()
            return
        window = self._new_child_window()
        self.nature_picker_window = window
        window.title("选择目标性格")
        window.geometry("720x520")
        window.minsize(620, 400)
        window.transient(self.root)

        ttk.Label(
            window,
            text="输入中文或英文会立即筛选；双击或按 Enter 确认。5 种无修正性格合并为一项。",
            padding=(10, 10, 10, 4),
        ).pack(fill=X)
        search_frame = ttk.Frame(window, padding=(10, 2, 10, 2))
        search_frame.pack(fill=X)
        ttk.Label(search_frame, text="快速查找", style="Field.TLabel").pack(side=LEFT, padx=(0, 8))
        nature_query_var = StringVar()
        search_entry = ttk.Entry(search_frame, textvariable=nature_query_var)
        search_entry.pack(side=LEFT, fill=X, expand=True)
        ttk.Label(
            search_frame,
            text="例：输入“固”即可找到固执",
            style="Muted.TLabel",
        ).pack(side=LEFT, padx=(8, 0))
        columns = ("chinese", "english", "increased", "decreased", "effect")
        tree_frame = ttk.Frame(window)
        tree_frame.pack(fill=BOTH, expand=True, padx=10, pady=6)
        tree = ttk.Treeview(tree_frame, columns=columns, show="headings", selectmode="browse", height=18)
        headings = {
            "chinese": "中文性格",
            "english": "英文",
            "increased": "提升属性",
            "decreased": "降低属性",
            "effect": "说明",
        }
        widths = {"chinese": 95, "english": 105, "increased": 85, "decreased": 85, "effect": 220}
        for column in columns:
            tree.heading(column, text=headings[column])
            tree.column(column, width=widths[column], anchor="center")

        def insert_nature(nature) -> None:
            tree.insert(
                "",
                END,
                iid=nature.english.lower(),
                values=(
                    planner_nature_display_name(nature),
                    nature.english,
                    nature.increased or "—",
                    nature.decreased or "—",
                    nature.effect,
                ),
            )

        def populate(query: str = "") -> None:
            previous = tree.selection()[0] if tree.selection() else ""
            tree.delete(*tree.get_children())
            needle = "".join(query.strip().lower().split())
            if not needle or needle in "不指定noneany":
                tree.insert("", END, iid="__none__", values=("不指定", "—", "—", "—", "不要求遗传性格"))
            for nature in filter_planner_natures(query):
                insert_nature(nature)
            neutral_haystack = "无修正任一勤奋坦率认真害羞浮躁neutral"
            if not needle or needle in neutral_haystack:
                tree.insert(
                    "",
                    END,
                    iid="__neutral__",
                    values=(NEUTRAL_TARGET_NAME, "5 种合并", "—", "—", "勤奋/坦率/认真/害羞/浮躁任一即可"),
                )
            children = tree.get_children()
            if previous in children:
                selected = previous
            else:
                selected = children[0] if children else ""
            if selected:
                tree.selection_set(selected)
                tree.focus(selected)
                tree.see(selected)

        populate()
        nature_scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=nature_scrollbar.set)
        tree.pack(side=LEFT, fill=BOTH, expand=True)
        nature_scrollbar.pack(side=RIGHT, fill=Y)

        def close() -> None:
            self.nature_picker_window = None
            window.destroy()

        def confirm(_event=None) -> None:
            selected = tree.selection()
            if not selected:
                return
            key = selected[0]
            if key == "__none__":
                self.target_nature_var.set("")
                self.target_nature_info_var.set("不指定性格")
                self.target_lock_nature_var.set(False)
            elif key == "__neutral__":
                self.target_nature_var.set(NEUTRAL_TARGET_NAME)
                self._on_nature_lock_changed()
            else:
                nature = find_nature(key)
                if nature is None:
                    return
                self.target_nature_var.set(nature.chinese)
                self._on_nature_lock_changed()
            close()

        def focus_first_result(_event=None):
            children = tree.get_children()
            if children:
                tree.selection_set(children[0])
                tree.focus(children[0])
                tree.see(children[0])
                tree.focus_set()
            return "break"

        def confirm_from_search(_event=None):
            focus_first_result()
            return confirm()

        nature_query_var.trace_add("write", lambda *_args: populate(nature_query_var.get()))
        search_entry.bind("<Down>", focus_first_result)
        search_entry.bind("<Return>", confirm_from_search)

        tree.bind("<Double-Button-1>", confirm)
        tree.bind("<Return>", confirm)
        buttons = ttk.Frame(window, padding=(10, 4, 10, 10))
        buttons.pack(fill=X)
        ttk.Button(buttons, text="确认选择", style="Primary.TButton", command=confirm).pack(side=RIGHT, padx=4)
        ttk.Button(buttons, text="取消", command=close).pack(side=RIGHT, padx=4)
        window.protocol("WM_DELETE_WINDOW", close)
        self._bind_popup_escape(window, close)
        current = find_nature(self.target_nature_var.get())
        if is_neutral_nature(self.target_nature_var.get()):
            initial = "__neutral__"
        else:
            initial = current.english.lower() if current else "__none__"
        tree.selection_set(initial)
        tree.see(initial)
        tree.focus(initial)
        search_entry.focus_set()

    @staticmethod
    def _clamp_target_iv_text(value: str) -> str:
        raw = (value or "").strip()
        if not raw or raw.lower() in {"x", "任意", "-"}:
            return raw
        try:
            number = int(raw)
        except ValueError:
            return raw
        return str(max(0, min(31, number)))

    def _collect_target_iv_string(self) -> str | None:
        values: list[str] = []
        for stat, variable in zip(STATS, self.target_iv_vars):
            raw = self._clamp_target_iv_text(variable.get())
            variable.set(raw)
            if not raw or raw.lower() in {"x", "任意", "-"}:
                values.append("x")
                continue
            try:
                number = int(raw)
            except ValueError:
                messagebox.showwarning("目标个体值无效", f"{stat} 必须填写 0–31，或留空/X 表示任意。")
                return None
            values.append(str(number))
        result = "/".join(values)
        self.target_iv_var.set(result)
        return result

    def _enrich_inventory(self) -> bool:
        changed = False
        for monster in self.inventory:
            record = self.species_db.get(monster.species)
            if record is None:
                continue
            if monster.species != record.display_name:
                monster.species = record.display_name
                changed = True
            if not monster.egg_groups:
                monster.egg_groups = list(record.egg_groups)
                changed = True
            if not monster.gender and record.allowed_genders == ("N",):
                monster.gender = "N"
                changed = True
        return changed

    def _reconcile_active_plan(self) -> None:
        if self.active_plan is None:
            return
        inventory_ids = {monster.id for monster in self.inventory}
        changed = False
        for step in self.active_plan.steps:
            if not step.completed and step.child.id in inventory_ids:
                step.completed = True
                changed = True
        if changed:
            save_active_plan(self.active_plan.to_dict())

    def lookup_target_species(self, silent: bool = False) -> SpeciesRecord | None:
        query = self.target_species_var.get().strip().lstrip("#").strip()
        if not query:
            return None
        record = self.species_db.get_by_id(self.selected_target_species_id) if self.selected_target_species_id else None
        if record is None:
            record = self.species_db.get_by_id(query) if query.isdigit() else self.species_db.get(query)
        if record is None:
            matches = self.species_db.search(query, limit=30)
            if len(matches) == 1:
                record = matches[0]
        if record is None:
            self.target_info_var.set("目标精灵尚未确认；请从搜索结果中双击正确的精灵。")
            if not silent:
                messagebox.showwarning("尚未选择目标精灵", self.target_info_var.get())
            return None
        return self._apply_target_species(record)

    def _remember_account(self, value: str) -> str:
        account = value.strip() or "主账号"
        if account not in self.accounts:
            self.accounts.append(account)
            save_accounts(self.accounts)
        self.account_var.set(account)
        self.refresh_inventory_tree()
        return account

    def open_add_account_dialog(self) -> None:
        window = self._new_child_window()
        window.title("新建小号")
        window.geometry("360x150")
        window.resizable(False, False)
        window.transient(self.root)
        window.grab_set()
        body = ttk.Frame(window, padding=16)
        body.pack(fill=BOTH, expand=True)
        ttk.Label(body, text="账号/角色名称", style="Field.TLabel").pack(anchor="w")
        value_var = StringVar()
        entry = ttk.Entry(body, textvariable=value_var)
        entry.pack(fill=X, pady=(6, 12))

        def confirm(_event=None) -> None:
            value = value_var.get().strip()
            if not value:
                messagebox.showwarning("名称为空", "请输入小号或角色名称。", parent=window)
                entry.focus_set()
                return
            self._remember_account(value)
            self.status_var.set(f"已新建账号“{value}”；扫描与库存记录可按账号分别筛选。")
            window.destroy()

        buttons = ttk.Frame(body)
        buttons.pack(fill=X)
        ttk.Button(buttons, text="取消", command=window.destroy).pack(side=RIGHT, padx=(6, 0))
        ttk.Button(buttons, text="新建并切换", style="Primary.TButton", command=confirm).pack(side=RIGHT)
        entry.bind("<Return>", confirm)
        self._bind_popup_escape(window)
        entry.focus_set()

    def _ocr_profile_key(self) -> str:
        return {"省资源": "low", "快速": "fast"}.get(self.ocr_performance_var.get(), "balanced")

    def _ocr_poll_interval_ms(self) -> int:
        return {"low": 650, "balanced": 420, "fast": 300}[self._ocr_profile_key()]

    def _batch_poll_interval_ms(self) -> int:
        return {"low": 550, "balanced": 400, "fast": 300}[self._ocr_profile_key()]

    def _on_ocr_performance_changed(self, _event=None) -> None:
        if self.batch_running or self.batch_worker_busy:
            self.status_var.set("连续扫描正在运行；OCR 负载会在停止并重新开始扫描后生效。")
        else:
            self.ocr = None
            label = self.ocr_performance_var.get()
            self.status_var.set(
                f"OCR 负载已切换为“{label}”。识别模型与准确度不变，仅调整 CPU 线程和预览刷新频率。"
            )

    @staticmethod
    def _fingerprint(full_image: Image.Image, detail_image: Image.Image | None = None) -> bytes:
        detail = detail_image or full_image
        # Use the information panel rather than the full game window. Animated
        # backgrounds otherwise prevent the frame from ever being considered
        # stable. Within the panel, prefer the lower text rows so the Pokemon's
        # idle animation does not invalidate OCR while it is running.
        if detail.height >= 20:
            detail = detail.crop((0, round(detail.height * 0.38), detail.width, detail.height))
        return (
            detail.convert("L")
            .resize((64, 64), Image.Resampling.BILINEAR)
            .filter(ImageFilter.GaussianBlur(radius=0.8))
            .tobytes()
        )

    @staticmethod
    def _fingerprint_difference(left: bytes | None, right: bytes | None) -> float:
        if left is None or right is None or len(left) != len(right):
            return 255.0
        return sum(abs(a - b) for a, b in zip(left, right)) / max(1, len(left))

    def _crop_for_ocr(self, image: Image.Image) -> Image.Image:
        if self.roi:
            left, top, right, bottom = self.roi
            right = min(right, image.width)
            bottom = min(bottom, image.height)
            if right > left and bottom > top:
                return image.crop((left, top, right, bottom))
        return image

    @staticmethod
    def _format_batch_countdown(remaining: float) -> str:
        return f"{max(0.0, remaining):.2f} 秒"

    def _batch_delay_seconds(self) -> float:
        variable = getattr(self, "batch_delay_var", None)
        try:
            value = float(variable.get()) if variable is not None else BATCH_NEXT_COUNTDOWN_SECONDS
        except (TypeError, ValueError):
            value = BATCH_NEXT_COUNTDOWN_SECONDS
        value = max(1.5, min(8.0, value))
        value = round(value * 2) / 2
        if variable is not None:
            variable.set(f"{value:g}")
        return value

    @staticmethod
    def _monster_batch_signature(monster: Monster) -> tuple:
        return (
            monster.species.strip(),
            normalize_gender(monster.gender),
            tuple(monster.ivs[:6]),
            monster.nature.strip(),
            monster.ability.strip(),
            monster.held_item.strip(),
            tuple(move.strip() for move in monster.moves if move.strip()),
            bool(monster.is_alpha),
            bool(monster.has_hidden_ability),
        )

    def _parsed_batch_signature(self, parsed: dict) -> tuple:
        record, _confident = self._resolve_ocr_species(parsed)
        species = record.display_name if record is not None else str(parsed.get("species", "")).strip()
        moves = tuple(
            self.reference_db.canonical_move(str(move).strip())
            for move in parsed.get("moves", [])
            if str(move).strip()
        )
        ivs = list(parsed.get("ivs", [None] * 6))[:6]
        ivs.extend([None] * (6 - len(ivs)))
        return (
            species,
            normalize_gender(str(parsed.get("gender", ""))),
            tuple(ivs),
            str(parsed.get("nature", "")).strip(),
            str(parsed.get("ability", "")).strip(),
            str(parsed.get("item", parsed.get("held_item", ""))).strip(),
            moves,
            bool(parsed.get("is_alpha", False)),
            bool(parsed.get("has_hidden_ability", False)),
        )

    def _set_batch_cycle_state(
        self,
        state: str,
        title: str,
        value: str,
        hint: str,
        *,
        retry_enabled: bool = False,
    ) -> None:
        for variable_name, text in (
            ("batch_cycle_title_var", title),
            ("batch_cycle_value_var", value),
            ("batch_cycle_hint_var", hint),
        ):
            variable = getattr(self, variable_name, None)
            if variable is not None:
                variable.set(text)
        style_name = state if state in {"Info", "Success", "Warning"} else "Info"
        panel = getattr(self, "batch_cycle_panel", None)
        if panel is not None:
            panel.configure(style=f"BatchCycle{style_name}.TFrame")
        for widget_name, suffix in (
            ("batch_cycle_title_label", "Title"),
            ("batch_cycle_value_label", "Value"),
            ("batch_cycle_hint_label", "Hint"),
        ):
            widget = getattr(self, widget_name, None)
            if widget is not None:
                widget.configure(style=f"BatchCycle{style_name}{suffix}.TLabel")
        retry_button = getattr(self, "batch_retry_button", None)
        if retry_button is not None:
            retry_button.configure(state="normal" if retry_enabled else "disabled")
        self._update_batch_skip_action()

    def _can_skip_batch_location(self) -> bool:
        return bool(
            getattr(self, "batch_running", False)
            and getattr(self, "batch_saved_count", 0) > 0
            and not getattr(self, "batch_waiting_confirmation", False)
            and not getattr(self, "batch_worker_busy", False)
        )

    def _update_batch_skip_action(self) -> None:
        button = getattr(self, "batch_skip_button", None)
        if button is not None:
            button.configure(state="normal" if self._can_skip_batch_location() else "disabled")

    def _cancel_batch_countdown(self) -> None:
        after_id = getattr(self, "batch_countdown_after_id", None)
        if after_id is not None:
            try:
                self.root.after_cancel(after_id)
            except Exception:
                pass
        self.batch_countdown_after_id = None
        self.batch_countdown_deadline = 0.0
        self.batch_countdown_active = False

    def _start_batch_countdown(self) -> bool:
        if not self.batch_running or self.batch_waiting_confirmation or self.batch_worker_busy:
            return False
        self._cancel_batch_countdown()
        delay = self._batch_delay_seconds()
        self.batch_awaiting_visual_change = True
        self.batch_countdown_active = True
        self.batch_countdown_deadline = time.perf_counter() + delay
        self.save_monster_button.configure(text="请在倒计时内点击下一只…")
        self.status_var.set(
            f"下一条位置已准备好：请在 {delay:.2f} 秒内手动点击下一只精灵；到点后工具会强制截图并 OCR。"
        )
        self._batch_countdown_tick()
        return True

    def _batch_countdown_tick(self) -> None:
        self.batch_countdown_after_id = None
        if not self.batch_running or not self.batch_countdown_active:
            return
        remaining = self.batch_countdown_deadline - time.perf_counter()
        if remaining <= 0:
            self.batch_countdown_active = False
            self.batch_countdown_deadline = 0.0
            self._set_batch_cycle_state(
                "Info",
                "倒计时结束",
                "OCR 处理中",
                "正在强制读取当前可见画面，请稍候。",
            )
            self._force_batch_countdown_ocr()
            return
        self._set_batch_cycle_state(
            "Info",
            "请点击下一只精灵",
            self._format_batch_countdown(remaining),
            "倒计时结束后将强制截图并执行 OCR；可按 F8 重新计时。",
            retry_enabled=True,
        )
        self.batch_countdown_after_id = self.root.after(BATCH_COUNTDOWN_TICK_MS, self._batch_countdown_tick)

    def restart_batch_countdown(self) -> bool:
        if not self.batch_running:
            self.status_var.set("连续扫描尚未启动，请先点击“开始连续扫描”。")
            return False
        if self.batch_waiting_confirmation:
            self.status_var.set("当前识别结果仍待确认，请先核对并按回车保存。")
            return False
        if self.batch_worker_busy:
            self.status_var.set("OCR 仍在处理中，请等待结果后再重新计时。")
            return False
        return self._start_batch_countdown()

    def _handle_batch_retry_hotkey(self, _event=None) -> str | None:
        if not self.batch_running:
            return None
        self.restart_batch_countdown()
        return "break"

    def _focus_helper_for_batch_action(self) -> None:
        # This only foregrounds the helper. It does not send keyboard or mouse
        # input to PokeMMO and does not inspect game memory.
        root = getattr(self, "root", None)
        if root is None:
            return

        def call_root(name: str, *args) -> bool:
            method = getattr(root, name, None)
            if not callable(method):
                return False
            try:
                method(*args)
                return True
            except Exception:
                return False

        def focus_once() -> None:
            call_root("deiconify")
            call_root("lift")
            if call_root("attributes", "-topmost", True):
                after = getattr(root, "after", None)
                if callable(after):
                    try:
                        after(80, lambda: call_root("attributes", "-topmost", False))
                    except Exception:
                        pass
            call_root("focus_force")
            save_button = getattr(self, "save_monster_button", None)
            focus_set = getattr(save_button, "focus_set", None)
            if getattr(self, "batch_waiting_confirmation", False) and callable(focus_set):
                try:
                    focus_set()
                except Exception:
                    pass

        call_root("bell")
        focus_once()
        # Windows may reject the first foreground request while the capture
        # thread is returning. A short second attempt is still local window
        # focus management; it neither listens globally nor sends game input.
        after = getattr(root, "after", None)
        if callable(after):
            try:
                after(180, focus_once)
            except Exception:
                pass

    def _mark_batch_retry_required(self, message: str) -> None:
        delay = self._batch_delay_seconds()
        self.batch_awaiting_visual_change = True
        self.batch_waiting_confirmation = False
        self.save_monster_button.configure(text="等待切换（F8 重新计时）")
        self._set_batch_cycle_state(
            "Warning",
            "未检测到新的精灵",
            "按 F8 重试",
            f"请点击下一只后按 F8 重开 {delay:g} 秒倒计时；若两只可见资料完全相同，可点上方“识别当前精灵”强制录入。",
            retry_enabled=True,
        )
        retry_button = getattr(self, "batch_retry_button", None)
        if retry_button is not None:
            retry_button.configure(text=f"重新开始 {delay:g} 秒倒计时（F8）")
        self.status_var.set(message)
        self._focus_helper_for_batch_action()
        self._focus_batch_shortcuts()

    def _force_batch_countdown_ocr(self) -> None:
        if not self.batch_running or self.batch_worker_busy:
            return
        if self.live_window is None:
            self._mark_batch_retry_required("强制识别失败：当前没有可用的实时窗口。请重新连接窗口后按 F8 重试。")
            return
        try:
            image = capture_window(self.live_window)
            self._set_live_image(image, f"实时窗口：{self.live_window.title}")
            crop = self._crop_for_ocr(image)
            fingerprint = self._fingerprint(image, crop)
        except Exception as exc:
            self._mark_batch_retry_required(f"倒计时截图失败：{exc}。请检查窗口后按 F8 重试。")
            return
        self.batch_last_processed = fingerprint
        self.batch_latest_fingerprint = fingerprint
        self.batch_worker_busy = True
        self._update_batch_skip_action()
        self.save_monster_button.configure(text="正在强制识别…")
        self.status_var.set("切换等待已结束，正在强制 OCR 当前可见画面……")
        self._start_ocr_worker(crop.copy(), image.copy(), fingerprint, self.batch_session, reason="next")

    def start_batch_scan(self) -> None:
        index = self.window_combo.current()
        if index < 0 or index >= len(self.windows):
            messagebox.showwarning("没有选择窗口", "请先刷新并选择 PokeMMO 窗口。")
            return
        try:
            page = int(self.batch_page_var.get())
            slot = int(self.batch_slot_var.get())
            slots_per_page = int(self.batch_slots_per_page_var.get())
            if page < 1 or slot < 1 or slots_per_page < 1 or slot > slots_per_page:
                raise ValueError
        except ValueError:
            messagebox.showwarning("连续扫描参数无效", "箱号和每箱格数必须为正整数；起始格必须在当前箱的格数范围内。")
            return
        self._batch_delay_seconds()
        account = self._remember_account(self.account_var.get())
        self.live_window = self.windows[index]
        self.live_preview_running = True
        self._cancel_live_preview_tick()
        try:
            image = capture_window(self.live_window)
            self._set_live_image(image, f"实时窗口：{self.live_window.title}")
            if self.roi is None:
                self.set_default_roi()
        except Exception as exc:
            self.live_preview_running = False
            messagebox.showerror("连接窗口失败", str(exc))
            return
        try:
            if self.ocr is None:
                self.status_var.set("正在加载本地 OCR 模型……")
                self.root.update_idletasks()
                self.ocr = OCRProcessor(self._ocr_profile_key())
        except Exception as exc:
            messagebox.showerror("OCR 初始化失败", str(exc))
            self._schedule_live_preview_tick()
            return
        self.batch_running = True
        self._set_batch_parameters_compact(True)
        self.batch_session += 1
        self._cancel_batch_countdown()
        self.batch_pending_fingerprint = None
        self.batch_pending_count = 0
        self.batch_last_processed = None
        # Keep the last confirmed visible identity for the lifetime of this app
        # process, including stop/start cycles. It is intentionally not loaded
        # from inventory and therefore resets naturally when the app is closed.
        self.batch_latest_fingerprint = None
        self.batch_current_fingerprint = None
        self.batch_current_confidence = None
        self.batch_waiting_confirmation = False
        self.batch_awaiting_visual_change = False
        self.batch_worker_busy = False
        self.batch_saved_count = 0
        self.page_var.set(str(page))
        self.slot_var.set(str(slot))
        self.right_tabs.select(self.current_tab)
        self.batch_start_button.configure(state="disabled")
        self.batch_stop_button.configure(state="normal")
        self.save_monster_button.configure(text="等待识别结果…")
        self._set_batch_cycle_state(
            "Info",
            "正在识别第一只",
            "等待画面稳定",
            "首次识别完成后请核对结果并按 Enter 保存。",
        )
        self.status_var.set(
            f"连续扫描已启动：账号 {account}，从箱 {page} / 格 {slot} 开始。保持当前精灵约 1 秒，识别后按回车确认。"
        )
        self._batch_tick()

    def stop_batch_scan(self) -> None:
        self.batch_running = False
        self.batch_session += 1
        self._cancel_batch_countdown()
        if self.batch_after_id is not None:
            try:
                self.root.after_cancel(self.batch_after_id)
            except Exception:
                pass
            self.batch_after_id = None
        self.batch_start_button.configure(state="normal")
        self.batch_stop_button.configure(state="disabled")
        self._set_batch_parameters_compact(False)
        self.batch_waiting_confirmation = False
        self.batch_awaiting_visual_change = False
        self.save_monster_button.configure(text="保存/更新并标记已核对")
        self._set_batch_cycle_state(
            "Info",
            "连续录入节奏",
            "未启动",
            "启动连续扫描后，这里会显示下一只精灵的操作提示。",
        )
        self.status_var.set(f"连续扫描已停止：本次回车确认 {self.batch_saved_count} 条；库存共 {len(self.inventory)} 只。")
        self._schedule_live_preview_tick()

    def _batch_tick(self) -> None:
        while True:
            try:
                item = self.batch_result_queue.get_nowait()
            except queue.Empty:
                break
            if len(item) == 5:
                session, parsed, image, fingerprint, error = item
                reason = "auto"
            else:
                session, parsed, image, fingerprint, error, reason = item
            if session != self.batch_session:
                continue
            self._handle_batch_ocr_result(parsed, image, fingerprint, error, reason)

        if not self.batch_running:
            return
        if self.live_window is not None:
            try:
                image = capture_window(self.live_window)
                self._set_live_image(image, f"实时窗口：{self.live_window.title}")
                crop = self._crop_for_ocr(image)
                fingerprint = self._fingerprint(image, crop)
                self.batch_latest_fingerprint = fingerprint

                if not self.batch_worker_busy and not self.batch_waiting_confirmation:
                    if self.batch_awaiting_visual_change:
                        # After the first save, recognition is intentionally
                        # countdown-driven. Keep refreshing the preview here,
                        # but never decide on the user's behalf when to OCR.
                        pass
                    else:
                        pending_diff = self._fingerprint_difference(fingerprint, self.batch_pending_fingerprint)
                        if pending_diff <= BATCH_STABLE_DIFFERENCE:
                            self.batch_pending_count += 1
                        else:
                            self.batch_pending_fingerprint = fingerprint
                            self.batch_pending_count = 1
                        if self.batch_pending_count >= BATCH_STABLE_FRAMES:
                            self.batch_last_processed = fingerprint
                            self.batch_worker_busy = True
                            self.batch_pending_count = 0
                            self._start_ocr_worker(crop.copy(), image.copy(), fingerprint, self.batch_session, reason="auto")
                            self.status_var.set("画面已稳定，正在识别当前精灵……")
            except Exception as exc:
                self.status_var.set(f"连续截图失败：{exc}")
        self.batch_after_id = self.root.after(self._batch_poll_interval_ms(), self._batch_tick)

    def force_scan_current_slot(self) -> None:
        if not self.batch_running:
            messagebox.showwarning("连续扫描未启动", "请先启动连续扫描，再重新识别当前精灵。")
            return
        if self.batch_worker_busy:
            self.status_var.set("上一张仍在 OCR，请稍候再强制识别。")
            return
        if self.live_window is None:
            return
        self._cancel_batch_countdown()
        try:
            image = capture_window(self.live_window)
            self._set_live_image(image, f"实时窗口：{self.live_window.title}")
            crop = self._crop_for_ocr(image)
            fingerprint = self._fingerprint(image, crop)
        except Exception as exc:
            messagebox.showerror("截图失败", str(exc))
            return
        self.batch_last_processed = fingerprint
        self.batch_latest_fingerprint = fingerprint
        self.batch_waiting_confirmation = False
        self.batch_awaiting_visual_change = False
        self.batch_current_fingerprint = None
        self.batch_pending_fingerprint = None
        self.batch_pending_count = 0
        self.batch_worker_busy = True
        self._update_batch_skip_action()
        self.save_monster_button.configure(text="正在重新识别…")
        self.status_var.set("正在重新识别当前精灵……")
        self._set_batch_cycle_state(
            "Info",
            "手动强制识别",
            "OCR 处理中",
            "本次会按新的素材处理，即使画面与上一只完全相同。",
        )
        self._start_ocr_worker(crop.copy(), image.copy(), fingerprint, self.batch_session, reason="manual")

    def _start_ocr_worker(
        self,
        crop: Image.Image,
        full_image: Image.Image,
        fingerprint: bytes,
        session: int,
        *,
        reason: str = "auto",
    ) -> None:
        def worker() -> None:
            try:
                assert self.ocr is not None
                items = self.ocr.recognize(crop)
                parsed = OCRProcessor.parse(items, crop)
                self.batch_result_queue.put((session, parsed, full_image, fingerprint, "", reason))
            except Exception as exc:
                self.batch_result_queue.put((session, None, full_image, fingerprint, str(exc), reason))

        threading.Thread(target=worker, name="pokemmo-ocr", daemon=True).start()

    def _handle_batch_ocr_result(
        self,
        parsed: dict | None,
        image: Image.Image,
        fingerprint: bytes,
        error: str,
        reason: str,
    ) -> None:
        self.batch_worker_busy = False
        if error:
            if reason == "next":
                self._mark_batch_retry_required(f"强制 OCR 失败：{error}。请按 F8 重新开始倒计时。")
            else:
                self.status_var.set(f"连续 OCR 失败：{error}。工具会继续等待下一次稳定画面。")
            return
        moved_during_ocr = (
            self.batch_latest_fingerprint is not None
            and self._fingerprint_difference(fingerprint, self.batch_latest_fingerprint) >= BATCH_CHANGE_DIFFERENCE
        )
        if moved_during_ocr:
            self.batch_pending_fingerprint = None
            self.batch_pending_count = 0
            if reason == "next":
                self._mark_batch_retry_required("OCR 过程中画面再次变化，旧结果已丢弃。请在画面稳定后按 F8 重试。")
            else:
                self.status_var.set("OCR 过程中画面发生变化，已丢弃旧结果并重新等待当前精灵稳定。")
            return
        if reason in {"next", "auto"} and self.batch_last_confirmed_fingerprint is not None:
            change = self._fingerprint_difference(fingerprint, self.batch_last_confirmed_fingerprint)
            if change < BATCH_CHANGE_DIFFERENCE:
                current_signature = self._parsed_batch_signature(parsed or {})
                semantic_changed = parsed is not None and (
                    self.batch_last_confirmed_signature is None
                    or current_signature != self.batch_last_confirmed_signature
                )
                if not semantic_changed:
                    prefix = "强制 OCR 已完成" if reason == "next" else "本次启动后的首轮 OCR 已完成"
                    self._mark_batch_retry_required(
                        f"{prefix}：文字字段与本次软件运行期间上一只完全相同，信息区变化率为 {change:.1f}。"
                        "若确实已经切换到资料完全相同的另一只，请点“识别当前精灵”强制录入；否则点击下一只后按 F8 重试。"
                    )
                    return
        if parsed is not None:
            self._accept_batch_result(parsed, image, fingerprint)

    def _resolve_ocr_species(self, parsed: dict) -> tuple[SpeciesRecord | None, bool]:
        raw_lines = [line.strip() for line in str(parsed.get("raw_text", "")).splitlines() if line.strip()]
        primary_lines = [
            str(parsed.get("species", "")),
            *(line for line in raw_lines if "lv" in line.lower()),
        ]
        gender = str(parsed.get("gender", ""))
        best: tuple[SpeciesRecord | None, bool, float] = (None, False, 0.0)
        for candidate in dict.fromkeys(line for line in primary_lines if line.strip()):
            resolved = self.species_db.resolve_ocr_name(candidate, gender)
            if resolved[0] is not None and resolved[2] > best[2]:
                best = resolved
            if resolved[1] and resolved[2] >= 1.0:
                break
        return best[0], best[1]

    def _apply_parsed_result(self, parsed: dict) -> tuple[SpeciesRecord | None, bool]:
        record, exact_species = self._resolve_ocr_species(parsed)
        species = record.display_name if record else str(parsed.get("species", "")).strip()
        gender = normalize_gender(str(parsed.get("gender", "")))
        confidence = float(parsed.get("confidence", 0.0) or 0.0)
        if record and record.allowed_genders == ("N",):
            gender = "N"
        nature = str(parsed.get("nature", "")).strip()
        is_alpha = bool(parsed.get("is_alpha", False))
        ability = self.reference_db.canonical_ability(str(parsed.get("ability", "")).strip())
        raw_moves = [str(move).strip() for move in parsed.get("moves", []) if str(move).strip()]
        moves = [self.reference_db.canonical_move(move) for move in raw_moves]
        self.species_var.set(species)
        self.gender_var.set(gender)
        self.nature_var.set(nature)
        self.alpha_var.set("头目" if is_alpha else "普通")
        self.ability_var.set(ability)
        hidden_names = set(self.reference_db.hidden_ability_names(record.id)) if record else set()
        self.hidden_ability_var.set(
            bool(parsed.get("has_hidden_ability", False) or is_alpha or (ability and ability in hidden_names))
        )
        self.iv_var.set("/".join("x" if value is None else str(value) for value in parsed.get("ivs", [None] * 6)))
        self.moves_var.set(", ".join(moves))
        if hasattr(self, "ocr_confidence_var"):
            self.ocr_confidence_var.set(f"OCR 置信度：{confidence:.0%}")
        self.item_var.set("")
        self.groups_var.set(", ".join(record.egg_groups) if record else "")
        move_labels = [
            f"{move}（遗传）" if record and self.reference_db.is_egg_move(record.id, move) else move
            for move in moves
        ]
        gender_text = {"F": "母", "M": "公", "N": "无性别"}.get(gender, "未识别")
        self.recent_scan_var.set(
            f"最近识别：{'头目' if is_alpha else '普通'}｜{species or '未识别'}｜{gender_text}｜"
            f"IV {self.iv_var.get()}｜{nature or '性格未识别'}"
        )
        summary = "\n".join(
            (
                f"名字：{species or '未识别'}",
                f"性别：{gender_text}",
                f"个体值：{self.iv_var.get()}",
                f"性格：{nature or '未识别'}",
                f"梦特：{'已解锁' if self.hidden_ability_var.get() else '未确认'}"
                + (f"（{ability}）" if ability else ""),
                f"技能：{'、'.join(move_labels) if move_labels else '未识别'}",
                f"类别：{'头目' if is_alpha else '普通'}",
            )
        )
        self.raw_text_box.delete("1.0", END)
        self.raw_text_box.insert("1.0", summary)
        self._set_batch_parameters_compact(True)
        if self.layout_orientation == "compact" and max(1, self.root.winfo_height()) < 780:
            self.current_form_expanded = False
            self._apply_current_result_density(True, True)
        self._set_compact_scan_view("result")
        return record, exact_species

    def _accept_batch_result(self, parsed: dict, image: Image.Image, fingerprint: bytes) -> None:
        self._cancel_batch_countdown()
        self._set_live_image(image, "连续窗口扫描")
        record, exact_species = self._apply_parsed_result(parsed)
        ivs = parsed.get("ivs", [None] * 6)
        complete_ivs = len(ivs) == 6 and all(isinstance(value, int) and 0 <= value <= 31 for value in ivs)
        confidence = float(parsed.get("confidence", 0.0) or 0.0)
        gender = normalize_gender(self.gender_var.get())
        gender_valid = bool(gender) and (record is None or gender in record.allowed_genders)
        if not self.species_var.get().strip():
            self.species_var.set("待识别")
        self.page_var.set(self.batch_page_var.get().strip())
        self.slot_var.set(self.batch_slot_var.get().strip())
        self.editing_monster_id = None
        self.batch_current_fingerprint = fingerprint
        self.batch_current_confidence = confidence
        self.batch_waiting_confirmation = True
        self.batch_awaiting_visual_change = False
        self.save_monster_button.configure(text="按回车或点击这里确认当前结果")
        self._set_batch_cycle_state(
            "Success",
            "已识别新的精灵",
            "按 Enter 保存",
            f"请先核对名字、性别、个体值、性格和技能；保存后自动开始下一轮 {self._batch_delay_seconds():g} 秒倒计时。",
        )
        warnings: list[str] = []
        if not record or not exact_species:
            warnings.append("名字需核对")
        if not gender_valid:
            warnings.append("性别需核对")
        if not complete_ivs:
            warnings.append("个体值需补全")
        if warnings and self.layout_orientation == "compact" and max(1, self.root.winfo_height()) < 780:
            self.current_form_expanded = True
            self._apply_current_result_density(True, True)
        warning_text = f"；{'、'.join(warnings)}后再确认" if warnings else ""
        self.status_var.set(
            f"已识别箱 {self.page_var.get()} / 格 {self.slot_var.get()}：{self.species_var.get()} "
            f"{gender or '性别未知'}，OCR {confidence:.0%}{warning_text}。确认无误请按回车。"
        )
        # The user just clicked the game to select this breeder, so keyboard
        # focus is normally still in PokeMMO. Bring only this read-only helper
        # back to the foreground once the result is ready; no key is captured
        # globally and no input is sent to the game.
        self._focus_helper_for_batch_action()

    def _handle_batch_enter(self, _event=None) -> str | None:
        if not self.batch_running:
            return None
        if not self.batch_waiting_confirmation:
            self.status_var.set("当前还没有可确认的识别结果，请等待 OCR 完成。")
            return "break"
        self.confirm_batch_result()
        return "break"

    def _handle_batch_space(self, event=None) -> str | None:
        """Skip one empty box position without creating an inventory row.

        It is active throughout the post-save countdown and F8 retry state,
        while editable fields keep their normal space input behavior.
        """
        if not self._can_skip_batch_location():
            return None
        widget = getattr(event, "widget", None) if event is not None else None
        class_name = ""
        if widget is not None:
            class_getter = getattr(widget, "winfo_class", None)
            if callable(class_getter):
                try:
                    class_name = str(class_getter())
                except Exception:
                    class_name = ""
        if class_name in {"Entry", "TEntry", "Text", "TCombobox", "Spinbox", "TSpinbox"}:
            return None
        self.skip_batch_location()
        return "break"

    def _focus_batch_shortcuts(self) -> None:
        root = getattr(self, "root", None)
        focus_set = getattr(root, "focus_set", None)
        if callable(focus_set):
            try:
                focus_set()
            except Exception:
                pass

    def confirm_batch_result(self) -> bool:
        if not self.batch_running or not self.batch_waiting_confirmation:
            return False
        species = self.species_var.get().strip()
        if not species or species == "待识别":
            messagebox.showwarning("名字未确认", "请先在右侧修正精灵名字，再按回车保存。")
            return False
        record = self.species_db.get(species, fuzzy=True)
        if record:
            self.species_var.set(record.display_name)
            self.groups_var.set(", ".join(record.egg_groups))
            if record.allowed_genders == ("N",):
                self.gender_var.set("N")
        gender = normalize_gender(self.gender_var.get())
        if not gender:
            messagebox.showwarning("性别未确认", "请先选择性别：F=母，M=公，N=无性别。")
            return False
        if record and gender not in record.allowed_genders:
            messagebox.showwarning("性别不匹配", f"{record.display_name} 不能保存为当前选择的性别。")
            return False
        if any(value is None for value in self._parse_form_ivs()):
            messagebox.showwarning("个体值未补全", "连续录入需要六项个体值完整；请修正 X 后再按回车。")
            return False

        saved_page = self.page_var.get().strip()
        saved_slot = self.slot_var.get().strip()
        fingerprint = self.batch_current_fingerprint or self.batch_latest_fingerprint
        monster = self._monster_from_form(
            verified=True,
            confidence=self.batch_current_confidence,
            scan_fingerprint=hashlib.sha1(fingerprint).hexdigest() if fingerprint else "",
            notes="连续扫描回车确认",
        )
        # Continuous capture deliberately appends every confirmed row. Duplicate
        # review is an explicit inventory action because two legitimate Pokemon
        # can have identical visible data, and box positions are only temporary.
        self._upsert_inventory(monster, match_location=False)
        self.batch_saved_count += 1
        self.batch_waiting_confirmation = False
        self.batch_last_confirmed_fingerprint = fingerprint
        self.batch_last_confirmed_signature = self._monster_batch_signature(monster)
        self.batch_current_fingerprint = None
        self.batch_current_confidence = None
        self.batch_awaiting_visual_change = True
        self.batch_pending_fingerprint = None
        self.batch_pending_count = 0
        self.advance_batch_location(update_status=False)
        self.save_monster_button.configure(text="等待下一只识别…")
        self.status_var.set(
            f"已保存箱 {saved_page} / 格 {saved_slot} 的 {monster.species}；"
            f"下一条将记录到箱 {self.batch_page_var.get()} / 格 {self.batch_slot_var.get()}。"
        )
        self._start_batch_countdown()
        self._focus_batch_shortcuts()
        return True

    def skip_batch_location(self) -> None:
        if not self.batch_running:
            self.status_var.set("连续扫描尚未启动，不能跳过空位。")
            self._update_batch_skip_action()
            return
        if self.batch_saved_count <= 0:
            self.status_var.set("请先识别并按 Enter 保存第一只精灵，再用 Space 跳过它后面的空位。")
            self._update_batch_skip_action()
            return
        if self.batch_waiting_confirmation:
            self.status_var.set("当前识别结果仍待确认，请先按 Enter 保存；Space 只跳过保存后的下一空位。")
            return
        if self.batch_worker_busy:
            self.status_var.set("OCR 正在处理中，当前不能跳过；请等待识别结果后再操作。")
            self._update_batch_skip_action()
            return
        skipped_page = self.batch_page_var.get().strip()
        skipped_slot = self.batch_slot_var.get().strip()
        self.batch_waiting_confirmation = False
        self.batch_last_confirmed_fingerprint = self.batch_current_fingerprint or self.batch_latest_fingerprint
        self.batch_last_confirmed_signature = None
        self.batch_current_fingerprint = None
        self.batch_current_confidence = None
        self.batch_awaiting_visual_change = True
        self.batch_pending_fingerprint = None
        self.batch_pending_count = 0
        self.advance_batch_location(update_status=False)
        self.save_monster_button.configure(text="等待下一只识别…")
        skipped_position = format_box_position(skipped_page, skipped_slot) or f"箱 {skipped_page} / 格 {skipped_slot}"
        next_position = format_box_position(self.batch_page_var.get(), self.batch_slot_var.get()) or (
            f"箱 {self.batch_page_var.get()} / 格 {self.batch_slot_var.get()}"
        )
        self.status_var.set(
            f"已跳过空位 {skipped_position}（未写入素材库）；"
            f"下一条将记录到 {next_position}。"
        )
        self._start_batch_countdown()
        self._focus_batch_shortcuts()

    @staticmethod
    def _next_batch_location(page: int, slot: int, per_page: int) -> tuple[int, int]:
        slot += 1
        if slot > per_page:
            return page + 1, 1
        return page, slot

    def advance_batch_location(self, update_status: bool = True) -> None:
        try:
            page = max(1, int(self.batch_page_var.get()))
            slot = max(1, int(self.batch_slot_var.get()))
            per_page = max(1, int(self.batch_slots_per_page_var.get()))
        except ValueError:
            return
        page, slot = self._next_batch_location(page, slot, per_page)
        self.batch_page_var.set(str(page))
        self.batch_slot_var.set(str(slot))
        self.page_var.set(str(page))
        self.slot_var.set(str(slot))
        if update_status:
            self.status_var.set(f"批量位置已前进到箱 {page} / 格 {slot}。")

    def refresh_windows(self) -> None:
        def is_helper(window: WindowInfo) -> bool:
            title = window.title.lower()
            return "breeder-helper" in title or "孵蛋助手" in title

        # Never offer this program as an OCR source. Its title also contains
        # "PokeMMO", which previously made it win the automatic selection.
        self.windows = [window for window in list_windows() if not is_helper(window)]
        labels = [window.label() for window in self.windows]
        self.window_combo["values"] = labels
        preferred = next(
            (index for index, window in enumerate(self.windows) if "pokemmo" in window.title.lower()),
            0,
        )
        if labels:
            self.window_combo.current(preferred)
        self.status_var.set(f"已发现 {len(labels)} 个可见窗口。")

    def capture_selected_window(self) -> None:
        if self.batch_running:
            self.stop_batch_scan()
        index = self.window_combo.current()
        if index < 0 or index >= len(self.windows):
            messagebox.showwarning("没有选择窗口", "请先刷新并选择 PokeMMO 窗口。")
            return
        self.live_window = self.windows[index]
        try:
            image = capture_window(self.live_window)
        except Exception as exc:
            messagebox.showerror("连接窗口失败", str(exc))
            self.status_var.set("连接失败，请确认目标窗口仍然存在且没有最小化。")
            self._set_source_collapsed(False)
            return
        self.set_image(image, f"实时窗口：{self.live_window.title}")
        if self.roi is None:
            self.set_default_roi()
        self.live_preview_running = True
        self._cancel_live_preview_tick()
        self._schedule_live_preview_tick()
        self.source_summary_var.set(f"已连接：{self.live_window.label()}")
        self._set_source_collapsed(True)
        self._set_compact_scan_view("preview")
        self.status_var.set("已连接选中窗口；预览会跟随 PokeMMO 的移动、缩放和画面变化。")

    def _cancel_live_preview_tick(self) -> None:
        after_id = getattr(self, "live_preview_after_id", None)
        if after_id is None:
            return
        try:
            self.root.after_cancel(after_id)
        except Exception:
            pass
        self.live_preview_after_id = None

    def _schedule_live_preview_tick(self) -> None:
        if not self.live_preview_running or self.batch_running or self.live_window is None:
            return
        self._cancel_live_preview_tick()
        self.live_preview_after_id = self.root.after(self._ocr_poll_interval_ms(), self._live_preview_tick)

    def _live_preview_tick(self) -> None:
        self.live_preview_after_id = None
        if not self.live_preview_running or self.batch_running or self.live_window is None:
            return
        detached_open = bool(
            self.preview_zoom_window is not None
            and not getattr(self.preview_zoom_window, "closed", True)
        )
        if (self.window_suspended or self.workspace_mode_var.get() != "扫描素材") and not detached_open:
            # Keep the connection alive, but do not capture and resize frames
            # that cannot currently be seen. The next normal tick resumes it.
            self._schedule_live_preview_tick()
            return
        try:
            image = capture_window(self.live_window)
            self._set_live_image(image, f"实时窗口：{self.live_window.title}")
        except Exception as exc:
            self.status_var.set(f"实时预览暂停：{exc}")
            return
        self._schedule_live_preview_tick()

    def _set_live_image(self, image: Image.Image, source: str) -> None:
        old_size = self.current_image.size if self.current_image is not None else None
        self.current_image = image
        self.current_source = source
        self.source_var.set(source)
        if self.roi and old_size and old_size != image.size:
            old_width, old_height = old_size
            left, top, right, bottom = self.roi
            self.roi = (
                int(left * image.width / max(1, old_width)),
                int(top * image.height / max(1, old_height)),
                int(right * image.width / max(1, old_width)),
                int(bottom * image.height / max(1, old_height)),
            )
        if self._embedded_preview_visible():
            if self.roi:
                self.draw_roi()
            else:
                self.show_preview()
        self._update_detached_preview(image)

    def load_image(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("图片", "*.png *.jpg *.jpeg *.webp *.bmp"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            image = Image.open(path).convert("RGB")
        except Exception as exc:
            messagebox.showerror("加载失败", str(exc))
            return
        if self.batch_running:
            self.stop_batch_scan()
        self.set_image(image, path)

    def load_clipboard(self) -> None:
        image = ImageGrab.grabclipboard()
        if not isinstance(image, Image.Image):
            messagebox.showwarning("剪贴板没有图片", "请先复制一张截图。")
            return
        if self.batch_running:
            self.stop_batch_scan()
        self.set_image(image.convert("RGB"), "剪贴板")

    def set_image(self, image: Image.Image, source: str) -> None:
        if not source.startswith("实时窗口："):
            self.live_preview_running = False
            self._cancel_live_preview_tick()
        # A newly loaded/captured image represents a new inventory material.
        # Updating an existing row is only allowed after the user explicitly
        # selects that row in the inventory table.
        self.editing_monster_id = None
        self.current_image = image
        self.current_source = source
        self.source_var.set(source)
        self.roi = None
        self.drag_rectangle = None
        if hasattr(self, "save_monster_button"):
            self.save_monster_button.configure(text="保存为新素材并标记已核对")
        if hasattr(self, "source_summary_var"):
            if source.startswith("实时窗口："):
                self.source_summary_var.set(f"已连接：{source.removeprefix('实时窗口：')}")
            else:
                source_name = "剪贴板图片" if source == "剪贴板" else Path(source).name
                self.source_summary_var.set(f"已载入：{source_name}")
        if hasattr(self, "source_details"):
            self._set_source_collapsed(True)
        if hasattr(self, "main_pane"):
            self._set_compact_scan_view("preview")
        self.show_preview()
        self._update_detached_preview(image)
        self.status_var.set(f"已载入画面 {image.width}×{image.height}。可以框选信息区或直接识别。")

    def show_preview(self) -> None:
        if self.current_image is None:
            self.canvas.delete("all")
            self.preview_image_item = None
            self.preview_roi_item = None
            self.preview_photo = None
            self.preview_render_key = None
            return
        max_width = max(1, self.canvas.winfo_width() - 8)
        max_height = max(1, self.canvas.winfo_height() - 8)
        self.preview_scale = min(1.0, max_width / self.current_image.width, max_height / self.current_image.height)
        render_size = (
            max(1, round(self.current_image.width * self.preview_scale)),
            max(1, round(self.current_image.height * self.preview_scale)),
        )
        # High-DPI Tk can alternate a canvas dimension by one physical pixel.
        # Reuse the prior target size in that case so the preview does not pulse.
        if self.preview_render_size and all(
            abs(current - previous) <= 1
            for current, previous in zip(render_size, self.preview_render_size)
        ):
            render_size = self.preview_render_size
            self.preview_scale = min(render_size[0] / self.current_image.width, render_size[1] / self.current_image.height)
        self.preview_render_size = render_size
        render_key = (id(self.current_image), render_size)
        if self.preview_render_key == render_key and self.preview_photo is not None and self.preview_image_item is not None:
            x = max(4, (self.canvas.winfo_width() - render_size[0]) // 2)
            y = max(4, (self.canvas.winfo_height() - render_size[1]) // 2)
            self.preview_offset = (x, y)
            self.canvas.coords(self.preview_image_item, x, y)
            return
        display = self.current_image.resize(render_size, Image.Resampling.BILINEAR)
        new_photo = ImageTk.PhotoImage(display)
        x = max(4, (self.canvas.winfo_width() - display.width) // 2)
        y = max(4, (self.canvas.winfo_height() - display.height) // 2)
        self.preview_offset = (x, y)
        if self.preview_image_item is None:
            self.preview_image_item = self.canvas.create_image(x, y, image=new_photo, anchor="nw")
        else:
            self.canvas.coords(self.preview_image_item, x, y)
            self.canvas.itemconfigure(self.preview_image_item, image=new_photo)
        # Keep the old PhotoImage alive until the canvas item references the new
        # one; replacing this order caused visible black flashes on 2K screens.
        self.preview_photo = new_photo
        self.preview_render_key = render_key
        self.canvas.tag_lower(self.preview_image_item)
        if self.roi is None and self.drag_start is None and self.preview_roi_item is not None:
            self.canvas.delete(self.preview_roi_item)
            self.preview_roi_item = None
            self.drag_rectangle = None

    def set_default_roi(self) -> None:
        if self.current_image is None:
            return
        width = min(self.current_image.width, int(self.current_image.width * 0.32))
        self.roi = (0, 0, width, self.current_image.height)
        self.draw_roi()
        self.status_var.set(f"已设置左侧信息区：{width}×{self.current_image.height}。")

    def clear_roi(self) -> None:
        self.roi = None
        self.draw_roi()

    def draw_roi(self) -> None:
        self.show_preview()
        if not self.roi:
            if self.preview_roi_item is not None:
                self.canvas.delete(self.preview_roi_item)
                self.preview_roi_item = None
            return
        left, top, right, bottom = self.roi
        ox, oy = self.preview_offset
        coords = (
            ox + left * self.preview_scale,
            oy + top * self.preview_scale,
            ox + right * self.preview_scale,
            oy + bottom * self.preview_scale,
        )
        if self.preview_roi_item is None:
            self.preview_roi_item = self.canvas.create_rectangle(*coords, outline="#29b6f6", width=2)
        else:
            self.canvas.coords(self.preview_roi_item, *coords)
        self.drag_rectangle = self.preview_roi_item

    def open_preview_zoom(self, _event=None) -> str:
        if self.current_image is None:
            return "break"
        existing = self.preview_zoom_window
        if existing is not None:
            try:
                if existing.window.winfo_exists():
                    existing.focus()
                    return "break"
            except Exception:
                pass
        self.preview_zoom_window = PreviewZoomWindow(
            self.root,
            self.current_image,
            self.roi,
            self._apply_zoom_roi,
            on_close=self._on_preview_zoom_closed,
            background=UI_COLORS["preview"],
        )
        return "break"

    def _update_detached_preview(self, image: Image.Image) -> None:
        preview = getattr(self, "preview_zoom_window", None)
        if preview is None:
            return
        try:
            preview.update_image(image, self.roi)
        except Exception:
            self.preview_zoom_window = None

    def _on_preview_zoom_closed(self) -> None:
        self.preview_zoom_window = None

    def _apply_zoom_roi(self, roi: tuple[int, int, int, int] | None) -> None:
        self.roi = roi
        self.preview_zoom_window = None
        self.draw_roi()
        if roi:
            left, top, right, bottom = roi
            self.status_var.set(f"已从放大预览应用 OCR 区域：{right-left}×{bottom-top}。")
        else:
            self.status_var.set("已清除 OCR 框选，将识别完整画面。")

    def start_roi(self, event) -> None:
        if self.current_image is None:
            return
        self.drag_start = (event.x, event.y)

    def drag_roi(self, event) -> None:
        if not self.drag_start:
            return
        if self.preview_roi_item is None:
            self.preview_roi_item = self.canvas.create_rectangle(
                self.drag_start[0], self.drag_start[1], event.x, event.y, outline="#29b6f6", width=2
            )
        else:
            self.canvas.coords(self.preview_roi_item, self.drag_start[0], self.drag_start[1], event.x, event.y)
        self.drag_rectangle = self.preview_roi_item

    def finish_roi(self, event) -> None:
        if not self.drag_start or self.current_image is None:
            return
        x1, y1 = self.drag_start
        x2, y2 = event.x, event.y
        self.drag_start = None
        ox, oy = self.preview_offset
        left = int(max(0, min(x1, x2) - ox) / self.preview_scale)
        top = int(max(0, min(y1, y2) - oy) / self.preview_scale)
        right = int(max(0, max(x1, x2) - ox) / self.preview_scale)
        bottom = int(max(0, max(y1, y2) - oy) / self.preview_scale)
        left = min(left, self.current_image.width)
        right = min(right, self.current_image.width)
        top = min(top, self.current_image.height)
        bottom = min(bottom, self.current_image.height)
        if right - left > 20 and bottom - top > 20:
            self.roi = (left, top, right, bottom)
            self.draw_roi()
            self.status_var.set(f"已框选 OCR 区域：{right-left}×{bottom-top}。")

    def image_for_ocr(self) -> Image.Image:
        if self.current_image is None:
            raise RuntimeError("请先加载截图或截取窗口。")
        if self.roi:
            return self.current_image.crop(self.roi)
        return self.current_image

    def ocr_current(self) -> None:
        try:
            image = self.image_for_ocr()
            self.ocr_confidence_var.set("OCR 置信度：识别中")
            if self.ocr is None:
                self.status_var.set("正在加载本地 OCR 模型，首次可能需要几秒……")
                self.root.update_idletasks()
                self.ocr = OCRProcessor(self._ocr_profile_key())
            items = self.ocr.recognize(image)
            parsed = OCRProcessor.parse(items, image)
        except Exception as exc:
            messagebox.showerror("OCR 失败", str(exc))
            self.ocr_confidence_var.set("OCR 置信度：识别失败")
            self.status_var.set("OCR 失败，请检查图片或依赖。")
            return
        self._apply_parsed_result(parsed)
        self.source_var.set(self.current_source)
        confidence = float(parsed.get("confidence", 0.0) or 0.0)
        self.status_var.set(
            f"OCR 完成，已提取名字、性别、个体值、性格、技能和头目标识；"
            f"核心字段置信度 {confidence:.0%}，请确认后保存。"
        )

    def clear_current(self) -> None:
        for variable in (self.species_var, self.gender_var, self.nature_var, self.iv_var, self.ability_var, self.item_var, self.moves_var, self.groups_var, self.source_var):
            variable.set("")
        self.alpha_var.set("普通")
        self.hidden_ability_var.set(False)
        self.recent_scan_var.set("最近识别：—")
        self.ocr_confidence_var.set("OCR 置信度：—")
        self.raw_text_box.delete("1.0", END)
        self.editing_monster_id = None
        self.save_monster_button.configure(text="保存为新素材并标记已核对")

    def _parse_form_ivs(self) -> list[int | None]:
        values = [x.strip() for x in self.iv_var.get().replace("／", "/").split("/")]
        ivs: list[int | None] = []
        for value in values[:6]:
            try:
                ivs.append(int(value) if value.lower() not in {"x", ""} else None)
            except ValueError:
                ivs.append(None)
        return ivs + [None] * max(0, 6 - len(ivs))

    def _monster_from_form(
        self,
        verified: bool,
        confidence: float | None = None,
        scan_fingerprint: str = "",
        notes: str = "",
    ) -> Monster:
        existing = next((item for item in self.inventory if item.id == self.editing_monster_id), None)
        return Monster(
            id=existing.id if existing else str(uuid.uuid4()),
            species=self.species_var.get().strip(),
            gender=self.gender_var.get(),
            nature=self.nature_var.get(),
            ivs=self._parse_form_ivs(),
            ability=self.ability_var.get(),
            held_item=self.item_var.get(),
            moves=[x.strip() for x in self.moves_var.get().replace("，", ",").split(",") if x.strip()],
            egg_groups=[x.strip() for x in self.groups_var.get().replace("，", ",").split(",") if x.strip()],
            is_alpha=self.alpha_var.get() == "头目",
            has_hidden_ability=bool(self.hidden_ability_var.get()),
            account=self.account_var.get().strip() or "主账号",
            page=self.page_var.get().strip(),
            slot=self.slot_var.get().strip(),
            source=self.current_source or self.source_var.get(),
            confidence=confidence if confidence is not None else (existing.confidence if existing else None),
            notes=notes or (existing.notes if existing else ""),
            verified=verified,
            scan_fingerprint=scan_fingerprint or (existing.scan_fingerprint if existing else ""),
            created_at=existing.created_at if existing else "",
            updated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )

    def _upsert_inventory(self, monster: Monster, match_location: bool) -> None:
        replace_id = monster.id if any(item.id == monster.id for item in self.inventory) else ""
        if not replace_id and match_location and monster.page and monster.slot:
            located = next(
                (
                    item for item in self.inventory
                    if item.account == monster.account
                    and item.page == monster.page
                    and item.slot == monster.slot
                ),
                None,
            )
            if located:
                same_visible_material = (
                    located.species == monster.species
                    and located.gender == monster.gender
                    and located.ivs == monster.ivs
                    and located.nature == monster.nature
                    and located.is_alpha == monster.is_alpha
                    and located.has_hidden_ability == monster.has_hidden_ability
                    and tuple(located.moves) == tuple(monster.moves)
                )
                if same_visible_material:
                    replace_id = located.id
                    monster.id = located.id
                    monster.created_at = located.created_at
                else:
                    # A box slot is only the last known location, not record
                    # identity. Preserve the displaced material and clear its
                    # stale location instead of silently deleting it.
                    located.page = ""
                    located.slot = ""
                    located.updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if replace_id:
            self.inventory = [monster if item.id == replace_id else item for item in self.inventory]
        else:
            self.inventory.append(monster)
        save_inventory(self.inventory)
        self.editing_monster_id = monster.id
        self.refresh_inventory_tree()

    def save_current_monster(self) -> None:
        if self.batch_running:
            if self.batch_waiting_confirmation:
                self.confirm_batch_result()
            else:
                self.status_var.set("当前还没有可保存的连续扫描结果。")
            return
        species = self.species_var.get().strip()
        if not species or species == "待识别":
            messagebox.showwarning("信息不完整", "至少需要填写精灵种类。")
            return
        record = self.species_db.get(species, fuzzy=True)
        if record:
            self.species_var.set(record.display_name)
            self.groups_var.set(", ".join(record.egg_groups))
            if record.allowed_genders == ("N",):
                self.gender_var.set("N")
        gender = normalize_gender(self.gender_var.get())
        if not gender:
            messagebox.showwarning("信息不完整", "请选择性别：F=母，M=公，N=无性别。")
            return
        if record and gender not in record.allowed_genders:
            messagebox.showwarning("性别不匹配", f"{record.display_name} 不能保存为当前选择的性别。")
            return
        if any(value is None for value in self._parse_form_ivs()):
            if not messagebox.askyesno("IV 未完整", "有未识别的 IV。仍保存为已核对记录吗？"):
                return
        monster = self._monster_from_form(verified=True, notes="人工核对")
        # Manual recognition also appends unless the user deliberately selected
        # an existing inventory row for editing. Duplicate review is performed
        # later from the inventory tab instead of blocking capture.
        self._upsert_inventory(monster, match_location=False)
        self.status_var.set(f"已保存并确认 {monster.species}，库存共 {len(self.inventory)} 只。")

    def refresh_inventory_tree(self) -> None:
        if not hasattr(self, "inventory_tree"):
            return
        for item in self.inventory_tree.get_children():
            self.inventory_tree.delete(item)
        query = self.inventory_filter_var.get().strip().lower() if hasattr(self, "inventory_filter_var") else ""
        status_filter = self.inventory_status_filter_var.get() if hasattr(self, "inventory_status_filter_var") else "全部状态"
        type_filter = self.inventory_type_filter_var.get() if hasattr(self, "inventory_type_filter_var") else "全部类别"
        accounts = list(dict.fromkeys([*self.accounts, *(monster.account for monster in self.inventory if monster.account)]))
        if accounts != self.accounts:
            self.accounts = accounts
            save_accounts(self.accounts)
        if hasattr(self, "account_combo"):
            self.account_combo.configure(values=tuple(accounts or ("主账号",)))
        if hasattr(self, "batch_account_combo"):
            self.batch_account_combo.configure(values=tuple(accounts or ("主账号",)))
        if hasattr(self, "inventory_account_filter"):
            self.inventory_account_filter.configure(values=("全部账号", *accounts))
            if self.inventory_account_filter_var.get() not in {"全部账号", *accounts}:
                self.inventory_account_filter_var.set("全部账号")
        account_filter = self.inventory_account_filter_var.get() if hasattr(self, "inventory_account_filter_var") else "全部账号"
        visible_count = 0
        for monster in self.inventory:
            haystack = " ".join(
                (
                    monster.account,
                    monster.page,
                    monster.slot,
                    monster.position_label,
                    monster.species,
                    monster.gender,
                    "性别待确认" if monster.gender_unconfirmed else "",
                    "头目" if monster.is_alpha else "普通",
                    monster.nature,
                    monster.iv_string,
                    monster.group_string,
                    monster.notes,
                )
            ).lower()
            if query and query not in haystack:
                continue
            if status_filter == "已确认" and not monster.verified:
                continue
            if status_filter == "待核对" and monster.verified:
                continue
            if type_filter == "头目" and not monster.is_alpha:
                continue
            if type_filter == "普通" and monster.is_alpha:
                continue
            if account_filter != "全部账号" and monster.account != account_filter:
                continue
            confidence = "" if monster.confidence is None else f"{monster.confidence:.0%}"
            self.inventory_tree.insert(
                "",
                END,
                iid=monster.id,
                values=(
                    monster.account,
                    monster.position_label or "未定位",
                    "已确认" if monster.verified else "待核对",
                    monster.species,
                    (
                        "待确认（本路线无需）"
                        if monster.gender_unconfirmed
                        else {"F": "母", "M": "公", "N": "无性别"}.get(monster.gender, "未识别")
                    ),
                    "头目" if monster.is_alpha else "普通",
                    "已解锁" if monster.has_hidden_ability else "否",
                    monster.nature,
                    monster.iv_string,
                    monster.group_string,
                    "、".join(monster.moves),
                    confidence,
                ),
                tags=("verified" if monster.verified else "pending",),
            )
            visible_count += 1
        if hasattr(self, "inventory_summary_var"):
            verified_count = sum(1 for monster in self.inventory if monster.verified)
            self.inventory_summary_var.set(
                f"显示 {visible_count} / {len(self.inventory)} 条 · 已确认 {verified_count} · 双击编辑"
            )
        if hasattr(self, "plan_excluded_ids"):
            inventory_ids = {monster.id for monster in self.inventory}
            self.plan_excluded_ids.intersection_update(inventory_ids)
            self.plan_exclusion_history = [
                material_id
                for material_id in getattr(self, "plan_exclusion_history", [])
                if material_id in self.plan_excluded_ids
            ]
            self._update_plan_exclusion_ui()
        self._on_inventory_selection_changed()

    def _on_inventory_selection_changed(self, _event=None) -> None:
        if not hasattr(self, "inventory_tree"):
            return
        count = len(self.inventory_tree.selection())
        if hasattr(self, "inventory_selection_var"):
            self.inventory_selection_var.set("未选择素材" if count == 0 else f"已选择 {count} 项")
        if hasattr(self, "inventory_delete_button"):
            self.inventory_delete_button.configure(
                text="删除选中" if count <= 1 else f"批量删除 {count} 项",
                state="normal" if count else "disabled",
            )

    def select_all_inventory(self, _event=None) -> str:
        children = self.inventory_tree.get_children()
        if children:
            self.inventory_tree.selection_set(children)
            self.inventory_tree.focus(children[0])
        self._on_inventory_selection_changed()
        return "break"

    def check_inventory_duplicates(self) -> None:
        """Review high-confidence visible-field matches without changing inventory."""
        groups = find_high_confidence_duplicate_groups(self.inventory)
        if not groups:
            self.status_var.set("重复检查完成：素材库里面没有重复素材。")
            messagebox.showinfo("重复检查", "素材库里面没有重复素材。")
            return

        pair_count = sum(
            1
            for group in groups
            for left_index in range(len(group) - 1)
            for right_index in range(left_index + 1, len(group))
            if are_high_confidence_duplicates(group[left_index], group[right_index])
        )
        window = self._new_child_window()
        window.title("重复素材检查")
        window.geometry("1180x620")
        window.minsize(820, 460)
        window.transient(self.root)

        header = ttk.Frame(window, style="App.TFrame", padding=(14, 12, 14, 8))
        header.pack(fill=X)
        ttk.Label(
            header,
            text=f"发现 {len(groups)} 组高度重复素材 · {pair_count} 对记录",
            style="Section.TLabel",
        ).pack(anchor="w")
        ttk.Label(
            header,
            text="判定条件：名字、性别、性格和六项 IV 一致，技能相同；也会包含 OCR 恰好少识别 1 个技能的高度疑似项。只检查，不自动删除。",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(4, 0))

        body = ttk.Frame(window, style="Panel.TFrame", padding=10)
        body.pack(fill=BOTH, expand=True, padx=14, pady=(0, 10))
        columns = ("group", "species", "gender", "nature", "ivs", "moves", "record_a", "record_b")
        tree = ttk.Treeview(body, columns=columns, show="headings", selectmode="browse")
        headings = {
            "group": "重复组",
            "species": "精灵",
            "gender": "性别",
            "nature": "性格",
            "ivs": "个体值",
            "moves": "技能",
            "record_a": "记录 A",
            "record_b": "记录 B",
        }
        widths = {
            "group": 62,
            "species": 96,
            "gender": 52,
            "nature": 62,
            "ivs": 126,
            "moves": 240,
            "record_a": 190,
            "record_b": 190,
        }
        for column in columns:
            tree.heading(column, text=headings[column])
            tree.column(column, width=widths[column], anchor="center" if column != "moves" else "w")
        ybar = ttk.Scrollbar(body, orient="vertical", command=tree.yview)
        xbar = ttk.Scrollbar(body, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
        tree.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)

        gender_names = {"F": "母", "M": "公", "N": "无性别"}
        pair_records: dict[str, tuple[str, str]] = {}
        pair_index = 0
        for group_index, group in enumerate(groups, start=1):
            for left_index in range(len(group) - 1):
                for right_index in range(left_index + 1, len(group)):
                    left_monster = group[left_index]
                    right_monster = group[right_index]
                    if not are_high_confidence_duplicates(left_monster, right_monster):
                        continue
                    pair_index += 1
                    item_id = f"pair-{pair_index}"
                    pair_records[item_id] = (left_monster.id, right_monster.id)
                    tree.insert(
                        "",
                        END,
                        iid=item_id,
                        values=(
                            f"第 {group_index} 组",
                            left_monster.species,
                            gender_names.get(left_monster.gender, left_monster.gender),
                            left_monster.nature,
                            left_monster.iv_string,
                            "、".join(left_monster.moves),
                            self._duplicate_record_label(left_monster),
                            self._duplicate_record_label(right_monster),
                        ),
                        tags=("duplicate_even" if group_index % 2 == 0 else "duplicate_odd",),
                    )
        tree.tag_configure("duplicate_odd", background=UI_COLORS["warning_soft"], foreground=UI_COLORS["warning_text"])
        tree.tag_configure("duplicate_even", background=UI_COLORS["accent_soft"], foreground=UI_COLORS["ink_blue"])

        footer = ttk.Frame(window, padding=(14, 0, 14, 12))
        footer.pack(fill=X)
        ttk.Label(footer, text="选择一行后可回到库存定位其中一条记录。", style="Muted.TLabel").pack(side=LEFT)
        ttk.Button(footer, text="关闭", command=window.destroy).pack(side=RIGHT)
        ttk.Button(
            footer,
            text="定位记录 B",
            command=lambda: self._focus_duplicate_record(tree, pair_records, 1, window),
        ).pack(side=RIGHT, padx=(6, 6))
        ttk.Button(
            footer,
            text="定位记录 A",
            command=lambda: self._focus_duplicate_record(tree, pair_records, 0, window),
        ).pack(side=RIGHT)
        self._bind_popup_escape(window)
        first = tree.get_children()
        if first:
            tree.selection_set(first[0])
            tree.focus(first[0])
        tree.focus_set()
        self.status_var.set(f"重复检查完成：发现 {len(groups)} 组、{pair_count} 对高度重复素材。")

    @staticmethod
    def _duplicate_record_label(monster: Monster) -> str:
        category = "头目" if monster.is_alpha else "普通"
        short_id = monster.id[:8] if monster.id else "无编号"
        return f"{monster.account} · {category} · #{short_id}"

    def _focus_duplicate_record(
        self,
        tree: ttk.Treeview,
        pair_records: dict[str, tuple[str, str]],
        side: int,
        window: Toplevel,
    ) -> None:
        selected = tree.selection()
        if not selected:
            messagebox.showinfo("未选择记录", "请先在重复结果中选择一行。", parent=window)
            return
        record_id = pair_records.get(selected[0], ("", ""))[side]
        if not record_id:
            return
        self.inventory_filter_var.set("")
        self.inventory_status_filter_var.set("全部状态")
        self.inventory_type_filter_var.set("全部类别")
        self.inventory_account_filter_var.set("全部账号")
        self.refresh_inventory_tree()
        self.workspace_mode_var.set("素材库存")
        self.right_tabs.select(self.inventory_tab)
        self._set_compact_scan_view("result")
        if self.inventory_tree.exists(record_id):
            self.inventory_tree.selection_set(record_id)
            self.inventory_tree.focus(record_id)
            self.inventory_tree.see(record_id)
        self.root.lift()

    def edit_inventory_selected(self, event=None) -> str:
        if event is not None:
            row_id = self.inventory_tree.identify_row(event.y)
            if not row_id:
                return "break"
            self.inventory_tree.selection_set(row_id)
            self.inventory_tree.focus(row_id)
        self.inventory_selected()
        if self.inventory_tree.selection():
            self.right_tabs.select(self.current_tab)
            self.current_form_expanded = True
            self._set_compact_scan_view("result")
            if hasattr(self, "current_species_entry"):
                self.root.after_idle(self.current_species_entry.focus_set)
        return "break"

    def inventory_selected(self, _event=None) -> None:
        selected = self.inventory_tree.selection()
        if not selected:
            return
        monster = next((item for item in self.inventory if item.id == selected[0]), None)
        if monster:
            self.editing_monster_id = monster.id
            self.save_monster_button.configure(text="更新选中素材并标记已核对")
            self.current_source = monster.source
            self.page_var.set(monster.page)
            self.slot_var.set(monster.slot)
            self.account_var.set(monster.account)
            self.species_var.set(monster.species)
            self.gender_var.set(monster.gender)
            self.nature_var.set(monster.nature)
            self.alpha_var.set("头目" if monster.is_alpha else "普通")
            self.hidden_ability_var.set(monster.has_hidden_ability)
            self.iv_var.set(monster.iv_string)
            self.ability_var.set(monster.ability)
            self.item_var.set(monster.held_item)
            self.groups_var.set(monster.group_string)
            self.moves_var.set(", ".join(monster.moves))
            self.source_var.set(monster.source)
            self.ocr_confidence_var.set(
                "OCR 置信度：—" if monster.confidence is None else f"OCR 置信度：{monster.confidence:.0%}"
            )
            gender_text = (
                "待确认（原路线与百变怪孵化时未记录）"
                if monster.gender_unconfirmed
                else {"F": "母", "M": "公", "N": "无性别"}.get(monster.gender, "未识别")
            )
            self.raw_text_box.delete("1.0", END)
            self.raw_text_box.insert(
                "1.0",
                "\n".join(
                    (
                        f"名字：{monster.species}",
                        f"性别：{gender_text}",
                        f"个体值：{monster.iv_string}",
                        f"性格：{monster.nature or '未识别'}",
                        f"梦特：{'已解锁' if monster.has_hidden_ability else '否'}",
                        f"技能：{'、'.join(monster.moves) if monster.moves else '未识别'}",
                        f"类别：{'头目' if monster.is_alpha else '普通'}",
                    )
                ),
            )
            pending_gender_note = " 请在性别栏选择实际公/母；保存后才能用于普通配对。" if monster.gender_unconfirmed else ""
            self.status_var.set(
                f"正在编辑 {monster.species}（{'已确认' if monster.verified else '待核对'}）。"
                f"保存后会更新原记录。{pending_gender_note}"
            )

    def delete_selected_inventory(self) -> None:
        selected = tuple(self.inventory_tree.selection())
        if not selected:
            messagebox.showinfo("未选择素材", "请先在库存表格中选择要删除的记录。")
            return
        selected_set = set(selected)
        monsters = [item for item in self.inventory if item.id in selected_set]
        if not monsters:
            return
        sample = "、".join(item.species for item in monsters[:4])
        if len(monsters) > 4:
            sample += f"等 {len(monsters)} 只"
        affected_plan = bool(
            self.active_plan
            and any(
                not step.completed and selected_set.intersection((step.parent_a_id, step.parent_b_id))
                for step in self.active_plan.steps
            )
        )
        plan_note = "\n\n其中包含当前执行方案使用的素材；删除后该方案会被取消，需要重新规划。" if affected_plan else ""
        if not messagebox.askyesno(
            "确认批量删除素材" if len(monsters) > 1 else "确认删除素材",
            f"确定从本地库存删除 {sample} 吗？\n\n删除 {len(monsters)} 条，可使用“撤销删除”一次性恢复。"
            f"{plan_note}\n\n此操作不会影响游戏内数据。",
        ):
            return
        try:
            deleted = delete_inventory_records(selected)
        except Exception as exc:
            messagebox.showerror("删除失败", str(exc))
            return
        deleted_ids = {item.id for item in deleted}
        self.inventory = [item for item in self.inventory if item.id not in deleted_ids]
        if self.editing_monster_id in deleted_ids:
            self.editing_monster_id = None
        if affected_plan:
            self.active_plan = None
            save_active_plan(None)
        self.refresh_inventory_tree()
        self.refresh_plan_status()
        self.status_var.set(f"已删除 {len(deleted)} 只素材，库存剩余 {len(self.inventory)} 只；可点击“撤销删除”恢复。")

    def undo_last_inventory_delete(self) -> None:
        try:
            restored = undo_last_inventory_deletion()
        except Exception as exc:
            messagebox.showerror("撤销删除失败", str(exc))
            return
        if not restored:
            messagebox.showinfo("没有删除记录", "没有可以撤销的库存删除记录。")
            return
        self.inventory = load_inventory()
        self.refresh_inventory_tree()
        restored_ids = [item.id for item in restored if self.inventory_tree.exists(item.id)]
        if restored_ids:
            self.inventory_tree.selection_set(restored_ids)
            self.inventory_tree.focus(restored_ids[0])
            self.inventory_tree.see(restored_ids[0])
        self._on_inventory_selection_changed()
        self.status_var.set(f"已恢复最近一次删除的 {len(restored)} 只素材。")

    def export_inventory(self) -> None:
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")])
        if not path:
            return
        try:
            Path(path).write_text(__import__("json").dumps([item.to_dict() for item in self.inventory], ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("导出失败", str(exc))

    def import_inventory(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            imported = [Monster.from_dict(item) for item in data if isinstance(item, dict)]
        except Exception as exc:
            messagebox.showerror("导入失败", str(exc))
            return
        by_id = {item.id: item for item in self.inventory}
        for item in imported:
            if not item.id:
                item.id = str(uuid.uuid4())
            by_id[item.id] = item
        self.inventory = list(by_id.values())
        self._enrich_inventory()
        save_inventory(self.inventory)
        self.refresh_inventory_tree()
        self.status_var.set(f"已导入 {len(imported)} 条素材。")

    def generate_plan(self) -> None:
        if self.plan_worker_busy:
            messagebox.showinfo("正在计算", "库存规划仍在计算中，请稍候。")
            return
        record = self.lookup_target_species(silent=False)
        if record is None:
            return
        target_iv = self._collect_target_iv_string()
        if target_iv is None:
            return
        target_gender = self._requested_target_gender(
            record,
            bool(self.target_lock_gender_var.get()),
            self.target_gender_var.get(),
            self.species_db.required_evolution_gender(record),
        )
        target_nature, nature_strategy = self._requested_target_nature(
            self.target_nature_var.get(),
            bool(self.target_lock_nature_var.get()),
        )
        breeding_parent = self.species_db.breeding_parent(record)
        groups = list(breeding_parent.egg_groups if breeding_parent else record.egg_groups)
        snapshot = [Monster.from_dict(item.to_dict()) for item in self.inventory]
        allow_ditto = bool(self.target_allow_ditto_var.get())
        allow_alpha_materials = bool(self.target_allow_alpha_materials_var.get())
        if self.target_alpha_var.get() == "普通" and not allow_alpha_materials:
            family_names = {
                item.display_name
                for item in (
                    self.species_db.linked_breeding_family(record)
                    or self.species_db.evolution_line(record)
                )
            } or {record.display_name}
            normal_scope, alpha_scope, alpha_ditto_scope = self._plan_material_scope_counts(
                snapshot,
                family_names,
                set(groups),
                allow_ditto,
            )
            warning_key = (
                record.id,
                tuple(sorted(item.id for item in snapshot if item.verified and item.is_alpha)),
                allow_ditto,
            )
            if (
                alpha_scope
                and not normal_scope
                and getattr(self, "alpha_scope_declined_key", None) != warning_key
            ):
                ditto_note = f"，其中百变怪 {alpha_ditto_scope} 只" if alpha_ditto_scope else ""
                use_alpha = messagebox.askyesno(
                    "检测到头目库存素材",
                    f"当前目标是普通精灵，但库存中与本路线相关的 {alpha_scope} 只已确认素材全部是头目"
                    f"{ditto_note}。\n\n"
                    "若继续保护头目素材，规划器无法使用它们，底层节点会改为交易行采购。\n\n"
                    "是否为本次规划开启“普通目标允许使用头目素材”？\n\n"
                    "是：允许这些库存素材参与，最终子代仍严格为普通。\n"
                    "否：继续保护这些头目素材。",
                )
                if use_alpha:
                    self.target_allow_alpha_materials_var.set(True)
                    allow_alpha_materials = True
                    self.alpha_scope_declined_key = None
                    self._on_target_alpha_changed()
                else:
                    self.alpha_scope_declined_key = warning_key
        excluded_snapshot = frozenset(self.plan_excluded_ids)
        request = (
            snapshot,
            record.display_name,
            target_gender,
            target_nature,
            target_iv,
            groups,
            self.target_alpha_var.get() == "头目",
            allow_ditto,
            "steps" if self.target_strategy_var.get() == "步骤优先" else "inventory",
            nature_strategy,
            allow_alpha_materials,
            excluded_snapshot,
            self.target_intermediate_gender_strategy_var.get(),
            bool(self.target_hidden_ability_var.get()),
            tuple(self.selected_egg_moves),
            bool(self.target_convert_mother_with_ditto_var.get()),
            frozenset(self.auto_replan_preferred_material_ids),
        )
        self._set_planner_busy(True)
        self.plan_status_var.set(
            f"正在从 {sum(item.verified and item.id not in excluded_snapshot for item in snapshot)} 条可用已确认库存中"
            f"按{self.target_strategy_var.get()}搜索最佳路线"
            + (f"（本次保护 {len(excluded_snapshot)} 只）……" if excluded_snapshot else "……")
        )

        def worker() -> None:
            try:
                report, candidates = make_report_with_candidates(*request)
                self.plan_result_queue.put((report, candidates, ""))
            except Exception as exc:
                self.plan_result_queue.put(("", [], str(exc)))

        threading.Thread(target=worker, name="breed-planner", daemon=True).start()
        self.root.after(100, self._poll_plan_result)

    def _poll_plan_result(self) -> None:
        try:
            report, candidates, error = self.plan_result_queue.get_nowait()
        except queue.Empty:
            if self.plan_worker_busy:
                self.root.after(100, self._poll_plan_result)
            return
        if error:
            self.auto_activate_replan_pending = False
            self.auto_replan_reason = ""
            self.auto_replan_progress_keys.clear()
            self.auto_replan_preferred_material_ids.clear()
            self._set_planner_busy(False)
            self.plan_status_var.set(f"规划失败：{error}")
            messagebox.showerror("规划失败", error)
            return
        self.current_candidates = candidates
        self.proposed_plan = build_execution_plan(candidates[0]) if candidates else None
        if self.proposed_plan is not None and candidates:
            self.plan_candidate_cache[self.proposed_plan.id] = candidates[0]
        auto_activate = self.auto_activate_replan_pending
        auto_reason = self.auto_replan_reason
        self.auto_activate_replan_pending = False
        self.auto_replan_reason = ""
        auto_activated = bool(auto_activate and self.proposed_plan and self.proposed_plan.steps)
        if auto_activated:
            self.active_plan = self.proposed_plan
            for step in self.active_plan.steps:
                if self._plan_step_progress_key(step) in self.auto_replan_progress_keys:
                    step.in_progress = True
            self.auto_replan_progress_keys.clear()
            save_active_plan(self.active_plan.to_dict())
        elif auto_activate:
            self.auto_replan_progress_keys.clear()
        self.auto_replan_preferred_material_ids.clear()
        self._render_plan_tree(candidates[0] if candidates else None, report)
        if self.proposed_plan is None:
            self.plan_status_var.set("没有可执行方案。请检查目标和库存。")
        elif not self.proposed_plan.steps:
            candidate = candidates[0]
            actual_species = candidate.root.leaf.species if candidate.root.leaf else candidate.root.output_species
            if actual_species != candidate.target_species:
                self.plan_status_var.set(
                    f"库存中已有满足属性的 {actual_species}；无需孵化，进化为 {candidate.target_species} 即可。"
                )
            else:
                self.plan_status_var.set("库存中已经有满足目标的成品，不需要执行孵化步骤。")
        elif auto_activated:
            self.plan_status_var.set(
                f"已根据实际结果（{auto_reason or '库存变化'}）自动局部重算并启用剩余路线。"
                f"{self.active_plan.status_text()}"
            )
        elif self.proposed_plan.purchase_requirements:
            self.plan_status_var.set(
                "路线包含交易行补购素材；购买后可直接勾选对应孵化节点完成，"
                "不需要将购买素材 OCR 扫描入库。"
            )
        else:
            self.plan_status_var.set("最佳路线全部由现有库存组成。确认无误后点击“启用最佳方案”。")
        if self.plan_excluded_ids:
            self.plan_status_var.set(
                f"{self.plan_status_var.get()} 本次已保护 {len(self.plan_excluded_ids)} 只库存素材。"
            )
        self._set_planner_busy(False)
        self._update_plan_compact_summary()
        if self.proposed_plan is not None:
            self._set_planner_details_collapsed(True)

    @staticmethod
    def _plan_state_iv_text(state: ChainState, candidate: ChainCandidate) -> str:
        if state.action is None and state.leaf is not None:
            return state.leaf.iv_string.upper()
        return "/".join(
            str(candidate.target_ivs[index])
            if candidate.target_ivs[index] is not None and state.mask & (1 << index)
            else "X"
            for index in range(6)
        )

    @staticmethod
    def _iv_badge(values: list[int | None] | tuple[int | None, ...]) -> str:
        perfect = sum(value == 31 for value in values[:6])
        custom = sum(value is not None and value != 31 for value in values[:6])
        return f"{perfect}V" + (f"+{custom}项精确" if custom else "")

    def _latest_failed_nature_material(
        self,
        candidate: ChainCandidate,
        *,
        role: str,
        level: int,
        gender: str,
    ) -> Monster | None:
        matches = [
            monster
            for monster in self.inventory
            if monster.verified
            and monster.breeding_target_key == candidate.nature_target_key
            and monster.breeding_role == role
            and monster.nature_attempt_level == level
            and monster.nature_attempt_result == "miss"
            and monster.gender == gender
        ]
        if not matches:
            return None
        return max(
            matches,
            key=lambda monster: (monster.updated_at, monster.created_at, monster.id),
        )

    def _failed_nature_material_node(
        self,
        candidate: ChainCandidate,
        monster: Monster,
        *,
        map_key_prefix: str,
        role: str,
        species_sprite_id,
    ) -> MindMapNode:
        position = monster.position_label
        source = f"{monster.account} {position}" if position else f"{monster.account} 未定位"
        material_v = f"{sum(value == 31 for value in monster.ivs[:6])}V"
        if role == "maternal":
            display_species = candidate.target_species or monster.species
            title = f"已保留{material_v}母体（未爆性格） · {display_species}"
            if display_species != monster.species:
                source += f" · 当前形态 {monster.species}"
        else:
            title = f"已保留{material_v}性格手（未爆性格） · {monster.species}"
        return MindMapNode(
            key=f"{map_key_prefix}-nature-history-{monster.id}",
            title=title,
            iv_text=material_v,
            iv_values=tuple("X" if value is None else str(value) for value in monster.ivs[:6]),
            detail=f"{source} · {gender_name(monster.gender)} · {monster.nature or '非目标性格'}",
            item_text="已保留：等待后续性格合成",
            status_text="已完成入库",
            nature_text="爆性格：否",
            kind="completed",
            completed=True,
            show_checkbox=True,
            species_id=species_sprite_id(monster.species),
        )

    def _wrap_staged_nature_context(
        self,
        candidate: ChainCandidate,
        current_root: MindMapNode,
        *,
        map_key_prefix: str,
        species_sprite_id,
    ) -> MindMapNode:
        """Add parked failed materials around the currently executable gamble branch.

        These nodes are explanatory only.  The execution plan still contains
        exactly the steps in ``candidate.root`` so a user cannot accidentally
        re-consume a saved 5V mother or a failed 4V nature hand.
        """
        if (
            not candidate.target_nature
            or candidate.nature_phase not in {"gamble_upper", "gamble_lower"}
            or not candidate.nature_target_key
        ):
            return current_root

        target_level = sum(value is not None for value in candidate.target_ivs)
        upper_level = max(1, target_level - 1)
        lower_level = max(1, target_level - 2)
        body = self._latest_failed_nature_material(
            candidate,
            role="maternal",
            level=target_level,
            gender="F",
        )
        upper = self._latest_failed_nature_material(
            candidate,
            role="nature_hand",
            level=upper_level,
            gender="M",
        )

        staged_branch = current_root
        if candidate.nature_phase == "gamble_lower" and upper is not None:
            upper_history = self._failed_nature_material_node(
                candidate,
                upper,
                map_key_prefix=map_key_prefix,
                role="nature_hand",
                species_sprite_id=species_sprite_id,
            )
            staged_branch = MindMapNode(
                key=f"{map_key_prefix}-nature-preview-{upper_level}",
                title=f"性格手目标 · {upper_level}V {candidate.target_nature}",
                iv_text=f"{upper_level}V",
                iv_values=tuple("X" if value is None else str(value) for value in upper.ivs[:6]),
                detail=(
                    f"保留的 {upper_level}V 未命中素材，与本轮 {lower_level}V "
                    f"爆性格结果合成为对性 {upper_level}V 性格手"
                ),
                item_text="后续合成：未命中素材携带缺项护腕 · 爆性格素材携带不变之石",
                status_text="后续合成预览",
                nature_text=f"目标性格：{candidate.target_nature}",
                kind="target",
                species_id=species_sprite_id(upper.species),
                item_keys=("everstone",),
                children=[upper_history, current_root],
            )

        if body is None:
            return staged_branch

        body_history = self._failed_nature_material_node(
            candidate,
            body,
            map_key_prefix=map_key_prefix,
            role="maternal",
            species_sprite_id=species_sprite_id,
        )
        offspring = candidate.offspring_species or candidate.target_species
        evolution = (
            f"；孵出 {offspring} 后进化为 {candidate.target_species}"
            if offspring and candidate.target_species and offspring != candidate.target_species
            else ""
        )
        return MindMapNode(
            key=f"{map_key_prefix}-nature-preview-target",
            title=(
                f"孵蛋目标 · {self._iv_badge(candidate.target_ivs)} "
                f"{candidate.target_nature} · {candidate.target_species or offspring}"
            ),
            iv_text=f"{sum(value == 31 for value in candidate.target_ivs[:6])}V",
            iv_values=tuple("X" if value is None else str(value) for value in candidate.target_ivs[:6]),
            detail=f"保留未命中母体，等待右侧性格手完成后进行最终合成{evolution}",
            item_text="最终合成：母体携带缺项护腕 · 性格手携带不变之石",
            status_text="后续合成预览",
            nature_text=f"目标性格：{candidate.target_nature}",
            kind="target",
            species_id=species_sprite_id(candidate.target_species or offspring),
            item_keys=("everstone",),
            children=[body_history, staged_branch],
        )

    def _render_plan_tree(self, candidate: ChainCandidate | None, fallback_report: str = "") -> None:
        if not hasattr(self, "plan_map"):
            return
        if candidate is None:
            self.plan_summary_var.set("未找到能严格保证目标结果的路线。")
            self.plan_purchase_var.set(fallback_report.strip() or "请检查目标精灵、蛋组、性别、性格与库存素材。")
            self.plan_purchase_label.configure(style="Warning.TLabel")
            self._set_plan_map_root(None, "暂无可执行路线｜请检查目标与库存")
            return

        root = candidate.root
        audit_text = candidate.inventory_audit_text()
        if root.action is None:
            actual_species = root.leaf.species if root.leaf else root.output_species
            if actual_species != candidate.target_species:
                self.plan_summary_var.set(
                    f"库存预检｜{audit_text}\n库存已有满足属性的 {actual_species}；无需孵化，进化为 {candidate.target_species} 即可。"
                )
            else:
                self.plan_summary_var.set(f"库存预检｜{audit_text}\n库存中已经有满足目标的成品，不需要继续孵化。")
        else:
            target_route = (
                f" · 孵出 {candidate.offspring_species} 后进化为 {candidate.target_species}"
                if candidate.target_species != candidate.offspring_species
                else ""
            )
            target_exact = sum(value is not None for value in candidate.target_ivs)
            target_v = sum(value == 31 for value in candidate.target_ivs)
            custom_count = target_exact - target_v
            target_label = f"{target_v}V" + (f"+{custom_count}项精确" if custom_count else "")
            if candidate.target_nature and candidate.nature_strategy == "late" and target_exact >= 2:
                phase = candidate.nature_phase
                if phase == "maternal":
                    nature_route = (
                        f"\n母体阶段｜先把雌性本体升到 {target_label}；"
                        f"低于 {target_exact - 1} 项精确不统计爆性格，"
                        f"只在母体最后两档确认是否命中 {candidate.target_nature}。"
                    )
                elif phase == "gamble_upper":
                    nature_route = (
                        f"\n主动赌性格手①｜满档母体未命中；本轮制作 "
                        f"{candidate.nature_attempt_level} 项精确的雄性素材，孵出后确认性格。"
                    )
                elif phase == "gamble_lower":
                    nature_route = (
                        f"\n主动赌性格手②｜上一档未命中；本轮降至 "
                        f"{candidate.nature_attempt_level} 项精确并锁母，再确认一次性格。"
                    )
                elif phase == "promote":
                    nature_route = (
                        f"\n性格手升档｜低档素材已命中 {candidate.target_nature}；"
                        "后续逐层使用不变之石，不再统计随机性格。"
                    )
                elif phase == "guarantee":
                    nature_route = (
                        f"\n最终保底｜可赌档位均未命中或已到最低档；"
                        f"现在才补购最低档 {candidate.target_nature} 素材或百变怪，并用不变石升档。"
                    )
                elif phase == "finish":
                    nature_route = (
                        f"\n性格收尾｜库存已有可用的 {candidate.target_nature} 高档素材；"
                        "直接使用不变之石与母体主线合成。"
                    )
                elif root.has_nature:
                    nature_route = f"\n性格收尾｜已锁定 {candidate.target_nature}，后续仅做 IV 合并。"
                else:
                    nature_route = ""
            elif candidate.target_nature:
                nature_route = f"\n不变石链｜沿性格支线逐级锁定 {candidate.target_nature}。"
            else:
                nature_route = ""
            self.plan_summary_var.set(
                f"库存预检｜{audit_text}\n"
                f"推荐方案｜复用库存 {root.existing_leaves} 只 · 补购 {root.purchases} 只 · "
                f"孵化 {root.breeds} 次 · 护腕 {root.braces} 个 · 不变之石 {root.everstones} 个{target_route}"
                f"{nature_route}\n"
                + ("梦特路线｜成品必须保留梦特潜力；同进化线梦特父母会沿主线传递。\n" if candidate.target_hidden_ability else "")
                + (f"遗传技能｜{'、'.join(candidate.target_moves)}；技能素材需沿主线持续保留。\n" if candidate.target_moves else "")
                + (
                    "母体转换｜本路线仅在起点使用一次目标公体＋百变怪锁母；其余支线继续遵守百变怪总开关。\n"
                    if root.maternal_conversion
                    else ""
                )
                + f"中间性别｜{self.target_intermediate_gender_strategy_var.get()}；随机节点核销后记录实际性别并自动重算。"
            )

        egg_route_note = ""
        if candidate.target_moves:
            offspring = self.species_db.get(candidate.offspring_species, fuzzy=True)
            routes_by_move = self.reference_db.egg_moves_for_species(offspring.id) if offspring else {}
            route_lines: list[str] = []
            for move in candidate.target_moves:
                routes = routes_by_move.get(move, ())
                if not routes:
                    route_lines.append(f"{move}：暂无内置传递链，请人工核对来源")
                    continue
                # Prefer the shortest direct donor route; the picker still keeps
                # every alternative for users who want a different species.
                route = min(routes, key=lambda value: (value.count("<="), len(value), value))
                route_lines.append(f"{move}：{route} → {candidate.offspring_species}")
            egg_route_note = "\n遗传技能前置｜" + "；".join(route_lines)

        requirements = candidate.purchase_requirements()
        if requirements:
            self.plan_purchase_var.set(
                f"仅靠库存无法完成，还需手动采购 {root.purchases} 只。"
                "雌性目标线负责出种；雄性缺料按同蛋组通用父本列出。"
                "橙色素材购买后直接按路线孵化；确认节点完成时自动视为已使用，无需 OCR 入库。"
                + egg_route_note
            )
            self.plan_purchase_label.configure(style="Warning.TLabel")
        else:
            self.plan_purchase_var.set(
                "仅库存即可完成；所有叶子素材均已绑定本地记录，勾选步骤会自动核销父母。"
                + egg_route_note
            )
            self.plan_purchase_label.configure(style="Success.TLabel")

        step_numbers: dict[int, int] = {}
        counter = 0

        def execution_children(state: ChainState) -> list[ChainState]:
            if state.action is None:
                return []
            children = [state.action.parent_a, state.action.parent_b]
            children.sort(
                key=lambda child: (
                    child.purchases > 0,
                    child.purchases,
                    -child.inventory_breeds,
                    child.breeds,
                )
            )
            return children

        def number_steps(state: ChainState) -> None:
            nonlocal counter
            if state.action is None:
                return
            for child in execution_children(state):
                number_steps(child)
            counter += 1
            step_numbers[id(state)] = counter

        number_steps(root)
        same_active_plan = bool(
            self.active_plan
            and self.proposed_plan
            and self.active_plan.id == self.proposed_plan.id
        )
        display_plan = self.active_plan if same_active_plan else self.proposed_plan
        map_key_prefix = display_plan.id if display_plan else f"candidate-{id(candidate)}"
        step_by_number = {step.number: step for step in display_plan.steps} if display_plan else {}
        ready_step_numbers = {
            step.number for step in self.active_plan.ready_steps
        } if same_active_plan and self.active_plan else set()
        frontier_step_numbers = {
            step.number for step in self.active_plan.frontier_steps
        } if same_active_plan and self.active_plan else set()
        target_mask = sum(1 << index for index, value in enumerate(candidate.target_ivs) if value is not None)

        def state_v(state: ChainState) -> int:
            return sum(
                bool(state.mask & (1 << index)) and candidate.target_ivs[index] == 31
                for index in range(6)
            )

        def state_iv_summary(state: ChainState) -> str:
            perfect = state_v(state)
            custom = sum(
                bool(state.mask & (1 << index))
                and candidate.target_ivs[index] is not None
                and candidate.target_ivs[index] != 31
                for index in range(6)
            )
            return f"{perfect}V" + (f"+{custom}项精确" if custom else "")

        def species_sprite_id(species: str) -> int | None:
            record = self.species_db.get(species, fuzzy=True)
            return record.id if record is not None else None

        def item_asset_keys(*items: str) -> tuple[str, ...]:
            return tuple(
                PLAN_ITEM_ASSET_KEYS[item]
                for item in items
                if item in PLAN_ITEM_ASSET_KEYS
            )

        def state_nature_text(state: ChainState) -> str:
            return state.nature if state.has_nature and state.nature else "随机性格"

        def leaf_role(state: ChainState) -> str:
            assert state.leaf is not None
            if state.leaf.source.startswith("孵化方案"):
                return "已完成子代"
            if any(move in state.leaf.moves for move in candidate.target_moves):
                return "遗传技能父本"
            if state.is_virtual:
                return "交易行素材"
            if state.leaf.gender == "M":
                return "同组父本"
            if state.leaf.gender == "F" and state.species == candidate.offspring_species:
                return "母系出种"
            if state.leaf.gender == "F":
                return "中转母系"
            return "库存素材"

        def build_node(state: ChainState, edge_item: str = "", depth: int = 0, is_root: bool = False) -> MindMapNode:
            if state.action is None and state.leaf is not None:
                monster = state.leaf
                role = leaf_role(state)
                source = "手动采购" if state.is_virtual else (
                    f"{monster.account} {monster.position_label}" if monster.position_label else f"{monster.account} 未定位"
                )
                nature_badge = "目标性格素材" if state.has_nature and candidate.target_nature else ""
                hatched_result = monster.source.startswith("孵化方案")
                leaf_values = tuple("X" if value is None else str(value) for value in monster.ivs[:6])
                feature_bits = []
                if monster.has_hidden_ability:
                    feature_bits.append("梦特已解锁")
                inherited = [move for move in candidate.target_moves if move in monster.moves]
                if inherited:
                    feature_bits.append("技能 " + "、".join(inherited))
                return MindMapNode(
                    key=f"{map_key_prefix}-leaf-{id(state)}",
                    title=f"{role} · {monster.species}",
                    iv_text=f"{sum(value == 31 for value in monster.ivs)}V",
                    iv_values=leaf_values,
                    detail=f"{source} · {gender_name(monster.gender)} · {monster.nature or '性格未知'}"
                    + (" · " + " · ".join(feature_bits) if feature_bits else ""),
                    item_text=f"本只携带：{edge_item or '无需道具'}",
                    status_text="待采购" if state.is_virtual else ("已完成入库" if hatched_result else "库存"),
                    nature_text=nature_badge,
                    kind="purchase" if state.is_virtual else "inventory",
                    completed=not state.is_virtual,
                    show_checkbox=True,
                    species_id=species_sprite_id(monster.species),
                    item_keys=item_asset_keys(edge_item),
                    exclude_material_id="" if state.is_virtual else monster.id,
                )

            step_number = step_numbers.get(id(state), 0)
            step = step_by_number.get(step_number)
            completed = bool(step and step.completed)
            history_key = (display_plan.id, step_number) if display_plan and step_number else ("", 0)
            history_expanded = history_key in self.expanded_completed_sources
            blocked = bool(step and step.requires_purchase)
            if completed:
                status = "已完成·双击收起" if history_expanded else "已完成·来源折叠"
                kind = "completed"
            elif step and step.in_progress:
                status = "孵化中"
                kind = "in_progress"
            elif step_number in ready_step_numbers:
                status = (
                    "采购后可执行"
                    if blocked
                    else ("可并行执行" if len(ready_step_numbers) > 1 else "当前可执行")
                )
                kind = "purchase" if blocked else "current"
            elif blocked:
                status = "待采购"
                kind = "purchase"
            else:
                status = "待执行" if same_active_plan else "启用后执行"
                kind = "target" if is_root else "pending"

            if is_root:
                category = "头目" if candidate.target_alpha else "普通"
                hatch_species = state.output_species
                special = " 梦特" if candidate.target_hidden_ability else ""
                if candidate.nature_phase == "gamble_upper":
                    title = f"主动赌性格手① · {state_iv_summary(state)} · 锁公"
                elif candidate.nature_phase == "gamble_lower":
                    title = f"主动赌性格手② · {state_iv_summary(state)} · 锁母"
                elif candidate.target_nature and candidate.nature_strategy == "late" and not state.has_nature:
                    title = f"母体主线 · {state_iv_summary(state)} 随机性格 {category}{special} {hatch_species}"
                else:
                    title = f"孵蛋目标 · {state_iv_summary(state)} {candidate.target_nature or '任意性格'} {category}{special} {hatch_species}"
            elif (
                state.action is not None
                and state.maternal_conversion
                and any(is_ditto(parent.species) for parent in (state.action.parent_a, state.action.parent_b))
            ):
                title = f"百变转换母体 · {state_iv_summary(state)} 锁母"
            elif candidate.nature_phase in {"gamble_upper", "gamble_lower"}:
                title = f"性格手素材支线 · {state_iv_summary(state)} {state_nature_text(state)}"
            elif candidate.target_nature and candidate.nature_strategy == "late" and not root.has_nature:
                if state.species == candidate.offspring_species and state.gender == "F":
                    title = f"母体主线 · {state_iv_summary(state)} {state_nature_text(state)}"
                else:
                    title = f"同组素材支线 · {state_iv_summary(state)} {state_nature_text(state)}"
            elif depth == 1 and candidate.target_nature and state.has_nature:
                title = f"性格支线 · {state_iv_summary(state)} {state_nature_text(state)}"
            elif depth == 1 and candidate.target_nature:
                title = f"主 IV 线 · {state_iv_summary(state)} {state_nature_text(state)}"
            else:
                title = f"步骤 {step_number} · {state_iv_summary(state)} {state_nature_text(state)}"

            output_species = state.output_species
            evolution = ""
            if state.breeding_species and state.breeding_species != output_species and not is_root:
                evolution = f" → 下步前进化为 {state.breeding_species}"
            gender_detail = step.gender_instruction if step else gender_name(state.gender)
            feature_bits = []
            if state.has_hidden_ability:
                feature_bits.append("梦特保留")
            inherited = [move for move in candidate.target_moves if move in state.inherited_moves]
            if inherited:
                feature_bits.append("遗传 " + "、".join(inherited))
            introduced = [move for move in candidate.target_moves if move in state.introduced_moves]
            if introduced:
                feature_bits.append("遗传技能导入：" + "、".join(introduced))
            detail = f"{gender_detail} · 子代 {output_species}{evolution}"
            if feature_bits:
                detail += " · " + " · ".join(feature_bits)
            item_text = f"本只携带：{edge_item or '无需道具'}"

            if display_plan and display_plan.target_nature and step:
                if step.uses_everstone:
                    nature_status = "性格：锁定"
                elif display_plan.should_check_nature(step):
                    if completed:
                        nature_status = (
                            "爆性格：是"
                            if step.child.nature == display_plan.target_nature
                            else "爆性格：否"
                        )
                    else:
                        nature_status = "爆性格：待确认"
                elif display_plan.adaptive_nature:
                    nature_status = (
                        "性格：无需统计"
                        if display_plan.nature_phase in {"finish", "promote", "guarantee"}
                        else "性格：暂不统计"
                    )
                else:
                    nature_status = "性格：随机"
            else:
                nature_status = "性格：不要求"

            node = MindMapNode(
                key=f"{map_key_prefix}-step-{step_number}",
                title=("遗传技能导入 · " + title) if introduced else title,
                iv_text=f"{state_v(state)}V",
                iv_values=tuple(self._plan_state_iv_text(state, candidate).split("/")),
                detail=detail,
                item_text=item_text,
                status_text=status,
                nature_text=nature_status,
                kind=kind,
                step_number=step_number or None,
                completed=completed,
                in_progress=bool(step and step.in_progress),
                actionable=bool(step_number in ready_step_numbers),
                show_checkbox=True,
                species_id=species_sprite_id(output_species),
                item_keys=item_asset_keys(edge_item),
                egg_move_highlight=bool(introduced),
                history_toggleable=completed,
                sources_collapsed=bool(completed and not history_expanded),
            )
            if completed and not history_expanded:
                node.children = []
                return node
            children = [
                (state.action.parent_a, state.action.item_a),
                (state.action.parent_b, state.action.item_b),
            ]
            if is_root and candidate.target_nature:
                children.sort(key=lambda pair: pair[0].has_nature)
            else:
                children.sort(
                    key=lambda pair: (
                        pair[0].purchases > 0,
                        pair[0].purchases,
                        -pair[0].inventory_breeds,
                    )
                )
            node.children = [
                build_node(child, item, depth + 1, False)
                for child, item in children
            ]
            return node

        map_root = build_node(root, "", 0, True)
        map_root = self._wrap_staged_nature_context(
            candidate,
            map_root,
            map_key_prefix=map_key_prefix,
            species_sprite_id=species_sprite_id,
        )
        self._set_plan_map_root(map_root)

    def _set_plan_map_root(
        self,
        root: MindMapNode | None,
        empty_message: str = "暂无可显示的路线",
    ) -> None:
        self.plan_map.set_root(root, empty_message)
        detached = self.detached_plan_map
        if detached is not None:
            try:
                if detached.winfo_exists():
                    detached.set_root(root, empty_message)
            except Exception:
                self.detached_plan_map = None
                self.plan_map_window = None

    def _activate_plan_step_number(self, step_number: int):
        plan = self.active_plan
        if plan is None or not self.proposed_plan or plan.id != self.proposed_plan.id:
            messagebox.showinfo("先启用方案", "请先点击“启用最佳方案”，再勾选思维导图中可执行的节点。")
            return "break"
        step = next((item for item in plan.steps if item.number == step_number), None)
        if step is None:
            return "break"
        if step.completed:
            messagebox.showinfo("步骤已完成", "该步骤已经核销。若要恢复，请使用“撤销上一次核销”。")
            return "break"
        if not plan.dependencies_completed(step):
            messagebox.showwarning("依赖尚未完成", "这个节点直接连接的下级子代尚未完成；请先完成它所依赖的节点。")
            return "break"
        self.selected_plan_step_number = step.number
        self.complete_next_step(step)
        return "break"

    def activate_best_plan(self) -> None:
        plan = self.proposed_plan
        if plan is None:
            messagebox.showwarning("没有方案", "请先生成库存优先方案。")
            return
        if not plan.steps:
            messagebox.showinfo("无需执行", "库存中已经有满足目标的成品。")
            return
        if self.active_plan and not self.active_plan.completed:
            if not messagebox.askyesno("替换执行中的方案", "当前还有未完成方案。确定用新方案替换吗？已完成的库存核销不会自动撤销。"):
                return
        self.active_plan = plan
        self.selected_plan_step_number = None
        save_active_plan(plan.to_dict())
        self.refresh_plan_status()
        if plan.purchase_requirements:
            self.status_var.set(
                "路线已启用：橙色交易行素材购买后直接完成对应节点，无需 OCR 扫描入库。"
            )

    def refresh_plan_status(self) -> None:
        if not hasattr(self, "plan_status_var"):
            return
        if self.active_plan is None:
            self._update_plan_action_states()
            if self.current_candidates:
                self._render_plan_tree(self.current_candidates[0])
            return
        self.plan_status_var.set(self.active_plan.status_text())
        self._update_plan_action_states()
        if self.current_candidates:
            self._render_plan_tree(self.current_candidates[0])

    def complete_next_step(self, requested_step: ExecutionStep | None = None) -> None:
        plan = self.active_plan
        if plan is None:
            messagebox.showwarning("没有执行方案", "请先生成并启用最佳方案。")
            return
        step = requested_step or self._selected_ready_step()
        if step is None:
            if plan.completed:
                messagebox.showinfo("方案已完成", "所有步骤已经完成；最终成品不会写入素材库存。")
            else:
                messagebox.showwarning("暂无可执行节点", "当前节点仍有尚未完成的下级依赖。")
            return
        if not plan.is_step_ready(step):
            messagebox.showwarning("依赖尚未完成", "这个节点直接连接的下级子代尚未完成。")
            return
        plan_snapshot_before_completion = plan.to_dict()
        snapshot_candidate = self.plan_candidate_cache.get(plan.id)
        if snapshot_candidate is not None:
            plan_snapshot_before_completion["_candidate_snapshot"] = snapshot_candidate.to_dict()
        parent_pairs = (
            (step.parent_a_id, step.parent_a_label),
            (step.parent_b_id, step.parent_b_label),
        )
        inventory_parents = [label for identifier, label in parent_pairs if not identifier.startswith("buy:")]
        purchase_parents = [label for identifier, label in parent_pairs if identifier.startswith("buy:")]
        inventory_text = (
            "将从本地库存删除：\n" + "\n".join(f"- {label}" for label in inventory_parents) + "\n\n"
            if inventory_parents
            else "本步骤不会删除已有库存素材。\n\n"
        )
        purchase_text = (
            "本步骤包含以下交易行素材：\n"
            + "\n".join(f"- {label}" for label in purchase_parents)
            + "\n\n请确认已经在游戏中购买并用于本次孵化；它们不会单独写入素材库存。\n\n"
            if purchase_parents
            else ""
        )
        prompt = (
            f"确认游戏中已经完成步骤 {step.number}？\n\n"
            f"{purchase_text}"
            f"{inventory_text}"
            f"并生成子代：{step.child.species} {step.child.iv_string}\n"
            f"性别操作：{step.gender_instruction}\n\n"
            + (f"注意：{step.child.notes}\n\n" if step.child.notes else "")
            +
            "中间代会写入素材库存；达到最终成品时只完成核销，不再入库。\n"
            "该操作只修改工具的本地数据库，不会操作游戏。"
        )
        if not messagebox.askyesno("确认核销父母", prompt):
            return
        child_to_save = Monster.from_dict(step.child.to_dict())
        species_record = self.species_db.get(child_to_save.species, fuzzy=True)
        allowed_genders = species_record.allowed_genders if species_record is not None else ("F", "M")
        if step.effective_gender_policy == "random" and allowed_genders == ("F", "M"):
            gender_answer = messagebox.askyesnocancel(
                "记录实际性别",
                "本步骤没有锁定子代性别。请记录游戏中实际孵出的性别：\n\n"
                "是 ＝ 母\n"
                "否 ＝ 公\n"
                "取消 ＝ 返回核对，不核销库存\n\n"
                "保存后，工具会根据实际性别自动重算剩余路线。",
            )
            if gender_answer is None:
                return
            child_to_save.gender = "F" if gender_answer else "M"
        elif step.effective_gender_policy == "irrelevant" and allowed_genders == ("F", "M"):
            child_to_save.gender = step.expected_gender
            child_to_save.gender_unconfirmed = True
            child_to_save.notes = "；".join(
                value
                for value in (
                    child_to_save.notes,
                    "本路线下一步与百变怪孵化，暂不记录实际性别",
                )
                if value
            )
        elif allowed_genders != ("F", "M") and allowed_genders:
            child_to_save.gender = allowed_genders[0]
        else:
            child_to_save.gender = step.expected_gender
        nature_hit = False
        nature_missed = False
        nature_checked = plan.should_check_nature(step)
        if nature_checked:
            nature_hand_step = step.nature_check_role == "nature_hand"
            prompt_intro = (
                "这是满 IV 母体失败后主动制作的性格手。"
                if nature_hand_step
                else "本步骤没有使用不变之石，子代性格是随机的。"
            )
            miss_action = (
                "否：按未命中保存，并自动进入下一档性格手或最终保底。"
                if nature_hand_step
                else "否：按未命中保存；若这是满 IV 母体，将自动进入性格手阶段。"
            )
            nature_answer = messagebox.askyesnocancel(
                "记录随机性格",
                f"{prompt_intro}\n\n"
                f"是否爆出了目标性格“{plan.target_nature}”？\n\n"
                "是：按目标性格保存，并可立即用最新库存重算路线。\n"
                f"{miss_action}\n"
                "取消：返回核对，不核销库存。",
            )
            if nature_answer is None:
                return
            if nature_answer:
                child_to_save.nature = plan.target_nature
                child_to_save.notes = "；".join(
                    value for value in (child_to_save.notes, f"随机爆出目标性格 {plan.target_nature}") if value
                )
                nature_hit = True
            else:
                child_to_save.notes = "；".join(
                    value
                    for value in (
                        child_to_save.notes,
                        f"随机性格未命中目标性格 {plan.target_nature}",
                    )
                    if value
                )
                nature_missed = True
            child_to_save.breeding_target_key = plan.nature_target_key
            child_to_save.breeding_role = (
                "nature_hand" if nature_hand_step else "maternal"
            )
            child_to_save.nature_attempt_level = sum(
                value is not None for value in child_to_save.ivs
            )
            child_to_save.nature_attempt_result = "hit" if nature_hit else "miss"
        final_step = plan.is_final_step(step)
        nature_hand_step = step.nature_check_role == "nature_hand"
        plan_will_complete = all(candidate.completed or candidate is step for candidate in plan.steps)
        final_gender_pending = bool(
            final_step
            and nature_hit
            and not nature_hand_step
            and plan.target_gender in {"F", "M"}
            and child_to_save.gender != plan.target_gender
        )
        nature_miss_requires_finish = bool(final_step and nature_missed)
        should_auto_replan = bool(
            (step.outcome_changes_plan and not plan_will_complete)
            or (nature_hit and (not plan_will_complete or final_gender_pending))
            or (nature_hit and nature_hand_step)
            or nature_miss_requires_finish
        )
        finished_product = bool(final_step and plan_will_complete and not should_auto_replan)
        try:
            consume_parents_and_add_child(
                (step.parent_a_id, step.parent_b_id),
                child_to_save,
                plan.id,
                step.number,
                (step.parent_a_label, step.parent_b_label),
                plan_snapshot=plan_snapshot_before_completion,
                add_child_to_inventory=not finished_product,
            )
        except Exception as exc:
            messagebox.showerror("核销失败", str(exc))
            return
        step.child = child_to_save
        step.completed = True
        step.in_progress = False
        self.selected_plan_step_number = None
        save_active_plan(plan.to_dict())
        self.inventory = load_inventory()
        self.refresh_inventory_tree()
        if finished_product:
            self.status_var.set(
                f"步骤 {step.number} 已完成：父母已核销，最终成品未写入素材库存。"
            )
        elif purchase_parents:
            self.status_var.set(
                f"步骤 {step.number} 已完成：交易行素材已按本次孵化直接结算，未写入库存；子代已保存。"
            )
        if should_auto_replan:
            reasons = []
            if step.outcome_changes_plan and not plan.completed:
                reasons.append(f"实际性别为{gender_name(child_to_save.gender)}")
            if nature_hit:
                reasons.append(
                    f"{child_to_save.nature_attempt_level} 项性格手爆出 {plan.target_nature}"
                    if nature_hand_step
                    else f"爆出目标性格 {plan.target_nature}"
                )
            if final_gender_pending:
                reasons.append(f"还需锁定成品为{gender_name(plan.target_gender)}")
            if nature_miss_requires_finish:
                if nature_hand_step:
                    reasons.append(
                        f"{child_to_save.nature_attempt_level} 项性格手未命中 {plan.target_nature}，进入下一阶段"
                    )
                else:
                    reasons.append(f"满 IV 母体未爆出 {plan.target_nature}，转入性格手阶段")
            self.auto_activate_replan_pending = True
            self.auto_replan_reason = "、".join(reasons)
            self.auto_replan_progress_keys = self._capture_plan_progress_keys(plan)
            self.auto_replan_preferred_material_ids = {child_to_save.id}
            self.active_plan = None
            save_active_plan(None)
            self.status_var.set(
                f"步骤 {step.number} 已核销，子代已入库（{'、'.join(reasons)}）；正在按最新库存自动重新规划。"
            )
            self.generate_plan()
            return
        self.refresh_plan_status()
        if plan.completed:
            final_note = (
                f"请在游戏中将其进化为最终目标 {plan.target_species}。"
                if step.child.species != plan.target_species
                else ""
            )
            messagebox.showinfo(
                "方案完成",
                f"所有父母已按步骤核销，最终 {step.child.species} 已完成且未写入素材库存。{final_note}",
            )

    def undo_last_step(self) -> None:
        if not messagebox.askyesno(
            "撤销核销",
            "撤销最近一次核销并恢复两只父母；若该步是中间代，也会从素材库存移除其子代。继续吗？",
        ):
            return
        try:
            restored = undo_last_consumption()
        except Exception as exc:
            messagebox.showerror("撤销失败", str(exc))
            return
        if restored is None:
            messagebox.showinfo("没有历史", "没有可撤销的核销记录。")
            return
        _parent_a, _parent_b, child, plan_snapshot = restored
        if plan_snapshot:
            candidate_snapshot = plan_snapshot.pop("_candidate_snapshot", None)
            try:
                restored_plan = ExecutionPlan.from_dict(plan_snapshot)
            except Exception:
                restored_plan = None
            if restored_plan is not None:
                self.active_plan = restored_plan
                self.proposed_plan = restored_plan
                cached_candidate = self.plan_candidate_cache.get(restored_plan.id)
                if cached_candidate is None and isinstance(candidate_snapshot, dict):
                    try:
                        cached_candidate = ChainCandidate.from_dict(candidate_snapshot)
                        self.plan_candidate_cache[restored_plan.id] = cached_candidate
                    except Exception:
                        cached_candidate = None
                if cached_candidate is not None:
                    self.current_candidates = [cached_candidate]
                else:
                    self.current_candidates = []
                    self._set_plan_map_root(
                        None,
                        "已恢复执行步骤；旧版核销记录未包含可视路线快照。",
                    )
                self.selected_plan_step_number = None
                self.auto_replan_preferred_material_ids.clear()
                save_active_plan(restored_plan.to_dict())
                self.inventory = load_inventory()
                self.refresh_inventory_tree()
                self.refresh_plan_status()
                self.status_var.set("已撤销最近一次核销，并精确恢复核销前的步骤、依赖与路线状态。")
                return
        matched_active_step = False
        if self.active_plan:
            step = next((item for item in self.active_plan.steps if item.child.id == child.id), None)
            if step:
                step.completed = False
                step.in_progress = False
                matched_active_step = True
                save_active_plan(self.active_plan.to_dict())
            else:
                self.auto_replan_progress_keys = self._capture_plan_progress_keys(self.active_plan)
                self.active_plan = None
                save_active_plan(None)
        self.inventory = load_inventory()
        self.refresh_inventory_tree()
        if not matched_active_step and self.target_species_var.get().strip():
            self.auto_activate_replan_pending = True
            self.auto_replan_reason = "撤销上一次核销"
            self.status_var.set("已恢复两只父母，正在按恢复后的库存自动重算剩余路线。")
            self.generate_plan()
            return
        self.refresh_plan_status()
        self.status_var.set("已撤销最近一次核销并恢复两只父母。")


def main() -> None:
    import tkinter as tk

    if "--check-ocr" in sys.argv:
        OCRProcessor()
        return

    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()

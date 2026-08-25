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
from chain_planner import ChainCandidate, ChainState, gender_name
from execution import ExecutionPlan, build_execution_plan
from mind_map import BreedingMindMap, MindMapNode
from models import STATS, Monster, normalize_gender
from nature_data import NEUTRAL_TARGET_NAME, PLANNER_NATURES, find_nature, is_neutral_nature
from ocr_engine import OCRProcessor
from planner import make_report_with_candidates
from reference_data import get_reference_database
from species_data import SpeciesRecord, get_species_database
from storage import (
    consume_parents_and_add_child,
    load_active_plan,
    load_inventory,
    save_active_plan,
    save_inventory,
    undo_last_consumption,
)


class App:
    def __init__(self, root: ttk.Frame | object) -> None:
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("880x920")
        self.root.minsize(700, 600)
        self.layout_orientation = ""
        self.layout_after_id = None
        self.preview_after_id = None

        self.current_image: Image.Image | None = None
        self.current_source = ""
        self.preview_scale = 1.0
        self.preview_offset = (0, 0)
        self.roi: tuple[int, int, int, int] | None = None
        self.drag_start: tuple[int, int] | None = None
        self.drag_rectangle = None
        self.preview_photo = None
        self.windows: list[WindowInfo] = []
        self.inventory = load_inventory()
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
        self.species_var = StringVar()
        self.gender_var = StringVar()
        self.nature_var = StringVar()
        self.iv_var = StringVar()
        self.ability_var = StringVar()
        self.item_var = StringVar()
        self.moves_var = StringVar()
        self.alpha_var = StringVar(value="普通")
        self.groups_var = StringVar()
        self.source_var = StringVar()
        self.status_var = StringVar(value="准备就绪。")
        self.target_species_var = StringVar()
        self.target_gender_var = StringVar(value="雌性")
        self.target_alpha_var = StringVar(value="普通")
        self.target_nature_var = StringVar()
        self.target_nature_info_var = StringVar(value="不指定性格")
        self.target_lock_nature_var = BooleanVar(value=False)
        self.target_lock_gender_var = BooleanVar(value=True)
        self.target_allow_ditto_var = BooleanVar(value=False)
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
        self.inventory_status_filter_var = StringVar(value="全部状态")
        self.inventory_type_filter_var = StringVar(value="全部类别")

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
        self.root.bind("<Return>", self._handle_batch_enter, add="+")
        self.root.bind("<F8>", self._handle_batch_retry_hotkey, add="+")
        self.root.after_idle(self._apply_responsive_layout)

    def build_ui(self) -> None:
        self._configure_styles()
        try:
            self.root.configure(background=UI_COLORS["app_bg"])
        except Exception:
            pass

        self.main_pane = self._create_paned_window(
            self.root,
            orient="horizontal",
            background=UI_COLORS["app_bg"],
        )
        self.main_pane.pack(fill=BOTH, expand=True, padx=12, pady=10)

        self.left_panel = ttk.Frame(self.main_pane, style="Panel.TFrame", padding=10)
        self.right_panel = ttk.Frame(self.main_pane, style="Panel.TFrame", padding=10)
        self.build_capture_panel(self.left_panel)
        self.build_right_panel(self.right_panel)
        self.left_panel.bind("<Configure>", self._resize_left_content, add="+")
        self.right_panel.bind("<Configure>", self._resize_right_content, add="+")

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

    def _schedule_responsive_layout(self, event=None) -> None:
        if event is not None and event.widget is not self.root:
            return
        if self.layout_after_id is not None:
            try:
                self.root.after_cancel(self.layout_after_id)
            except Exception:
                pass
        self.layout_after_id = self.root.after(80, self._apply_responsive_layout)

    def _apply_responsive_layout(self) -> None:
        self.layout_after_id = None
        width = max(1, self.root.winfo_width())
        desired = self._layout_for_width(width)
        if desired == self.layout_orientation:
            return
        for panel in (self.left_panel, self.right_panel):
            try:
                self.main_pane.forget(panel)
            except Exception:
                pass
        self.main_pane.configure(orient=desired)
        if desired == "horizontal":
            self.main_pane.add(self.left_panel, minsize=420, stretch="always")
            self.main_pane.add(self.right_panel, minsize=520, stretch="always")
        else:
            self.main_pane.add(self.left_panel, minsize=300, stretch="always")
            self.main_pane.add(self.right_panel, minsize=260, stretch="always")
        self.layout_orientation = desired
        self.root.after_idle(lambda orientation=desired: self._place_initial_main_sash(orientation))
        self.root.after_idle(self._redraw_preview)

    def _place_initial_main_sash(self, orientation: str) -> None:
        if orientation != self.layout_orientation:
            return
        try:
            if len(self.main_pane.panes()) < 2:
                return
            if orientation == "horizontal":
                position = max(420, round(self.main_pane.winfo_width() * 0.42))
                self.main_pane.sash_place(0, position, 0)
            else:
                position = max(300, round(self.main_pane.winfo_height() * 0.40))
                self.main_pane.sash_place(0, 0, position)
        except Exception:
            return

    def _adjust_preview_height(self, amount: int) -> None:
        """Keyboard/button alternative to dragging either preview boundary."""
        try:
            x, y = self.capture_pane.sash_coord(0)
            self.capture_pane.sash_place(0, x, y - amount // 2)
        except Exception:
            pass
        if self.layout_orientation == "vertical":
            try:
                x, y = self.main_pane.sash_coord(0)
                self.main_pane.sash_place(0, x, y + amount // 2)
            except Exception:
                pass
        self._schedule_preview_redraw()

    @staticmethod
    def _layout_for_width(width: int) -> str:
        return "horizontal" if width >= 1180 else "vertical"

    def _resize_left_content(self, event) -> None:
        wraplength = max(240, event.width - 34)
        for widget_name in ("batch_help_label", "recent_scan_label", "capture_tip"):
            widget = getattr(self, widget_name, None)
            if widget is not None:
                widget.configure(wraplength=wraplength)

    def _resize_right_content(self, event) -> None:
        wraplength = max(300, event.width - 42)
        if hasattr(self, "target_info_label"):
            self.target_info_label.configure(wraplength=max(180, round(event.width * 0.38)))
        for widget_name in ("plan_status_label", "plan_summary_label", "plan_purchase_label"):
            widget = getattr(self, widget_name, None)
            if widget is not None:
                widget.configure(wraplength=wraplength)

    def _schedule_preview_redraw(self, _event=None) -> None:
        if self.current_image is None:
            return
        if self.preview_after_id is not None:
            try:
                self.root.after_cancel(self.preview_after_id)
            except Exception:
                pass
        self.preview_after_id = self.root.after(60, self._redraw_preview)

    def _redraw_preview(self) -> None:
        self.preview_after_id = None
        if self.roi:
            self.draw_roi()
        else:
            self.show_preview()

    def build_capture_panel(self, parent: ttk.Frame) -> None:
        self.capture_pane = self._create_paned_window(parent, orient="vertical")
        self.capture_pane.pack(fill=BOTH, expand=True)
        controls = ttk.Frame(self.capture_pane)
        preview_area = ttk.Frame(self.capture_pane)
        self.capture_pane.add(controls, minsize=210, stretch="never")
        self.capture_pane.add(preview_area, minsize=80, stretch="always")

        source = ttk.LabelFrame(controls, text="画面来源", padding=8)
        source.pack(fill=X, pady=(0, 8))

        ttk.Button(source, text="刷新窗口", command=self.refresh_windows).grid(row=0, column=0, padx=3, pady=3)
        self.window_combo = ttk.Combobox(source, state="readonly", width=43)
        self.window_combo.grid(row=0, column=1, columnspan=2, sticky="ew", padx=3, pady=3)
        ttk.Button(source, text="连接实时预览", command=self.capture_selected_window).grid(row=0, column=3, padx=3, pady=3)

        ttk.Button(source, text="加载截图", command=self.load_image).grid(row=1, column=0, padx=3, pady=3)
        ttk.Button(source, text="读取剪贴板", command=self.load_clipboard).grid(row=1, column=1, padx=3, pady=3)
        ttk.Button(source, text="默认左侧信息区", command=self.set_default_roi).grid(row=1, column=2, padx=3, pady=3)
        ttk.Button(source, text="清除框选", command=self.clear_roi).grid(row=1, column=3, padx=3, pady=3)
        source.columnconfigure(1, weight=1)
        source.columnconfigure(2, weight=1)

        batch = ttk.LabelFrame(controls, text="OCR 连续扫描", padding=8)
        batch.pack(fill=X, pady=(0, 8))
        ttk.Label(batch, text="起始箱", style="Field.TLabel").grid(row=0, column=0, padx=2, pady=2)
        ttk.Entry(batch, textvariable=self.batch_page_var, width=6).grid(row=0, column=1, padx=2, pady=2)
        ttk.Label(batch, text="起始格", style="Field.TLabel").grid(row=0, column=2, padx=2, pady=2)
        ttk.Entry(batch, textvariable=self.batch_slot_var, width=6).grid(row=0, column=3, padx=2, pady=2)
        ttk.Label(batch, text="每箱格数", style="Field.TLabel").grid(row=0, column=4, padx=2, pady=2)
        ttk.Entry(batch, textvariable=self.batch_slots_per_page_var, width=6).grid(row=0, column=5, padx=2, pady=2)
        ttk.Label(batch, text="切换等待", style="Field.TLabel").grid(row=0, column=6, padx=(8, 2), pady=2)
        self.batch_delay_spinbox = ttk.Spinbox(
            batch,
            textvariable=self.batch_delay_var,
            from_=1.5,
            to=8.0,
            increment=0.5,
            width=5,
        )
        self.batch_delay_spinbox.grid(row=0, column=7, padx=2, pady=2)
        ttk.Label(batch, text="秒", style="Muted.TLabel").grid(row=0, column=8, padx=(0, 2), pady=2)
        self.batch_start_button = ttk.Button(batch, text="开始连续扫描", style="Primary.TButton", command=self.start_batch_scan)
        self.batch_start_button.grid(row=1, column=0, columnspan=2, padx=3, pady=2, sticky="ew")
        self.batch_stop_button = ttk.Button(batch, text="停止", style="Danger.TButton", command=self.stop_batch_scan, state="disabled")
        self.batch_stop_button.grid(row=1, column=2, padx=3, pady=2, sticky="ew")
        ttk.Button(batch, text="跳过一格", command=self.skip_batch_location).grid(row=1, column=3, padx=3, pady=2)
        ttk.Button(batch, text="识别当前精灵", command=self.force_scan_current_slot).grid(
            row=1, column=4, columnspan=2, sticky="ew", padx=3, pady=2
        )
        self.batch_help_label = ttk.Label(
            batch,
            style="Muted.TLabel",
            text="首次画面稳定后自动 OCR；按回车保存后会按“切换等待”倒计时，请在到点前手动选择下一只。到点强制 OCR，未切换时按 F8 重新计时。",
            wraplength=455,
            justify="left",
        )
        self.batch_help_label.grid(row=2, column=0, columnspan=9, sticky="w", pady=(4, 0))
        self.recent_scan_label = ttk.Label(
            batch,
            textvariable=self.recent_scan_var,
            style="RecentScan.TLabel",
            padding=(10, 7),
            wraplength=520,
            justify="left",
        )
        self.recent_scan_label.grid(row=3, column=0, columnspan=9, sticky="ew", padx=2, pady=(6, 0))
        batch.columnconfigure(5, weight=1)

        preview_header = ttk.Frame(preview_area)
        ttk.Label(preview_header, text="实时预览 · 可拖动上下分隔线", style="Field.TLabel").pack(side=LEFT)
        ttk.Button(
            preview_header,
            text="−",
            width=3,
            style="Compact.TButton",
            command=lambda: self._adjust_preview_height(-60),
        ).pack(side=LEFT, padx=(8, 2))
        ttk.Button(
            preview_header,
            text="+",
            width=3,
            style="Compact.TButton",
            command=lambda: self._adjust_preview_height(60),
        ).pack(side=LEFT)
        preview = ttk.LabelFrame(preview_area, labelwidget=preview_header, padding=6)
        preview.pack(fill=BOTH, expand=True)
        self.canvas = Canvas(preview, background=UI_COLORS["preview"], highlightthickness=0)
        self.canvas.pack(fill=BOTH, expand=True)
        self.canvas.bind("<ButtonPress-1>", self.start_roi)
        self.canvas.bind("<B1-Motion>", self.drag_roi)
        self.canvas.bind("<ButtonRelease-1>", self.finish_roi)
        self.canvas.bind("<Configure>", self._schedule_preview_redraw, add="+")

    def build_right_panel(self, parent: ttk.Frame) -> None:
        tabs = ttk.Notebook(parent)
        tabs.pack(fill=BOTH, expand=True)
        self.right_tabs = tabs

        current_tab = ttk.Frame(tabs, padding=8)
        self.current_tab = current_tab
        inventory_tab = ttk.Frame(tabs, padding=8)
        planner_tab = ttk.Frame(tabs, padding=8)
        tabs.add(current_tab, text="识别当前")
        tabs.add(inventory_tab, text="素材库存")
        tabs.add(planner_tab, text="孵蛋规划")
        self.build_current_tab(current_tab)
        self.build_inventory_tab(inventory_tab)
        self.build_planner_tab(planner_tab)

    def build_current_tab(self, parent: ttk.Frame) -> None:
        form = ttk.LabelFrame(parent, text="当前识别结果", padding=(8, 6))
        form.pack(fill=X)

        field_padx = (3, 4)
        field_pady = 2
        ttk.Label(form, text="仓库页", style="Field.TLabel").grid(row=0, column=0, sticky="e", padx=field_padx, pady=field_pady)
        ttk.Entry(form, textvariable=self.page_var, width=6).grid(row=0, column=1, sticky="w", padx=field_padx, pady=field_pady)
        ttk.Label(form, text="格子", style="Field.TLabel").grid(row=0, column=2, sticky="e", padx=field_padx, pady=field_pady)
        ttk.Entry(form, textvariable=self.slot_var, width=6).grid(row=0, column=3, sticky="w", padx=field_padx, pady=field_pady)

        ttk.Label(form, text="精灵名字", style="Field.TLabel").grid(row=1, column=0, sticky="e", padx=field_padx, pady=field_pady)
        self.current_species_entry = ttk.Entry(form, textvariable=self.species_var, width=20)
        self.current_species_entry.grid(row=1, column=1, sticky="ew", padx=field_padx, pady=field_pady)
        ttk.Label(form, text="性别", style="Field.TLabel").grid(row=1, column=2, sticky="e", padx=field_padx, pady=field_pady)
        ttk.Combobox(
            form,
            textvariable=self.gender_var,
            values=("F", "M", "N"),
            state="readonly",
            width=6,
        ).grid(row=1, column=3, sticky="w", padx=field_padx, pady=field_pady)

        ttk.Label(form, text="个体值", style="Field.TLabel").grid(row=2, column=0, sticky="e", padx=field_padx, pady=field_pady)
        ttk.Entry(form, textvariable=self.iv_var, width=20).grid(row=2, column=1, sticky="ew", padx=field_padx, pady=field_pady)
        ttk.Label(form, text="素材类别", style="Field.TLabel").grid(row=2, column=2, sticky="e", padx=field_padx, pady=field_pady)
        ttk.Combobox(
            form,
            textvariable=self.alpha_var,
            values=("普通", "头目"),
            state="readonly",
            width=7,
        ).grid(row=2, column=3, sticky="w", padx=field_padx, pady=field_pady)
        ttk.Label(form, text="性格", style="Field.TLabel").grid(row=3, column=0, sticky="e", padx=field_padx, pady=field_pady)
        ttk.Entry(form, textvariable=self.nature_var, width=20).grid(row=3, column=1, sticky="ew", padx=field_padx, pady=field_pady)
        ttk.Label(form, text="技能", style="Field.TLabel").grid(row=3, column=2, sticky="e", padx=field_padx, pady=field_pady)
        ttk.Entry(form, textvariable=self.moves_var, width=20).grid(row=3, column=3, sticky="ew", padx=field_padx, pady=field_pady)
        ttk.Label(form, text="F=母，M=公，N=无性别；蛋组会根据名字自动填写。", style="Muted.TLabel").grid(
            row=4, column=0, columnspan=4, sticky="w", padx=3, pady=(2, 0)
        )
        form.columnconfigure(1, weight=2)
        form.columnconfigure(3, weight=1)

        actions = ttk.Frame(parent)
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
            height=6,
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

        inventory_buttons = ttk.Frame(actions)
        inventory_buttons.grid(row=1, column=0, columnspan=3, sticky="w")
        ttk.Button(inventory_buttons, text="刷新列表", command=self.refresh_inventory_tree).pack(side=LEFT, padx=(0, 5))
        ttk.Button(inventory_buttons, text="导出 JSON", command=self.export_inventory).pack(side=LEFT, padx=(0, 5))
        ttk.Button(inventory_buttons, text="导入 JSON", command=self.import_inventory).pack(side=LEFT)
        ttk.Label(actions, textvariable=self.inventory_summary_var, style="Muted.TLabel").grid(
            row=1, column=3, columnspan=2, padx=6, sticky="e"
        )
        ttk.Button(actions, text="删除选中", style="Danger.TButton", command=self.delete_selected_inventory).grid(
            row=1, column=5, sticky="e"
        )
        actions.columnconfigure(1, weight=1)

        columns = ("page", "slot", "status", "species", "gender", "alpha", "nature", "ivs", "groups", "moves", "confidence")
        tree_frame = ttk.Frame(parent)
        tree_frame.pack(fill=BOTH, expand=True)
        self.inventory_tree = ttk.Treeview(tree_frame, columns=columns, show="headings", selectmode="browse", height=7)
        headings = {
            "page": "页",
            "slot": "格",
            "status": "状态",
            "species": "种类",
            "gender": "性别",
            "alpha": "类别",
            "nature": "性格",
            "ivs": "个体值",
            "groups": "蛋组",
            "moves": "技能",
            "confidence": "OCR",
        }
        widths = {
            "page": 38, "slot": 33, "status": 56, "species": 95, "gender": 45,
            "alpha": 50, "nature": 58, "ivs": 115, "groups": 100, "moves": 150, "confidence": 48,
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

    def build_planner_tab(self, parent: ttk.Frame) -> None:
        form = ttk.LabelFrame(parent, text="目标与约束", padding=10)
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

        rules = ttk.LabelFrame(form, text="高级规划规则", padding=(8, 5))
        self.planner_rules_frame = rules
        rules.grid(row=5, column=0, columnspan=8, sticky="ew", padx=4, pady=(5, 2))
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
            text="允许使用百变怪",
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
        ttk.Label(rules, text="中间性别", style="Field.TLabel").grid(
            row=2, column=0, sticky="w", padx=(0, 4), pady=3
        )
        self.target_intermediate_gender_combo = ttk.Combobox(
            rules,
            textvariable=self.target_intermediate_gender_strategy_var,
            values=("智能锁定", "全程锁定", "尽量不锁"),
            state="readonly",
            width=10,
        )
        self.target_intermediate_gender_combo.grid(row=2, column=1, sticky="w", padx=(0, 12), pady=3)
        self.target_intermediate_gender_combo.bind(
            "<<ComboboxSelected>>", self._on_intermediate_gender_strategy_changed
        )
        ttk.Label(
            rules,
            textvariable=self.target_gender_strategy_hint_var,
            style="Muted.TLabel",
        ).grid(row=2, column=2, columnspan=4, sticky="w", pady=3)
        ttk.Label(
            rules,
            text="库存优先＝少补素材；步骤优先＝少孵化次数。中间性别策略不会改变成品性别要求。",
            style="Muted.TLabel",
        ).grid(row=3, column=0, columnspan=6, sticky="w", pady=(0, 2))
        rules.columnconfigure(5, weight=1)
        self._on_target_alpha_changed()
        rules.grid_remove()
        form.columnconfigure(1, weight=1)
        form.columnconfigure(3, weight=1)
        form.columnconfigure(4, weight=1)

        actions = ttk.Frame(parent)
        actions.pack(fill=X, pady=8)
        self.generate_plan_button = ttk.Button(actions, text="生成规划方案", style="Primary.TButton", command=self.generate_plan)
        self.generate_plan_button.pack(side=LEFT, padx=(0, 6))
        self.activate_plan_button = ttk.Button(actions, text="启用最佳方案", style="Teal.TButton", command=self.activate_best_plan)
        self.activate_plan_button.pack(side=LEFT, padx=(0, 6))
        self.complete_step_button = ttk.Button(actions, text="完成下一步并核销父母", style="Teal.TButton", command=self.complete_next_step)
        self.complete_step_button.pack(side=LEFT, padx=(0, 6))
        self.undo_step_button = ttk.Button(actions, text="撤销上一次核销", style="Danger.TButton", command=self.undo_last_step)
        self.undo_step_button.pack(side=LEFT)
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
            on_material_exclude=self.exclude_plan_material,
        )
        self.plan_map.pack(fill=BOTH, expand=True)
        self._update_plan_action_states()

    def _toggle_planner_rules(self) -> None:
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
        can_complete = bool(
            self.active_plan
            and self.active_plan.next_step is not None
            and not self.active_plan.next_step.requires_purchase
            and not self.plan_worker_busy
        )
        self.complete_step_button.configure(state="normal" if can_complete else "disabled")
        if hasattr(self, "next_step_gender_frame"):
            step = self.active_plan.next_step if self.active_plan else None
            if step is None or step.requires_purchase:
                self.next_step_gender_frame.pack_forget()
            else:
                override_labels = {"": "自动", "random": "不锁", "F": "锁母", "M": "锁公"}
                self.next_step_gender_var.set(override_labels.get(step.gender_override, "自动"))
                self.next_step_gender_hint_var.set(
                    f"当前：{step.gender_instruction}。仅覆盖这一节点；随机结果保存后会自动重算剩余路线。"
                )
                self.next_step_gender_combo.configure(state="readonly" if can_complete else "disabled")
                if not self.next_step_gender_frame.winfo_manager():
                    self.next_step_gender_frame.pack(fill=X, pady=(0, 6), before=self.plan_status_label)
        if hasattr(self, "clear_plan_exclusions_button"):
            self.clear_plan_exclusions_button.configure(
                state="disabled" if self.plan_worker_busy else "normal"
            )

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
        if forced_gender:
            forced_label = "雄性" if forced_gender == "M" else "雌性"
            ratio = f"最终进化要求{forced_label}，已自动锁定成品性别"
            self.target_gender_var.set(forced_label)
            self.target_lock_gender_var.set(True)
        elif record.female_percent is None:
            ratio = "无性别，可与同进化线无性别精灵或百变怪孵化"
            self.target_gender_var.set("任意")
            self.target_lock_gender_var.set(False)
        elif record.female_percent == 0:
            ratio = "仅雄性"
            self.target_gender_var.set("雄性")
            self.target_lock_gender_var.set(False)
        elif record.female_percent == 100:
            ratio = "仅雌性"
            self.target_gender_var.set("雌性")
            self.target_lock_gender_var.set(False)
        else:
            ratio = f"雌性比例 {record.female_percent:g}%"
            self.target_gender_var.set("雌性")
            self.target_lock_gender_var.set(True)
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
        egg_move_count = len(self.reference_db.egg_moves_for_species(record.id))
        self.target_info_var.set(
            f"已选择 #{record.id} {record.display_name}｜蛋组 {' / '.join(effective_groups)}｜{ratio}{baby}{hatch}{reuse}{incense}｜"
            f"分布 {location_count} 条｜可遗传技能 {egg_move_count} 种"
        )
        return record

    def _sync_plan_exclusion_scope(self, record: SpeciesRecord) -> None:
        offspring = self.species_db.breeding_offspring(record)
        scope_id = offspring.id if offspring is not None else record.id
        if self.plan_exclusion_scope_id is None:
            self.plan_exclusion_scope_id = scope_id
        elif self.plan_exclusion_scope_id != scope_id:
            self.plan_exclusion_scope_id = scope_id
            self.plan_excluded_ids.clear()
        inventory_ids = {monster.id for monster in self.inventory}
        self.plan_excluded_ids.intersection_update(inventory_ids)
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
        self.proposed_plan = None
        self._update_plan_exclusion_ui()
        self.plan_status_var.set(f"已保护 {monster.species}；正在从本次路线中排除并重新规划……")
        self.generate_plan()
        return "break"

    def clear_plan_exclusions(self) -> None:
        if self.plan_worker_busy or not self.plan_excluded_ids:
            return
        restored = len(self.plan_excluded_ids)
        self.plan_excluded_ids.clear()
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
        step = plan.next_step if plan else None
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
            return
        self.target_allow_alpha_materials_check.configure(state="normal")
        self.target_alpha_material_hint_var.set("关闭＝仅普通素材；开启＝普通与头目均可用，最终仍为普通。")

    def _on_nature_lock_changed(self) -> None:
        selected = self.target_nature_var.get().strip()
        if not selected:
            self.target_nature_info_var.set("请先选择性格" if self.target_lock_nature_var.get() else "不指定性格")
            return
        if not self.target_lock_nature_var.get():
            self.target_nature_info_var.set(
                f"后置性格：先做高 V 主线，最终用低一档的 {selected} 素材 + 不变石合成；中间可记录爆性格"
            )
            return
        if is_neutral_nature(selected):
            self.target_nature_info_var.set("全程不变石链；五种无修正性格任意一种均可")
            return
        nature = find_nature(selected)
        effect = nature.effect if nature else selected
        self.target_nature_info_var.set(f"{effect}；沿性格支线全程使用不变石")

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

    def open_species_reference(self) -> None:
        record = self.lookup_target_species(silent=False)
        if record is None:
            return
        locations = self.reference_db.locations_for_species(record.id)
        egg_moves = self.reference_db.egg_moves_for_species(record.id)
        window = Toplevel(self.root)
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
        window = Toplevel(self.root)
        self.nature_picker_window = window
        window.title("选择目标性格")
        window.geometry("720x520")
        window.minsize(620, 400)
        window.transient(self.root)

        ttk.Label(
            window,
            text="双击性格即可确认；5 种无修正性格已合并为“无修正（任一）”。",
            padding=(10, 10, 10, 4),
        ).pack(fill=X)
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
        tree.insert("", END, iid="__none__", values=("不指定", "—", "—", "—", "不要求遗传性格"))
        tree.insert(
            "",
            END,
            iid="__neutral__",
            values=(NEUTRAL_TARGET_NAME, "5 种合并", "—", "—", "勤奋/坦率/认真/害羞/浮躁任一即可"),
        )
        for nature in PLANNER_NATURES:
            tree.insert(
                "",
                END,
                iid=nature.english.lower(),
                values=(
                    nature.chinese,
                    nature.english,
                    nature.increased or "—",
                    nature.decreased or "—",
                    nature.effect,
                ),
            )
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

        tree.bind("<Double-Button-1>", confirm)
        tree.bind("<Return>", confirm)
        buttons = ttk.Frame(window, padding=(10, 4, 10, 10))
        buttons.pack(fill=X)
        ttk.Button(buttons, text="确认选择", style="Primary.TButton", command=confirm).pack(side=RIGHT, padx=4)
        ttk.Button(buttons, text="取消", command=close).pack(side=RIGHT, padx=4)
        window.protocol("WM_DELETE_WINDOW", close)
        current = find_nature(self.target_nature_var.get())
        if is_neutral_nature(self.target_nature_var.get()):
            initial = "__neutral__"
        else:
            initial = current.english.lower() if current else "__none__"
        tree.selection_set(initial)
        tree.see(initial)
        tree.focus(initial)
        tree.focus_set()

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
        try:
            self.root.lift()
            self.root.focus_force()
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
                self.ocr = OCRProcessor()
        except Exception as exc:
            messagebox.showerror("OCR 初始化失败", str(exc))
            self._schedule_live_preview_tick()
            return
        self.batch_running = True
        self.batch_session += 1
        self._cancel_batch_countdown()
        self.batch_pending_fingerprint = None
        self.batch_pending_count = 0
        self.batch_last_processed = None
        self.batch_last_confirmed_fingerprint = None
        self.batch_last_confirmed_signature = None
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
            f"连续扫描已启动：从箱 {page} / 格 {slot} 开始。保持当前精灵约 1 秒，识别后按回车确认。"
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
        self.batch_after_id = self.root.after(BATCH_SCAN_INTERVAL_MS, self._batch_tick)

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
        if reason == "next":
            change = self._fingerprint_difference(fingerprint, self.batch_last_confirmed_fingerprint)
            if change < BATCH_CHANGE_DIFFERENCE:
                current_signature = self._parsed_batch_signature(parsed or {})
                semantic_changed = parsed is not None and (
                    self.batch_last_confirmed_signature is None
                    or current_signature != self.batch_last_confirmed_signature
                )
                if not semantic_changed:
                    self._mark_batch_retry_required(
                        f"强制 OCR 已完成：文字字段与上一只完全相同，信息区变化率为 {change:.1f}。"
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
        raw_moves = [str(move).strip() for move in parsed.get("moves", []) if str(move).strip()]
        moves = [self.reference_db.canonical_move(move) for move in raw_moves]
        self.species_var.set(species)
        self.gender_var.set(gender)
        self.nature_var.set(nature)
        self.alpha_var.set("头目" if is_alpha else "普通")
        self.iv_var.set("/".join("x" if value is None else str(value) for value in parsed.get("ivs", [None] * 6)))
        self.moves_var.set(", ".join(moves))
        if hasattr(self, "ocr_confidence_var"):
            self.ocr_confidence_var.set(f"OCR 置信度：{confidence:.0%}")
        # Ability and held item remain outside the breeding-focused OCR scope.
        for variable in (self.ability_var, self.item_var):
            variable.set("")
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
                f"技能：{'、'.join(move_labels) if move_labels else '未识别'}",
                f"类别：{'头目' if is_alpha else '普通'}",
            )
        )
        self.raw_text_box.delete("1.0", END)
        self.raw_text_box.insert("1.0", summary)
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
        self._upsert_inventory(monster, match_location=True)
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
        return True

    def skip_batch_location(self) -> None:
        if not self.batch_running:
            self.advance_batch_location()
            return
        if self.batch_worker_busy:
            self.status_var.set("OCR 正在处理中，当前不能跳过；请等待识别结果后再操作。")
            return
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
        self.status_var.set(
            f"已跳过，下一条将记录到箱 {self.batch_page_var.get()} / 格 {self.batch_slot_var.get()}。"
        )
        self._start_batch_countdown()

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
            return
        self.set_image(image, f"实时窗口：{self.live_window.title}")
        if self.roi is None:
            self.set_default_roi()
        self.live_preview_running = True
        self._cancel_live_preview_tick()
        self._schedule_live_preview_tick()
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
        self.live_preview_after_id = self.root.after(LIVE_PREVIEW_INTERVAL_MS, self._live_preview_tick)

    def _live_preview_tick(self) -> None:
        self.live_preview_after_id = None
        if not self.live_preview_running or self.batch_running or self.live_window is None:
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
        if self.roi:
            self.draw_roi()
        else:
            self.show_preview()

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
        self.show_preview()
        self.status_var.set(f"已载入画面 {image.width}×{image.height}。可以框选信息区或直接识别。")

    def show_preview(self) -> None:
        self.canvas.delete("all")
        if self.current_image is None:
            return
        self.canvas.update_idletasks()
        max_width = max(300, self.canvas.winfo_width() - 8)
        max_height = max(240, self.canvas.winfo_height() - 8)
        self.preview_scale = min(1.0, max_width / self.current_image.width, max_height / self.current_image.height)
        display = self.current_image.resize((int(self.current_image.width * self.preview_scale), int(self.current_image.height * self.preview_scale)))
        self.preview_photo = ImageTk.PhotoImage(display)
        x = max(4, (self.canvas.winfo_width() - display.width) // 2)
        y = max(4, (self.canvas.winfo_height() - display.height) // 2)
        self.preview_offset = (x, y)
        self.canvas.create_image(x, y, image=self.preview_photo, anchor="nw")

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
            return
        left, top, right, bottom = self.roi
        ox, oy = self.preview_offset
        self.drag_rectangle = self.canvas.create_rectangle(
            ox + left * self.preview_scale,
            oy + top * self.preview_scale,
            ox + right * self.preview_scale,
            oy + bottom * self.preview_scale,
            outline="#29b6f6",
            width=2,
        )

    def start_roi(self, event) -> None:
        if self.current_image is None:
            return
        self.drag_start = (event.x, event.y)

    def drag_roi(self, event) -> None:
        if not self.drag_start:
            return
        if self.drag_rectangle:
            self.canvas.delete(self.drag_rectangle)
        self.drag_rectangle = self.canvas.create_rectangle(self.drag_start[0], self.drag_start[1], event.x, event.y, outline="#29b6f6", width=2)

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
                self.ocr = OCRProcessor()
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
                (item for item in self.inventory if item.page == monster.page and item.slot == monster.slot),
                None,
            )
            if located:
                replace_id = located.id
                monster.id = located.id
                monster.created_at = located.created_at
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
        # Manual image recognition appends a row unless the user deliberately
        # selected an existing inventory row. Location-based replacement is
        # reserved for continuous scans, where rescanning the same slot should
        # update that slot instead of duplicating it.
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
        visible_count = 0
        for monster in self.inventory:
            haystack = " ".join(
                (
                    monster.page,
                    monster.slot,
                    monster.species,
                    monster.gender,
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
            confidence = "" if monster.confidence is None else f"{monster.confidence:.0%}"
            self.inventory_tree.insert(
                "",
                END,
                iid=monster.id,
                values=(
                    monster.page,
                    monster.slot,
                    "已确认" if monster.verified else "待核对",
                    monster.species,
                    {"F": "母", "M": "公", "N": "无性别"}.get(monster.gender, "未识别"),
                    "头目" if monster.is_alpha else "普通",
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
            self._update_plan_exclusion_ui()

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
            self.species_var.set(monster.species)
            self.gender_var.set(monster.gender)
            self.nature_var.set(monster.nature)
            self.alpha_var.set("头目" if monster.is_alpha else "普通")
            self.iv_var.set(monster.iv_string)
            self.ability_var.set(monster.ability)
            self.item_var.set(monster.held_item)
            self.groups_var.set(monster.group_string)
            self.moves_var.set(", ".join(monster.moves))
            self.source_var.set(monster.source)
            self.ocr_confidence_var.set(
                "OCR 置信度：—" if monster.confidence is None else f"OCR 置信度：{monster.confidence:.0%}"
            )
            gender_text = {"F": "母", "M": "公", "N": "无性别"}.get(monster.gender, "未识别")
            self.raw_text_box.delete("1.0", END)
            self.raw_text_box.insert(
                "1.0",
                "\n".join(
                    (
                        f"名字：{monster.species}",
                        f"性别：{gender_text}",
                        f"个体值：{monster.iv_string}",
                        f"性格：{monster.nature or '未识别'}",
                        f"技能：{'、'.join(monster.moves) if monster.moves else '未识别'}",
                        f"类别：{'头目' if monster.is_alpha else '普通'}",
                    )
                ),
            )
            self.status_var.set(f"正在编辑 {monster.species}（{'已确认' if monster.verified else '待核对'}）。保存后会更新原记录。")

    def delete_selected_inventory(self) -> None:
        selected = self.inventory_tree.selection()
        if not selected:
            messagebox.showinfo("未选择素材", "请先在库存表格中选择要删除的记录。")
            return
        monster = next((item for item in self.inventory if item.id == selected[0]), None)
        label = f"{monster.species}（箱 {monster.page} / 格 {monster.slot}）" if monster else "这条素材"
        if not messagebox.askyesno("确认删除素材", f"确定从本地库存删除 {label} 吗？\n\n此操作不会影响游戏内数据。"):
            return
        self.inventory = [item for item in self.inventory if item.id != selected[0]]
        save_inventory(self.inventory)
        if self.editing_monster_id == selected[0]:
            self.editing_monster_id = None
        self.refresh_inventory_tree()
        self.status_var.set(f"已删除，库存剩余 {len(self.inventory)} 只。")

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
        excluded_snapshot = frozenset(self.plan_excluded_ids)
        request = (
            snapshot,
            record.display_name,
            target_gender,
            target_nature,
            target_iv,
            groups,
            self.target_alpha_var.get() == "头目",
            bool(self.target_allow_ditto_var.get()),
            "steps" if self.target_strategy_var.get() == "步骤优先" else "inventory",
            nature_strategy,
            bool(self.target_allow_alpha_materials_var.get()),
            excluded_snapshot,
            self.target_intermediate_gender_strategy_var.get(),
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
            self._set_planner_busy(False)
            self.plan_status_var.set(f"规划失败：{error}")
            messagebox.showerror("规划失败", error)
            return
        self.current_candidates = candidates
        self.proposed_plan = build_execution_plan(candidates[0]) if candidates else None
        self._render_plan_tree(candidates[0] if candidates else None, report)
        if self.proposed_plan is None:
            self.plan_status_var.set("没有可执行方案。请检查目标和库存。")
        elif not self.proposed_plan.steps:
            candidate = candidates[0]
            actual_species = candidate.root.leaf.species if candidate.root.leaf else candidate.root.species
            if actual_species != candidate.target_species:
                self.plan_status_var.set(
                    f"库存中已有满足属性的 {actual_species}；无需孵化，进化为 {candidate.target_species} 即可。"
                )
            else:
                self.plan_status_var.set("库存中已经有满足目标的成品，不需要执行孵化步骤。")
        elif self.proposed_plan.purchase_requirements:
            next_step = self.proposed_plan.next_step
            if next_step and next_step.requires_purchase:
                self.plan_status_var.set("路线已生成，但第一个可执行节点就缺料；手动采购并 OCR 入库后重新规划。")
            else:
                self.plan_status_var.set("路线包含后续缺料；可先启用并完成蓝色库存节点，走到橙色节点时再采购重算。")
        else:
            self.plan_status_var.set("最佳路线全部由现有库存组成。确认无误后点击“启用最佳方案”。")
        if self.plan_excluded_ids:
            self.plan_status_var.set(
                f"{self.plan_status_var.get()} 本次已保护 {len(self.plan_excluded_ids)} 只库存素材。"
            )
        self._set_planner_busy(False)

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

    def _render_plan_tree(self, candidate: ChainCandidate | None, fallback_report: str = "") -> None:
        if not hasattr(self, "plan_map"):
            return
        if candidate is None:
            self.plan_summary_var.set("未找到能严格保证目标结果的路线。")
            self.plan_purchase_var.set(fallback_report.strip() or "请检查目标精灵、蛋组、性别、性格与库存素材。")
            self.plan_purchase_label.configure(style="Warning.TLabel")
            self.plan_map.set_root(None, "暂无可执行路线｜请检查目标与库存")
            return

        root = candidate.root
        audit_text = candidate.inventory_audit_text()
        if root.action is None:
            actual_species = root.leaf.species if root.leaf else root.species
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
            target_v = sum(value is not None for value in candidate.target_ivs)
            if candidate.target_nature and candidate.nature_strategy == "late" and target_v >= 2:
                nature_route = (
                    f"\n性格后置｜{target_v}V 随机性格主线 + "
                    f"{target_v - 1}V {candidate.target_nature} 支线，最终一步上不变石。"
                )
            elif candidate.target_nature:
                nature_route = f"\n不变石链｜沿性格支线逐级锁定 {candidate.target_nature}。"
            else:
                nature_route = ""
            self.plan_summary_var.set(
                f"库存预检｜{audit_text}\n"
                f"推荐方案｜复用库存 {root.existing_leaves} 只 · 补购 {root.purchases} 只 · "
                f"孵化 {root.breeds} 次 · 护腕 {root.braces} 个 · 不变之石 {root.everstones} 个{target_route}"
                f"{nature_route}\n中间性别｜{self.target_intermediate_gender_strategy_var.get()}；随机节点核销后记录实际性别并自动重算。"
            )

        requirements = candidate.purchase_requirements()
        if requirements:
            self.plan_purchase_var.set(
                f"仅靠库存无法完成，还需手动采购 {root.purchases} 只。"
                "雌性目标线负责出种；雄性缺料按同蛋组通用父本列出。"
                "可先完成蓝色库存节点，到橙色缺料节点时采购并 OCR 入库后重新规划。"
            )
            self.plan_purchase_label.configure(style="Warning.TLabel")
        else:
            self.plan_purchase_var.set("仅库存即可完成；所有叶子素材均已绑定本地记录，勾选步骤会自动核销父母。")
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
        next_step_number = (
            self.active_plan.next_step.number
            if same_active_plan and self.active_plan and self.active_plan.next_step
            else None
        )
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
            if state.is_virtual:
                return "交易行缺料"
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
                location = "/".join(value for value in (monster.page, monster.slot) if value)
                role = leaf_role(state)
                source = "手动采购" if state.is_virtual else (f"仓库 {location}" if location else "本地库存")
                nature_badge = "目标性格素材" if state.has_nature and candidate.target_nature else ""
                leaf_values = tuple("X" if value is None else str(value) for value in monster.ivs[:6])
                return MindMapNode(
                    key=f"{map_key_prefix}-leaf-{id(state)}",
                    title=f"{role} · {monster.species}",
                    iv_text=f"{sum(value == 31 for value in monster.ivs)}V",
                    iv_values=leaf_values,
                    detail=f"{gender_name(monster.gender)} · {monster.nature or '性格未知'} · {source}",
                    item_text=f"用于上层：{edge_item or '无需锁定道具'}",
                    status_text="缺料" if state.is_virtual else "库存",
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
            blocked = bool(step and step.requires_purchase)
            if completed:
                status = "已完成"
                kind = "completed"
            elif step_number == next_step_number:
                status = "缺料" if blocked else "当前步骤"
                kind = "purchase" if blocked else "current"
            elif blocked:
                status = "缺料"
                kind = "purchase"
            else:
                status = "待执行" if same_active_plan else "启用后执行"
                kind = "target" if is_root else "pending"

            if is_root:
                category = "头目" if candidate.target_alpha else "普通"
                hatch_species = candidate.offspring_species or state.species
                title = f"孵蛋目标 · {state_iv_summary(state)} {candidate.target_nature or '任意性格'} {category} {hatch_species}"
            elif depth == 1 and candidate.target_nature and state.has_nature:
                title = f"性格支线 · {state_iv_summary(state)} {state_nature_text(state)}"
            elif depth == 1 and candidate.target_nature:
                title = f"主 IV 线 · {state_iv_summary(state)} {state_nature_text(state)}"
            else:
                title = f"步骤 {step_number} · {state_iv_summary(state)} {state_nature_text(state)}"

            evolution = ""
            if state.breeding_species and state.breeding_species != state.species and not is_root:
                evolution = f" → 下步前进化为 {state.breeding_species}"
            gender_detail = step.gender_instruction if step else gender_name(state.gender)
            detail = f"{gender_detail} · 子代 {state.species}{evolution}"
            own_items = "、".join(value for value in ((step.item_a if step else ""), (step.item_b if step else "")) if value)
            item_text = f"本步道具：{own_items or '无'}"
            if edge_item:
                item_text += f"｜上层携带：{edge_item}"

            if display_plan and display_plan.target_nature and step:
                if step.uses_everstone:
                    nature_status = "性格：锁定"
                elif display_plan.adaptive_nature:
                    if completed:
                        nature_status = (
                            "爆性格：是"
                            if step.child.nature == display_plan.target_nature
                            else "爆性格：否"
                        )
                    else:
                        nature_status = "爆性格：待确认"
                else:
                    nature_status = "性格：随机"
            else:
                nature_status = "性格：不要求"

            node = MindMapNode(
                key=f"{map_key_prefix}-step-{step_number}",
                title=title,
                iv_text="IV",
                iv_values=tuple(self._plan_state_iv_text(state, candidate).split("/")),
                detail=detail,
                item_text=item_text,
                status_text=status,
                nature_text=nature_status,
                kind=kind,
                step_number=step_number or None,
                completed=completed,
                actionable=bool(step_number == next_step_number and not blocked),
                show_checkbox=True,
                species_id=species_sprite_id(state.species),
                item_keys=item_asset_keys(
                    *((step.item_a, step.item_b) if step else ((edge_item,) if edge_item else ()))
                ),
            )
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
        self.plan_map.set_root(map_root)

    def _activate_plan_step_number(self, step_number: int):
        plan = self.active_plan
        if plan is None or not self.proposed_plan or plan.id != self.proposed_plan.id:
            messagebox.showinfo("先启用方案", "请先点击“启用最佳方案”，再从思维导图底部按顺序勾选已完成节点。")
            return "break"
        step = next((item for item in plan.steps if item.number == step_number), None)
        if step is None:
            return "break"
        if step.completed:
            messagebox.showinfo("步骤已完成", "该步骤已经核销。若要恢复，请使用“撤销上一次核销”。")
            return "break"
        if plan.next_step is not step:
            messagebox.showwarning("依赖尚未完成", "请先完成导图中更靠下的当前步骤；孵化链必须按依赖顺序核销。")
            return "break"
        if step.requires_purchase:
            messagebox.showwarning("当前节点缺料", "请先手动采购橙色节点素材并 OCR 扫描入库，然后重新规划。")
            return "break"
        self.complete_next_step()
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
        save_active_plan(plan.to_dict())
        self.refresh_plan_status()
        if plan.next_step and plan.next_step.requires_purchase:
            messagebox.showinfo(
                "已启用路线",
                "当前第一个节点需要补购。请手动采购对应素材、OCR 扫描入库，再重新生成方案。",
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

    def complete_next_step(self) -> None:
        plan = self.active_plan
        if plan is None:
            messagebox.showwarning("没有执行方案", "请先生成并启用最佳方案。")
            return
        step = plan.next_step
        if step is None:
            messagebox.showinfo("方案已完成", "所有步骤已经完成，最终子代保留在库存中。")
            return
        if step.requires_purchase:
            messagebox.showwarning(
                "当前节点缺料",
                "当前步骤包含交易行补购素材，尚未绑定本地库存记录。请手动采购并 OCR 入库，然后重新规划。",
            )
            return
        prompt = (
            f"确认游戏中已经完成步骤 {step.number}？\n\n"
            f"将从本地库存删除：\n- {step.parent_a_label}\n- {step.parent_b_label}\n\n"
            f"并加入子代：{step.child.species} {step.child.iv_string}\n"
            f"性别操作：{step.gender_instruction}\n\n"
            + (f"注意：{step.child.notes}\n\n" if step.child.notes else "")
            +
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
        elif allowed_genders != ("F", "M") and allowed_genders:
            child_to_save.gender = allowed_genders[0]
        else:
            child_to_save.gender = step.expected_gender
        nature_hit = False
        if plan.adaptive_nature and plan.target_nature and not step.uses_everstone:
            nature_answer = messagebox.askyesnocancel(
                "记录随机性格",
                f"本步骤没有使用不变之石，子代性格是随机的。\n\n"
                f"是否爆出了目标性格“{plan.target_nature}”？\n\n"
                "是：按目标性格保存，并可立即用最新库存重算路线。\n"
                "否：按未命中保存，继续当前严格保底路线。\n"
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
        try:
            consume_parents_and_add_child(
                (step.parent_a_id, step.parent_b_id),
                child_to_save,
                plan.id,
                step.number,
            )
        except Exception as exc:
            messagebox.showerror("核销失败", str(exc))
            return
        step.child = child_to_save
        step.completed = True
        save_active_plan(plan.to_dict())
        self.inventory = load_inventory()
        self.refresh_inventory_tree()
        if (step.outcome_changes_plan or nature_hit) and not plan.completed:
            reasons = []
            if step.outcome_changes_plan:
                reasons.append(f"实际性别为{gender_name(child_to_save.gender)}")
            if nature_hit:
                reasons.append(f"爆出目标性格 {plan.target_nature}")
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
                f"所有父母已按步骤核销，最终 {step.child.species} 已保留在库存。{final_note}",
            )

    def undo_last_step(self) -> None:
        if not messagebox.askyesno("撤销核销", "撤销最近一次核销：删除该步子代并恢复两只父母。继续吗？"):
            return
        try:
            restored = undo_last_consumption()
        except Exception as exc:
            messagebox.showerror("撤销失败", str(exc))
            return
        if restored is None:
            messagebox.showinfo("没有历史", "没有可撤销的核销记录。")
            return
        _parent_a, _parent_b, child = restored
        if self.active_plan:
            step = next((item for item in self.active_plan.steps if item.child.id == child.id), None)
            if step:
                step.completed = False
                save_active_plan(self.active_plan.to_dict())
        self.inventory = load_inventory()
        self.refresh_inventory_tree()
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

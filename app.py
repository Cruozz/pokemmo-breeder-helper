from __future__ import annotations

import sys
import uuid
from pathlib import Path
from tkinter import END, BOTH, LEFT, RIGHT, TOP, X, Y, Canvas, StringVar, filedialog, messagebox
from tkinter import ttk

from PIL import Image, ImageGrab, ImageTk

BASE_DIR = Path(__file__).resolve().parent
VENDOR_DIR = BASE_DIR / "vendor"
if VENDOR_DIR.exists():
    sys.path.insert(0, str(VENDOR_DIR))

from capture import WindowInfo, capture_window, list_windows
from models import Monster, normalize_gender
from ocr_engine import OCRProcessor
from planner import make_report
from storage import load_inventory, save_inventory


class App:
    def __init__(self, root: ttk.Frame | object) -> None:
        self.root = root
        self.root.title("PokeMMO 孵蛋助手 - 只读 OCR MVP")
        self.root.geometry("1320x820")
        self.root.minsize(1100, 700)

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
        self.ocr: OCRProcessor | None = None

        self.page_var = StringVar()
        self.slot_var = StringVar()
        self.species_var = StringVar()
        self.gender_var = StringVar()
        self.nature_var = StringVar()
        self.iv_var = StringVar()
        self.ability_var = StringVar()
        self.item_var = StringVar()
        self.moves_var = StringVar()
        self.groups_var = StringVar()
        self.source_var = StringVar()
        self.status_var = StringVar(value="准备就绪。")
        self.target_species_var = StringVar()
        self.target_gender_var = StringVar(value="任意")
        self.target_nature_var = StringVar()
        self.target_iv_var = StringVar(value="31/31/x/x/x/31")
        self.target_groups_var = StringVar()

        self.build_ui()
        self.refresh_windows()
        self.refresh_inventory_tree()

    def build_ui(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("vista")
        except Exception:
            pass

        warning = ttk.Label(
            self.root,
            text="只读模式：你手动点击和翻页，本程序只截图/OCR，不自动点击、不发送游戏输入、不读内存。",
            foreground="#8a3b12",
        )
        warning.pack(fill=X, padx=10, pady=(8, 4))

        main = ttk.PanedWindow(self.root, orient="horizontal")
        main.pack(fill=BOTH, expand=True, padx=8, pady=5)

        left = ttk.Frame(main, padding=6)
        right = ttk.Frame(main, padding=6)
        main.add(left, weight=1)
        main.add(right, weight=2)
        self.build_capture_panel(left)
        self.build_right_panel(right)

        ttk.Label(self.root, textvariable=self.status_var, relief="sunken", anchor="w").pack(fill=X, padx=8, pady=(0, 8))

    def build_capture_panel(self, parent: ttk.Frame) -> None:
        source = ttk.LabelFrame(parent, text="当前画面", padding=6)
        source.pack(fill=X, pady=(0, 6))

        ttk.Button(source, text="刷新窗口", command=self.refresh_windows).grid(row=0, column=0, padx=3, pady=3)
        self.window_combo = ttk.Combobox(source, state="readonly", width=43)
        self.window_combo.grid(row=0, column=1, columnspan=2, sticky="ew", padx=3, pady=3)
        ttk.Button(source, text="截取选中窗口", command=self.capture_selected_window).grid(row=0, column=3, padx=3, pady=3)

        ttk.Button(source, text="加载截图", command=self.load_image).grid(row=1, column=0, padx=3, pady=3)
        ttk.Button(source, text="读取剪贴板", command=self.load_clipboard).grid(row=1, column=1, padx=3, pady=3)
        ttk.Button(source, text="默认左侧信息区", command=self.set_default_roi).grid(row=1, column=2, padx=3, pady=3)
        ttk.Button(source, text="清除框选", command=self.clear_roi).grid(row=1, column=3, padx=3, pady=3)
        source.columnconfigure(1, weight=1)
        source.columnconfigure(2, weight=1)

        self.canvas = Canvas(parent, background="#20252b", highlightthickness=1, highlightbackground="#77808a")
        self.canvas.pack(fill=BOTH, expand=True)
        self.canvas.bind("<ButtonPress-1>", self.start_roi)
        self.canvas.bind("<B1-Motion>", self.drag_roi)
        self.canvas.bind("<ButtonRelease-1>", self.finish_roi)

        tip = ttk.Label(
            parent,
            text="可以在预览图上框选左侧信息面板。建议每次你手动点选精灵后，点击右侧“识别当前”。",
            wraplength=470,
            justify="left",
        )
        tip.pack(fill=X, pady=(6, 0))

    def build_right_panel(self, parent: ttk.Frame) -> None:
        tabs = ttk.Notebook(parent)
        tabs.pack(fill=BOTH, expand=True)

        current_tab = ttk.Frame(tabs, padding=8)
        inventory_tab = ttk.Frame(tabs, padding=8)
        planner_tab = ttk.Frame(tabs, padding=8)
        tabs.add(current_tab, text="识别当前")
        tabs.add(inventory_tab, text="素材库存")
        tabs.add(planner_tab, text="孵蛋规划")
        self.build_current_tab(current_tab)
        self.build_inventory_tab(inventory_tab)
        self.build_planner_tab(planner_tab)

    def build_current_tab(self, parent: ttk.Frame) -> None:
        form = ttk.LabelFrame(parent, text="识别结果（可手动修正）", padding=8)
        form.pack(fill=X)
        fields = [
            ("仓库页", self.page_var),
            ("格子", self.slot_var),
            ("种类", self.species_var),
            ("性别 M/F", self.gender_var),
            ("性格", self.nature_var),
            ("个体值", self.iv_var),
            ("特性", self.ability_var),
            ("持有道具", self.item_var),
            ("蛋组", self.groups_var),
            ("招式（逗号分隔）", self.moves_var),
        ]
        for index, (label, variable) in enumerate(fields):
            row = index // 2
            column = (index % 2) * 2
            ttk.Label(form, text=label).grid(row=row, column=column, sticky="e", padx=4, pady=4)
            ttk.Entry(form, textvariable=variable, width=27).grid(row=row, column=column + 1, sticky="ew", padx=4, pady=4)
        form.columnconfigure(1, weight=1)
        form.columnconfigure(3, weight=1)

        actions = ttk.Frame(parent)
        actions.pack(fill=X, pady=8)
        ttk.Button(actions, text="识别当前截图", command=self.ocr_current).pack(side=LEFT, padx=(0, 6))
        ttk.Button(actions, text="保存到库存", command=self.save_current_monster).pack(side=LEFT, padx=6)
        ttk.Button(actions, text="清空结果", command=self.clear_current).pack(side=LEFT, padx=6)

        ttk.Label(parent, text="OCR 原始文本（用于检查识别错误）").pack(anchor="w")
        self.raw_text = ttk.Frame(parent)
        self.raw_text.pack(fill=BOTH, expand=True)
        self.raw_text_box = __import__("tkinter").Text(self.raw_text, height=12, wrap="word")
        self.raw_text_box.pack(fill=BOTH, expand=True)

    def build_inventory_tab(self, parent: ttk.Frame) -> None:
        actions = ttk.Frame(parent)
        actions.pack(fill=X, pady=(0, 8))
        ttk.Button(actions, text="刷新列表", command=self.refresh_inventory_tree).pack(side=LEFT, padx=4)
        ttk.Button(actions, text="删除选中", command=self.delete_selected_inventory).pack(side=LEFT, padx=4)
        ttk.Button(actions, text="导出 JSON", command=self.export_inventory).pack(side=LEFT, padx=4)
        ttk.Button(actions, text="导入 JSON", command=self.import_inventory).pack(side=LEFT, padx=4)

        columns = ("page", "slot", "species", "gender", "nature", "ivs", "groups")
        self.inventory_tree = ttk.Treeview(parent, columns=columns, show="headings", selectmode="browse")
        headings = {
            "page": "页",
            "slot": "格",
            "species": "种类",
            "gender": "性别",
            "nature": "性格",
            "ivs": "个体值",
            "groups": "蛋组",
        }
        widths = {"page": 65, "slot": 55, "species": 150, "gender": 55, "nature": 100, "ivs": 145, "groups": 150}
        for column in columns:
            self.inventory_tree.heading(column, text=headings[column])
            self.inventory_tree.column(column, width=widths[column], anchor="center")
        self.inventory_tree.pack(fill=BOTH, expand=True)
        self.inventory_tree.bind("<<TreeviewSelect>>", self.inventory_selected)

    def build_planner_tab(self, parent: ttk.Frame) -> None:
        form = ttk.LabelFrame(parent, text="目标精灵", padding=8)
        form.pack(fill=X)
        target_fields = [
            ("种类", self.target_species_var),
            ("目标性格", self.target_nature_var),
            ("目标 IV", self.target_iv_var),
            ("蛋组（可选）", self.target_groups_var),
        ]
        for row, (label, variable) in enumerate(target_fields):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="e", padx=4, pady=4)
            ttk.Entry(form, textvariable=variable, width=34).grid(row=row, column=1, sticky="ew", padx=4, pady=4)
        ttk.Label(form, text="目标性别").grid(row=0, column=2, sticky="e", padx=4, pady=4)
        ttk.Combobox(form, textvariable=self.target_gender_var, values=("任意", "雄性", "雌性"), state="readonly", width=12).grid(row=0, column=3, padx=4, pady=4)
        form.columnconfigure(1, weight=1)

        ttk.Button(parent, text="根据当前库存生成方案", command=self.generate_plan).pack(anchor="w", pady=8)
        self.plan_box = __import__("tkinter").Text(parent, height=24, wrap="word")
        self.plan_box.pack(fill=BOTH, expand=True)

    def refresh_windows(self) -> None:
        self.windows = list_windows()
        labels = [window.label() for window in self.windows]
        self.window_combo["values"] = labels
        preferred = next((index for index, window in enumerate(self.windows) if "pokemmo" in window.title.lower()), 0)
        if labels:
            self.window_combo.current(preferred)
        self.status_var.set(f"已发现 {len(labels)} 个可见窗口。")

    def capture_selected_window(self) -> None:
        index = self.window_combo.current()
        if index < 0 or index >= len(self.windows):
            messagebox.showwarning("没有选择窗口", "请先刷新并选择 PokeMMO 窗口。")
            return
        try:
            image = capture_window(self.windows[index])
        except Exception as exc:
            messagebox.showerror("截图失败", str(exc))
            return
        self.set_image(image, f"窗口：{self.windows[index].title}")

    def load_image(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("图片", "*.png *.jpg *.jpeg *.webp *.bmp"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            image = Image.open(path).convert("RGB")
        except Exception as exc:
            messagebox.showerror("加载失败", str(exc))
            return
        self.set_image(image, path)

    def load_clipboard(self) -> None:
        image = ImageGrab.grabclipboard()
        if not isinstance(image, Image.Image):
            messagebox.showwarning("剪贴板没有图片", "请先复制一张截图。")
            return
        self.set_image(image.convert("RGB"), "剪贴板")

    def set_image(self, image: Image.Image, source: str) -> None:
        self.current_image = image
        self.current_source = source
        self.source_var.set(source)
        self.roi = None
        self.drag_rectangle = None
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
            if self.ocr is None:
                self.status_var.set("正在加载本地 OCR 模型，首次可能需要几秒……")
                self.root.update_idletasks()
                self.ocr = OCRProcessor()
            items = self.ocr.recognize(image)
            parsed = OCRProcessor.parse(items)
        except Exception as exc:
            messagebox.showerror("OCR 失败", str(exc))
            self.status_var.set("OCR 失败，请检查图片或依赖。")
            return
        self.species_var.set(parsed["species"])
        self.gender_var.set(parsed["gender"])
        self.nature_var.set(parsed["nature"])
        self.iv_var.set("/".join("x" if value is None else str(value) for value in parsed["ivs"]))
        self.ability_var.set(parsed["ability"])
        self.item_var.set(parsed["held_item"])
        self.source_var.set(self.current_source)
        self.raw_text_box.delete("1.0", END)
        self.raw_text_box.insert("1.0", parsed["raw_text"])
        self.status_var.set(f"OCR 完成，识别到 {len(items)} 个文本块；请确认后保存。")

    def clear_current(self) -> None:
        for variable in (self.species_var, self.gender_var, self.nature_var, self.iv_var, self.ability_var, self.item_var, self.moves_var, self.groups_var, self.source_var):
            variable.set("")
        self.raw_text_box.delete("1.0", END)

    def save_current_monster(self) -> None:
        species = self.species_var.get().strip()
        if not species:
            messagebox.showwarning("信息不完整", "至少需要填写精灵种类。")
            return
        values = [x.strip() for x in self.iv_var.get().replace("／", "/").split("/")]
        ivs = []
        for value in values[:6]:
            try:
                ivs.append(int(value) if value.lower() not in {"x", ""} else None)
            except ValueError:
                ivs.append(None)
        ivs = ivs + [None] * max(0, 6 - len(ivs))
        monster = Monster(
            id=str(uuid.uuid4()),
            species=species,
            gender=self.gender_var.get(),
            nature=self.nature_var.get(),
            ivs=ivs,
            ability=self.ability_var.get(),
            held_item=self.item_var.get(),
            moves=[x.strip() for x in self.moves_var.get().split(",") if x.strip()],
            egg_groups=[x.strip() for x in self.groups_var.get().replace("，", ",").split(",") if x.strip()],
            page=self.page_var.get(),
            slot=self.slot_var.get(),
            source=self.current_source,
        )
        self.inventory.append(monster)
        save_inventory(self.inventory)
        self.refresh_inventory_tree()
        self.status_var.set(f"已保存 {monster.species}，库存共 {len(self.inventory)} 只。")

    def refresh_inventory_tree(self) -> None:
        if not hasattr(self, "inventory_tree"):
            return
        for item in self.inventory_tree.get_children():
            self.inventory_tree.delete(item)
        for monster in self.inventory:
            self.inventory_tree.insert("", END, iid=monster.id, values=(monster.page, monster.slot, monster.species, monster.gender, monster.nature, monster.iv_string, monster.group_string))

    def inventory_selected(self, _event=None) -> None:
        selected = self.inventory_tree.selection()
        if not selected:
            return
        monster = next((item for item in self.inventory if item.id == selected[0]), None)
        if monster:
            self.page_var.set(monster.page)
            self.slot_var.set(monster.slot)
            self.species_var.set(monster.species)
            self.gender_var.set(monster.gender)
            self.nature_var.set(monster.nature)
            self.iv_var.set(monster.iv_string)
            self.ability_var.set(monster.ability)
            self.item_var.set(monster.held_item)
            self.groups_var.set(monster.group_string)
            self.moves_var.set(", ".join(monster.moves))

    def delete_selected_inventory(self) -> None:
        selected = self.inventory_tree.selection()
        if not selected:
            return
        self.inventory = [item for item in self.inventory if item.id != selected[0]]
        save_inventory(self.inventory)
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
            data = __import__("json").loads(Path(path).read_text(encoding="utf-8"))
            imported = [Monster.from_dict(item) for item in data if isinstance(item, dict)]
        except Exception as exc:
            messagebox.showerror("导入失败", str(exc))
            return
        self.inventory.extend(imported)
        save_inventory(self.inventory)
        self.refresh_inventory_tree()
        self.status_var.set(f"已导入 {len(imported)} 条素材。")

    def generate_plan(self) -> None:
        target_gender = {"任意": "", "雄性": "M", "雌性": "F"}.get(self.target_gender_var.get(), "")
        groups = [x.strip() for x in self.target_groups_var.get().replace("，", ",").split(",") if x.strip()]
        report = make_report(
            self.inventory,
            self.target_species_var.get(),
            target_gender,
            self.target_nature_var.get(),
            self.target_iv_var.get(),
            groups,
        )
        self.plan_box.delete("1.0", END)
        self.plan_box.insert("1.0", report)


def main() -> None:
    import tkinter as tk

    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()

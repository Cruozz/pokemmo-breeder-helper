from __future__ import annotations

from collections.abc import Callable
from tkinter import BOTH, LEFT, X, BooleanVar, Canvas, StringVar, Toplevel
from tkinter import ttk

from PIL import Image, ImageTk

from preview_geometry import fit_scale, image_point, normalized_roi, rescale_roi


class PreviewZoomWindow:
    """Live frames and the user's uncommitted selection have separate ownership."""

    def __init__(self, root, image: Image.Image, roi, on_apply: Callable, *, on_close=None, background="#0F172A"):
        self.root = root
        self.image = image.copy()
        self.roi = roi
        self.on_apply = on_apply
        self.on_close = on_close
        self.scale = 1.0
        self.fit_mode = True
        self.closed = False
        self.dirty = False
        self.photo = None
        self.image_item = None
        self.roi_item = None
        self.drag_start = None
        self.draft_roi = None
        self.pending_frame = None
        self.resize_after_id = None
        self.offset = (0, 0)
        self.rendered_size = image.size
        self.fields_pending = False
        self.syncing_fields = False

        self.window = Toplevel(root)
        self.window.title("放大预览与 OCR 框选")
        self.window.geometry("1000x720")
        self.window.minsize(640, 460)
        self.window.transient(root)
        self.always_on_top_var = BooleanVar(self.window, value=False)
        self.status_var = StringVar(self.window)
        self.view_var = StringVar(self.window)

        toolbar = ttk.Frame(self.window, padding=(10, 8))
        toolbar.pack(fill=X)
        ttk.Button(toolbar, text="适合窗口", command=self.fit_to_window).pack(side=LEFT)
        ttk.Button(toolbar, text="1:1", command=self.actual_size).pack(side=LEFT, padx=4)
        ttk.Button(toolbar, text="−", width=3, command=lambda: self.zoom_by(1 / 1.2)).pack(side=LEFT, padx=2)
        ttk.Button(toolbar, text="+", width=3, command=lambda: self.zoom_by(1.2)).pack(side=LEFT, padx=2)
        ttk.Label(toolbar, textvariable=self.view_var).pack(side=LEFT, padx=8)
        ttk.Checkbutton(toolbar, text="始终置顶", variable=self.always_on_top_var,
                        command=self._toggle_always_on_top).pack(side="right")

        selection = ttk.Frame(self.window, padding=(10, 0, 10, 6))
        selection.pack(fill=X)
        ttk.Button(selection, text="默认左侧", command=self.default_roi).pack(side=LEFT)
        ttk.Button(selection, text="清除框选", command=self.clear_roi).pack(side=LEFT, padx=6)
        ttk.Label(selection, text="左键自由框选 · 滚轮缩放 · 中键平移").pack(side=LEFT)
        coords = ttk.Frame(self.window, padding=(10, 0, 10, 8))
        coords.pack(fill=X)
        self.coord_vars = []
        for label in ("X", "Y", "宽", "高"):
            ttk.Label(coords, text=label).pack(side=LEFT, padx=(0, 3))
            variable = StringVar(self.window)
            variable.trace_add("write", self._fields_changed)
            self.coord_vars.append(variable)
            entry = ttk.Entry(coords, textvariable=variable, width=6)
            entry.pack(side=LEFT, padx=(0, 8))
            entry.bind("<Return>", self._commit_coordinates)
        ttk.Button(coords, text="更新选框", command=self._commit_coordinates).pack(side=LEFT)
        ttk.Label(coords, text="原图像素").pack(side=LEFT, padx=8)

        footer = ttk.Frame(self.window, padding=(10, 8))
        footer.pack(side="bottom", fill=X)
        self.close_button = ttk.Button(footer, text="收回主窗口", command=self.close)
        self.close_button.pack(side="right")
        ttk.Button(footer, text="应用框选并收回", style="Primary.TButton", command=self.apply).pack(side="right", padx=8)
        ttk.Label(footer, textvariable=self.status_var, wraplength=310).pack(side=LEFT, fill=X, expand=True)

        body = ttk.Frame(self.window)
        body.pack(fill=BOTH, expand=True)
        self.canvas = Canvas(body, background=background, highlightthickness=0)
        xbar = ttk.Scrollbar(body, orient="horizontal", command=self.canvas.xview)
        ybar = ttk.Scrollbar(body, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=xbar.set, yscrollcommand=ybar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)
        for sequence, callback in (
            ("<MouseWheel>", self._zoom), ("<ButtonPress-2>", self._pan_start),
            ("<B2-Motion>", self._pan_move), ("<ButtonPress-1>", self._roi_start),
            ("<B1-Motion>", self._roi_drag), ("<ButtonRelease-1>", self._roi_finish),
            ("<Configure>", self._schedule_resize),
        ):
            self.canvas.bind(sequence, callback)
        self.window.bind("<Escape>", lambda _event: self.close())
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self._sync_fields()
        self._update_status()
        self.resize_after_id = self.window.after_idle(self._resize)

    def focus(self):
        self.window.deiconify()
        self.window.lift()
        self.window.focus_force()

    def _schedule_resize(self, _event=None):
        if self.closed:
            return
        if self.resize_after_id is not None:
            self.window.after_cancel(self.resize_after_id)
        self.resize_after_id = self.window.after(50, self._resize)

    def _resize(self):
        self.resize_after_id = None
        if not self.closed and self.drag_start is None:
            self._render()

    def fit_to_window(self):
        if self.drag_start is not None:
            return
        self.fit_mode = True
        self._render()
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)

    def actual_size(self):
        if self.drag_start is not None:
            return
        self.fit_mode = False
        self.scale = 1.0
        self._render()

    def _render(self):
        cw, ch = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
        if self.fit_mode:
            self.scale = fit_scale(self.image.size, (cw, ch))
        width, height = (max(1, round(n * self.scale)) for n in self.image.size)
        self.rendered_size = (width, height)
        self.offset = (max(0, (cw - width) // 2), max(0, (ch - height) // 2))
        display = self.image.resize((width, height), Image.Resampling.BILINEAR)
        # Retain the old image until the canvas has received its replacement.
        photo = ImageTk.PhotoImage(display, master=self.window)
        if self.image_item is None:
            self.image_item = self.canvas.create_image(*self.offset, image=photo, anchor="nw")
        else:
            self.canvas.coords(self.image_item, *self.offset)
            self.canvas.itemconfigure(self.image_item, image=photo)
        self.photo = photo
        self.canvas.tag_lower(self.image_item)
        self.canvas.configure(scrollregion=(0, 0, max(cw, width), max(ch, height)))
        if self.fit_mode:
            self.canvas.xview_moveto(0)
            self.canvas.yview_moveto(0)
        self.view_var.set(f"{'适合窗口' if self.fit_mode else '手动缩放'} · {self.scale:.0%}")
        self._draw_roi()

    def _draw_roi(self):
        roi = self.draft_roi if self.drag_start is not None else self.roi
        if roi is None:
            if self.roi_item is not None:
                self.canvas.itemconfigure(self.roi_item, state="hidden")
            return
        sx, sy = (self.rendered_size[i] / self.image.size[i] for i in (0, 1))
        ox, oy = self.offset
        coords = (ox + roi[0] * sx, oy + roi[1] * sy, ox + roi[2] * sx, oy + roi[3] * sy)
        if self.roi_item is None:
            self.roi_item = self.canvas.create_rectangle(*coords, outline="#38BDF8", width=2)
        else:
            self.canvas.coords(self.roi_item, *coords)
            self.canvas.itemconfigure(self.roi_item, state="normal")
        self.canvas.tag_raise(self.roi_item)

    def zoom_by(self, factor, anchor=None):
        if self.drag_start is not None:
            return
        if anchor is None:
            anchor = (self.canvas.winfo_width() / 2, self.canvas.winfo_height() / 2)
        point = self._image_point(*anchor)
        self.scale = max(0.01, min(8.0, self.scale * factor))
        self.fit_mode = False
        self._render()
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        w, h = self.rendered_size
        ox, oy = self.offset
        self.canvas.xview_moveto((point[0] * w / self.image.width + ox - anchor[0]) / max(cw, w))
        self.canvas.yview_moveto((point[1] * h / self.image.height + oy - anchor[1]) / max(ch, h))

    def _zoom(self, event):
        if event.delta:
            self.zoom_by(1.12 if event.delta > 0 else 1 / 1.12, (event.x, event.y))
        return "break"

    def _pan_start(self, event):
        if self.drag_start is None:
            self.fit_mode = False
            self.canvas.scan_mark(event.x, event.y)

    def _pan_move(self, event):
        if self.drag_start is None:
            self.canvas.scan_dragto(event.x, event.y, gain=1)

    def _image_point(self, x, y):
        return image_point((self.canvas.canvasx(x), self.canvas.canvasy(y)), self.offset,
                           self.rendered_size, self.image.size)

    def _roi_start(self, event):
        point = self._image_point(event.x, event.y)
        if not (0 <= point[0] <= self.image.width and 0 <= point[1] <= self.image.height):
            return
        self.drag_start = point
        self.draft_roi = self.roi
        self.status_var.set("正在框选，松开鼠标后确认；应用后用于 OCR。")

    def _roi_drag(self, event):
        if self.drag_start is not None:
            self.draft_roi = normalized_roi(self.drag_start, self._image_point(event.x, event.y), self.image.size)
            self._draw_roi()

    def _roi_finish(self, event):
        if self.drag_start is None:
            return
        roi = normalized_roi(self.drag_start, self._image_point(event.x, event.y), self.image.size)
        self.drag_start = None
        self.draft_roi = None
        if roi[2] - roi[0] >= 2 and roi[3] - roi[1] >= 2:
            self.roi = roi
            self.dirty = True
        self._sync_fields()
        self._flush_pending_frame()
        self._render()
        self._update_status()

    def _fields_changed(self, *_args):
        if not self.syncing_fields:
            self.fields_pending = True
            self.status_var.set("坐标待确认：按回车或点击「更新选框」。")
            self.close_button.configure(text="取消并收回")

    def _sync_fields(self):
        self.syncing_fields = True
        try:
            l, t, r, b = self.roi or (0, 0, self.image.width, self.image.height)
            for var, value in zip(self.coord_vars, (l, t, r - l, b - t)):
                var.set(str(value))
        finally:
            self.syncing_fields = False
            self.fields_pending = False

    def _commit_coordinates(self, _event=None):
        try:
            x, y, w, h = [int(var.get()) for var in self.coord_vars]
            if x < 0 or y < 0 or w < 2 or h < 2 or x + w > self.image.width or y + h > self.image.height:
                raise ValueError
        except ValueError:
            self.status_var.set(f"请输入有效整数：选区须在 {self.image.width}×{self.image.height} 内，宽高至少 2。")
            return "break"
        self.roi = (x, y, x + w, y + h)
        self.dirty = True
        self._sync_fields()
        self._flush_pending_frame()
        self._draw_roi()
        self._update_status()
        return "break"

    def _update_status(self):
        self.close_button.configure(text="取消并收回" if self.dirty or self.fields_pending else "收回主窗口")
        text = "整幅画面" if self.roi is None else f"选区 {self.roi[2]-self.roi[0]}×{self.roi[3]-self.roi[1]} 像素"
        self.status_var.set(f"{text} · {'尚未应用' if self.dirty else '当前 OCR 区域'}")

    def default_roi(self):
        self.roi = (0, 0, round(self.image.width * 0.32), self.image.height)
        self.dirty = True
        self._sync_fields()
        self._flush_pending_frame()
        self._draw_roi()
        self._update_status()

    def clear_roi(self):
        self.roi = None
        self.dirty = True
        self._sync_fields()
        self._flush_pending_frame()
        self._draw_roi()
        self._update_status()

    def apply(self):
        if self.fields_pending:
            self._commit_coordinates()
            if self.fields_pending:
                return
        self.on_apply(self.roi)
        self.close()

    def update_image(self, image: Image.Image, roi=None):
        if self.closed or not self.window.winfo_exists():
            return
        # Keep the coordinate transform fixed for the whole gesture/edit.
        if self.drag_start is not None or self.fields_pending:
            self.pending_frame = (image, roi)
            return
        old_size = self.image.size
        self.image = image.copy()
        if self.dirty:
            self.roi = rescale_roi(self.roi, old_size, image.size)
        else:
            self.roi = roi
        self._sync_fields()
        self._render()
        self._update_status()

    def _flush_pending_frame(self):
        pending, self.pending_frame = self.pending_frame, None
        if pending:
            self.update_image(*pending)

    def _toggle_always_on_top(self):
        self.window.attributes("-topmost", bool(self.always_on_top_var.get()))

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.resize_after_id is not None:
            self.window.after_cancel(self.resize_after_id)
            self.resize_after_id = None
        self.pending_frame = None
        if self.on_close is not None:
            self.on_close()
        self.window.destroy()

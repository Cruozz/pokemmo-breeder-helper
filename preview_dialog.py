from __future__ import annotations

from collections.abc import Callable
from tkinter import BOTH, LEFT, X, BooleanVar, Canvas, Toplevel
from tkinter import ttk

from PIL import Image, ImageTk


class PreviewZoomWindow:
    """Resizable live preview that also supports precise OCR ROI selection."""

    def __init__(
        self,
        root,
        image: Image.Image,
        roi: tuple[int, int, int, int] | None,
        on_apply: Callable[[tuple[int, int, int, int] | None], None],
        *,
        on_close: Callable[[], None] | None = None,
        background: str = "#0F172A",
    ) -> None:
        self.root = root
        self.image = image.copy()
        self.roi = roi
        self.on_apply = on_apply
        self.on_close = on_close
        self.scale = 1.0
        self.fit_mode = True
        self.closed = False
        self.photo = None
        self.image_item = None
        self.roi_item = None
        self.drag_start: tuple[float, float] | None = None

        self.window = Toplevel(root)
        self.window.title("放大预览与 OCR 框选")
        self.window.geometry("1000x720")
        self.window.minsize(640, 460)
        self.window.transient(root)
        self.always_on_top_var = BooleanVar(value=False)

        toolbar = ttk.Frame(self.window, padding=(10, 8))
        toolbar.pack(fill=X)
        ttk.Label(toolbar, text="左键拖动框选 · 滚轮缩放 · 按住中键拖动画面").pack(side=LEFT)
        ttk.Button(toolbar, text="适合窗口", command=self.fit_to_window).pack(side=LEFT, padx=(12, 4))
        ttk.Button(toolbar, text="−", width=3, command=lambda: self.zoom_by(1 / 1.2)).pack(side=LEFT, padx=2)
        ttk.Button(toolbar, text="+", width=3, command=lambda: self.zoom_by(1.2)).pack(side=LEFT, padx=2)
        ttk.Button(toolbar, text="默认左侧", command=self.default_roi).pack(side=LEFT, padx=4)
        ttk.Button(toolbar, text="清除框选", command=self.clear_roi).pack(side=LEFT, padx=4)
        ttk.Checkbutton(
            toolbar,
            text="始终置顶",
            variable=self.always_on_top_var,
            command=self._toggle_always_on_top,
        ).pack(side=LEFT, padx=(8, 0))
        ttk.Button(toolbar, text="应用框选", style="Primary.TButton", command=self.apply).pack(side="right")
        ttk.Button(toolbar, text="收回主窗口", command=self.close).pack(side="right", padx=(4, 8))

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

        self.canvas.bind("<MouseWheel>", self._zoom)
        self.canvas.bind("<ButtonPress-2>", self._pan_start)
        self.canvas.bind("<B2-Motion>", self._pan_move)
        self.canvas.bind("<ButtonPress-1>", self._roi_start)
        self.canvas.bind("<B1-Motion>", self._roi_drag)
        self.canvas.bind("<ButtonRelease-1>", self._roi_finish)
        self.window.bind("<Escape>", lambda _event: self.close())
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.window.after_idle(self.fit_to_window)

    def focus(self) -> None:
        self.window.deiconify()
        self.window.lift()
        self.window.focus_force()

    def fit_to_window(self) -> None:
        self.canvas.update_idletasks()
        width = max(1, self.canvas.winfo_width() - 20)
        height = max(1, self.canvas.winfo_height() - 20)
        self.scale = max(0.1, min(2.0, width / self.image.width, height / self.image.height))
        self.fit_mode = True
        self._render()
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)

    def _render(self) -> None:
        width = max(1, round(self.image.width * self.scale))
        height = max(1, round(self.image.height * self.scale))
        display = self.image.resize((width, height), Image.Resampling.BILINEAR)
        self.photo = ImageTk.PhotoImage(display)
        if self.image_item is None:
            self.image_item = self.canvas.create_image(0, 0, image=self.photo, anchor="nw")
        else:
            self.canvas.itemconfigure(self.image_item, image=self.photo)
        self.canvas.configure(scrollregion=(0, 0, width, height))
        self._draw_roi()

    def _draw_roi(self) -> None:
        if self.roi is None:
            if self.roi_item is not None:
                self.canvas.itemconfigure(self.roi_item, state="hidden")
            return
        left, top, right, bottom = self.roi
        coords = (
            left * self.scale,
            top * self.scale,
            right * self.scale,
            bottom * self.scale,
        )
        if self.roi_item is None:
            self.roi_item = self.canvas.create_rectangle(
                *coords,
                outline="#38BDF8",
                width=3,
            )
        else:
            self.canvas.coords(self.roi_item, *coords)
            self.canvas.itemconfigure(self.roi_item, state="normal")

    def zoom_by(self, factor: float) -> None:
        old_scale = self.scale
        self.scale = max(0.1, min(5.0, self.scale * factor))
        if abs(self.scale - old_scale) >= 0.001:
            self.fit_mode = False
            self._render()

    def _zoom(self, event) -> str:
        old_scale = self.scale
        factor = 1.12 if event.delta > 0 else 1 / 1.12
        self.scale = max(0.1, min(5.0, self.scale * factor))
        if abs(self.scale - old_scale) < 0.001:
            return "break"
        self.fit_mode = False
        image_x = self.canvas.canvasx(event.x) / old_scale
        image_y = self.canvas.canvasy(event.y) / old_scale
        self._render()
        total_width = max(1, self.image.width * self.scale)
        total_height = max(1, self.image.height * self.scale)
        self.canvas.xview_moveto(max(0.0, (image_x * self.scale - event.x) / total_width))
        self.canvas.yview_moveto(max(0.0, (image_y * self.scale - event.y) / total_height))
        return "break"

    def _pan_start(self, event) -> None:
        self.fit_mode = False
        self.canvas.scan_mark(event.x, event.y)

    def _pan_move(self, event) -> None:
        self.canvas.scan_dragto(event.x, event.y, gain=1)

    def _image_point(self, x: int, y: int) -> tuple[float, float]:
        return self.canvas.canvasx(x) / self.scale, self.canvas.canvasy(y) / self.scale

    def _roi_start(self, event) -> None:
        self.drag_start = self._image_point(event.x, event.y)

    def _roi_drag(self, event) -> None:
        if self.drag_start is None:
            return
        end = self._image_point(event.x, event.y)
        self.roi = self._normalized_roi(self.drag_start, end)
        self._draw_roi()

    def _roi_finish(self, event) -> None:
        if self.drag_start is None:
            return
        end = self._image_point(event.x, event.y)
        roi = self._normalized_roi(self.drag_start, end)
        self.drag_start = None
        if roi[2] - roi[0] < 20 or roi[3] - roi[1] < 20:
            return
        self.roi = roi
        self._draw_roi()

    def _normalized_roi(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
    ) -> tuple[int, int, int, int]:
        left = max(0, min(self.image.width, round(min(start[0], end[0]))))
        right = max(0, min(self.image.width, round(max(start[0], end[0]))))
        top = max(0, min(self.image.height, round(min(start[1], end[1]))))
        bottom = max(0, min(self.image.height, round(max(start[1], end[1]))))
        return left, top, right, bottom

    def default_roi(self) -> None:
        self.roi = (0, 0, round(self.image.width * 0.32), self.image.height)
        self._draw_roi()

    def clear_roi(self) -> None:
        self.roi = None
        self._draw_roi()

    def apply(self) -> None:
        self.on_apply(self.roi)
        self.close()

    def update_image(self, image: Image.Image, roi: tuple[int, int, int, int] | None = None) -> None:
        """Refresh the detached view without creating a second capture loop."""
        if self.closed or not self.window.winfo_exists():
            return
        size_changed = image.size != self.image.size
        self.image = image.copy()
        self.roi = roi
        if size_changed and self.fit_mode:
            self.fit_to_window()
        else:
            self._render()

    def _toggle_always_on_top(self) -> None:
        self.window.attributes("-topmost", bool(self.always_on_top_var.get()))

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if self.on_close is not None:
            self.on_close()
        try:
            self.window.destroy()
        except Exception:
            pass

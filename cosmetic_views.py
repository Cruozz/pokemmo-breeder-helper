"""Explicit desktop editors; automatic capture never opens these windows."""
from pathlib import Path
from tkinter import BooleanVar, Canvas, StringVar, Toplevel, ttk

from cosmetics import PARTICLE_MODES, costume_family, particle_catalog, particle_names


def choose_particles(parent, selected, callback):
    from PIL import Image, ImageTk
    window = Toplevel(parent)
    window.title("选择粒子")
    window.geometry("580x570")
    window.minsize(420, 360)
    window.transient(parent)
    entries = [entry for entry in particle_catalog() if not entry["intrinsic"]]
    preserved = [value for value in selected if value not in {entry["id"] for entry in entries}]
    choices = {entry["id"]: BooleanVar(window, entry["id"] in selected) for entry in entries}
    search = StringVar(window)
    ttk.Entry(window, textvariable=search).pack(fill="x", padx=12, pady=10)
    host = ttk.Frame(window)
    host.pack(fill="both", expand=True, padx=12)
    canvas = Canvas(host, highlightthickness=0)
    scroll = ttk.Scrollbar(host, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=scroll.set)
    scroll.pack(side="right", fill="y"); canvas.pack(side="left", fill="both", expand=True)
    body = ttk.Frame(canvas)
    item = canvas.create_window(0, 0, window=body, anchor="nw")
    canvas.bind("<Configure>", lambda event: canvas.itemconfigure(item, width=event.width))
    body.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
    rows = []
    photos = []
    for entry in entries:
        photo = ImageTk.PhotoImage(Image.open(Path(__file__).resolve().parent / "data" / entry["icon"]), master=window)
        photos.append(photo)
        row = ttk.Frame(body)
        ttk.Checkbutton(row, text=entry["name"] + "  /  " + entry["english_name"], image=photo,
                        compound="left", variable=choices[entry["id"]]).pack(anchor="w", fill="x", pady=5)
        row.pack(fill="x")
        rows.append((entry, row))
    def filter_rows(*_):
        query = search.get().casefold().strip()
        for entry, row in rows:
            row.pack_forget()
            if not query or query in (entry["name"] + " " + entry["english_name"]).casefold():
                row.pack(fill="x")
        canvas.yview_moveto(0)
    search.trace_add("write", filter_rows)
    def save():
        callback(preserved + [entry["id"] for entry in entries if choices[entry["id"]].get()])
        window.destroy()
    controls = ttk.Frame(window, padding=12); controls.pack(fill="x")
    ttk.Button(controls, text="保存", command=save).pack(side="right")
    ttk.Button(controls, text="取消", command=window.destroy).pack(side="right", padx=8)
    window.bind("<Escape>", lambda _: window.destroy())
    window._particle_photos = photos
    return window


class CosmeticControls:
    def _init_cosmetics(self):
        self.has_particles_var = BooleanVar(self.root, False)
        self.costume_var = BooleanVar(self.root, False)
        self.current_particles = []
        self.current_particle_label_var = StringVar(self.root, "")
        self.target_particle_mode_var = StringVar(self.root, "protect")
        self.target_costume_var = BooleanVar(self.root, False)
        self.target_particles = []
        self.target_costume_lineage = ""
        self.target_cosmetic_summary_var = StringVar(self.root, "粒子素材默认保护 · 时装素材默认保护")

    @staticmethod
    def _next_cosmetic_row(form):
        return max((int(widget.grid_info().get("row", 0)) for widget in form.grid_slaves()), default=0) + 1

    def _build_cosmetic_editor(self, form):
        row = ttk.Frame(form)
        row.grid(row=self._next_cosmetic_row(form), column=0, columnspan=6, sticky="ew", pady=3)
        def toggle():
            if not self.has_particles_var.get():
                self.current_particles = []
                self.current_particle_label_var.set("")
        ttk.Checkbutton(row, text="带粒子", variable=self.has_particles_var, command=toggle).pack(side="left")
        ttk.Button(row, text="多粒子 / 选择粒子…", command=self._edit_current_particles).pack(side="left", padx=5)
        ttk.Checkbutton(row, text="时装精灵", variable=self.costume_var).pack(side="left")
        ttk.Label(row, textvariable=self.current_particle_label_var, wraplength=250).pack(side="left", padx=5)

    def _edit_current_particles(self):
        def save(values):
            self.current_particles = values
            self.has_particles_var.set(bool(values))
            self.current_particle_label_var.set(particle_names(values))
        return choose_particles(self.root, self.current_particles, save)

    def _build_cosmetic_planning(self, form):
        row = ttk.Frame(form)
        row.grid(row=self._next_cosmetic_row(form), column=0, columnspan=8, sticky="ew", pady=4)
        ttk.Button(row, text="粒子 / 时装规则…", command=self._edit_cosmetic_planning).pack(side="left")
        ttk.Label(row, textvariable=self.target_cosmetic_summary_var, wraplength=480).pack(side="left", padx=8)

    def _cosmetic_options(self):
        return dict(particle_mode=self.target_particle_mode_var.get(), target_particles=list(self.target_particles),
                    target_costume=self.target_costume_var.get(), costume_lineage=self.target_costume_lineage)

    def _restore_cosmetic_options(self, options):
        if not hasattr(self, "target_particle_mode_var"):
            return
        self.target_particle_mode_var.set(options.get("particle_mode", "protect"))
        self.target_particles = list(options.get("target_particles") or ())
        self.target_costume_var.set(bool(options.get("target_costume")))
        self.target_costume_lineage = str(options.get("costume_lineage") or "")
        self._refresh_cosmetic_summary()

    def _refresh_cosmetic_summary(self):
        text = PARTICLE_MODES.get(self.target_particle_mode_var.get(), "保护粒子素材")
        if self.target_particle_mode_var.get() == "target":
            text += "：" + (particle_names(self.target_particles) or "尚未选择")
        text += " · " + ("时装主线；取消本次 X 位 31 保护" if self.target_costume_var.get() else "时装素材保护")
        self.target_cosmetic_summary_var.set(text)

    def _edit_cosmetic_planning(self):
        window = self._new_child_window()
        window.title("粒子与时装规划")
        frame = ttk.Frame(window, padding=16); frame.pack(fill="both", expand=True)
        for value, name in PARTICLE_MODES.items():
            ttk.Radiobutton(frame, text=name, value=value, variable=self.target_particle_mode_var,
                            command=self._refresh_cosmetic_summary).pack(anchor="w", pady=5)
        def chosen(values):
            self.target_particles = values
            self._refresh_cosmetic_summary()
        ttk.Button(frame, text="多选成品粒子…", command=lambda: choose_particles(window, self.target_particles, chosen)).pack(anchor="w", pady=8)
        ttk.Label(frame, text="指定粒子和同种限一次：双亲实际携带的全部粒子不得重复。", wraplength=430).pack(anchor="w")
        ttk.Checkbutton(frame, text="时装成品：沿时装后代主线孵至目标", variable=self.target_costume_var,
                        command=lambda: (setattr(self, "target_costume_lineage", ""), self._refresh_cosmetic_summary())).pack(anchor="w", pady=12)
        ttk.Label(frame, text="时装公体可使用百变怪转母；本次规划取消 X 位 31 素材保护。", wraplength=430).pack(anchor="w")
        ttk.Button(frame, text="完成", command=window.destroy).pack(anchor="e", pady=(14, 0))
        return window

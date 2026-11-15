"""Independent Windows batch-capture workflow; never sends input to the game."""
from __future__ import annotations

from dataclasses import asdict
import queue
import threading
import uuid
from tkinter import BooleanVar, StringVar, Toplevel, filedialog, messagebox, ttk

from PIL import Image, ImageGrab, ImageOps, ImageTk

from bulk_ocr import BulkResult, BulkRow, recognize_bulk, slot_range, validate_roi
from bulk_session import BulkSessionStore
from capture import capture_window, list_windows
from cosmetic_views import choose_particles
from cosmetics import particle_names
from nature_data import NATURES
from preview_dialog import PreviewZoomWindow
from species_data import get_species_database


class BulkCaptureWorkspace(ttk.Frame):
    def __init__(self, parent, *, directory, accounts, get_processor, inference_lock, on_import):
        super().__init__(parent,padding=8)
        self.store = BulkSessionStore(directory)
        self.get_processor,self.inference_lock,self.on_import = get_processor,inference_lock,on_import
        self.session_id = str(uuid.uuid4())
        self.images = {}
        self.rois = {}
        self.roi_sizes = {}
        self.result = BulkResult()
        self.stale = False
        self.busy = False
        self.request = 0
        self.messages = queue.Queue()
        self.poll_id = None
        self.preview = None
        self.editor = None
        self.photos = {}
        self.windows = []
        self.loading = True
        self.account = StringVar(self,value=accounts[0] if accounts else "主账号")
        self.page = StringVar(self,value="1")
        self.start = StringVar(self,value="1")
        self.count = StringVar(self,value="20")
        self.order_confirmed = BooleanVar(self,value=False)
        self.status = StringVar(self,value="先读取仓库网格，再读取放生确认列表。")
        self.range_text = StringVar(self)
        self.summary = StringVar(self,value="尚未识别；草稿与素材库存分开保存。")
        self.source_text = {kind:StringVar(self,value="未载入") for kind in ("warehouse","release")}
        self._build(accounts)
        try:
            state = self.store.load()
            if state:
                self._restore(state)
        except (OSError,ValueError,KeyError,TypeError) as error:
            self.session_id = str(uuid.uuid4())
            self.images,self.rois = {},{}
            self.result = BulkResult()
            self.stale = False
            self.status.set(f"旧草稿读取失败，原文件保留：{error}")
        self.loading = False
        for variable in (self.account,self.page,self.start,self.count):
            variable.trace_add("write",self._parameters_changed)
        self.order_confirmed.trace_add("write",lambda *_:self._save())
        self._range()
        self._refresh()
        self.poll_id = self.after(100,self._poll)

    def _build(self, accounts):
        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both",expand=True)
        self.input_page = ttk.Frame(self.tabs,padding=8)
        self.review_page = ttk.Frame(self.tabs,padding=8)
        self.tabs.add(self.input_page,text="1 位置与截图")
        self.tabs.add(self.review_page,text="2 核对与入库")
        parameters = ttk.Frame(self.input_page)
        parameters.pack(fill="x")
        for index,(label,variable,width) in enumerate((("账号",self.account,18),("仓库页",self.page,6),("起始格",self.start,6),("数量",self.count,6))):
            column = index%2*2
            row = index//2
            ttk.Label(parameters,text=label).grid(row=row,column=column,sticky="e",padx=4,pady=4)
            entry = ttk.Combobox(parameters,textvariable=variable,values=accounts or ["主账号"],width=width) if index==0 else ttk.Entry(parameters,textvariable=variable,width=width)
            entry.grid(row=row,column=column+1,sticky="ew",padx=4,pady=4)
            parameters.columnconfigure(column+1,weight=1)
        ttk.Label(self.input_page,textvariable=self.range_text).pack(anchor="w",pady=(6,8))
        window_bar = ttk.Frame(self.input_page)
        window_bar.pack(fill="x",pady=(0,8))
        ttk.Button(window_bar,text="刷新窗口",command=self.refresh_windows).pack(side="left")
        self.window_combo = ttk.Combobox(window_bar,state="readonly")
        self.window_combo.pack(side="left",fill="x",expand=True,padx=(6,0))
        sources = ttk.Frame(self.input_page)
        sources.pack(fill="both",expand=True)
        self.source_labels = {}
        for column,(kind,title,hint) in enumerate((("warehouse","仓库网格","框选完整 10 列×6 行网格"),("release","放生确认列表","只框名单，排除左侧详情和背景"))):
            panel = ttk.LabelFrame(sources,text=title,padding=6)
            panel.grid(row=0,column=column,sticky="nsew",padx=(0,4) if column==0 else (4,0))
            sources.columnconfigure(column,weight=1)
            ttk.Label(panel,text=hint,wraplength=270).pack(anchor="w")
            self.source_labels[kind] = ttk.Label(panel,text="载入图片后，点击“框选范围”")
            self.source_labels[kind].pack(fill="both",expand=True,pady=6)
            source_label = ttk.Label(panel,textvariable=self.source_text[kind],wraplength=270)
            source_label.pack(anchor="w")
            buttons = ttk.Frame(panel)
            buttons.pack(fill="x",pady=(6,0))
            for i,(text,command) in enumerate((("截取窗口",lambda k=kind:self.capture(k)),("加载图片",lambda k=kind:self.load_file(k)),
                                                ("剪贴板",lambda k=kind:self.load_clipboard(k)),("框选范围",lambda k=kind:self.select_roi(k)))):
                ttk.Button(buttons,text=text,command=command).grid(row=i//2,column=i%2,sticky="ew",padx=2,pady=2)
                buttons.columnconfigure(i%2,weight=1)
            # Reserve actions before the expandable preview on short screens.
            self.source_labels[kind].pack_forget()
            source_label.pack_forget()
            buttons.pack_forget()
            buttons.pack(side="bottom",fill="x",pady=(6,0))
            source_label.pack(side="bottom",anchor="w")
            self.source_labels[kind].pack(fill="both",expand=True,pady=6)
        sources.rowconfigure(0,weight=1)
        actions = ttk.Frame(self.input_page)
        actions.pack(fill="x",pady=(8,0))
        self.recognize_button = ttk.Button(actions,text="识别这一批",style="Primary.TButton",command=self.recognize)
        self.recognize_button.pack(side="left")
        ttk.Button(actions,text="新批次",command=self.new_batch).pack(side="left",padx=6)
        ttk.Button(actions,text="恢复上批",command=self.restore_previous).pack(side="left")
        sources.pack_forget();actions.pack_forget()
        actions.pack(side="bottom",fill="x",pady=(8,0))
        sources.pack(fill="both",expand=True)
        self.summary_label = ttk.Label(self.review_page,textvariable=self.summary,wraplength=900)
        self.summary_label.pack(anchor="w",fill="x",pady=(0,6))
        review_controls = ttk.Frame(self.review_page)
        review_controls.pack(side="bottom",fill="x")
        table = ttk.Frame(self.review_page)
        table.pack(fill="both",expand=True)
        columns = ("position","species","gender","ivs","ha","nature","extra","status")
        self.tree = ttk.Treeview(table,columns=columns,show="headings",selectmode="extended",height=10)
        for name,title,width in zip(columns,("仓位","名字","性别","六项 IV","梦特","性格","头目 / 粒子 / 时装","核对状态"),(80,95,42,155,65,70,165,110)):
            self.tree.heading(name,text=title)
            self.tree.column(name,width=width,minwidth=40,stretch=name in {"species","extra"})
        ybar = ttk.Scrollbar(table,orient="vertical",command=self.tree.yview)
        xbar = ttk.Scrollbar(table,orient="horizontal",command=self.tree.xview)
        self.tree.configure(yscrollcommand=ybar.set,xscrollcommand=xbar.set)
        self.tree.grid(row=0,column=0,sticky="nsew")
        ybar.grid(row=0,column=1,sticky="ns")
        xbar.grid(row=1,column=0,sticky="ew")
        table.rowconfigure(0,weight=1);table.columnconfigure(0,weight=1)
        self.tree.bind("<Double-Button-1>",lambda _event:self.edit_selected())
        self.tree.bind("<Control-a>",self.select_all)
        edit = ttk.Frame(review_controls)
        edit.pack(fill="x",pady=(6,0))
        ttk.Button(edit,text="全选",command=self.select_all).pack(side="left")
        ttk.Button(edit,text="逐项核对…",command=self.edit_selected).pack(side="left",padx=5)
        ttk.Button(edit,text="确认所选资料",command=self.confirm_selected).pack(side="left")
        bulk = ttk.Frame(review_controls)
        bulk.pack(fill="x",pady=(6,0))
        ttk.Label(bulk,text="将所选标为：").grid(row=0,column=0,padx=(0,4))
        for i,(label,field) in enumerate((("普通", "is_alpha"),("无粒子","has_particles"),("非时装","is_costume"))):
            ttk.Button(bulk,text=label,command=lambda f=field:self.apply_to_selected(f,False)).grid(row=0,column=i+1,padx=2)
        ttk.Button(bulk,text="性格不登记",command=lambda:self.apply_to_selected("nature","")).grid(row=1,column=1,columnspan=2,sticky="w",pady=4)
        ttk.Checkbutton(review_controls,text="已核对：列表按仓库从左到右、从上到下对应，包含重复名字的精灵",variable=self.order_confirmed).pack(anchor="w",pady=(6,0))
        self.import_button = ttk.Button(review_controls,text="导入所选已核对项",style="Primary.TButton",command=self.import_selected)
        self.import_button.pack(anchor="e",pady=(6,0))
        ttk.Label(self,textvariable=self.status,wraplength=900).pack(fill="x",pady=(6,0))
        self.bind("<Configure>",lambda event:self._wrap(event.width) if event.widget is self else None)

    def _wrap(self, width):
        self.summary_label.configure(wraplength=max(300,width-40))
        for widget in self.winfo_children():
            if widget.winfo_class()=="TLabel":
                widget.configure(wraplength=max(300,width-24))

    def _range(self):
        try:
            slots = slot_range(int(self.page.get()),int(self.start.get()),int(self.count.get()))
            self.range_text.set(f"第 {self.page.get()} 页，第 {slots[0]}～{slots[-1]} 格，共 {len(slots)} 只；跨页请拆批。")
        except (ValueError,TypeError) as error:
            self.range_text.set(str(error))

    def _parameters_changed(self, *_args):
        if self.loading:
            return
        self.stale = bool(self.result.rows)
        self.order_confirmed.set(False)
        self.request += 1
        self._range();self._refresh();self._save()

    def _state(self):
        return {"schema_version":1,"session_id":self.session_id,
                "parameters":{"account":self.account.get(),"page":self.page.get(),"start":self.start.get(),"count":self.count.get()},
                "rois":self.rois,"roi_sizes":self.roi_sizes,"image_sizes":{kind:list(image.size) for kind,image in self.images.items()},
                "result":self.result.to_dict(),"stale":self.stale,"order_confirmed":self.order_confirmed.get()}

    def _save(self):
        if self.loading:
            return
        try:
            self.store.save(self._state())
        except (OSError,ValueError) as error:
            self.status.set(f"草稿尚未保存：{error}")

    def _restore(self,state):
        self.loading = True
        self.session_id = state["session_id"]
        for name,variable in (("account",self.account),("page",self.page),("start",self.start),("count",self.count)):
            variable.set(str(state["parameters"][name]))
        self.rois = dict(state.get("rois",{}))
        self.roi_sizes = dict(state.get("roi_sizes",state.get("image_sizes",{})))
        self.result = BulkResult.from_dict(state.get("result",{}))
        self.stale = bool(state.get("stale"))
        self.order_confirmed.set(bool(state.get("order_confirmed")))
        self.images = {}
        missing_images = False
        for kind,size in state.get("image_sizes",{}).items():
            path = self.store.image_path(self.session_id,kind)
            if path.exists():
                try:
                    with Image.open(path) as image:
                        self.images[kind] = image.convert("RGB")
                except (OSError,ValueError):
                    missing_images = True
                    self.stale = bool(self.result.rows)
            else:
                missing_images = True
                self.stale = bool(self.result.rows)
        self.loading = False
        for kind in self.source_text:
            self._thumbnail(kind)
        self.status.set("草稿图片缺失或损坏，请重新载入并识别；原资料保留。" if missing_images else "已恢复本机批量草稿；未确认项尚未进入素材库存。")

    def pause(self):
        self.request += 1
        if self.preview is not None:
            self.preview.close();self.preview=None
        if self.editor is not None and self.editor.winfo_exists():
            self.editor.destroy();self.editor=None
        self._save()

    def shutdown(self):
        self.pause()
        if self.poll_id is not None:
            self.after_cancel(self.poll_id);self.poll_id=None

    def refresh_windows(self):
        self.windows = [window for window in list_windows() if "孵蛋助手" not in window.title and "breeder-helper" not in window.title.lower()]
        self.window_combo.configure(values=[window.label() for window in self.windows])
        if self.windows:
            self.window_combo.current(next((i for i,w in enumerate(self.windows) if "pokemmo" in w.title.lower()),0))

    def set_source(self, kind, image):
        if self.busy:
            self.status.set("正在识别，请完成后再更换截图。")
            return
        image = image.convert("RGB").copy()
        self.store.save_image(self.session_id,kind,image)
        if self.roi_sizes.get(kind) != list(image.size):
            self.rois.pop(kind,None)
        self.roi_sizes[kind] = list(image.size)
        self.images[kind] = image
        self.stale = bool(self.result.rows)
        self.order_confirmed.set(False)
        self._thumbnail(kind);self._refresh();self._save()

    def _thumbnail(self, kind):
        label = self.source_labels[kind]
        image = self.images.get(kind)
        if image is None:
            label.configure(image="",text="载入图片后，点击“框选范围”")
            self.photos.pop(kind,None)
            self.source_text[kind].set("未载入")
            return
        display = image.crop(self.rois[kind]) if self.rois.get(kind) else image
        self.photos[kind] = ImageTk.PhotoImage(ImageOps.contain(display,(270,160)),master=self)
        label.configure(image=self.photos[kind],text="")
        self.source_text[kind].set(f"{image.width}×{image.height} · "+("范围已设置" if self.rois.get(kind) else "请框选范围"))

    def load_file(self, kind):
        if self.busy:
            return
        path = filedialog.askopenfilename(parent=self,filetypes=[("图片","*.png *.jpg *.jpeg *.bmp *.webp")])
        if path:
            try:
                with Image.open(path) as image:
                    self.set_source(kind,image)
                self.select_roi(kind)
            except (OSError,ValueError) as error:
                messagebox.showerror("读取图片失败",str(error),parent=self)

    def load_clipboard(self, kind):
        if self.busy:
            return
        try:
            image = ImageGrab.grabclipboard()
            if not isinstance(image,Image.Image):
                raise ValueError("剪贴板中没有图片。")
            self.set_source(kind,image)
            self.select_roi(kind)
        except (OSError,ValueError) as error:
            messagebox.showwarning("无法读取剪贴板",str(error),parent=self)

    def capture(self, kind):
        if self.busy:
            return
        index = self.window_combo.current()
        if not 0 <= index < len(self.windows):
            self.refresh_windows()
            index = self.window_combo.current()
        if not 0 <= index < len(self.windows):
            messagebox.showwarning("没有选择窗口","请刷新并选择 PokeMMO 窗口。",parent=self)
            return
        target = self.windows[index]
        root = self.winfo_toplevel()
        root.withdraw()
        def finish():
            image,error = None,None
            try:
                image = capture_window(target)
            except Exception as exception:
                error = exception
            finally:
                root.deiconify()
            if error:
                messagebox.showerror("截取失败",str(error),parent=self)
            else:
                try:
                    self.set_source(kind,image)
                    self.select_roi(kind)
                except (OSError,ValueError) as exception:
                    messagebox.showerror("截图保存失败",str(exception),parent=self)
        self.after(180,finish)

    def select_roi(self, kind):
        if self.busy:
            return
        image = self.images.get(kind)
        if image is None:
            self.status.set("请先载入图片。")
            return
        if self.preview is not None:
            self.preview.close()
        def apply(bounds):
            try:
                if bounds is None:
                    raise ValueError("请框选完整的识别区域。")
                self.rois[kind] = validate_roi(image,bounds)
                self.stale = bool(self.result.rows)
                self.order_confirmed.set(False)
                self._thumbnail(kind);self._refresh();self._save()
            except ValueError as error:
                self.status.set(str(error))
        self.preview = PreviewZoomWindow(self.winfo_toplevel(),image,self.rois.get(kind),apply)
        self.preview.window.title("框选仓库完整网格（10列×6行）" if kind=="warehouse" else "框选放生确认名单（排除背景）")

    def recognize(self):
        if self.busy:
            return
        try:
            page,start,count = int(self.page.get()),int(self.start.get()),int(self.count.get())
            slot_range(page,start,count)
            cropped = {}
            for kind in ("warehouse","release"):
                if kind not in self.images or not self.rois.get(kind):
                    raise ValueError("请先载入两张图片，并分别框选仓库网格与确认名单。")
                cropped[kind] = self.images[kind].crop(validate_roi(self.images[kind],self.rois[kind]))
            ratio = cropped["warehouse"].width/cropped["warehouse"].height
            if not 1.6 <= ratio <= 2.4:
                raise ValueError("仓库范围比例不符，请只框选完整 10 列×6 行网格，排除左侧详情。")
            self.status.set("正在准备本地识别……")
            self.update_idletasks()
            processor = self.get_processor()
        except Exception as error:
            messagebox.showwarning("尚不能识别",str(error),parent=self)
            return
        self.request += 1
        request = self.request
        self.busy = True
        self._refresh()
        self.status.set("正在读取这一批的名字、个体值、梦特、性别和等级……")
        def work():
            try:
                with self.inference_lock:
                    result = recognize_bulk(cropped["warehouse"],cropped["release"],page,start,count,processor)
                self.messages.put((request,result,None))
            except Exception as error:
                self.messages.put((request,None,str(error)))
        threading.Thread(target=work,daemon=True).start()

    def _poll(self):
        self.poll_id = None
        try:
            while True:
                request,result,error = self.messages.get_nowait()
                self.busy = False
                if request != self.request:
                    self.status.set("上次识别已暂停，保留原草稿。")
                elif error:
                    self.status.set("识别失败："+error)
                else:
                    self.result = result
                    self.stale = False
                    self.order_confirmed.set(False)
                    self.tabs.select(self.review_page)
                    self._refresh(select=True)
                    self._save()
                    self.status.set("请先处理数量与格位问题。" if result.blockers else f"已读取 {len(result.rows)} 只，请核对后导入。")
                self._refresh()
        except queue.Empty:
            pass
        self.poll_id = self.after(100,self._poll)

    def _refresh(self, *, select=False):
        selected = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        for row in self.result.rows:
            position = "待对应" if row.slot is None else f"{self.page.get()}-{(row.slot-1)//10+1},{(row.slot-1)%10+1}"
            extra = " / ".join("待核对" if value is None else yes if value else no for value,yes,no in
                               ((row.is_alpha,"头目","普通"),(row.has_particles,"有粒子","无粒子"),(row.is_costume,"时装","非时装")))
            status = "已导入" if row.imported else "已核对" if not row.problems() else "待核对"
            self.tree.insert("","end",iid=str(row.index),values=(position,row.species or "待补全",{"M":"公","F":"母","N":"无"}.get(row.gender,"待核对"),
                             "/".join("x" if value is None else str(value) for value in row.ivs),
                             "待核对" if row.hidden_ability is None else "有蓝钻" if row.hidden_ability else "未见蓝钻",
                             "待核对" if row.nature is None else row.nature or "未登记",extra,status))
        keep = self.tree.get_children() if select else [item for item in selected if self.tree.exists(item)]
        if keep:
            self.tree.selection_set(keep)
        ready = sum(not row.problems() and not row.imported for row in self.result.rows)
        self.summary.set("参数或截图已更改，请重新识别；原核对结果暂保留。" if self.stale else
                         "；".join(self.result.blockers) if self.result.blockers else
                         f"共 {len(self.result.rows)} 只 · 可导入 {ready} 只 · 双击逐项核对；未知项目保留待核对。")
        self.recognize_button.configure(state="disabled" if self.busy else "normal")
        self.import_button.configure(state="disabled" if self.busy or self.stale or self.result.blockers else "normal")

    def select_all(self, _event=None):
        self.tree.selection_set(self.tree.get_children())
        return "break"

    def _selected(self):
        indices = {int(value) for value in self.tree.selection()}
        return [row for row in self.result.rows if row.index in indices and not row.imported]

    def apply_to_selected(self, field, value):
        if self.busy or self.stale:
            return
        rows = self._selected()
        for row in rows:
            setattr(row,field,value)
            if field=="has_particles" and not value:
                row.particles = []
            row.reviewed = False
        self._refresh();self._save()
        self.status.set(f"已将所选 {len(rows)} 项更新；请核对完整资料后确认。")

    def confirm_selected(self):
        if self.stale or self.result.blockers or self.busy:
            self.status.set("请先排除数量、格位问题并重新识别。")
            return
        rows = self._selected()
        problems = [f"第 {row.index} 条：{'、'.join(row.problems(require_review=False))}" for row in rows if row.problems(require_review=False)]
        if problems:
            messagebox.showwarning("资料尚未完整","\n".join(problems[:5]),parent=self)
            return
        for row in rows:
            row.reviewed = True
        self._refresh();self._save()

    def import_selected(self):
        if self.stale or self.busy:
            return
        rows = self._selected()
        try:
            added = self.on_import(self.result,self.session_id,self.account.get().strip(),int(self.page.get()),
                                   [row.index for row in rows],self.order_confirmed.get())
        except Exception as error:
            messagebox.showwarning("尚不能入库",str(error),parent=self)
            return
        for row in rows:
            row.imported = True
        self._refresh();self._save()
        self.status.set(f"已导入所选 {len(rows)} 项，本次新增 {added} 只；原仓位记录未被覆盖。")

    def new_batch(self):
        if self.busy:
            return
        self._save()
        self.loading = True
        self.session_id = str(uuid.uuid4())
        self.images = {}
        self.result = BulkResult()
        self.stale = False
        self.order_confirmed.set(False)
        self.loading = False
        for kind in self.source_text:
            self._thumbnail(kind)
        self._refresh();self._save()
        self.tabs.select(self.input_page)
        self.status.set("新批次已开始，上批草稿保留，可点击“恢复上批”找回。")

    def restore_previous(self):
        if self.busy:
            return
        try:
            state = self.store.previous(self.session_id)
            if state is None:
                self.status.set("没有可恢复的上一批。")
                return
            self._save()
            self._restore(state)
            self._range();self._refresh();self._save()
        except (OSError,ValueError,KeyError,TypeError) as error:
            messagebox.showerror("恢复失败",str(error),parent=self)

    def edit_selected(self):
        if self.busy or self.stale:
            self.status.set("请先完成本批识别。")
            return
        rows = self._selected()
        if rows:
            self._edit_row(rows[0],rows[1:])
        else:
            self.status.set("请先选择要核对的条目。")

    def _edit_row(self, row, following):
        if self.editor is not None and self.editor.winfo_exists():
            self.editor.lift()
            return
        from autocomplete import AutocompletePopup
        window = Toplevel(self)
        self.editor = window
        window.title(f"核对第 {row.index} 只 · 第 {self.page.get()} 页第 {row.slot or '?'} 格")
        window.geometry(f"640x{min(610,max(460,window.winfo_screenheight()-100))}")
        window.minsize(580,460)
        window.transient(self.winfo_toplevel())
        window.grab_set()
        body = ttk.Frame(window,padding=10)
        body.pack(fill="both",expand=True)
        evidence = ttk.Frame(body)
        evidence.pack(fill="x",pady=(0,8))
        photos = []
        for column,kind in enumerate(("warehouse","release")):
            image = self.images.get(kind)
            if image is None or not self.rois.get(kind):
                continue
            cropped = image.crop(self.rois[kind])
            if kind=="release" and row.source_box:
                cropped = cropped.crop(row.source_box)
            elif kind=="warehouse" and row.slot:
                y,x = divmod(row.slot-1,10)
                w,h = cropped.width/10,cropped.height/6
                cropped = cropped.crop((round(x*w),round(y*h),round((x+1)*w),round((y+1)*h)))
            else:
                continue
            photo = ImageTk.PhotoImage(ImageOps.contain(cropped,(280,70)),master=window)
            photos.append(photo)
            ttk.Label(evidence,image=photo).grid(row=0,column=column,padx=8)
        window.evidence_photos = photos
        form = ttk.Frame(body)
        form.pack(fill="x")
        species = StringVar(window,value=row.species)
        gender = StringVar(window,value={"M":"公","F":"母","N":"无性别"}.get(row.gender,"待核对"))
        ivs = StringVar(window,value="/".join("x" if value is None else str(value) for value in row.ivs))
        level = StringVar(window,value=str(row.level or ""))
        ha = StringVar(window,value="待核对" if row.hidden_ability is None else "有蓝钻" if row.hidden_ability else "未见蓝钻")
        nature = StringVar(window,value="待核对" if row.nature is None else row.nature or "未登记（仅作IV素材）")
        alpha = StringVar(window,value="待核对" if row.is_alpha is None else "头目" if row.is_alpha else "普通")
        costume = StringVar(window,value="待核对" if row.is_costume is None else "时装" if row.is_costume else "非时装")
        particle = StringVar(window,value="待核对" if row.has_particles is None else "有粒子" if row.has_particles else "无粒子")
        position = BooleanVar(window,value=row.position_reviewed)
        selected_particles = list(row.particles)
        particle_text = StringVar(window,value=particle_names(selected_particles))
        definitions = (("名字",species,row.candidates,False),("性别",gender,("待核对","公","母","无性别"),True),
                       ("六项个体值",ivs,None,False),("等级",level,None,False),
                       ("梦特",ha,("待核对","有蓝钻","未见蓝钻"),True),
                       ("性格",nature,("待核对","未登记（仅作IV素材）",*[item.chinese for item in NATURES]),True),
                       ("类别",alpha,("待核对","普通","头目"),True),("外观",costume,("待核对","非时装","时装"),True),
                       ("粒子",particle,("待核对","无粒子","有粒子"),True))
        species_entry = None
        for i,(label,variable,values,readonly) in enumerate(definitions):
            r,c = i//2,i%2*2
            ttk.Label(form,text=label).grid(row=r,column=c,sticky="e",padx=4,pady=5)
            if values is None:
                entry = ttk.Entry(form,textvariable=variable,width=23)
            else:
                entry = ttk.Combobox(form,textvariable=variable,values=values,state="readonly" if readonly else "normal",width=23)
            entry.grid(row=r,column=c+1,sticky="ew",padx=4,pady=5)
            form.columnconfigure(c+1,weight=1)
            if i==0:
                species_entry = entry
        database = get_species_database()
        window.species_autocomplete = AutocompletePopup(window,species_entry,lambda query:[item.display_name for item in database.search(query,limit=20)])
        def pick_particles():
            def chosen(values):
                selected_particles[:] = values
                particle.set("有粒子" if values else "无粒子")
                particle_text.set(particle_names(values))
            choose_particles(window,selected_particles,chosen)
        ttk.Button(form,text="选择粒子…",command=pick_particles).grid(row=4,column=2,columnspan=2,sticky="w",padx=4)
        ttk.Label(body,textvariable=particle_text,wraplength=590).pack(anchor="w",pady=4)
        ttk.Checkbutton(body,text="已人工核对当前仓位与等级（仓库等级缺失或不符时需勾选）",variable=position).pack(anchor="w",pady=5)
        ttk.Label(body,text=f"原名字：{row.raw_name or '未读出'}\n仓库等级：{row.warehouse_level or '未读出'}；未显示的项目保持待核对。",wraplength=590).pack(anchor="w",pady=5)
        footer = ttk.Frame(body)
        footer.pack(side="bottom",fill="x",pady=(8,0))
        def close():
            window.destroy()
            self.editor = None
        def save(complete=False):
            parts = ivs.get().replace("／","/").split("/")
            try:
                parsed_ivs = [None if part.strip().lower() in {"","x","?"} else int(part.strip()) for part in parts]
                parsed_level = int(level.get()) if level.get().strip() else None
                if len(parsed_ivs)!=6 or any(value is not None and not 0<=value<=31 for value in parsed_ivs):
                    raise ValueError
                if parsed_level is not None and not 1<=parsed_level<=100:
                    raise ValueError
            except ValueError:
                messagebox.showwarning("格式不正确","请填写六项 0～31 的个体值（未知用 x）和 1～100 的等级。",parent=window)
                return
            record = database.get(species.get().strip())
            row.species = record.display_name if record else species.get().strip()
            row.gender = {"公":"M","母":"F","无性别":"N"}.get(gender.get(),"")
            row.ivs,row.level = parsed_ivs,parsed_level
            row.hidden_ability = None if ha.get()=="待核对" else ha.get()=="有蓝钻"
            row.nature = None if nature.get()=="待核对" else "" if nature.get().startswith("未登记") else nature.get()
            row.is_alpha = None if alpha.get()=="待核对" else alpha.get()=="头目"
            row.is_costume = None if costume.get()=="待核对" else costume.get()=="时装"
            row.has_particles = None if particle.get()=="待核对" else particle.get()=="有粒子"
            row.particles = list(selected_particles) if row.has_particles else []
            row.position_reviewed = position.get()
            row.reviewed = False
            problems = row.problems(require_review=False)
            if complete and not problems:
                row.reviewed = True
            self._refresh();self._save()
            if complete and problems:
                messagebox.showwarning("还需核对","、".join(problems),parent=window)
                return
            close()
            if complete and following:
                self.tree.selection_set(str(following[0].index))
                self.tree.see(str(following[0].index))
                self._edit_row(following[0],following[1:])
        ttk.Button(footer,text="取消",command=close).pack(side="right")
        ttk.Button(footer,text="保存草稿",command=save).pack(side="right",padx=6)
        ttk.Button(footer,text="核对完成 / 下一只",style="Primary.TButton",command=lambda:save(True)).pack(side="right")
        window.protocol("WM_DELETE_WINDOW",close)
        window.bind("<Escape>",lambda _event:close())

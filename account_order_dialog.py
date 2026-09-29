"""A local draft of account ordering; Save is the only commit action."""
from __future__ import annotations

from collections.abc import Callable
import tkinter as tk
from tkinter import font, ttk


class AccountOrderDialog:
    def __init__(self, window: tk.Toplevel, accounts: list[str], on_save: Callable[[list[str]], bool],
                 on_save_deletions: Callable[[list[str], list[str]], bool] | None = None) -> None:
        self.window = window
        self.on_save = on_save
        self.on_save_deletions = on_save_deletions
        self.removed_accounts: list[str] = []
        self.dragged: str | None = None
        self.drag_y = 0
        self.scroll_timer = None
        window.title("账号排序")
        window.geometry("460x440")
        window.minsize(400, 330)
        window.transient(window.master)
        window.protocol("WM_DELETE_WINDOW", self.cancel)
        window.bind("<Escape>", lambda _event: self.cancel())
        window.bind("<Return>", lambda _event: self.save())

        body = ttk.Frame(window, padding=16)
        body.pack(fill="both", expand=True)
        instruction = ttk.Label(
            body, text="拖动或上移 / 下移调整顺序。\n删除账号及其素材在保存时确认，取消不生效。",
            justify="left", wraplength=410,
        )
        instruction.pack(fill="x", pady=(0, 12))
        body.bind("<Configure>", lambda event: instruction.configure(wraplength=max(220, event.width - 32)))
        frame = ttk.Frame(body)
        frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(frame, show="tree", selectmode="browse", height=9)
        name_font = font.nametofont("TkDefaultFont")
        width = max([320, *(name_font.measure(name) + 48 for name in accounts)])
        self.tree.column("#0", width=width, minwidth=320, stretch=True)
        vertical = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        horizontal = ttk.Scrollbar(frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        for index, name in enumerate(accounts):
            self.tree.insert("", "end", iid=str(index), text=name)
        self.tree.bind("<ButtonPress-1>", self._press)
        self.tree.bind("<B1-Motion>", self._drag)
        self.tree.bind("<ButtonRelease-1>", self._release)
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self._update_controls())
        self.tree.bind("<Alt-Up>", lambda _event: self.move_selected(-1))
        self.tree.bind("<Alt-Down>", lambda _event: self.move_selected(1))

        movement = ttk.Frame(body)
        movement.pack(fill="x", pady=(10, 12))
        self.up_button = ttk.Button(movement, text="上移", command=lambda: self.move_selected(-1))
        self.up_button.pack(side="left", padx=(0, 6))
        self.down_button = ttk.Button(movement, text="下移", command=lambda: self.move_selected(1))
        self.down_button.pack(side="left")
        self.delete_button = ttk.Button(movement, text="删除账号", style="Danger.TButton", command=self.delete_selected)
        if on_save_deletions is not None:
            self.delete_button.pack(side="left", padx=(8, 0))
        self.position = ttk.Label(movement)
        self.position.pack(side="right")
        footer = ttk.Frame(body)
        footer.pack(fill="x")
        self.deletion_note = ttk.Label(body, text="", style="Muted.TLabel")
        self.deletion_note.pack(fill="x", pady=(8, 0))
        self.save_button = ttk.Button(footer, text="保存并重新排列", style="Primary.TButton", command=self.save)
        self.save_button.pack(side="right")
        self.cancel_button = ttk.Button(footer, text="取消", command=self.cancel)
        self.cancel_button.pack(side="right", padx=(0, 8))
        if accounts:
            self.tree.selection_set("0")
            self.tree.focus("0")
        self._update_controls()
        window.grab_set()
        self.tree.focus_set()

    def ordered_accounts(self) -> list[str]:
        return [self.tree.item(item, "text") for item in self.tree.get_children()]

    def _update_controls(self) -> None:
        selection = self.tree.selection()
        index = self.tree.index(selection[0]) if selection else -1
        count = len(self.tree.get_children())
        self.up_button.configure(state="normal" if index > 0 else "disabled")
        self.down_button.configure(state="normal" if 0 <= index < count - 1 else "disabled")
        self.delete_button.configure(state="normal" if selection else "disabled")
        self.position.configure(text=f"第 {index + 1} / {count} 位" if selection else f"共 {count} 个账号")

    def move_selected(self, direction: int) -> str:
        selection = self.tree.selection()
        if selection:
            item = selection[0]
            index = max(0, min(len(self.tree.get_children()) - 1, self.tree.index(item) + direction))
            self.tree.move(item, "", index)
            self.tree.see(item)
            self._update_controls()
        return "break"

    def delete_selected(self) -> None:
        selected = self.tree.selection()
        if not selected or self.on_save_deletions is None:
            return
        self._release()
        item = selected[0]
        index = self.tree.index(item)
        self.removed_accounts.append(self.tree.item(item, "text"))
        self.tree.delete(item)
        remaining = self.tree.get_children()
        if remaining:
            item = remaining[min(index, len(remaining) - 1)]
            self.tree.selection_set(item)
            self.tree.focus(item)
        self.deletion_note.configure(text=f"待删除 {len(self.removed_accounts)} 个账号及其素材；保存后生效。")
        self._update_controls()

    def _press(self, event) -> str:
        item = self.tree.identify_row(event.y)
        if item:
            self.dragged = item
            self.drag_y = event.y
            self.tree.selection_set(item)
            self.tree.focus(item)
            self.tree.focus_set()
            self.tree.configure(cursor="fleur")
        return "break"

    def _move_dragged(self) -> None:
        height = self.tree.winfo_height()
        target = self.tree.identify_row(max(2, min(height - 3, self.drag_y)))
        if not self.dragged or not target or target == self.dragged:
            return
        bbox = self.tree.bbox(target)
        if not bbox:
            return
        destination = self.tree.index(target) + (self.drag_y >= bbox[1] + bbox[3] / 2)
        if self.tree.index(self.dragged) < destination:
            destination -= 1
        self.tree.move(self.dragged, "", destination)
        self._update_controls()

    def _drag(self, event) -> str:
        if self.dragged:
            self.drag_y = event.y
            self._move_dragged()
            if self.scroll_timer is None:
                self.scroll_timer = self.window.after(100, self._scroll_drag)
        return "break"

    def _scroll_drag(self) -> None:
        self.scroll_timer = None
        if not self.dragged:
            return
        height = self.tree.winfo_height()
        direction = -1 if self.drag_y < 18 else 1 if self.drag_y > height - 18 else 0
        if direction:
            self.tree.yview_scroll(direction, "units")
            self._move_dragged()
        self.scroll_timer = self.window.after(100, self._scroll_drag)

    def _release(self, _event=None) -> str:
        self.dragged = None
        if self.scroll_timer is not None:
            self.window.after_cancel(self.scroll_timer)
            self.scroll_timer = None
        self.tree.configure(cursor="")
        return "break"

    def save(self) -> None:
        self._release()
        saved = (self.on_save_deletions(self.ordered_accounts(), self.removed_accounts)
                 if self.removed_accounts and self.on_save_deletions else self.on_save(self.ordered_accounts()))
        if saved:
            self.window.destroy()

    def cancel(self) -> None:
        self._release()
        self.window.destroy()

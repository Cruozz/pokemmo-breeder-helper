from __future__ import annotations

from collections.abc import Callable, Iterable
from tkinter import END, Listbox, Toplevel


class AutocompletePopup:
    """Small keyboard-accessible suggestion list anchored to a Tk entry.

    The popup never owns application data.  It only replaces the current entry
    value (or the final comma-separated token) after an explicit click/Enter.
    """

    def __init__(
        self,
        root,
        entry,
        provider: Callable[[str], Iterable[str]],
        *,
        token_mode: bool = False,
        on_selected: Callable[[str], None] | None = None,
        limit: int = 30,
    ) -> None:
        self.root = root
        self.entry = entry
        self.provider = provider
        self.token_mode = token_mode
        self.on_selected = on_selected
        self.limit = limit
        self.values: list[str] = []

        self.window = Toplevel(root)
        self.window.withdraw()
        self.window.overrideredirect(True)
        try:
            self.window.attributes("-topmost", True)
        except Exception:
            pass
        self.listbox = Listbox(
            self.window,
            height=7,
            exportselection=False,
            activestyle="dotbox",
            borderwidth=1,
            relief="solid",
        )
        self.listbox.pack(fill="both", expand=True)
        self.listbox.bind("<ButtonRelease-1>", self._accept_event)
        self.listbox.bind("<Double-Button-1>", self._accept_event)
        self.listbox.bind("<Return>", self._accept_event)
        self.listbox.bind("<Escape>", self._hide_event)

        entry.bind("<KeyRelease>", self._on_key_release, add="+")
        entry.bind("<Down>", self._focus_list, add="+")
        entry.bind("<Escape>", self._hide_event, add="+")
        entry.bind("<FocusOut>", self._defer_hide, add="+")

    @property
    def visible(self) -> bool:
        return bool(self.window.winfo_viewable())

    def destroy(self) -> None:
        try:
            self.window.destroy()
        except Exception:
            pass

    def _current_query(self) -> str:
        value = self.entry.get()
        if not self.token_mode:
            return value.strip()
        normalized = value.replace("，", ",")
        return normalized.rsplit(",", 1)[-1].strip()

    def _on_key_release(self, event=None) -> None:
        if event is not None and event.keysym in {
            "Up", "Down", "Left", "Right", "Return", "Escape", "Tab",
        }:
            return
        query = self._current_query()
        if not query:
            self.hide()
            return
        self.values = list(dict.fromkeys(str(value) for value in self.provider(query) if str(value).strip()))[: self.limit]
        if not self.values:
            self.hide()
            return
        self.listbox.delete(0, END)
        for value in self.values:
            self.listbox.insert(END, value)
        self.listbox.selection_set(0)
        self._show()

    def _show(self) -> None:
        self.entry.update_idletasks()
        x = self.entry.winfo_rootx()
        y = self.entry.winfo_rooty() + self.entry.winfo_height()
        width = max(self.entry.winfo_width(), 220)
        row_height = 24
        height = min(7, len(self.values)) * row_height + 4
        screen_width = max(width, self.window.winfo_screenwidth())
        screen_height = max(height, self.window.winfo_screenheight())
        x = max(0, min(x, screen_width - width))
        if y + height > screen_height:
            y = max(0, self.entry.winfo_rooty() - height)
        self.window.geometry(f"{width}x{height}+{x}+{y}")
        self.window.deiconify()
        self.window.lift()

    def hide(self) -> None:
        self.window.withdraw()

    def _hide_event(self, _event=None) -> str:
        self.hide()
        return "break"

    def _defer_hide(self, _event=None) -> None:
        self.root.after(120, self._hide_unless_focused)

    def _hide_unless_focused(self) -> None:
        focus = self.root.focus_get()
        if focus not in {self.entry, self.listbox}:
            self.hide()

    def _focus_list(self, _event=None) -> str | None:
        if not self.visible:
            self._on_key_release()
        if not self.visible:
            return None
        self.listbox.focus_set()
        self.listbox.selection_clear(0, END)
        self.listbox.selection_set(0)
        self.listbox.activate(0)
        return "break"

    def _accept_event(self, _event=None) -> str:
        selection = self.listbox.curselection()
        if not selection:
            return "break"
        value = str(self.listbox.get(selection[0]))
        current = self.entry.get()
        if self.token_mode:
            normalized = current.replace("，", ",")
            prefix = normalized.rsplit(",", 1)[0].strip() if "," in normalized else ""
            replacement = f"{prefix}, {value}" if prefix else value
        else:
            replacement = value
        self.entry.delete(0, END)
        self.entry.insert(0, replacement)
        self.entry.icursor(END)
        self.hide()
        self.entry.focus_set()
        if self.on_selected is not None:
            self.on_selected(value)
        return "break"

"""Dialog for creating and editing categories (config/categories.json)."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from ..config import DEFAULT_CATEGORIES, save_categories


class CategoryEditor(tk.Toplevel):
    """Modal editor. ``result`` holds the saved categories, or None on cancel."""

    def __init__(self, master: tk.Misc, categories: dict[str, list[str]]) -> None:
        super().__init__(master)
        self.title("Edit categories")
        self.geometry("720x460")
        self.minsize(600, 380)
        self.transient(master)
        self.result: dict[str, list[str]] | None = None

        self._categories = {name: list(phrases) for name, phrases in categories.items()}
        self._current: str | None = None

        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        # --- left: category list
        left = ttk.Frame(self, padding=(10, 10, 4, 10))
        left.grid(row=0, column=0, sticky="nsw")
        left.rowconfigure(0, weight=1)

        self.listbox = tk.Listbox(left, width=24, exportselection=False, activestyle="none")
        self.listbox.grid(row=0, column=0, columnspan=2, sticky="ns")
        self.listbox.bind("<<ListboxSelect>>", self._on_select)

        ttk.Button(left, text="New", command=self._add).grid(
            row=1, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(left, text="Delete", command=self._delete).grid(
            row=1, column=1, sticky="ew", pady=(8, 0), padx=(4, 0))
        ttk.Button(left, text="Rename", command=self._rename).grid(
            row=2, column=0, columnspan=2, sticky="ew", pady=(4, 0))

        # --- right: phrases of the selected category
        right = ttk.Frame(self, padding=(4, 10, 10, 10))
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        ttk.Label(
            right,
            text="Search terms - one per line. More terms give more different "
                 "results. {year} and {last_year} are replaced with the current "
                 "and the previous year.",
            wraplength=430,
            justify="left",
        ).grid(row=0, column=0, sticky="w", pady=(0, 6))

        text_frame = ttk.Frame(right)
        text_frame.grid(row=1, column=0, sticky="nsew")
        text_frame.columnconfigure(0, weight=1)
        text_frame.rowconfigure(0, weight=1)

        self.text = tk.Text(text_frame, wrap="none", undo=True, height=10)
        self.text.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(text_frame, orient="vertical", command=self.text.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.text.configure(yscrollcommand=scroll.set)

        # --- bottom buttons
        bottom = ttk.Frame(self, padding=(10, 0, 10, 10))
        bottom.grid(row=1, column=0, columnspan=2, sticky="ew")
        ttk.Button(bottom, text="Add default categories",
                   command=self._restore_defaults).pack(side="left")
        ttk.Button(bottom, text="Cancel", command=self._cancel).pack(side="right")
        ttk.Button(bottom, text="Save", command=self._save).pack(side="right", padx=(0, 6))

        self._reload_list(select_first=True)
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.grab_set()

    # ------------------------------------------------------------------ list

    def _reload_list(self, select: str | None = None, select_first: bool = False) -> None:
        names = sorted(self._categories)
        self.listbox.delete(0, tk.END)
        for name in names:
            self.listbox.insert(tk.END, name)
        target = select if select in self._categories else (names[0] if (select_first and names) else None)
        if target is not None:
            index = names.index(target)
            self.listbox.selection_clear(0, tk.END)
            self.listbox.selection_set(index)
            self._show(target)
        else:
            self._current = None
            self.text.delete("1.0", tk.END)

    def _store_current(self) -> None:
        """Copy the text box back into the in-memory category."""
        if self._current is None:
            return
        phrases = [
            line.strip()
            for line in self.text.get("1.0", tk.END).splitlines()
            if line.strip()
        ]
        self._categories[self._current] = phrases

    def _show(self, name: str) -> None:
        self._current = name
        self.text.delete("1.0", tk.END)
        self.text.insert("1.0", "\n".join(self._categories.get(name, [])))

    def _on_select(self, _event: tk.Event) -> None:
        selection = self.listbox.curselection()
        if not selection:
            return
        name = self.listbox.get(selection[0])
        if name == self._current:
            return
        self._store_current()
        self._show(name)

    # --------------------------------------------------------------- actions

    def _add(self) -> None:
        name = simpledialog.askstring("New category", "Name:", parent=self)
        if not name:
            return
        name = name.strip()
        if not name:
            return
        if name in self._categories:
            messagebox.showinfo("Category", f"'{name}' already exists.", parent=self)
            return
        self._store_current()
        self._categories[name] = []
        self._reload_list(select=name)
        self.text.focus_set()

    def _rename(self) -> None:
        if self._current is None:
            return
        old = self._current
        name = simpledialog.askstring("Rename", "New name:", initialvalue=old, parent=self)
        if not name or not name.strip() or name.strip() == old:
            return
        name = name.strip()
        if name in self._categories:
            messagebox.showinfo("Category", f"'{name}' already exists.", parent=self)
            return
        self._store_current()
        self._categories[name] = self._categories.pop(old)
        self._current = name
        self._reload_list(select=name)

    def _delete(self) -> None:
        if self._current is None:
            return
        if not messagebox.askyesno("Delete", f"Delete the category '{self._current}'?", parent=self):
            return
        self._categories.pop(self._current, None)
        self._current = None
        self._reload_list(select_first=True)

    def _restore_defaults(self) -> None:
        """Adds missing default categories without touching your own edits."""
        self._store_current()
        added = 0
        for name, phrases in DEFAULT_CATEGORIES.items():
            if name not in self._categories:
                self._categories[name] = list(phrases)
                added += 1
        self._reload_list(select=self._current, select_first=True)
        messagebox.showinfo("Defaults", f"{added} category(ies) added.", parent=self)

    def _save(self) -> None:
        self._store_current()
        cleaned = {name: phrases for name, phrases in self._categories.items() if phrases}
        dropped = len(self._categories) - len(cleaned)
        if not cleaned:
            messagebox.showwarning(
                "Save", "At least one category with search terms is needed.",
                parent=self)
            return
        if dropped and not messagebox.askyesno(
            "Save",
            f"{dropped} category(ies) without search terms will be discarded. Continue?",
            parent=self,
        ):
            return
        try:
            save_categories(cleaned)
        except OSError as exc:
            messagebox.showerror("Save", f"Could not save: {exc}", parent=self)
            return
        self.result = cleaned
        self.grab_release()
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.grab_release()
        self.destroy()

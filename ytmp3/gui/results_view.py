"""The result table: a ttk.Treeview with a clickable check mark column.

A Treeview is used instead of hundreds of Checkbutton widgets because it
stays responsive with 500 rows and gives sortable columns for free.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Iterable, Sequence

from ..models import Track

CHECKED = "☑"
UNCHECKED = "☐"


class ResultsView(ttk.Frame):
    def __init__(self, master: tk.Misc, on_change: Callable[[], None] | None = None) -> None:
        super().__init__(master)
        self._tracks: list[Track] = []
        self._by_id: dict[str, Track] = {}
        self._on_change = on_change
        self._sort_column: str | None = None
        self._sort_reverse = False

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        columns = ("check", "title", "uploader", "duration")
        self.tree = ttk.Treeview(self, columns=columns, show="headings", selectmode="extended")
        self.tree.heading("check", text="", command=self.toggle_all)
        self.tree.heading("title", text="Titel", command=lambda: self._sort("title"))
        self.tree.heading("uploader", text="Kanal", command=lambda: self._sort("uploader"))
        self.tree.heading("duration", text="Länge", command=lambda: self._sort("duration"))
        self.tree.column("check", width=36, minwidth=36, stretch=False, anchor="center")
        self.tree.column("title", width=520, minwidth=200, stretch=True)
        self.tree.column("uploader", width=200, minwidth=120, stretch=False)
        self.tree.column("duration", width=80, minwidth=60, stretch=False, anchor="e")
        self.tree.grid(row=0, column=0, sticky="nsew")

        scroll_y = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        scroll_y.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll_y.set)

        self.tree.tag_configure("off", foreground="#8a8a8a")

        self.tree.bind("<Button-1>", self._on_click)
        self.tree.bind("<space>", self._on_space)
        self.tree.bind("<Return>", self._on_space)

        toolbar = ttk.Frame(self)
        toolbar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Button(toolbar, text="Alle", width=8, command=lambda: self.set_all(True)).pack(side="left")
        ttk.Button(toolbar, text="Keine", width=8, command=lambda: self.set_all(False)).pack(side="left", padx=(4, 0))
        ttk.Button(toolbar, text="Umkehren", width=10, command=self.invert).pack(side="left", padx=(4, 0))
        ttk.Button(toolbar, text="Entfernen", width=10, command=self.remove_selected_rows).pack(side="left", padx=(4, 0))

        ttk.Label(toolbar, text="Filter:").pack(side="left", padx=(16, 4))
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", lambda *_: self.refresh())
        entry = ttk.Entry(toolbar, textvariable=self.filter_var, width=24)
        entry.pack(side="left")

        self.count_var = tk.StringVar(value="0 Treffer, 0 ausgewählt")
        ttk.Label(toolbar, textvariable=self.count_var).pack(side="right")

    # ------------------------------------------------------------------ data

    def set_tracks(self, tracks: Iterable[Track]) -> None:
        self._tracks = list(tracks)
        self._by_id = {t.video_id: t for t in self._tracks}
        self.refresh()

    def add_tracks(self, tracks: Iterable[Track]) -> int:
        """Append tracks, skipping ids that are already listed."""
        added = 0
        for track in tracks:
            if track.video_id in self._by_id:
                continue
            self._by_id[track.video_id] = track
            self._tracks.append(track)
            added += 1
        self.refresh()
        return added

    def clear(self) -> None:
        self.set_tracks([])

    @property
    def tracks(self) -> Sequence[Track]:
        return tuple(self._tracks)

    def selected_tracks(self) -> list[Track]:
        return [t for t in self._tracks if t.selected]

    # ----------------------------------------------------------------- render

    def _visible_tracks(self) -> list[Track]:
        needle = self.filter_var.get().strip().lower()
        if not needle:
            return self._tracks
        return [
            t for t in self._tracks
            if needle in t.title.lower() or needle in t.uploader.lower()
        ]

    def refresh(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for track in self._visible_tracks():
            self.tree.insert(
                "", "end", iid=track.video_id,
                values=self._row(track),
                tags=() if track.selected else ("off",),
            )
        self._update_count()

    @staticmethod
    def _row(track: Track) -> tuple[str, str, str, str]:
        return (
            CHECKED if track.selected else UNCHECKED,
            track.title,
            track.uploader,
            track.duration_text,
        )

    def _refresh_row(self, track: Track) -> None:
        if self.tree.exists(track.video_id):
            self.tree.item(
                track.video_id,
                values=self._row(track),
                tags=() if track.selected else ("off",),
            )

    def _update_count(self) -> None:
        selected = sum(1 for t in self._tracks if t.selected)
        visible = len(self._visible_tracks())
        text = f"{len(self._tracks)} Treffer, {selected} ausgewählt"
        if visible != len(self._tracks):
            text = f"{visible} gefiltert · {text}"
        self.count_var.set(text)
        if self._on_change is not None:
            self._on_change()

    # --------------------------------------------------------------- actions

    def _toggle(self, video_id: str) -> None:
        track = self._by_id.get(video_id)
        if track is None:
            return
        track.selected = not track.selected
        self._refresh_row(track)
        self._update_count()

    def set_all(self, value: bool) -> None:
        """Applies to the currently visible (filtered) rows only."""
        for track in self._visible_tracks():
            track.selected = value
            self._refresh_row(track)
        self._update_count()

    def invert(self) -> None:
        for track in self._visible_tracks():
            track.selected = not track.selected
            self._refresh_row(track)
        self._update_count()

    def toggle_all(self) -> None:
        visible = self._visible_tracks()
        self.set_all(not all(t.selected for t in visible) if visible else True)

    def remove_selected_rows(self) -> None:
        """Drop the highlighted rows from the list entirely."""
        highlighted = set(self.tree.selection())
        if not highlighted:
            return
        self._tracks = [t for t in self._tracks if t.video_id not in highlighted]
        self._by_id = {t.video_id: t for t in self._tracks}
        self.refresh()

    # ---------------------------------------------------------------- events

    def _on_click(self, event: tk.Event) -> str | None:
        if self.tree.identify_region(event.x, event.y) != "cell":
            return None
        if self.tree.identify_column(event.x) != "#1":
            return None
        row = self.tree.identify_row(event.y)
        if row:
            self._toggle(row)
            return "break"  # keep the click from also changing the selection
        return None

    def _on_space(self, _event: tk.Event) -> str:
        for row in self.tree.selection():
            self._toggle(row)
        return "break"

    def _sort(self, column: str) -> None:
        reverse = self._sort_reverse if self._sort_column == column else False
        if self._sort_column == column:
            reverse = not self._sort_reverse

        def key(track: Track):
            if column == "duration":
                return track.duration if track.duration is not None else -1
            return getattr(track, column, "").lower()

        self._tracks.sort(key=key, reverse=reverse)
        self._sort_column = column
        self._sort_reverse = reverse
        self.refresh()

"""Main window.

Threading rule of this file: tkinter is touched from the main thread only.
Workers push ProgressEvent objects into a queue, and ``_pump`` drains that
queue from the tkinter event loop every 100 ms.
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from ..config import (
    FAILED_LOG,
    load_categories,
    load_settings,
    resolve_output_dir,
    save_settings,
)
from ..downloader import download_tracks, ffmpeg_available
from ..models import BITRATES, ProgressEvent, Track
from ..search import resolve_urls, search_category
from .category_editor import CategoryEditor
from .results_view import ResultsView

POLL_MS = 100


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("YouTube → MP3 Downloader")
        self.geometry("1000x700")
        self.minsize(860, 600)

        self.settings = load_settings()
        self.categories = load_categories()

        self.events: queue.Queue[ProgressEvent] = queue.Queue()
        self.cancel_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.busy = False

        self._init_style()
        self._build_ui()
        self._pump()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

        if not ffmpeg_available():
            self._log("FFmpeg wurde nicht im PATH gefunden – die MP3-Umwandlung "
                      "wird fehlschlagen.")
        self._log("Bereit. Kategorie wählen und auf 'Suchen' klicken.")

    # -------------------------------------------------------------------- UI

    def _init_style(self) -> None:
        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("Treeview", rowheight=22)
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"))

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        self._build_top()
        self.results = ResultsView(self, on_change=self._update_download_button)
        self.results.grid(row=1, column=0, sticky="nsew", padx=10, pady=(8, 0))
        self._build_bottom()

    def _build_top(self) -> None:
        top = ttk.Frame(self, padding=(10, 10, 10, 0))
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(8, weight=1)

        ttk.Label(top, text="Kategorie:").grid(row=0, column=0, sticky="w")
        self.category_var = tk.StringVar()
        self.category_box = ttk.Combobox(
            top, textvariable=self.category_var, state="readonly", width=22)
        self.category_box.grid(row=0, column=1, padx=(6, 12))
        self._fill_categories(self.settings.last_category)

        ttk.Label(top, text="Anzahl Links:").grid(row=0, column=2, sticky="w")
        self.count_var = tk.IntVar(value=self.settings.target_count)
        ttk.Spinbox(top, from_=10, to=1000, increment=10, width=7,
                    textvariable=self.count_var).grid(row=0, column=3, padx=(6, 12))

        self.search_button = ttk.Button(top, text="Suchen", command=self.start_search)
        self.search_button.grid(row=0, column=4)

        self.category_button = ttk.Button(top, text="Kategorien…", command=self.edit_categories)
        self.category_button.grid(row=0, column=5, padx=(6, 0))

        self.import_button = ttk.Button(top, text="Links aus Datei…", command=self.import_links)
        self.import_button.grid(row=0, column=6, padx=(6, 0))

        self.cancel_button = ttk.Button(top, text="Abbrechen", command=self.cancel,
                                        state="disabled")
        self.cancel_button.grid(row=0, column=7, padx=(6, 0))

    def _build_bottom(self) -> None:
        bottom = ttk.Frame(self, padding=(10, 8, 10, 10))
        bottom.grid(row=2, column=0, sticky="ew")
        bottom.columnconfigure(1, weight=1)

        # --- settings row 1: output folder
        ttk.Label(bottom, text="Ordner:").grid(row=0, column=0, sticky="w")
        self.output_var = tk.StringVar(value=self.settings.output_dir)
        ttk.Entry(bottom, textvariable=self.output_var).grid(
            row=0, column=1, sticky="ew", padx=(6, 6))
        ttk.Button(bottom, text="Durchsuchen…", command=self.choose_folder).grid(row=0, column=2)
        ttk.Button(bottom, text="Öffnen", command=self.open_folder).grid(
            row=0, column=3, padx=(6, 0))

        # --- settings row 2: the rest
        opts = ttk.Frame(bottom)
        opts.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(8, 0))

        ttk.Label(opts, text="Bitrate:").pack(side="left")
        self.bitrate_var = tk.StringVar(value=self.settings.bitrate)
        ttk.Combobox(opts, textvariable=self.bitrate_var, values=list(BITRATES),
                     state="readonly", width=6).pack(side="left", padx=(6, 2))
        ttk.Label(opts, text="kbps").pack(side="left")

        ttk.Label(opts, text="Länge min/max (Sek.):").pack(side="left", padx=(16, 0))
        self.min_var = tk.IntVar(value=self.settings.min_duration)
        self.max_var = tk.IntVar(value=self.settings.max_duration)
        ttk.Spinbox(opts, from_=0, to=3600, increment=30, width=6,
                    textvariable=self.min_var).pack(side="left", padx=(6, 2))
        ttk.Spinbox(opts, from_=0, to=36000, increment=60, width=7,
                    textvariable=self.max_var).pack(side="left", padx=(2, 0))

        ttk.Label(opts, text="Parallel:").pack(side="left", padx=(16, 0))
        self.concurrency_var = tk.IntVar(value=self.settings.concurrency)
        ttk.Spinbox(opts, from_=1, to=8, width=4,
                    textvariable=self.concurrency_var).pack(side="left", padx=(6, 0))

        self.skip_var = tk.BooleanVar(value=self.settings.skip_existing)
        ttk.Checkbutton(opts, text="Bereits geladene überspringen",
                        variable=self.skip_var).pack(side="left", padx=(16, 0))

        # --- progress
        progress = ttk.Frame(bottom)
        progress.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(10, 0))
        progress.columnconfigure(1, weight=1)

        ttk.Label(progress, text="Aktuell:").grid(row=0, column=0, sticky="w")
        self.file_bar = ttk.Progressbar(progress, maximum=100)
        self.file_bar.grid(row=0, column=1, sticky="ew", padx=(6, 6))
        self.file_label = ttk.Label(progress, text="–", width=44, anchor="w")
        self.file_label.grid(row=0, column=2, sticky="w")

        ttk.Label(progress, text="Gesamt:").grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.total_bar = ttk.Progressbar(progress, maximum=100)
        self.total_bar.grid(row=1, column=1, sticky="ew", padx=(6, 6), pady=(4, 0))
        self.total_label = ttk.Label(progress, text="0 / 0", width=44, anchor="w")
        self.total_label.grid(row=1, column=2, sticky="w", pady=(4, 0))

        # --- action + log
        action = ttk.Frame(bottom)
        action.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(10, 0))
        action.columnconfigure(1, weight=1)

        self.download_button = ttk.Button(action, text="Download starten",
                                          style="Accent.TButton",
                                          command=self.start_download, state="disabled")
        self.download_button.grid(row=0, column=0, sticky="w")

        log_frame = ttk.Frame(bottom)
        log_frame.grid(row=4, column=0, columnspan=4, sticky="ew", pady=(10, 0))
        log_frame.columnconfigure(0, weight=1)
        self.log_text = tk.Text(log_frame, height=6, wrap="word", state="disabled",
                                background="#1e1e1e", foreground="#d4d4d4",
                                insertbackground="#d4d4d4", relief="flat")
        self.log_text.grid(row=0, column=0, sticky="ew")
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        log_scroll.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=log_scroll.set)

    def _fill_categories(self, preferred: str = "") -> None:
        names = sorted(self.categories)
        self.category_box.configure(values=names)
        if preferred in self.categories:
            self.category_var.set(preferred)
        elif names:
            self.category_var.set(names[0])
        else:
            self.category_var.set("")

    # ----------------------------------------------------------------- state

    def _log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message.rstrip() + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        state = "disabled" if busy else "normal"
        self.search_button.configure(state=state)
        self.category_button.configure(state=state)
        self.import_button.configure(state=state)
        self.cancel_button.configure(state="normal" if busy else "disabled")
        self._update_download_button()

    def _update_download_button(self) -> None:
        if self.busy:
            self.download_button.configure(state="disabled")
            return
        has_selection = bool(self.results.selected_tracks())
        self.download_button.configure(state="normal" if has_selection else "disabled")

    def _collect_settings(self) -> None:
        """Read the widgets back into self.settings, ignoring invalid input."""
        def number(var: tk.IntVar, fallback: int, low: int, high: int) -> int:
            try:
                return max(low, min(int(var.get()), high))
            except (tk.TclError, ValueError):
                return fallback

        self.settings.output_dir = self.output_var.get().strip() or self.settings.output_dir
        self.settings.bitrate = self.bitrate_var.get() or "192"
        self.settings.target_count = number(self.count_var, self.settings.target_count, 1, 1000)
        self.settings.min_duration = number(self.min_var, self.settings.min_duration, 0, 36000)
        self.settings.max_duration = number(self.max_var, self.settings.max_duration, 0, 360000)
        self.settings.concurrency = number(self.concurrency_var, self.settings.concurrency, 1, 8)
        self.settings.skip_existing = bool(self.skip_var.get())
        self.settings.last_category = self.category_var.get()

    def _start_worker(self, target, *args) -> None:
        self.cancel_event.clear()
        self._set_busy(True)
        self.worker = threading.Thread(target=target, args=args, daemon=True)
        self.worker.start()

    def _sink(self, event: ProgressEvent) -> None:
        """Called from worker threads – only touches the queue."""
        self.events.put(event)

    # --------------------------------------------------------------- actions

    def start_search(self) -> None:
        if self.busy:
            return
        category = self.category_var.get()
        phrases = self.categories.get(category)
        if not phrases:
            messagebox.showwarning("Suche", "Diese Kategorie hat keine Suchbegriffe.")
            return

        self._collect_settings()
        append = False
        if self.results.tracks:
            answer = messagebox.askyesnocancel(
                "Ergebnisse",
                "Neue Treffer an die bestehende Liste anhängen?\n\n"
                "Ja = anhängen, Nein = Liste ersetzen",
            )
            if answer is None:
                return
            append = bool(answer)

        target = self.settings.target_count
        self._log(f"Suche '{category}': Ziel {target} Links über "
                  f"{len(phrases)} Suchbegriffe…")
        self.total_bar.configure(value=0)
        self.total_label.configure(text=f"0 / {target}")
        self.file_label.configure(text="–")
        self.file_bar.configure(value=0)

        settings = self.settings

        def job() -> None:
            try:
                tracks = search_category(
                    phrases,
                    target,
                    min_duration=settings.min_duration,
                    max_duration=settings.max_duration,
                    on_event=self._sink,
                    cancel=self.cancel_event,
                )
                self._sink(ProgressEvent(
                    kind="search_done", payload=(tracks, append),
                    total=target, current=len(tracks)))
            except Exception as exc:  # noqa: BLE001
                self._sink(ProgressEvent(kind="error", message=f"{type(exc).__name__}: {exc}"))

        self._start_worker(job)

    def import_links(self) -> None:
        if self.busy:
            return
        path = filedialog.askopenfilename(
            title="Datei mit Links wählen",
            filetypes=[("Textdateien", "*.txt"), ("Alle Dateien", "*.*")],
        )
        if not path:
            return
        try:
            lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            messagebox.showerror("Import", f"Datei konnte nicht gelesen werden: {exc}")
            return

        urls = [line.strip() for line in lines
                if line.strip() and not line.strip().startswith("#")]
        if not urls:
            messagebox.showinfo("Import", "Die Datei enthält keine Links.")
            return

        self._log(f"Importiere {len(urls)} Zeile(n) aus {Path(path).name} – "
                  "Titel werden geladen…")

        def job() -> None:
            try:
                tracks = resolve_urls(urls, on_event=self._sink, cancel=self.cancel_event)
                self._sink(ProgressEvent(
                    kind="search_done", payload=(tracks, True),
                    total=len(urls), current=len(tracks)))
            except Exception as exc:  # noqa: BLE001
                self._sink(ProgressEvent(kind="error", message=f"{type(exc).__name__}: {exc}"))

        self._start_worker(job)

    def start_download(self) -> None:
        if self.busy:
            return
        tracks = self.results.selected_tracks()
        if not tracks:
            messagebox.showinfo("Download", "Es ist kein Titel ausgewählt.")
            return

        self._collect_settings()
        try:
            output_dir = resolve_output_dir(self.settings.output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror("Download", f"Ausgabeordner nicht nutzbar: {exc}")
            return

        save_settings(self.settings)
        self._log(f"Starte Download von {len(tracks)} Titel(n) nach {output_dir} "
                  f"({self.settings.bitrate} kbps, {self.settings.concurrency} parallel)…")
        self.total_bar.configure(value=0)
        self.total_label.configure(text=f"0 / {len(tracks)}")
        self.file_bar.configure(value=0)

        settings = self.settings

        def job() -> None:
            try:
                download_tracks(tracks, settings, on_event=self._sink,
                                cancel=self.cancel_event)
            except Exception as exc:  # noqa: BLE001
                self._sink(ProgressEvent(kind="error", message=f"{type(exc).__name__}: {exc}"))

        self._start_worker(job)

    def cancel(self) -> None:
        if not self.busy:
            return
        self.cancel_event.set()
        self.cancel_button.configure(state="disabled")
        self._log("Abbruch angefordert – laufende Datei wird noch beendet…")

    def edit_categories(self) -> None:
        editor = CategoryEditor(self, self.categories)
        self.wait_window(editor)
        if editor.result is not None:
            self.categories = editor.result
            self._fill_categories(self.category_var.get())
            self._log(f"Kategorien gespeichert ({len(self.categories)} Stück).")

    def choose_folder(self) -> None:
        current = str(resolve_output_dir(self.output_var.get()))
        path = filedialog.askdirectory(title="Ausgabeordner wählen", initialdir=current)
        if path:
            self.output_var.set(path)

    def open_folder(self) -> None:
        path = resolve_output_dir(self.output_var.get())
        try:
            path.mkdir(parents=True, exist_ok=True)
            if sys.platform == "win32":
                os.startfile(path)  # noqa: S606
            elif sys.platform == "darwin":
                subprocess.run(["open", str(path)], check=False)
            else:
                subprocess.run(["xdg-open", str(path)], check=False)
        except OSError as exc:
            messagebox.showerror("Ordner", f"Konnte nicht geöffnet werden: {exc}")

    # ---------------------------------------------------------- event bridge

    def _pump(self) -> None:
        try:
            while True:
                self._handle(self.events.get_nowait())
        except queue.Empty:
            pass
        self.after(POLL_MS, self._pump)

    def _handle(self, event: ProgressEvent) -> None:
        kind = event.kind

        if kind == "log":
            self._log(event.message)

        elif kind == "search_step":
            self.total_bar.configure(value=event.percent)
            self.file_label.configure(text=event.message[:60])
            found = event.payload if isinstance(event.payload, int) else 0
            self.total_label.configure(
                text=f"Suchbegriff {event.current}/{event.total} · {found} gefunden")

        elif kind == "search_done":
            tracks, append = event.payload
            self._finish_search(tracks, append)

        elif kind == "file_start":
            self.file_bar.configure(value=0)
            self.file_label.configure(text=event.message[:60])

        elif kind == "file_progress":
            self.file_bar.configure(value=event.percent)
            self.file_label.configure(text=event.message[:60])

        elif kind == "file_post":
            self.file_bar.configure(value=100)
            self.file_label.configure(text=f"Konvertiere: {event.message[:50]}")

        elif kind == "file_done":
            self.total_bar.configure(value=event.percent)
            self.total_label.configure(text=f"{event.current} / {event.total}")

        elif kind in {"finished", "cancelled"}:
            self._finish_download(event)

        elif kind == "error":
            self._set_busy(False)
            self._log(f"Abbruch wegen Fehler: {event.message}")
            messagebox.showerror("Fehler", event.message)

    def _finish_search(self, tracks: list[Track], append: bool) -> None:
        self._set_busy(False)
        self.file_label.configure(text="–")
        self.file_bar.configure(value=0)

        if append:
            added = self.results.add_tracks(tracks)
            self._log(f"{added} neue Titel ergänzt "
                      f"({len(tracks) - added} Duplikate übersprungen).")
        else:
            self.results.set_tracks(tracks)
            self._log(f"{len(tracks)} Titel gefunden.")

        total = len(self.results.tracks)
        self.total_bar.configure(value=100 if total else 0)
        self.total_label.configure(text=f"{total} Titel in der Liste")
        if self.cancel_event.is_set():
            self._log("Suche wurde abgebrochen.")
        self._collect_settings()
        save_settings(self.settings)

    def _finish_download(self, event: ProgressEvent) -> None:
        self._set_busy(False)
        summary = event.payload
        self.file_bar.configure(value=0)
        self.file_label.configure(text="–")

        if summary is None:
            return

        if event.kind == "cancelled":
            self._log(f"Abgebrochen: {summary.ok} fertig, {summary.failed} fehlgeschlagen, "
                      f"{summary.skipped} nicht gestartet.")
            return

        self._log(f"Fertig: {summary.ok} MP3s erstellt, {summary.failed} fehlgeschlagen.")
        if summary.failed:
            self._log(f"Details in {FAILED_LOG}")
        messagebox.showinfo(
            "Fertig",
            f"{summary.ok} MP3-Dateien erstellt.\n"
            f"{summary.failed} fehlgeschlagen"
            + (f"\n\nDetails: {FAILED_LOG}" if summary.failed else ""),
        )

    # ----------------------------------------------------------------- close

    def _on_close(self) -> None:
        if self.busy:
            if not messagebox.askyesno("Beenden", "Es läuft noch ein Vorgang. Trotzdem beenden?"):
                return
            self.cancel_event.set()
        try:
            self._collect_settings()
            save_settings(self.settings)
        except Exception:  # noqa: BLE001 - never block closing over a settings write
            pass
        self.destroy()


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()

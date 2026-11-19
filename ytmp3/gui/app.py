"""Main window.

Threading rule of this file: tkinter is touched from the main thread only.
Workers push ProgressEvent objects into a queue, and ``_pump`` drains that
queue from the tkinter event loop every 100 ms.
"""

from __future__ import annotations

import datetime as _dt
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont

from .. import __version__
from ..config import (
    FAILED_LOG,
    LOG_DIR,
    ensure_dirs,
    load_categories,
    load_settings,
    resolve_output_dir,
    save_settings,
)
from ..downloader import download_tracks, ffmpeg_available, read_url_file
from ..models import BITRATES, ProgressEvent, Track
from ..search import extract_video_id, resolve_urls, search_category
from ..tools import has_js_runtime
from .category_editor import CategoryEditor
from .results_view import ResultsView

POLL_MS = 100
ERROR_LOG = LOG_DIR / "error.log"


def _write_error_log(text: str) -> None:
    try:
        ensure_dirs()
        stamp = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with ERROR_LOG.open("a", encoding="utf-8") as handle:
            handle.write(f"--- {stamp}\n{text}\n")
    except OSError:
        pass


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"YouTube to MP3 Downloader {__version__}")
        self.geometry("1060x720")
        self.minsize(940, 600)

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
            self._log("FFmpeg was not found - converting to MP3 will fail. "
                      "Start the app with the start script to install it automatically.")
        if not has_js_runtime():
            self._log("No JavaScript runtime (Deno) found - some videos may fail to download. "
                      "Start the app with the start script to install it automatically.")
        self._log("Ready. Pick a category (or type your own search term) and click 'Search'.")

    # -------------------------------------------------------------------- UI

    def _init_style(self) -> None:
        style = ttk.Style(self)
        if sys.platform != "darwin" and "clam" in style.theme_names():
            style.theme_use("clam")
        default_font = tkfont.nametofont("TkDefaultFont")
        line_height = default_font.metrics("linespace")
        style.configure("Treeview", rowheight=max(22, line_height + 6))
        bold = default_font.copy()
        bold.configure(weight="bold")
        self._bold_font = bold  # keep a reference, Tk fonts are garbage collected
        style.configure("Accent.TButton", font=bold, padding=(12, 4))

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
        top.columnconfigure(9, weight=1)

        ttk.Label(top, text="Category:").grid(row=0, column=0, sticky="w")
        self.category_var = tk.StringVar()
        # Not read-only: anything typed that is not a category is searched as is.
        self.category_box = ttk.Combobox(top, textvariable=self.category_var, width=24)
        self.category_box.grid(row=0, column=1, padx=(6, 12))
        self.category_box.bind("<Return>", lambda _e: self.start_search())
        self._fill_categories(self.settings.last_category)

        ttk.Label(top, text="Links:").grid(row=0, column=2, sticky="w")
        self.count_var = tk.IntVar(value=self.settings.target_count)
        ttk.Spinbox(top, from_=10, to=1000, increment=10, width=6,
                    textvariable=self.count_var).grid(row=0, column=3, padx=(6, 12))

        self.search_button = ttk.Button(top, text="Search", command=self.start_search)
        self.search_button.grid(row=0, column=4)

        self.category_button = ttk.Button(top, text="Categories…", command=self.edit_categories)
        self.category_button.grid(row=0, column=5, padx=(6, 0))

        self.import_button = ttk.Button(top, text="Links from file…", command=self.import_links)
        self.import_button.grid(row=0, column=6, padx=(6, 0))

        self.paste_button = ttk.Button(top, text="Paste links", command=self.paste_links)
        self.paste_button.grid(row=0, column=7, padx=(6, 0))

        self.cancel_button = ttk.Button(top, text="Cancel", command=self.cancel,
                                        state="disabled")
        self.cancel_button.grid(row=0, column=8, padx=(6, 0))

    def _build_bottom(self) -> None:
        bottom = ttk.Frame(self, padding=(10, 8, 10, 10))
        bottom.grid(row=2, column=0, sticky="ew")
        bottom.columnconfigure(1, weight=1)

        # --- settings row 1: output folder
        ttk.Label(bottom, text="Folder:").grid(row=0, column=0, sticky="w")
        self.output_var = tk.StringVar(value=self.settings.output_dir)
        ttk.Entry(bottom, textvariable=self.output_var).grid(
            row=0, column=1, sticky="ew", padx=(6, 6))
        ttk.Button(bottom, text="Browse…", command=self.choose_folder).grid(row=0, column=2)
        ttk.Button(bottom, text="Open", command=self.open_folder).grid(
            row=0, column=3, padx=(6, 0))

        # --- settings row 2: the rest
        opts = ttk.Frame(bottom)
        opts.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(8, 0))

        ttk.Label(opts, text="Bitrate:").pack(side="left")
        self.bitrate_var = tk.StringVar(value=self.settings.bitrate)
        ttk.Combobox(opts, textvariable=self.bitrate_var, values=list(BITRATES),
                     state="readonly", width=5).pack(side="left", padx=(6, 2))
        ttk.Label(opts, text="kbps").pack(side="left")

        ttk.Label(opts, text="Length min/max (sec):").pack(side="left", padx=(16, 0))
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
        ttk.Checkbutton(opts, text="Skip already downloaded",
                        variable=self.skip_var).pack(side="left", padx=(16, 0))

        self.cover_var = tk.BooleanVar(value=self.settings.embed_thumbnail)
        ttk.Checkbutton(opts, text="Cover art",
                        variable=self.cover_var).pack(side="left", padx=(12, 0))

        # --- progress
        progress = ttk.Frame(bottom)
        progress.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(10, 0))
        progress.columnconfigure(1, weight=1)

        ttk.Label(progress, text="Current:").grid(row=0, column=0, sticky="w")
        self.file_bar = ttk.Progressbar(progress, maximum=100)
        self.file_bar.grid(row=0, column=1, sticky="ew", padx=(6, 6))
        self.file_label = ttk.Label(progress, text="–", width=44, anchor="w")
        self.file_label.grid(row=0, column=2, sticky="w")

        ttk.Label(progress, text="Total:").grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.total_bar = ttk.Progressbar(progress, maximum=100)
        self.total_bar.grid(row=1, column=1, sticky="ew", padx=(6, 6), pady=(4, 0))
        self.total_label = ttk.Label(progress, text="0 / 0", width=44, anchor="w")
        self.total_label.grid(row=1, column=2, sticky="w", pady=(4, 0))

        # --- action + log
        action = ttk.Frame(bottom)
        action.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(10, 0))
        action.columnconfigure(1, weight=1)

        self.download_button = ttk.Button(action, text="Start download",
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
        names = sorted(self.categories, key=str.lower)
        self.category_box.configure(values=names)
        if preferred:
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
        for button in (self.search_button, self.category_button,
                       self.import_button, self.paste_button):
            button.configure(state=state)
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
        self.settings.embed_thumbnail = bool(self.cover_var.get())
        self.settings.last_category = self.category_var.get().strip()

    def _save_settings_quietly(self) -> None:
        try:
            save_settings(self.settings)
        except OSError as exc:
            self._log(f"Could not save settings: {exc}")

    def _start_worker(self, target, *args) -> None:
        self.cancel_event.clear()
        self._set_busy(True)
        self.worker = threading.Thread(target=target, args=args, daemon=True)
        self.worker.start()

    def _sink(self, event: ProgressEvent) -> None:
        """Called from worker threads – only touches the queue."""
        self.events.put(event)

    def _reset_progress(self, total_text: str) -> None:
        self.total_bar.configure(value=0)
        self.total_label.configure(text=total_text)
        self.file_label.configure(text="–")
        self.file_bar.configure(value=0)

    # --------------------------------------------------------------- actions

    def _ask_append(self) -> bool | None:
        """True = append, False = replace, None = user cancelled."""
        if not self.results.tracks:
            return False
        return messagebox.askyesnocancel(
            "Results",
            "Add the new results to the current list?\n\n"
            "Yes = add, No = replace the list",
        )

    def start_search(self) -> None:
        if self.busy:
            return
        query = self.category_var.get().strip()
        if not query:
            messagebox.showwarning("Search", "Pick a category or type a search term.")
            return
        if query in self.categories:
            phrases = self.categories[query]
            what = f"category '{query}'"
        else:
            phrases = [query]
            what = f"'{query}'"

        self._collect_settings()
        if (self.settings.min_duration and self.settings.max_duration
                and self.settings.min_duration > self.settings.max_duration):
            messagebox.showwarning(
                "Search", "The minimum length is larger than the maximum length.\n"
                          "Nothing could ever match - please fix the length filter.")
            return

        append = self._ask_append()
        if append is None:
            return

        target = self.settings.target_count
        self._log(f"Searching {what}: up to {target} links using "
                  f"{len(phrases)} search term(s)…")
        self._reset_progress(f"0 / {target}")
        self._save_settings_quietly()

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
            title="Choose a file with links",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            urls = read_url_file(Path(path))
        except OSError as exc:
            messagebox.showerror("Import", f"Could not read the file: {exc}")
            return
        self._import_urls(urls, Path(path).name)

    def paste_links(self) -> None:
        if self.busy:
            return
        try:
            text = self.clipboard_get()
        except tk.TclError:
            text = ""
        urls = [line.strip() for line in text.split() if line.strip()]
        self._import_urls(urls, "clipboard")

    def _import_urls(self, urls: list[str], source: str) -> None:
        valid = [u for u in urls if extract_video_id(u)]
        if not valid:
            messagebox.showinfo(
                "Import", f"No YouTube links found in the {source}.\n\n"
                          "Expected one link per line, e.g.\n"
                          "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
            return

        self._log(f"Importing {len(valid)} link(s) from {source} – fetching titles…")
        self._reset_progress(f"0 / {len(valid)}")

        def job() -> None:
            try:
                tracks = resolve_urls(valid, on_event=self._sink, cancel=self.cancel_event)
                self._sink(ProgressEvent(
                    kind="search_done", payload=(tracks, True),
                    total=len(valid), current=len(tracks)))
            except Exception as exc:  # noqa: BLE001
                self._sink(ProgressEvent(kind="error", message=f"{type(exc).__name__}: {exc}"))

        self._start_worker(job)

    def start_download(self) -> None:
        if self.busy:
            return
        tracks = self.results.selected_tracks()
        if not tracks:
            messagebox.showinfo("Download", "No tracks are selected.")
            return

        self._collect_settings()
        try:
            output_dir = resolve_output_dir(self.settings.output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror("Download", f"The output folder cannot be used: {exc}")
            return

        if not ffmpeg_available():
            messagebox.showerror(
                "Download", "FFmpeg is missing, so no MP3 files can be created.\n\n"
                            "Close the app and start it again with the start script - "
                            "it installs FFmpeg automatically.")
            return

        self._save_settings_quietly()
        self._log(f"Downloading {len(tracks)} track(s) to {output_dir} "
                  f"({self.settings.bitrate} kbps, {self.settings.concurrency} in parallel)…")
        self._reset_progress(f"0 / {len(tracks)}")

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
        self._log("Cancelling…")

    def edit_categories(self) -> None:
        editor = CategoryEditor(self, self.categories)
        self.wait_window(editor)
        if editor.result is not None:
            self.categories = editor.result
            current = self.category_var.get()
            self._fill_categories(current if current in self.categories else "")
            self._log(f"Categories saved ({len(self.categories)} in total).")

    def choose_folder(self) -> None:
        current = str(resolve_output_dir(self.output_var.get()))
        path = filedialog.askdirectory(title="Choose the output folder", initialdir=current)
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
            messagebox.showerror("Folder", f"Could not open the folder: {exc}")

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
                text=f"Step {event.current}/{event.total} · {found} found")

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
            self.file_label.configure(text=f"Converting: {event.message[:48]}")

        elif kind == "file_done":
            self.total_bar.configure(value=event.percent)
            self.total_label.configure(text=f"{event.current} / {event.total}")

        elif kind in {"finished", "cancelled"}:
            self._finish_download(event)

        elif kind == "error":
            self._set_busy(False)
            self._log(f"Stopped because of an error: {event.message}")
            messagebox.showerror("Error", event.message)

    def _finish_search(self, tracks: list[Track], append: bool) -> None:
        self._set_busy(False)
        self.file_label.configure(text="–")
        self.file_bar.configure(value=0)

        if append:
            added = self.results.add_tracks(tracks)
            self._log(f"Added {added} new track(s) "
                      f"({len(tracks) - added} duplicate(s) skipped).")
        else:
            self.results.set_tracks(tracks)
            self._log(f"Found {len(tracks)} track(s).")

        if not tracks and not self.cancel_event.is_set():
            self._log("Nothing found. Check your internet connection, add more search "
                      "terms or relax the length filter.")

        total = len(self.results.tracks)
        self.total_bar.configure(value=100 if total else 0)
        self.total_label.configure(text=f"{total} track(s) in the list")
        if self.cancel_event.is_set():
            self._log("Search cancelled.")

    def _finish_download(self, event: ProgressEvent) -> None:
        self._set_busy(False)
        summary = event.payload
        self.file_bar.configure(value=0)
        self.file_label.configure(text="–")

        if summary is None:
            return

        already = (f", {summary.already_downloaded} already downloaded"
                   if summary.already_downloaded else "")

        if event.kind == "cancelled":
            self._log(f"Cancelled: {summary.ok} done{already}, {summary.failed} failed, "
                      f"{summary.not_started} not started.")
            return

        self._log(f"Done: {summary.ok} MP3 file(s) created{already}, "
                  f"{summary.failed} failed.")
        if summary.failed:
            self._log(f"Details in {FAILED_LOG}")
        message = f"{summary.ok} MP3 file(s) created."
        if summary.already_downloaded:
            message += (f"\n{summary.already_downloaded} were already downloaded earlier "
                        "and were skipped.")
        if summary.failed:
            message += f"\n{summary.failed} failed.\n\nDetails: {FAILED_LOG}"
        messagebox.showinfo("Done", message)

    # ---------------------------------------------------------------- errors

    def report_callback_exception(self, exc, val, tb) -> None:  # noqa: D401 - tk API
        """Unexpected errors in callbacks: log them instead of dying silently."""
        text = "".join(traceback.format_exception(exc, val, tb))
        _write_error_log(text)
        try:
            self._log(f"Unexpected error: {val} (details in {ERROR_LOG})")
        except tk.TclError:
            pass

    # ----------------------------------------------------------------- close

    def _on_close(self) -> None:
        if self.busy:
            if not messagebox.askyesno("Quit", "Something is still running. Quit anyway?"):
                return
            self.cancel_event.set()
        try:
            self._collect_settings()
            save_settings(self.settings)
        except Exception:  # noqa: BLE001 - never block closing over a settings write
            pass
        self.destroy()


def _enable_high_dpi() -> None:
    """Sharp text on Windows with display scaling instead of blurry bitmaps."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:  # noqa: BLE001 - older Windows versions
        pass


def main() -> None:
    _enable_high_dpi()
    try:
        app = App()
    except Exception:  # noqa: BLE001
        text = traceback.format_exc()
        _write_error_log(text)
        print(text, file=sys.stderr)
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(
                "YouTube to MP3",
                f"The app could not start.\n\n{text.strip().splitlines()[-1]}\n\n"
                f"Details: {ERROR_LOG}")
            root.destroy()
        except Exception:  # noqa: BLE001
            pass
        raise SystemExit(1)
    app.mainloop()


if __name__ == "__main__":
    main()

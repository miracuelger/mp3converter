"""Downloading and converting to MP3.

Each track is downloaded in its own yt-dlp call so that a single broken
video cannot abort the whole run: failures are logged to logs/failed.log
and the queue continues.
"""

from __future__ import annotations

import datetime as _dt
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Sequence

import yt_dlp

from .config import FAILED_LOG, ensure_dirs, resolve_output_dir
from .models import AppSettings, DownloadSummary, ProgressEvent, Track

EventSink = Callable[[ProgressEvent], None] | None

ARCHIVE_NAME = "downloaded_archive.txt"


class DownloadCancelled(Exception):
    """Raised from inside a progress hook to stop the current download."""


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _emit(sink: EventSink, event: ProgressEvent) -> None:
    if sink is not None:
        sink(event)


def _log_failure(track: Track, reason: str) -> None:
    ensure_dirs()
    stamp = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{stamp}\t{track.video_id}\t{track.title}\t{reason}\n"
    try:
        with FAILED_LOG.open("a", encoding="utf-8") as handle:
            handle.write(line)
    except OSError:
        pass


# Warnings that yt-dlp repeats for every single video and that the user can
# do nothing useful about - they would drown out the real messages.
_MUTED_WARNINGS = (
    "no supported javascript runtime",
    "nsig extraction failed",
    "unable to download webpage: http error 429",
)


class _TrackLogger:
    """Routes yt-dlp warnings/errors into the event stream instead of stdout."""

    def __init__(self, sink: EventSink, title: str) -> None:
        self._sink = sink
        self._title = title

    def debug(self, msg: str) -> None: ...

    def info(self, msg: str) -> None: ...

    def warning(self, msg: str) -> None:
        text = str(msg).strip()
        if not text:
            return
        lowered = text.lower()
        if any(muted in lowered for muted in _MUTED_WARNINGS):
            return
        _emit(self._sink, ProgressEvent(kind="log", message=f"Warnung: {text}"))

    def error(self, msg: str) -> None:
        text = str(msg).strip()
        if text:
            _emit(self._sink, ProgressEvent(kind="log", message=f"Fehler: {text}"))


def build_options(
    settings: AppSettings,
    output_dir: Path,
    hooks: Sequence[Callable] = (),
    post_hooks: Sequence[Callable] = (),
    logger: object | None = None,
) -> dict:
    """The yt-dlp options used for one download."""
    options: dict = {
        "format": "bestaudio/best",
        # %(title).150s keeps very long titles inside the Windows path limit.
        "outtmpl": str(output_dir / "%(title).150s [%(id)s].%(ext)s"),
        "noplaylist": True,
        "ignoreerrors": False,       # we handle errors per track ourselves
        "quiet": True,
        "no_warnings": False,
        "noprogress": True,
        "retries": 3,
        "fragment_retries": 3,
        "progress_hooks": list(hooks),
        "postprocessor_hooks": list(post_hooks),
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": settings.bitrate,
            },
            {"key": "FFmpegMetadata"},
        ],
    }
    if logger is not None:
        options["logger"] = logger
    if settings.skip_existing:
        options["download_archive"] = str(output_dir / ARCHIVE_NAME)
    return options


def download_tracks(
    tracks: Sequence[Track],
    settings: AppSettings,
    on_event: EventSink = None,
    cancel: threading.Event | None = None,
) -> DownloadSummary:
    """Download every track to MP3 and return a summary.

    Runs ``settings.concurrency`` downloads in parallel. Progress events carry
    the title they belong to, so the GUI can label its per-file bar correctly
    even when two downloads overlap.
    """
    summary = DownloadSummary()
    if not tracks:
        return summary

    output_dir = resolve_output_dir(settings.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    total = len(tracks)
    done = 0
    lock = threading.Lock()

    def finish(track: Track, ok: bool, reason: str = "") -> None:
        nonlocal done
        with lock:
            done += 1
            if ok:
                summary.ok += 1
            else:
                summary.failed += 1
                summary.failures.append((track.title, reason))
            current = done
        if not ok:
            _log_failure(track, reason)
            _emit(on_event, ProgressEvent(
                kind="log", message=f"Übersprungen: {track.title} ({reason})"))
        _emit(on_event, ProgressEvent(
            kind="file_done",
            message=track.title,
            current=current,
            total=total,
            percent=current / total * 100,
        ))

    def worker(item: tuple[int, Track]) -> None:
        index, track = item
        if cancel is not None and cancel.is_set():
            return

        _emit(on_event, ProgressEvent(
            kind="file_start", message=track.title, current=index, total=total))

        def progress_hook(data: dict) -> None:
            if cancel is not None and cancel.is_set():
                raise DownloadCancelled
            if data.get("status") == "downloading":
                total_bytes = data.get("total_bytes") or data.get("total_bytes_estimate")
                downloaded = data.get("downloaded_bytes") or 0
                percent = (downloaded / total_bytes * 100) if total_bytes else 0.0
                _emit(on_event, ProgressEvent(
                    kind="file_progress", message=track.title, percent=percent))

        announced_post = False

        def post_hook(data: dict) -> None:
            # Fires once per postprocessor; the user only needs to be told once
            # that this track moved on to the ffmpeg stage.
            nonlocal announced_post
            if cancel is not None and cancel.is_set():
                raise DownloadCancelled
            if data.get("status") == "started" and not announced_post:
                announced_post = True
                _emit(on_event, ProgressEvent(
                    kind="file_post", message=track.title, percent=100.0))

        options = build_options(
            settings,
            output_dir,
            hooks=[progress_hook],
            post_hooks=[post_hook],
            logger=_TrackLogger(on_event, track.title),
        )

        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                code = ydl.download([track.url])
            if code:
                finish(track, False, f"yt-dlp Rückgabecode {code}")
            else:
                finish(track, True)
        except DownloadCancelled:
            return
        except yt_dlp.utils.DownloadError as exc:
            finish(track, False, _short(exc))
        except Exception as exc:  # noqa: BLE001 - never let one track kill the run
            finish(track, False, f"{type(exc).__name__}: {exc}")

    workers = max(1, min(settings.concurrency, 8))
    items = list(enumerate(tracks, start=1))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(worker, items))

    if cancel is not None and cancel.is_set():
        summary.skipped = total - summary.ok - summary.failed
        _emit(on_event, ProgressEvent(kind="cancelled", payload=summary))
    else:
        _emit(on_event, ProgressEvent(kind="finished", payload=summary))
    return summary


def _short(exc: Exception, limit: int = 200) -> str:
    text = " ".join(str(exc).split())
    return text[:limit]


def _cli() -> None:
    """Quick test without the GUI:  python -m ytmp3.downloader urls.txt"""
    import sys

    from .config import load_settings
    from .search import extract_video_id

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("urls.txt")
    if not path.exists():
        print(f"{path} nicht gefunden.")
        raise SystemExit(1)

    lines = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    tracks = []
    for line in lines:
        video_id = extract_video_id(line)
        if video_id:
            tracks.append(Track(video_id=video_id, title=line))

    def show(event: ProgressEvent) -> None:
        if event.kind in {"file_start", "file_done", "log"}:
            print(f"[{event.kind}] {event.message}")

    summary = download_tracks(tracks, load_settings(), on_event=show)
    print(f"\nFertig: {summary.ok} ok, {summary.failed} fehlgeschlagen.")


if __name__ == "__main__":
    _cli()

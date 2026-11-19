"""Downloading and converting to MP3.

Each track is downloaded in its own yt-dlp call so that a single broken
video cannot abort the whole run: failures are logged to logs/failed.log
and the queue continues.
"""

from __future__ import annotations

import datetime as _dt
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Sequence

import yt_dlp

from .config import FAILED_LOG, ensure_dirs, resolve_output_dir
from .models import AppSettings, DownloadSummary, ProgressEvent, Track
from .tools import base_options, find_ffmpeg

EventSink = Callable[[ProgressEvent], None] | None

ARCHIVE_NAME = "downloaded_archive.txt"


class DownloadCancelled(yt_dlp.utils.DownloadCancelled):
    """Raised from inside a progress hook to stop the current download."""


def ffmpeg_available() -> bool:
    return find_ffmpeg() is not None


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


def read_archive(output_dir: Path) -> set[str]:
    """Video ids recorded in the yt-dlp download archive of ``output_dir``."""
    path = output_dir / ARCHIVE_NAME
    ids: set[str] = set()
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[0] == "youtube":
                ids.add(parts[1])
    except OSError:
        pass
    return ids


def _remove_leftovers(output_dir: Path, video_id: str) -> None:
    """Delete .part files and intermediate audio/thumbnail files of a track.

    Called after a failed or cancelled download. A finished .mp3 is kept.
    """
    marker = f"[{video_id}]"
    try:
        candidates = [p for p in output_dir.iterdir() if marker in p.name]
    except OSError:
        return
    for path in candidates:
        if path.suffix.lower() == ".mp3":
            continue
        try:
            path.unlink()
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
        _emit(self._sink, ProgressEvent(kind="log", message=f"Warning: {text}"))

    def error(self, msg: str) -> None:
        # Errors are raised as DownloadError as well and reported once by the
        # caller together with the track title, so they are not logged here.
        ...


def build_options(
    settings: AppSettings,
    output_dir: Path,
    hooks: Sequence[Callable] = (),
    post_hooks: Sequence[Callable] = (),
    logger: object | None = None,
) -> dict:
    """The yt-dlp options used for one download."""
    postprocessors: list[dict] = []
    if settings.embed_thumbnail:
        # YouTube thumbnails are WebP; MP3 players only understand JPEG/PNG.
        postprocessors.append(
            {"key": "FFmpegThumbnailsConvertor", "format": "jpg", "when": "before_dl"})
    postprocessors.append({
        "key": "FFmpegExtractAudio",
        "preferredcodec": "mp3",
        "preferredquality": settings.bitrate,
    })
    postprocessors.append({"key": "FFmpegMetadata"})
    if settings.embed_thumbnail:
        postprocessors.append({"key": "EmbedThumbnail"})

    options: dict = {
        **base_options(),
        "format": "bestaudio/best",
        # %(title).150s keeps very long titles inside the Windows path limit.
        "outtmpl": str(output_dir / "%(title).150s [%(id)s].%(ext)s"),
        "windowsfilenames": True,    # same file names on every OS
        "noplaylist": True,
        "ignoreerrors": False,       # we handle errors per track ourselves
        "quiet": True,
        "no_warnings": False,
        "noprogress": True,
        "retries": 3,
        "fragment_retries": 3,
        "writethumbnail": settings.embed_thumbnail,
        "progress_hooks": list(hooks),
        "postprocessor_hooks": list(post_hooks),
        "postprocessors": postprocessors,
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
    archived = read_archive(output_dir) if settings.skip_existing else set()

    total = len(tracks)
    done = 0
    lock = threading.Lock()

    def finish(track: Track, status: str, reason: str = "") -> None:
        """status is one of ok / failed / archived."""
        nonlocal done
        with lock:
            done += 1
            if status == "ok":
                summary.ok += 1
            elif status == "archived":
                summary.already_downloaded += 1
            else:
                summary.failed += 1
                summary.failures.append((track.title, reason))
            current = done
        if status == "failed":
            _log_failure(track, reason)
            _emit(on_event, ProgressEvent(
                kind="log", message=f"Skipped: {track.title} ({reason})"))
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
        if track.video_id in archived:
            finish(track, "archived")
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
                    kind="file_progress", message=track.title, percent=min(percent, 100.0)))

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
                _remove_leftovers(output_dir, track.video_id)
                finish(track, "failed", f"yt-dlp exit code {code}")
            else:
                finish(track, "ok")
        except DownloadCancelled:
            _remove_leftovers(output_dir, track.video_id)
            return
        except yt_dlp.utils.DownloadError as exc:
            _remove_leftovers(output_dir, track.video_id)
            finish(track, "failed", _short(exc))
        except Exception as exc:  # noqa: BLE001 - never let one track kill the run
            _remove_leftovers(output_dir, track.video_id)
            finish(track, "failed", f"{type(exc).__name__}: {exc}")

    workers = max(1, min(settings.concurrency, 8))
    items = list(enumerate(tracks, start=1))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(worker, items))

    if cancel is not None and cancel.is_set():
        summary.not_started = total - summary.ok - summary.failed - summary.already_downloaded
        _emit(on_event, ProgressEvent(kind="cancelled", payload=summary))
    else:
        _emit(on_event, ProgressEvent(kind="finished", payload=summary))
    return summary


def _short(exc: Exception, limit: int = 200) -> str:
    text = " ".join(str(exc).split())
    if text.startswith("ERROR: "):
        text = text[len("ERROR: "):]
    return text[:limit]


def read_url_file(path: Path) -> list[str]:
    """Non-empty, non-comment lines of a text file with one link per line."""
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def _cli() -> None:
    """Download without the GUI:  python -m ytmp3.downloader urls.txt"""
    import sys

    from .config import load_settings
    from .search import extract_video_id

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("urls.txt")
    if not path.exists():
        print(f"{path} not found.")
        raise SystemExit(1)

    tracks: list[Track] = []
    seen: set[str] = set()
    for line in read_url_file(path):
        video_id = extract_video_id(line)
        if video_id and video_id not in seen:
            seen.add(video_id)
            tracks.append(Track(video_id=video_id, title=line))
    if not tracks:
        print(f"No YouTube links found in {path}.")
        raise SystemExit(0)

    settings = load_settings()
    print(f"Downloading {len(tracks)} track(s) to {settings.output_dir} ...")

    def show(event: ProgressEvent) -> None:
        if event.kind == "file_done":
            print(f"[{event.current}/{event.total}] {event.message}")
        elif event.kind == "log":
            print(event.message)

    summary = download_tracks(tracks, settings, on_event=show)
    print(f"\nDone: {summary.ok} new, {summary.already_downloaded} already downloaded, "
          f"{summary.failed} failed.")


if __name__ == "__main__":
    _cli()

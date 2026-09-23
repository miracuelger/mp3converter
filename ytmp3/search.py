"""Finding YouTube links for a category.

Searching is done through yt-dlp's ``ytsearchN:`` pseudo URL with
``extract_flat`` enabled: that returns metadata only (id, title, channel,
duration) without touching the video pages, which makes it fast enough to
collect several hundred links in a few seconds.
"""

from __future__ import annotations

import math
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Iterable, Sequence

import yt_dlp

from .models import ProgressEvent, Track

EventSink = Callable[[ProgressEvent], None] | None

# Matches the 11 character video id in every common YouTube URL form.
_ID_PATTERNS = (
    re.compile(r"(?:v=|/v/|youtu\.be/|/embed/|/shorts/|/live/)([A-Za-z0-9_-]{11})"),
    re.compile(r"^([A-Za-z0-9_-]{11})$"),
)

_MAX_PER_PHRASE = 200


class _QuietLogger:
    """Swallows yt-dlp's console chatter; errors are raised anyway."""

    def debug(self, msg: str) -> None: ...
    def info(self, msg: str) -> None: ...
    def warning(self, msg: str) -> None: ...
    def error(self, msg: str) -> None: ...


def _emit(sink: EventSink, event: ProgressEvent) -> None:
    if sink is not None:
        sink(event)


def extract_video_id(text: str) -> str | None:
    """Pull the video id out of a URL, or return None for anything else."""
    text = text.strip()
    if not text:
        return None
    for pattern in _ID_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1)
    return None


def _flat_options() -> dict:
    return {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "skip_download": True,
        "extract_flat": "in_playlist",
        "ignoreerrors": True,
        "noplaylist": True,
        "logger": _QuietLogger(),
    }


def _keep(track: Track, min_duration: int, max_duration: int) -> bool:
    """Duration filter; videos without a known duration are always kept."""
    if track.duration is None:
        return True
    if min_duration and track.duration < min_duration:
        return False
    if max_duration and track.duration > max_duration:
        return False
    return True


def search_phrase(phrase: str, limit: int) -> list[Track]:
    """Run a single ``ytsearchN:`` query and return its entries as Tracks."""
    limit = max(1, min(limit, _MAX_PER_PHRASE))
    query = f"ytsearch{limit}:{phrase}"
    with yt_dlp.YoutubeDL(_flat_options()) as ydl:
        info = ydl.extract_info(query, download=False)

    tracks: list[Track] = []
    for entry in (info or {}).get("entries") or []:
        if not entry:
            continue
        track = Track.from_entry(entry)
        if track is not None:
            tracks.append(track)
    return tracks


def search_category(
    phrases: Sequence[str],
    target: int,
    min_duration: int = 0,
    max_duration: int = 0,
    on_event: EventSink = None,
    cancel: threading.Event | None = None,
) -> list[Track]:
    """Collect up to ``target`` unique tracks spread over ``phrases``.

    Each phrase gets a share of the target plus a buffer, because duplicates
    and filtered videos eat into the result. The loop stops early once the
    target is reached, so unused phrases simply cost nothing.
    """
    phrases = [p for p in phrases if p.strip()]
    if not phrases or target <= 0:
        return []

    per_phrase = max(10, math.ceil(target / len(phrases) * 1.6))
    found: list[Track] = []
    seen: set[str] = set()

    for index, phrase in enumerate(phrases, start=1):
        if cancel is not None and cancel.is_set():
            break
        if len(found) >= target:
            break

        try:
            results = search_phrase(phrase, per_phrase)
        except Exception as exc:  # network hiccup, extractor change, ...
            _emit(on_event, ProgressEvent(
                kind="log", message=f"Suche fehlgeschlagen für '{phrase}': {exc}"))
            results = []

        new = 0
        for track in results:
            if len(found) >= target:
                break
            if track.video_id in seen or not _keep(track, min_duration, max_duration):
                continue
            seen.add(track.video_id)
            found.append(track)
            new += 1

        _emit(on_event, ProgressEvent(
            kind="search_step",
            message=f"{phrase} (+{new})",
            current=index,
            total=len(phrases),
            percent=min(100.0, len(found) / target * 100),
            payload=len(found),
        ))

    return found


def resolve_urls(
    urls: Iterable[str],
    on_event: EventSink = None,
    cancel: threading.Event | None = None,
    workers: int = 4,
) -> list[Track]:
    """Turn a list of URLs into Tracks, fetching their titles in parallel.

    Used by the "load links from file" import. A URL whose title cannot be
    fetched still becomes a Track, so the download can be attempted anyway.
    """
    ids: list[str] = []
    seen: set[str] = set()
    for raw in urls:
        video_id = extract_video_id(raw)
        if video_id and video_id not in seen:
            seen.add(video_id)
            ids.append(video_id)

    if not ids:
        return []

    def fetch(video_id: str) -> Track:
        fallback = Track(video_id=video_id, title=f"(Titel unbekannt) {video_id}")
        if cancel is not None and cancel.is_set():
            return fallback
        try:
            with yt_dlp.YoutubeDL(_flat_options()) as ydl:
                info = ydl.extract_info(
                    f"https://www.youtube.com/watch?v={video_id}",
                    download=False,
                    process=False,
                )
            track = Track.from_entry(info or {})
            return track or fallback
        except Exception:
            return fallback

    tracks: list[Track] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for index, track in enumerate(pool.map(fetch, ids), start=1):
            tracks.append(track)
            _emit(on_event, ProgressEvent(
                kind="search_step",
                message=track.title,
                current=index,
                total=len(ids),
                percent=index / len(ids) * 100,
                payload=index,
            ))
    return tracks


def _cli() -> None:
    """Quick test without the GUI:  python -m ytmp3.search Techno 30"""
    import sys

    from .config import load_categories, load_settings

    # The Windows console defaults to cp1252 and chokes on emoji in titles.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    if len(sys.argv) < 2:
        print("Usage: python -m ytmp3.search <Kategorie|Suchbegriff> [Anzahl]")
        raise SystemExit(1)

    name = sys.argv[1]
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 25
    categories = load_categories()
    phrases = categories.get(name, [name])

    def show(event: ProgressEvent) -> None:
        if event.kind == "search_step":
            print(f"[{event.current}/{event.total}] {event.message} -> {event.payload} gesamt")
        else:
            print(event.message)

    settings = load_settings()
    tracks = search_category(
        phrases,
        count,
        min_duration=settings.min_duration,
        max_duration=settings.max_duration,
        on_event=show,
    )
    print(f"\n{len(tracks)} Treffer:\n")
    for track in tracks:
        print(f"{track.duration_text:>8}  {track.title}  [{track.uploader}]")


if __name__ == "__main__":
    _cli()

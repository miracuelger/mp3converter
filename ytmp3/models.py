"""Plain data containers.

This module knows nothing about yt-dlp or tkinter, so it can be imported
from anywhere without pulling in heavy dependencies.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any

BITRATES = ("128", "192", "256", "320")


def format_duration(seconds: int | float | None) -> str:
    """Return 3:42 / 1:04:11 for a duration in seconds."""
    if not seconds:
        return "-"
    total = int(seconds)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


@dataclass
class Track:
    """One YouTube video found by the search or imported from a file."""

    video_id: str
    title: str
    uploader: str = ""
    duration: int | None = None
    selected: bool = True

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.video_id}"

    @property
    def duration_text(self) -> str:
        return format_duration(self.duration)

    @classmethod
    def from_entry(cls, entry: dict[str, Any]) -> "Track | None":
        """Build a Track from a yt-dlp search/info entry, or None if unusable."""
        video_id = entry.get("id")
        if not video_id or len(video_id) != 11:
            # Playlists, channels and shorts collections have different ids.
            return None
        if entry.get("live_status") in {"is_live", "is_upcoming"} or entry.get("is_live"):
            # Radio streams never end and would block a download slot forever.
            return None
        title = entry.get("title") or video_id
        uploader = entry.get("uploader") or entry.get("channel") or ""
        duration = entry.get("duration")
        if isinstance(duration, float):
            duration = int(duration)
        return cls(video_id=video_id, title=title, uploader=uploader, duration=duration)


@dataclass
class AppSettings:
    """Everything the user can configure; persisted as config/settings.json."""

    output_dir: str = "mp3"
    bitrate: str = "192"
    target_count: int = 200
    min_duration: int = 60          # seconds; 0 disables the lower bound
    max_duration: int = 900         # seconds; 0 disables the upper bound
    concurrency: int = 2            # parallel downloads
    skip_existing: bool = True      # use a yt-dlp download archive
    embed_thumbnail: bool = True    # put the video thumbnail into the MP3 as cover art
    last_category: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppSettings":
        """Build settings from JSON, ignoring unknown keys and bad values.

        A hand-edited settings.json with e.g. ``"concurrency": "abc"`` must not
        crash the app later on, so every value is coerced to the type of the
        default and dropped if that fails.
        """
        defaults = cls()
        values: dict[str, Any] = {}
        for f in fields(cls):
            if f.name not in data:
                continue
            default = getattr(defaults, f.name)
            raw = data[f.name]
            try:
                if isinstance(default, bool):
                    value = raw if isinstance(raw, bool) else str(raw).lower() in {"1", "true", "yes"}
                elif isinstance(default, int):
                    value = int(raw)
                else:
                    value = str(raw)
            except (TypeError, ValueError):
                continue
            values[f.name] = value
        settings = cls(**values)
        if settings.bitrate not in BITRATES:
            settings.bitrate = defaults.bitrate
        return settings


@dataclass
class ProgressEvent:
    """The only language spoken between worker threads and the GUI.

    kind is one of:
      log            - a line for the log window
      search_step    - one search phrase finished (current/total/found)
      search_done    - payload holds the list[Track]
      file_start     - a download started (message=title, current/total)
      file_progress  - percent for the file named in message
      file_post      - ffmpeg conversion running for message
      file_done      - one file finished (current=done count, total)
      finished       - payload holds a DownloadSummary
      cancelled      - worker stopped on user request
      error          - unexpected worker crash (message holds the reason)
    """

    kind: str
    message: str = ""
    current: int = 0
    total: int = 0
    percent: float = 0.0
    payload: Any = field(default=None)


@dataclass
class DownloadSummary:
    ok: int = 0                     # new MP3 files created
    failed: int = 0
    already_downloaded: int = 0     # skipped because they are in the archive
    not_started: int = 0            # left over after the user cancelled
    failures: list[tuple[str, str]] = field(default_factory=list)

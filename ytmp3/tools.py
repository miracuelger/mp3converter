"""Locating the external programs yt-dlp needs.

Both are installed automatically from PyPI (see requirements.txt), so users
do not have to install anything by hand:

* FFmpeg converts the downloaded audio to MP3. A system-wide ``ffmpeg`` on the
  PATH is preferred (it usually ships with ``ffprobe``); otherwise the binary
  bundled with the ``imageio-ffmpeg`` package is used.
* A JavaScript runtime lets yt-dlp solve YouTube's player challenges. Without
  one, many videos only offer a few formats or fail entirely. ``deno`` from
  the PATH or from the ``deno`` PyPI package is used, plus ``node`` if present.
"""

from __future__ import annotations

import shutil
from functools import lru_cache


@lru_cache(maxsize=1)
def find_ffmpeg() -> str | None:
    """Path to an ffmpeg executable, or None if there is none at all."""
    path = shutil.which("ffmpeg")
    if path:
        return path
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001 - package missing or binary unavailable
        return None


@lru_cache(maxsize=1)
def find_js_runtimes() -> dict[str, dict]:
    """The ``js_runtimes`` option for yt-dlp, with explicit paths where known."""
    runtimes: dict[str, dict] = {}

    deno = shutil.which("deno")
    if not deno:
        try:
            from deno import find_deno_bin

            deno = find_deno_bin()
        except Exception:  # noqa: BLE001
            deno = None
    if deno:
        runtimes["deno"] = {"path": str(deno)}

    node = shutil.which("node")
    if node:
        runtimes["node"] = {"path": node}

    # Fall back to yt-dlp's own default so it can still report what's missing.
    return runtimes or {"deno": {}}


def has_js_runtime() -> bool:
    return any(cfg.get("path") for cfg in find_js_runtimes().values())


def base_options() -> dict:
    """yt-dlp options shared by searching and downloading."""
    options: dict = {"js_runtimes": find_js_runtimes()}
    ffmpeg = find_ffmpeg()
    if ffmpeg:
        options["ffmpeg_location"] = ffmpeg
    return options

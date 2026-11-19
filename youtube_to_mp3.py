"""Download every link in a text file without the GUI.

    python youtube_to_mp3.py            # reads urls.txt
    python youtube_to_mp3.py links.txt

Uses the same settings (folder, bitrate, archive) as the GUI. Kept for
people who used the original script; it calls ytmp3.downloader.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ytmp3.downloader import _cli  # noqa: E402

if __name__ == "__main__":
    _cli()

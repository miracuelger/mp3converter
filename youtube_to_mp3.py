import yt_dlp
from pathlib import Path

URL_FILE = Path("urls.txt")
OUTPUT_DIR = Path("mp3")

if not URL_FILE.exists():
    print("Error: urls.txt was not found.")
    input("Press Enter to exit...")
    raise SystemExit(1)

OUTPUT_DIR.mkdir(exist_ok=True)

# Read URLs from urls.txt
with URL_FILE.open("r", encoding="utf-8") as file:
    urls = [
        line.strip()
        for line in file
        if line.strip() and not line.strip().startswith("#")
    ]

if not urls:
    print("urls.txt is empty.")
    input("Press Enter to exit...")
    raise SystemExit(0)

options = {
    "format": "bestaudio/best",
    "outtmpl": str(OUTPUT_DIR / "%(title)s.%(ext)s"),
    "noplaylist": True,
    "ignoreerrors": True,
    "postprocessors": [
        {
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }
    ],
}

print(f"Found {len(urls)} URLs.")
print("Starting...\n")

with yt_dlp.YoutubeDL(options) as ydl:
    ydl.download(urls)

print("\nDone!")
print(f"MP3 files saved to: {OUTPUT_DIR.resolve()}")

input("Press Enter to exit...")
# YouTube to MP3 Converter

This script downloads audio from URLs and converts it to MP3 files using `yt-dlp` and FFmpeg.

## Requirements

- Python 3.10 or newer
- The Python library `yt-dlp`
- FFmpeg installed and available in your system `PATH`

Install the Python library with:

```powershell
python -m pip install yt-dlp
```

## Usage

1. Add one URL per line to `urls.txt`:

   ```text
   https://www.youtube.com/watch?v=example
   https://youtu.be/example
   ```

   Empty lines and lines beginning with `#` are ignored.

2. Open PowerShell in the project directory.

3. Run the script:

   ```powershell
   python .\youtube_to_mp3.py
   ```

The script downloads the best available audio, converts it to 192 kbps MP3, and saves the files in the `mp3` folder. Playlist downloads are disabled, so each URL is processed individually.

Run the script from the project directory because it uses the relative paths `urls.txt` and `mp3`.

## Notes

The program requires an internet connection. Download errors for individual URLs may be ignored by the script. Use the software only with content you are authorized to download, and follow applicable copyright laws and website terms.

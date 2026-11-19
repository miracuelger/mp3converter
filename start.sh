#!/bin/sh
# Start the YouTube to MP3 Downloader (Linux and macOS).
# The first start installs everything needed into the .venv folder.
cd "$(dirname "$0")" || exit 1

for candidate in python3.14 python3.13 python3.12 python3.11 python3.10 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 &&
        "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 10))' >/dev/null 2>&1; then
        "$candidate" run_gui.py "$@"
        status=$?
        if [ "$status" -ne 0 ] && [ -t 0 ]; then
            printf '\nSomething went wrong (see above). Press Enter to close. '
            read -r _
        fi
        exit "$status"
    fi
done

echo "Python 3.10 or newer was not found."
echo "Please install it from https://www.python.org/downloads/ and start again."
if [ "$(uname)" = "Darwin" ]; then
    open "https://www.python.org/downloads/macos/" 2>/dev/null
fi
if [ -t 0 ]; then
    printf 'Press Enter to close. '
    read -r _
fi
exit 1

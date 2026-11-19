#!/usr/bin/env python3
"""Start the YouTube to MP3 Downloader.

Usually started through start-windows.bat, start-macos.command or start.sh.

The first start sets everything up automatically: a private Python
environment is created in the .venv folder, and yt-dlp, FFmpeg and Deno are
installed into it. Nothing is installed system-wide, and deleting the
project folder removes everything. Later starts skip the setup and open the
app right away. yt-dlp is updated once a week, because YouTube changes often
break older versions.

Options:
  --update     update all components now instead of waiting a week
  --no-setup   run with the current Python as it is (for developers)
  --detach     on Windows: run the window without a console (used by the .bat)

This file must keep working on old Python versions long enough to print a
helpful message, so it only uses the standard library.
"""

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / ".venv"
REQUIREMENTS = ROOT / "requirements.txt"
STATE_FILE = VENV_DIR / "ytmp3-setup.json"
MIN_PYTHON = (3, 10)
UPDATE_INTERVAL = 7 * 24 * 3600  # seconds
REQUIRED = "yt-dlp"              # the app cannot run without it; the rest is optional
PYTHON_DOWNLOAD = "https://www.python.org/downloads/"


# --------------------------------------------------------------------------- output

def say(message=""):
    print(message, flush=True)


def fail(message):
    """Show an error in the console and, if possible, in a dialog, then exit."""
    print("\n" + message + "\n", file=sys.stderr, flush=True)
    try:
        import tkinter
        from tkinter import messagebox

        root = tkinter.Tk()
        root.withdraw()
        messagebox.showerror("YouTube to MP3 - setup", message)
        root.destroy()
    except Exception:  # noqa: BLE001 - no tkinter or no display
        pass
    sys.exit(1)


# --------------------------------------------------------------------------- checks

def check_python():
    if sys.version_info < MIN_PYTHON:
        fail(
            "Python {}.{} or newer is needed, but this is Python {}.{}.\n"
            "Please install a current version from {}".format(
                MIN_PYTHON[0], MIN_PYTHON[1],
                sys.version_info[0], sys.version_info[1], PYTHON_DOWNLOAD)
        )
    try:
        import tkinter  # noqa: F401
    except ImportError:
        if sys.platform.startswith("linux"):
            hint = ("Install it with your package manager, for example:\n"
                    "  Debian/Ubuntu:  sudo apt install python3-tk\n"
                    "  Fedora:         sudo dnf install python3-tkinter\n"
                    "  Arch:           sudo pacman -S tk")
        elif sys.platform == "darwin":
            hint = ("If you use Homebrew:  brew install python-tk\n"
                    "Or install Python from " + PYTHON_DOWNLOAD)
        else:
            hint = ("Run the Python installer again and make sure "
                    "'tcl/tk and IDLE' is ticked.")
        fail("Python's window toolkit (tkinter) is missing.\n\n" + hint)


def in_project_venv():
    try:
        return Path(sys.prefix).resolve() == VENV_DIR.resolve()
    except OSError:
        return False


def venv_python(windowed=False):
    if os.name == "nt":
        return VENV_DIR / "Scripts" / ("pythonw.exe" if windowed else "python.exe")
    return VENV_DIR / "bin" / "python"


def venv_works():
    python = venv_python()
    if not python.exists():
        return False
    try:
        result = subprocess.run([str(python), "-c", "import sys"],
                                capture_output=True, timeout=60)
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


# --------------------------------------------------------------------------- setup

def requirements_hash():
    data = REQUIREMENTS.read_bytes() if REQUIREMENTS.exists() else b""
    return hashlib.sha256(data).hexdigest()


def requirement_lines():
    if not REQUIREMENTS.exists():
        return [REQUIRED]
    lines = []
    for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            lines.append(line)
    return lines


def load_state():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(state):
    try:
        STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except OSError:
        pass


def pip(*args, quiet=False):
    command = [str(venv_python()), "-m", "pip", "install",
               "--disable-pip-version-check", "--no-input"]
    if quiet:
        command.append("--quiet")
    command.extend(args)
    try:
        return subprocess.call(command) == 0
    except OSError:
        return False


def create_venv():
    say("Creating a private Python environment in the .venv folder...")
    import venv

    try:
        venv.EnvBuilder(with_pip=True, clear=VENV_DIR.exists()).create(str(VENV_DIR))
    except Exception as exc:  # noqa: BLE001
        hint = ""
        if sys.platform.startswith("linux"):
            hint = ("\n\nOn Debian/Ubuntu the venv module is a separate package:\n"
                    "  sudo apt install python3-venv")
        fail("Could not create the Python environment: {}{}".format(exc, hint))


def install(upgrade):
    """Install requirements.txt; a failing optional package is not fatal."""
    flags = ["--upgrade"] if upgrade else []
    if pip(*flags, "-r", str(REQUIREMENTS)):
        return True

    # Most likely an optional package has no build for this computer.
    # Install one by one so the rest still works.
    say("\nInstalling the components one by one...")
    ok = True
    for requirement in requirement_lines():
        if pip(*flags, requirement):
            continue
        if requirement.lower().startswith(REQUIRED):
            ok = False
        else:
            say("Optional component '{}' could not be installed - "
                "continuing without it.".format(requirement))
    return ok


def setup(force_update=False):
    first_run = not venv_works()
    if first_run:
        say("=" * 64)
        say(" First start: setting up the YouTube to MP3 Downloader.")
        say(" This needs an internet connection and takes about a minute.")
        say("=" * 64)
        create_venv()

    state = load_state()
    now = time.time()
    needs_install = first_run or state.get("requirements") != requirements_hash()
    needs_update = force_update or now - state.get("updated", 0) > UPDATE_INTERVAL

    if needs_install:
        say("Installing yt-dlp, FFmpeg and Deno...")
        if not install(upgrade=not first_run):
            fail("Installing the required components failed.\n"
                 "Please check your internet connection and start again.\n\n"
                 "Technical details are shown in the console window.")
        state = {"requirements": requirements_hash(), "updated": now}
        save_state(state)
        say("Setup finished.\n")
    elif needs_update:
        say("Checking for updates (once a week)...")
        if install(upgrade=True):
            state["updated"] = now
            save_state(state)
        else:
            say("Update skipped (offline?). The app works with the installed version.")


def launch(detach):
    if os.name == "nt" and detach and venv_python(windowed=True).exists():
        # Start without a console window and let the console of the .bat close.
        flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        subprocess.Popen(
            [str(venv_python(windowed=True)), str(ROOT / "run_gui.py"), "--no-setup"],
            cwd=str(ROOT), creationflags=flags, close_fds=True)
        return 0
    return subprocess.call([str(venv_python()), str(ROOT / "run_gui.py"), "--no-setup"],
                           cwd=str(ROOT))


# --------------------------------------------------------------------------- app

def run_app():
    sys.path.insert(0, str(ROOT))
    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        fail("yt-dlp is not installed for this Python.\n\n"
             "Start the app with the start script (or 'python run_gui.py' "
             "without --no-setup) to set everything up automatically.")
    from ytmp3.gui.app import main

    main()


def main():
    args = sys.argv[1:]
    if "--no-setup" in args or in_project_venv():
        check_python()
        run_app()
        return
    check_python()
    setup(force_update="--update" in args)
    sys.exit(launch(detach="--detach" in args))


if __name__ == "__main__":
    main()

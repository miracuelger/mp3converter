"""Entry point for the GUI:  python run_gui.py"""

import sys
from pathlib import Path

# Allows starting the script from any working directory.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ytmp3.gui.app import main  # noqa: E402

if __name__ == "__main__":
    main()

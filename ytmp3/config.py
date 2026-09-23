"""Loading and saving of settings and categories.

Both files live in config/ next to the project root and are plain JSON, so
they can be edited by hand as well as through the GUI.
"""

from __future__ import annotations

import json
from pathlib import Path

from .models import AppSettings

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
LOG_DIR = ROOT / "logs"
CATEGORIES_FILE = CONFIG_DIR / "categories.json"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
FAILED_LOG = LOG_DIR / "failed.log"

# Category -> search phrases. More phrases means more unique hits, which is
# what makes 300-500 links per category possible without duplicates.
DEFAULT_CATEGORIES: dict[str, list[str]] = {
    "Pop": [
        "pop hits 2025", "top pop songs", "pop music playlist", "best pop songs 2024",
        "pop charts", "deutsche pop songs", "pop remix", "radio pop hits",
        "pop anthems", "female pop singers hits",
    ],
    "Party": [
        "party hits", "party mix 2025", "partyschlager", "party anthems",
        "mallorca party hits", "club party mix", "party remix 2024",
        "apres ski hits", "party classics", "feiern songs",
    ],
    "Disco": [
        "disco classics", "70s disco hits", "80s disco", "italo disco",
        "disco funk", "nu disco mix", "disco remix", "boney m songs",
        "studio 54 disco", "disco dance hits",
    ],
    "Techno": [
        "techno 2025", "hard techno set", "melodic techno", "techno remix",
        "techno anthems", "minimal techno", "berlin techno", "acid techno",
        "techno festival", "techno hits 2024",
    ],
    "House": [
        "house music 2025", "deep house mix", "tech house", "future house",
        "house classics", "afro house", "melodic house", "house remix 2024",
    ],
    "Turkish": [
        "türkçe pop", "türkçe hit şarkılar", "turkish pop 2025", "türkçe rap",
        "türkçe slow şarkılar", "türkçe pop remix", "halay oyun havası",
        "türkçe hit 2024", "turkish dance music", "türkçe akustik",
    ],
    "Arabesque": [
        "arabesk şarkılar", "arabesk mix", "müslüm gürses", "orhan gencebay",
        "ibrahim tatlıses", "arabesk rap", "damar arabesk", "arabesk 2025",
        "arabesk slow", "ferdi tayfur",
    ],
    "Arabic": [
        "arabic pop songs", "aghani arabiya", "arabic dance music",
        "khaleeji songs", "arabic remix 2025", "amr diab", "arabic hits 2024",
    ],
    "Balkan": [
        "balkan hits", "narodna muzika", "balkan party mix", "serbian hits",
        "turbo folk", "balkan remix 2025", "bosanske pjesme",
    ],
    "Rap / HipHop": [
        "deutschrap 2025", "rap hits", "hip hop playlist", "german rap charts",
        "trap music 2025", "rap remix", "old school hip hop", "deutschrap charts 2024",
    ],
    "80s / 90s": [
        "80s hits", "90s dance hits", "eurodance 90s", "80er hits deutsch",
        "90s pop hits", "eurodance classics", "90s club hits",
    ],
    "Charts": [
        "top charts 2025", "aktuelle charts", "billboard hot 100 songs",
        "charts 2024 hits", "radio charts", "top 50 songs",
    ],
    "Schlager": [
        "schlager hits", "schlager 2025", "schlager party", "helene fischer",
        "discofox schlager", "schlager classics",
    ],
    "Rock": [
        "rock classics", "rock hits 2025", "classic rock songs",
        "deutsche rockmusik", "rock anthems", "alternative rock hits",
    ],
}


def ensure_dirs() -> None:
    CONFIG_DIR.mkdir(exist_ok=True)
    LOG_DIR.mkdir(exist_ok=True)


# --------------------------------------------------------------------------- categories

def load_categories() -> dict[str, list[str]]:
    """Read categories.json, creating it with the defaults when missing."""
    ensure_dirs()
    if not CATEGORIES_FILE.exists():
        save_categories(DEFAULT_CATEGORIES)
        return dict(DEFAULT_CATEGORIES)
    try:
        data = json.loads(CATEGORIES_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULT_CATEGORIES)

    categories: dict[str, list[str]] = {}
    if isinstance(data, dict):
        for name, phrases in data.items():
            if isinstance(phrases, list):
                cleaned = [str(p).strip() for p in phrases if str(p).strip()]
                if cleaned:
                    categories[str(name)] = cleaned
    return categories or dict(DEFAULT_CATEGORIES)


def save_categories(categories: dict[str, list[str]]) -> None:
    ensure_dirs()
    CATEGORIES_FILE.write_text(
        json.dumps(categories, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


# --------------------------------------------------------------------------- settings

def load_settings() -> AppSettings:
    ensure_dirs()
    settings = AppSettings()
    if SETTINGS_FILE.exists():
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                settings = AppSettings.from_dict(data)
        except (OSError, json.JSONDecodeError, TypeError):
            settings = AppSettings()
    settings.output_dir = str(resolve_output_dir(settings.output_dir))
    return settings


def save_settings(settings: AppSettings) -> None:
    ensure_dirs()
    SETTINGS_FILE.write_text(
        json.dumps(settings.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def resolve_output_dir(value: str) -> Path:
    """Relative output paths are relative to the project root, not the cwd."""
    path = Path(value or "mp3")
    return path if path.is_absolute() else (ROOT / path)

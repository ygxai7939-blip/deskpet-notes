# Modified for DeskPet Notes.
import json
from pathlib import Path

_DEFAULTS: dict = {
    "pet_path":          None,
    "pet_scale":         0.5,
    "movement_enabled":  False,
    "personality_style": "friendly",
}


def load(path: Path) -> dict:
    """Return persisted settings merged over defaults."""
    try:
        with path.open(encoding="utf-8") as file:
            return {**_DEFAULTS, **json.load(file)}
    except (OSError, RecursionError, TypeError, ValueError):
        return dict(_DEFAULTS)


def save(path: Path, data: dict) -> None:
    """Persist settings when the local directory is writable."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as file:
            json.dump(data, file, indent=2)
    except OSError:
        pass

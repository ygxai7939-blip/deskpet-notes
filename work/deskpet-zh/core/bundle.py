# Modified for DeskPet Notes.
import json
import os
from pathlib import Path
import zipfile

from PIL import Image
from pet_packages import read_package
from .constants import TILE_W, TILE_H

CHARACTER_LOAD_ERRORS = (OSError, ValueError, zipfile.BadZipFile, KeyError, TypeError, AttributeError,
                         Image.DecompressionBombError)


def list_pets(folder: Path) -> list[Path]:
    """Return the installed character bundles in the app's library."""
    return sorted(path for path in folder.glob("*-pet.zip") if path.is_file())


def pet_display_name(zip_path: str) -> str:
    """Read the displayName from pet.json inside the bundle, fall back to filename."""
    try:
        with zipfile.ZipFile(zip_path) as z:
            entry = next(
                n for n in z.namelist()
                if os.path.basename(n) == "pet.json" and "__MACOSX" not in n
            )
            meta = json.loads(z.read(entry))
            return meta.get("displayName") or _stem(zip_path)
    except Exception:
        return _stem(zip_path)


def _stem(zip_path: str) -> str:
    name = os.path.basename(zip_path)
    idx  = name.lower().rfind("-pet.zip")
    if idx > 0:
        stem = name[:idx]
        dot  = stem.rfind(".")
        return stem[:dot] if dot > 0 else stem
    return name.removesuffix(".zip")


def load_pet_pil(zip_path: Path, scale: float) -> tuple[str, list[list[Image.Image]], dict, tuple[int, int]]:
    """Load the same validated clips used in the import and preview dialogs."""
    pack = read_package(zip_path)
    # Keep source pixels up to 2× the logical size for high-DPI monitors.
    width, height = pack.cell_size
    size = (min(width, round(TILE_W * scale * 2)), min(height, round(TILE_H * scale * 2)))
    frames: list[list[Image.Image]] = [[] for _ in pack.animations]
    for action, (row, _count, _fps) in pack.animations.items():
        frames[row] = [tile.resize(size, Image.LANCZOS) if tile.size != size else tile
                       for tile in pack.action_frames(action)]
    return pack.name, frames, pack.animations, (pack.lifted_loop_start, pack.early_landing_frame)

"""Prepare the example toolkit and the files shipped alongside the application."""
from argparse import ArgumentParser
from io import BytesIO
import json
from pathlib import Path
from shutil import copyfile
import sys
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
WORK = ROOT.parent
PROJECT = WORK.parent
OUTPUTS = PROJECT / "outputs"
LICENSE_FILES = (PROJECT / "LICENSE", PROJECT / "NOTICE", PROJECT / "LICENSE-APACHE-2.0.txt")
APP = WORK / "deskpet-live"
PET = WORK / "deskpet-zh"
sys.path.insert(0, str(APP))
from app_version import APP_VERSION
from pet_packages import read_package


def make_toolkit():
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    sheet = Image.new("RGBA", (1536, 1872))
    draw = ImageDraw.Draw(sheet)
    for row in range(9):
        for column, lift in enumerate((0, 5, 8, 5)):
            x = column * 192 + (column * (3 if row == 1 else -3 if row == 2 else 0))
            y = row * 208 - lift * (3 if row == 4 else 1)
            draw.rounded_rectangle((x + 45, y + 63, x + 147, y + 165), radius=31,
                                   fill="#777777", outline="#e0e0e0", width=4)
            draw.rounded_rectangle((x + 70, y + 102, x + 122, y + 124), radius=5, fill="#eeeeee")
    atlas = BytesIO()
    sheet.save(atlas, "WEBP", lossless=True)
    example = ROOT / "example.codex-pet.zip"
    with ZipFile(example, "w", ZIP_DEFLATED) as zip_file:
        zip_file.writestr(ZipInfo("pet.json"), json.dumps({
            "id": "atlas-example",
            "displayName": "格式示例",
            "description": "角色制作工具包内附的灰色几何素材",
            "spritesheetPath": "spritesheet.webp",
        }, ensure_ascii=False), compress_type=ZIP_DEFLATED)
        zip_file.writestr(ZipInfo("spritesheet.webp"), atlas.getvalue(), compress_type=ZIP_DEFLATED)
    assert len(read_package(example).idle_frames) == 4

    toolkit = OUTPUTS / "角色制作工具包.zip"
    with ZipFile(toolkit, "w", ZIP_DEFLATED) as zip_file:
        for path in (*LICENSE_FILES, ROOT / "小宠物制作指令.md", ROOT / "角色制作说明.md",
                     ROOT / "pack_character.py", APP / "pet_packages.py", example):
            zip_file.write(path, path.name)
        zip_file.writestr("requirements.txt", "Pillow==13.0.0\n")
    return toolkit


def stage(toolkit, dist):
    internal = dist / "_internal"
    if not (dist / "DeskPetNotes.exe").is_file() or not internal.is_dir():
        raise FileNotFoundError("The Windows application build is not ready.")
    # Qt on Windows imports the unversioned system ICU ABI. PyInstaller can
    # pick up an unrelated ICU build with suffixed exports from the host.
    for filename in ("icuuc.dll", "icudt78.dll"):
        (internal / filename).unlink(missing_ok=True)
    copyfile(toolkit, internal / toolkit.name)
    notices = dist / "licenses"
    notices.mkdir(exist_ok=True)
    license_file, notice_file, previous_license = LICENSE_FILES
    terms = notice_file.read_text(encoding="utf-8").rstrip() + "\n\n" + license_file.read_text(encoding="utf-8")
    (notices / "DeskPetNotes-LICENSE.txt").write_text(terms, encoding="utf-8")

    env = Path(sys.prefix) / "Lib" / "site-packages"
    for src, name in (
        (previous_license, previous_license.name),
        (PET / "LICENSE", "DeskPet-Apache-2.0.txt"),
        (PET / "NOTICE", "DeskPet-NOTICE.txt"),
        (APP / "DeskStickyNotes-MIT.txt", "DeskStickyNotes-MIT.txt"),
        (ROOT / "Inno-Translation-MIT.txt", "Inno-Translation-MIT.txt"),
        (ROOT / "LGPL-3.0.txt", "LGPL-3.0.txt"),
        (ROOT / "GPL-3.0.txt", "GPL-3.0.txt"),
        (ROOT / "第三方许可.md", "第三方许可.md"),
        (Path(sys.base_prefix) / "LICENSE.txt", "Python-LICENSE.txt"),
        (env / "pillow-13.0.0.dist-info" / "licenses" / "LICENSE", "Pillow-LICENSE.txt"),
    ):
        copyfile(src, notices / name)

    app_sources = ("app_version.py", "desk_style.py", "desk_workspace.py", "edge_drag.py", "edge_notes.py",
                   "file_picker.py", "open_preview.pyw", "paper_feed.py", "pet_packages.py", "pixel_snow.py",
                   "sticky_store.py", "sticky_window.py", "verify_notes.py", "workspace_style.py",
                   "DeskStickyNotes-MIT.txt")
    pet_sources = ("LICENSE", "NOTICE", "core/__init__.py", "core/bundle.py", "core/constants.py",
                   "core/settings.py", "core/state.py", "platforms/windows/desktop_pet.py")
    release_sources = ("DeskPetNotes.iss", "DeskPetNotes.spec", "prepare_assets.py", "pack_character.py",
                       "小宠物制作指令.md", "角色制作说明.md", "第三方许可.md", "LGPL-3.0.txt", "GPL-3.0.txt",
                       "ChineseSimplified.isl", "Inno-Translation-MIT.txt", "example.codex-pet.zip")
    with ZipFile(notices / f"DeskPetNotes-{APP_VERSION}-source.zip", "w", ZIP_DEFLATED) as zip_file:
        for path in (*LICENSE_FILES, PROJECT / "README.md", PROJECT / "requirements.txt"):
            zip_file.write(path, path.name)
        for folder, names in ((APP, app_sources), (PET, pet_sources), (ROOT, release_sources)):
            for name in names:
                path = folder / name
                zip_file.write(path, path.relative_to(PROJECT).as_posix())


if __name__ == "__main__":
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--kit-only", action="store_true")
    parser.add_argument("--dist", type=Path, default=ROOT / "dist" / "DeskPetNotes")
    options = parser.parse_args()
    toolkit = make_toolkit()
    if not options.kit_only:
        stage(toolkit, options.dist)

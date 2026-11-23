"""Read data-only character ZIPs and normalize their atlases for DeskPet."""
from dataclasses import dataclass, replace
from io import BytesIO
from itertools import count
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
from tempfile import NamedTemporaryFile
from zipfile import BadZipFile, ZipFile

from PIL import Image, UnidentifiedImageError


CELL_WIDTH = 192
CELL_HEIGHT = 208
CLASSIC_SIZE = (1536, 1872)
EXTENDED_SIZE = (1536, 2288)
MAX_PACKAGE = 24 * 1024 * 1024
MAX_METADATA = 65536
SAFE_COMPONENT = re.compile(r"[\w-][\w.-]{0,79}\Z")
SAFE_ID = re.compile(r"[a-z][a-z0-9_-]{0,47}\Z")
RESERVED_IDS = {"aux", "con", "nul", "prn", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


def require(condition, message):
    if not condition:
        raise ValueError(message)


@dataclass
class CharacterPackage:
    pet_id: str
    name: str
    description: str
    atlas: Image.Image
    idle_frames: tuple[Image.Image, ...]

    def target(self, folder):
        return folder / f"{self.pet_id}.codex-pet.zip"

    def as_new(self, folder):
        for index in count(2):
            suffix = f"-{index}"
            candidate = replace(self, pet_id=self.pet_id[:48 - len(suffix)] + suffix)
            if not candidate.target(folder).exists():
                return candidate

    def install(self, folder):
        """Write an atomic two-file ZIP consumed by the upstream renderer."""
        folder.mkdir(parents=True, exist_ok=True)
        destination = self.target(folder)
        meta = {"id": self.pet_id, "displayName": self.name, "description": self.description,
                "spritesheetPath": "spritesheet.webp"}
        image = BytesIO()
        self.atlas.save(image, format="WEBP", lossless=True)
        temp = None
        try:
            with NamedTemporaryFile(prefix=".pet-", suffix=".zip", dir=folder, delete=False) as file:
                temp = Path(file.name)
                with ZipFile(file, "w") as archive:
                    archive.writestr("pet.json", json.dumps(meta, indent=2))
                    archive.writestr("spritesheet.webp", image.getvalue())
                file.flush()
                os.fsync(file.fileno())
            os.replace(temp, destination)
        finally:
            if temp is not None:
                temp.unlink(missing_ok=True)
        return destination


def read_zip(source):
    with Path(source).open("rb") as stream:
        raw = stream.read(MAX_PACKAGE + 1)
    require(len(raw) <= MAX_PACKAGE, "角色包最大为 24 MiB。")
    with ZipFile(BytesIO(raw)) as archive:
        entries = archive.infolist()
        require(2 <= len(entries) <= 8, "请把 pet.json 和一张透明图集合成 ZIP。")
        total = 0
        files = {}
        seen = set()
        for entry in entries:
            path = entry.orig_filename
            parts = path.rstrip("/").split("/")
            require(len(parts) in (1, 2) and all(SAFE_COMPONENT.fullmatch(part) for part in parts),
                    "角色包中有无效的文件路径。请将素材放在同一层目录。")
            require(path not in seen and not entry.flag_bits & 1 and not stat.S_ISLNK(entry.external_attr >> 16),
                    "角色包中有重复、加密或非普通文件。")
            seen.add(path)
            if entry.is_dir():
                require(entry.file_size == 0, "ZIP 目录格式有误。")
                continue
            total += entry.file_size
            require(total <= MAX_PACKAGE, "角色包解压后超过 24 MiB。")
            limit = MAX_METADATA if parts[-1] == "pet.json" else MAX_PACKAGE
            require(entry.file_size <= limit, f"文件过大 · {parts[-1]}")
            with archive.open(entry) as stream:
                data = stream.read(entry.file_size + 1)
            require(len(data) == entry.file_size, f"文件已损坏 · {parts[-1]}")
            files[path] = data
    return files


def single_line(value, label, limit, mandatory=False):
    require(isinstance(value, str) and (not mandatory or value.strip()) and
            len(value) <= limit and all(ord(char) >= 32 and not 0xD800 <= ord(char) <= 0xDFFF for char in value),
            f"pet.json 的 {label} 需要是长度不超过 {limit} 的单行文字。")
    return value.strip()


def read_package(source):
    try:
        files = read_zip(source)
        manifests = [name for name in files if PurePosixPath(name).name == "pet.json"]
        require(len(manifests) == 1, "角色包中需要一份 pet.json。")
        manifest = manifests[0]
        try:
            metadata = json.loads(files[manifest].decode("utf-8-sig"))
        except json.JSONDecodeError as exc:
            raise ValueError("pet.json 不是有效的 JSON。") from exc
        require(isinstance(metadata, dict), "pet.json 应是一个 JSON 对象。")
        key = metadata.get("id")
        require(isinstance(key, str) and SAFE_ID.fullmatch(key) and key not in RESERVED_IDS,
                "pet.json 的 id 请使用小写英文字母、数字、连字符或下划线，并以字母开头。")
        name = single_line(metadata.get("displayName"), "displayName", 40, mandatory=True)
        description = single_line(metadata.get("description", ""), "description", 160)
        filename = metadata.get("spritesheetPath", "spritesheet.webp")
        require(isinstance(filename, str) and SAFE_COMPONENT.fullmatch(filename)
                and filename.lower().endswith((".png", ".webp")),
                "spritesheetPath 应指向与 pet.json 同目录的 PNG 或 WebP。")
        image_path = manifest[:-len("pet.json")] + filename
        require(files.keys() == {manifest, image_path},
                "ZIP 应包含同一目录下的 pet.json 和它声明的图集。")
        with Image.open(BytesIO(files[image_path]), formats=("PNG", "WEBP")) as source_image:
            require(source_image.size in (CLASSIC_SIZE, EXTENDED_SIZE)
                    and getattr(source_image, "n_frames", 1) == 1,
                    "请使用 1536 × 1872 或 1536 × 2288 像素的单张图集。")
            sheet = source_image.convert("RGBA").crop((0, 0, *CLASSIC_SIZE))
        lo, hi = sheet.getchannel("A").getextrema()
        require(lo == 0 and hi > 10, "图集需要透明背景和可见的角色。")
        for row in range(9):
            first = sheet.crop((0, row * CELL_HEIGHT, CELL_WIDTH, (row + 1) * CELL_HEIGHT))
            require(first.getchannel("A").getextrema()[1] > 10, f"第 {row+1} 行缺少首帧。")
        idle = []
        for column in range(8):
            frame = sheet.crop((column * CELL_WIDTH, 0, (column + 1) * CELL_WIDTH, CELL_HEIGHT))
            if frame.getchannel("A").getextrema()[1] <= 10:
                break
            idle.append(frame)
        return CharacterPackage(key, name, description, sheet, tuple(idle))
    except (OSError, BadZipFile, UnicodeError, RuntimeError, RecursionError, NotImplementedError,
            Image.DecompressionBombError, UnidentifiedImageError) as exc:
        raise ValueError("角色 ZIP 或图集无法读取。") from exc

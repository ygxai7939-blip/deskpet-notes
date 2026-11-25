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


STANDARD_CELL = (192, 208)
HD_CELL = (384, 416)
LEGACY_ACTIONS = {
    "idle": (0, 6), "run_right": (1, 10), "run_left": (2, 10),
    "waving": (3, 8), "jumping": (4, 10), "failed": (5, 3),
    "waiting": (6, 10), "running": (7, 6), "review": (8, 8),
}
EXTRA_ACTIONS = (
    "petting", "lifted", "landing", "sleeping", "waking",
    "stretching", "celebrate", "feed_open", "feed_ready",
)
MAX_COLUMNS = 16
MAX_PIXELS = 24_000_000
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
    cell_size: tuple[int, int]
    animations: dict[str, tuple[int, int, int]]
    schema_version: int = 1

    @property
    def idle_frames(self):
        return self.action_frames("idle")

    def action_frames(self, action):
        row, frames, _fps = self.animations[action]
        width, height = self.cell_size
        y = row * height
        return tuple(self.atlas.crop((x, y, x + width, y + height))
                     for x in range(0, frames * width, width))

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
        if self.schema_version == 2:
            meta.update(schemaVersion=2, frameSize=self.cell_size,
                        actions={action: {"row": row, "frames": frames, "fps": fps}
                                 for action, (row, frames, fps) in self.animations.items()})
        image = BytesIO()
        self.atlas.save(image, format="WEBP", lossless=True)
        temp = None
        try:
            with NamedTemporaryFile(prefix=".pet-", suffix=".zip", dir=folder, delete=False) as file:
                temp = Path(file.name)
                with ZipFile(file, "w") as archive:
                    archive.writestr("pet.json", json.dumps(meta, indent=2))
                    archive.writestr("spritesheet.webp", image.getvalue())
                require(file.tell() <= MAX_PACKAGE, "安装后的角色包超过 24 MiB。请压缩图集或减少空白格。")
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


def legacy_atlas(source):
    width, height = STANDARD_CELL
    classic_size = (8 * width, len(LEGACY_ACTIONS) * height)
    require(source.size in (classic_size, (8 * width, 11 * height)),
            "旧格式需要 1536 × 1872 或 1536 × 2288 像素的图集。")
    sheet = source.convert("RGBA").crop((0, 0, *classic_size))
    alpha = sheet.getchannel("A")
    actions = {}
    for action, (row, fps) in LEGACY_ACTIONS.items():
        top = row * height
        frames = 0
        for x in range(0, sheet.width, width):
            if alpha.crop((x, top, x + width, top + height)).getextrema()[1] <= 10:
                break
            frames += 1
        require(frames > 0, f"第 {row + 1} 行缺少首帧。")
        actions[action] = (row, frames, fps)
    return sheet, STANDARD_CELL, actions


def extended_atlas(source, metadata):
    size = metadata.get("frameSize")
    require(isinstance(size, list) and all(type(value) is int for value in size)
            and tuple(size) in (STANDARD_CELL, HD_CELL),
            "frameSize 需要是 [192, 208] 或 [384, 416]。")
    width, height = size
    columns, x_remainder = divmod(source.width, width)
    rows, y_remainder = divmod(source.height, height)
    require(not x_remainder and not y_remainder and 1 <= columns <= MAX_COLUMNS
            and source.width * source.height <= MAX_PIXELS,
            "图集须按整格排列，最多 16 列、2400 万像素。")
    clips = metadata.get("actions")
    require(isinstance(clips, dict) and LEGACY_ACTIONS.keys() <= clips.keys()
            and clips.keys() <= {*LEGACY_ACTIONS, *EXTRA_ACTIONS},
            "actions 需要九个基础动作，也可声明支持的扩展动作。")
    actions = {}
    for name, clip in clips.items():
        require(isinstance(clip, dict), f"{name} 的动作配置应包含 row、frames、fps。")
        row, frames, fps = (clip.get(key) for key in ("row", "frames", "fps"))
        require(type(row) is int and 0 <= row < rows and type(frames) is int and 1 <= frames <= columns
                and type(fps) is int and 1 <= fps <= 24,
                f"{name} 的行号、帧数或帧率超出范围。")
        actions[name] = row, frames, fps
    require(actions["idle"][0] == 0
            and sorted(row for row, _frames, _fps in actions.values()) == list(range(rows)),
            "图集每行需对应一个动作，且待机位于第 0 行。")
    sheet = source.convert("RGBA")
    alpha = sheet.getchannel("A")
    for name, (row, frames, _fps) in actions.items():
        top = row * height
        for col in range(columns):
            x = col * width
            hi = alpha.crop((x, top, x + width, top + height)).getextrema()[1]
            require(hi > 10 if col < frames else hi == 0, f"{name} 的第 {col + 1} 格与声明的帧数不符。")
    return sheet, (width, height), actions


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
        version = metadata.get("schemaVersion", 1)
        require(type(version) is int and version in (1, 2), "角色包格式版本不受支持。")
        with Image.open(BytesIO(files[image_path]), formats=("PNG", "WEBP")) as source_image:
            require(getattr(source_image, "n_frames", 1) == 1, "请使用单张静态图集。")
            sheet, cell, animations = (extended_atlas(source_image, metadata) if version == 2
                                       else legacy_atlas(source_image))
        lo, hi = sheet.getchannel("A").getextrema()
        require(lo == 0 and hi > 10, "图集需要透明背景和可见的角色。")
        return CharacterPackage(key, name, description, sheet, cell, animations, version)
    except (OSError, BadZipFile, UnicodeError, RuntimeError, RecursionError, NotImplementedError,
            Image.DecompressionBombError, UnidentifiedImageError) as exc:
        raise ValueError("角色 ZIP 或图集无法读取。") from exc

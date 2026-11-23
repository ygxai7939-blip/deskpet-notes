"""Portable, data-only DeskPet Notes backups and recoverable local restores."""
from dataclasses import asdict, dataclass
from datetime import datetime
import json
import os
from pathlib import Path
from shutil import copyfileobj, rmtree
import stat
from tempfile import NamedTemporaryFile, TemporaryDirectory, mkdtemp
from zipfile import BadZipFile, ZIP_DEFLATED, ZIP_STORED, ZipFile
from zlib import error as CompressionError

from pet_packages import MAX_PACKAGE, SAFE_COMPONENT, read_package
from sticky_store import Note, NoteStore


FORMAT = "deskpet-notes-backup"
MANIFEST = "manifest.json"
NOTES = "settings/notes.json"
SETTINGS = "settings/settings.json"
MANAGED = ("library", NOTES, SETTINGS)
JSON_LIMITS = {MANIFEST: 64 * 1024, NOTES: 64 * 1024**2, SETTINGS: 1024**2}
TOTAL_LIMIT = 512 * 1024**2
ENTRY_LIMIT = 4096
PENDING = ".restore-pending"


class RestorePendingError(OSError):
    """The transaction needs recovery before the application may write again."""


@dataclass
class StagedBackup:
    root: Path
    created_at: datetime
    records: dict
    preferences: dict
    roles: tuple[str, ...]
    active: str | None

    @property
    def selected(self):
        return self.active or (self.roles[0] if self.roles else None)


def backup_filename(prefix="桌宠便签-备份", *, unique=False):
    date = datetime.now()
    name = f"{prefix}-{date:%Y-%m-%d_%H%M%S}"
    return f"{name}-{date.microsecond:06d}.zip" if unique else f"{name}.zip"


def role_filename(name):
    return (
        name.endswith("-pet.zip")
        and SAFE_COMPONENT.fullmatch(name) is not None
        and not Path(name).is_reserved()
    )


def portable_preferences(data):
    if not isinstance(data, dict):
        raise ValueError("备份中的设置格式不正确。")
    scale = data.get("pet_scale")
    personality = data.get("personality_style")
    layout = data.get("note_edge_layout")
    return {
        "pet_scale": scale if type(scale) in (int, float) and .1 <= scale <= 2 else .5,
        "movement_enabled": data.get("movement_enabled") is True,
        "personality_style": personality if personality in ("friendly", "focused", "playful") else "friendly",
        "note_edge_layout": layout if isinstance(layout, dict) else {},
    }


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2).encode("utf-8")


def write_backup(destination, records, preferences, roles, active):
    roles = sorted(roles)
    manifest = {
        "format": FORMAT, "version": 1, "createdAt": datetime.now().astimezone().isoformat(),
        "activeCharacter": active.name if active in roles else None,
    }
    payload = {
        MANIFEST: json_bytes(manifest),
        NOTES: json_bytes([asdict(note) for note in records.values()]),
        SETTINGS: json_bytes(portable_preferences(preferences)),
    }
    if len(roles) + len(payload) > ENTRY_LIMIT or any(len(data) > JSON_LIMITS[name] for name, data in payload.items()):
        raise ValueError("备份数据超出支持的大小。")
    total = sum(map(len, payload.values()))
    for path in roles:
        size = path.stat().st_size
        if not role_filename(path.name) or size > MAX_PACKAGE:
            raise ValueError(f"角色文件无法备份：{path.name}")
        total += size
        if total > TOTAL_LIMIT:
            raise ValueError("备份最多支持 512 MiB 的数据。")
        try:
            read_package(path)
        except ValueError as error:
            raise ValueError(f"角色「{path.name}」无法备份。{error}") from error

    temporary = None
    try:
        with NamedTemporaryFile(dir=destination.parent, prefix=".backup-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
                for name, data in payload.items():
                    archive.writestr(name, data)
                for path in roles:
                    archive.write(path, f"library/{path.name}", compress_type=ZIP_STORED)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def read_snapshot(source, root):
    if source.stat().st_size > TOTAL_LIMIT + 1024**2:
        raise ValueError("备份文件超过可读取的大小。")
    with ZipFile(source) as archive:
        entries = archive.infolist()
        if len(entries) > ENTRY_LIMIT or sum(entry.file_size for entry in entries) > TOTAL_LIMIT:
            raise ValueError("备份解压后的内容过大。")
        files = {}
        seen = set()
        for entry in entries:
            name = entry.orig_filename
            folder, _, leaf = name.partition("/")
            role = folder == "library" and role_filename(leaf)
            limit = JSON_LIMITS.get(name, MAX_PACKAGE if role else 0)
            if (not limit or entry.file_size > limit or name.casefold() in seen
                    or entry.flag_bits & 1 or stat.S_ISLNK(entry.external_attr >> 16)):
                raise ValueError("备份里的文件名或文件格式无效。")
            seen.add(name.casefold())
            files[name] = entry
        if not JSON_LIMITS.keys() <= files.keys():
            raise ValueError("此 ZIP 缺少桌宠便签的备份清单、便签或设置。")

        manifest = json.loads(archive.read(files[MANIFEST]))
        if not isinstance(manifest, dict) or manifest.get("format") != FORMAT or manifest.get("version") != 1:
            raise ValueError("此 ZIP 不是当前支持的桌宠便签备份。")
        created = datetime.fromisoformat(manifest.get("createdAt", ""))
        if created.tzinfo is None:
            raise ValueError("备份日期格式无效。")
        raw_notes = json.loads(archive.read(files[NOTES]))
        records = {}
        if not isinstance(raw_notes, list):
            raise ValueError("备份中的便签格式不正确。")
        for row in raw_notes:
            if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"] or row["id"] in records:
                raise ValueError("备份中存在无效或重复的便签。")
            records[row["id"]] = Note.read(row)

        preferences = portable_preferences(json.loads(archive.read(files[SETTINGS])))
        library = root / "incoming" / "library"
        library.mkdir(parents=True)
        roles = []
        for name in sorted(files.keys() - JSON_LIMITS.keys()):
            target = library / name.split("/")[1]
            with archive.open(files[name]) as entry, target.open("wb") as stream:
                copyfileobj(entry, stream)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                read_package(target)
            except ValueError as error:
                raise ValueError(f"备份中的角色「{target.name}」无法读取。{error}") from error
            roles.append(target.name)
        active = manifest.get("activeCharacter")
        if active is not None and active not in roles:
            raise ValueError("备份里找不到选中的桌宠。")
        return StagedBackup(root, created, records, preferences, tuple(roles), active)


def stage_backup(source, root):
    try:
        return read_snapshot(source, root)
    except (BadZipFile, CompressionError, EOFError, UnicodeError, TypeError, OverflowError, RecursionError,
            NotImplementedError) as error:
        raise ValueError("无法读取此备份，文件可能已损坏。") from error


def discard_transaction(pending):
    finished = Path(mkdtemp(prefix=".restore-finished-", dir=pending.parent))
    finished.rmdir()
    pending.replace(finished)
    rmtree(finished, ignore_errors=True)


def recover_restore(data_dir):
    pending = data_dir / PENDING
    if not pending.is_dir():
        return
    if not (pending / "committed").is_file():
        for name in reversed(MANAGED):
            current = data_dir / name
            old = pending / "previous" / name
            incoming = pending / "incoming" / name
            if not incoming.exists() and current.exists():
                current.replace(incoming)
            if old.exists():
                old.replace(current)
    discard_transaction(pending)


def apply_backup(data_dir, snapshot):
    pending = data_dir / PENDING
    recover_restore(data_dir)
    snapshot.preferences["pet_path"] = str(data_dir / "library" / snapshot.selected) if snapshot.selected else None
    NoteStore(snapshot.root / "incoming" / NOTES).save(snapshot.records)
    with (snapshot.root / "incoming" / SETTINGS).open("wb") as stream:
        stream.write(json_bytes(snapshot.preferences))
        stream.flush()
        os.fsync(stream.fileno())
    (snapshot.root / "previous" / "settings").mkdir(parents=True)
    (data_dir / "settings").mkdir(exist_ok=True)
    snapshot.root.replace(pending)
    try:
        for name in MANAGED:
            current = data_dir / name
            if current.exists():
                current.replace(pending / "previous" / name)
            (pending / "incoming" / name).replace(current)
        (pending / "committed").touch()
    except OSError:
        try:
            recover_restore(data_dir)
        except OSError as error:
            raise RestorePendingError("还原未完成。请重新打开软件，程序将恢复原来的数据。") from error
        raise
    # Once committed, only remove the old files. Startup can retry cleanup.
    try:
        discard_transaction(pending)
    except OSError:
        pass


def staging_folder(data_dir):
    return TemporaryDirectory(dir=data_dir, prefix=".restore-preview-")

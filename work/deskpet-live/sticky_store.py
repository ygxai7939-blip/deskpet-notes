"""Note persistence adapted from DeskStickyNotes (MIT).

The note defaults, title normalization, geometry normalization and atomic
replacement derive from NoteModel.cs and NoteStorageService.cs at f5e2b148.
The independent document format stores Qt HTML, plain search text and snippets.
"""
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from unicodedata import normalize
from uuid import uuid4


MIN_WIDTH, MIN_HEIGHT = 350, 220
DEFAULT_WIDTH, DEFAULT_HEIGHT = 494, 356
TAG_NAME_LENGTH = 32
PASTEL_TONES = {
    "金盏": ("#f0dfa2", "#b78119"),
    "杏橙": ("#f3cdb4", "#bd572e"),
    "蔷薇": ("#efc8d4", "#bb4666"),
    "雾紫": ("#d9c9ed", "#7356ae"),
    "晴蓝": ("#c5dbeb", "#386ea5"),
    "薄荷": ("#c9e3d5", "#3d8065"),
    "燕麦": ("#e6d6be", "#927145"),
    "雾灰": ("#d2d8e0", "#53657a"),
}
# Keep the existing saved keys so older notes retain their chosen appearance tier.
NOTE_TONES = {
    "杏色": ("纸白", "#f2f2f2"),
    "奶油": ("淡灰", "#eaeaea"),
    "鼠尾草": ("浅灰", "#e0e0e0"),
    "浅紫": ("银灰", "#d6d6d6"),
    "暖灰": ("中灰", "#c8c8c8"),
    **{name: (name, paper) for name, (paper, _dot) in PASTEL_TONES.items()},
}


def now():
    return datetime.now(timezone.utc).isoformat()


def normalize_title(value):
    return " ".join(value.split())[:80] if isinstance(value, str) else ""


def normalize_tag(value):
    return " ".join(value.split())[:TAG_NAME_LENGTH] if isinstance(value, str) else ""


def tag_key(value):
    return normalize("NFKC", value).casefold()


def normalize_tags(values):
    tags = {}
    if isinstance(values, list):
        for value in values:
            name = normalize_tag(value)
            if name:
                tags.setdefault(tag_key(name), name)
    return list(tags.values())


def finite(value, default):
    return int(value) if isinstance(value, (int, float)) and math.isfinite(value) else default


@dataclass
class Note:
    id: str = field(default_factory=lambda: uuid4().hex)
    title: str = ""
    textContent: str = ""
    richContent: str = ""
    x: int = 100
    y: int = 100
    width: int = DEFAULT_WIDTH
    height: int = DEFAULT_HEIGHT
    color: str = "雾紫"
    backgroundOpacity: float = 1.0
    topmost: bool = False
    visible: bool = True
    collapsed: bool = False
    edge: str = ""
    edgeScreen: str = ""
    archived: bool = False
    updatedAt: str = field(default_factory=now)
    textClips: list[dict] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    @property
    def label(self):
        return self.title or normalize_title(self.textContent) or "无标题便签"

    @property
    def paper_tone(self):
        return NOTE_TONES[self.color][1]

    @property
    def on_desktop(self):
        return not (self.archived or self.collapsed) and (self.visible or bool(self.edge))

    def clear_dock(self):
        self.edge = self.edgeScreen = ""

    @classmethod
    def read(cls, value):
        if not isinstance(value, dict):
            raise ValueError("便签数据格式不正确。")
        note = cls()
        for key in ("id", "title", "textContent", "richContent", "updatedAt", "color", "edgeScreen"):
            if isinstance(value.get(key), str) and (key != "id" or value[key]):
                setattr(note, key, value[key])
        note.title = normalize_title(note.title)
        note.color = note.color if note.color in NOTE_TONES else "杏色"
        note.x = finite(value.get("x"), 100)
        note.y = finite(value.get("y"), 100)
        note.width = max(MIN_WIDTH, finite(value.get("width"), DEFAULT_WIDTH))
        note.height = max(MIN_HEIGHT, finite(value.get("height"), DEFAULT_HEIGHT))
        opacity = value.get("backgroundOpacity")
        if isinstance(opacity, (int, float)) and math.isfinite(opacity):
            note.backgroundOpacity = max(.3, min(1., opacity))
        note.edge = value["edge"] if value.get("edge") in ("left", "right") else ""
        for key in ("topmost", "visible", "collapsed", "archived"):
            if isinstance(value.get(key), bool):
                setattr(note, key, value[key])
        if note.collapsed or note.archived:
            note.visible = False
        if note.archived or not note.edge:
            note.clear_dock()
        clips = value.get("textClips")
        if isinstance(clips, list):
            note.textClips = [clip for clip in clips
                              if isinstance(clip, dict) and isinstance(clip.get("content"), str)
                              and isinstance(clip.get("title"), str)]
        note.tags = normalize_tags(value.get("tags"))
        return note


class NoteStore:
    def __init__(self, path: Path):
        self.path = path
        self.records: dict[str, Note] = {}
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            if not isinstance(data, list):
                raise ValueError("便签文件需要包含一组便签。")
            for row in data:
                note = Note.read(row)
                self.records.setdefault(note.id, note)

    def save(self, records=None):
        records = self.records if records is None else records
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = None
        try:
            with NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                    prefix=".notes-", suffix=".tmp", delete=False) as tmp:
                tmp_path = Path(tmp.name)
                json.dump([asdict(note) for note in records.values()], tmp, ensure_ascii=False, indent=2)
                tmp.flush()
                os.fsync(tmp.fileno())
            os.replace(tmp_path, self.path)
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)

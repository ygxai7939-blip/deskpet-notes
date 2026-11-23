"""DeskPet's transparent Windows pet window, adapted for 桌宠便签."""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
import sys

from PIL import Image
from PySide6.QtCore import QPoint, QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QCursor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QWidget

from core.bundle import list_pets, load_pet_pil, pet_display_name
from core.state import PetState
from core.constants import ANIM_DEFS, ROWS, TILE_W, TILE_H
from core.settings import save as save_settings

TICK_MS      = 16

ES_CONTINUOUS       = 0x80000000
ES_DISPLAY_REQUIRED = 0x00000002
ES_SYSTEM_REQUIRED  = 0x00000001

_SCALES        = [("小（25%）", 0.25), ("中（50%）", 0.50), ("大（75%）", 0.75)]
_PERSONALITIES = [("友好", "friendly"), ("安静", "focused"), ("活泼", "playful")]


# ── Image conversion ──────────────────────────────────────────────────────────

def _pil_to_pixmap(img: Image.Image) -> QPixmap:
    raw  = img.tobytes("raw", "RGBA")
    qi   = QImage(raw, img.width, img.height, QImage.Format_RGBA8888).copy()
    return QPixmap.fromImage(qi)


def _load_pet(zip_path: Path, scale: float):
    name, pil_frames, anims = load_pet_pil(str(zip_path), scale)
    frames = [[_pil_to_pixmap(tile) for tile in row] for row in pil_frames]
    return name, frames, anims


# ── Screen-awake ──────────────────────────────────────────────────────────────

def set_keep_awake(enabled: bool) -> None:
    flags = ES_CONTINUOUS
    if enabled:
        flags |= ES_DISPLAY_REQUIRED | ES_SYSTEM_REQUIRED
    ctypes.windll.kernel32.SetThreadExecutionState(flags)


# ── Autostart (Startup folder) ────────────────────────────────────────────────

def _startup_path() -> Path:
    appdata = os.environ.get("APPDATA")
    base    = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    return base / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "DeskPet.bat"


# ── Widget ────────────────────────────────────────────────────────────────────

class DesktopPet(QWidget):
    menu_requested = Signal(QPoint)
    note_library_requested = Signal()
    character_changed = Signal()

    def __init__(self, zip_path: Path | None, scale: float, settings: dict, *,
                 library: Path, settings_file: Path, launch_script: Path, startup_file: Path | None = None):
        super().__init__()
        self.library = library
        self._settings_file = settings_file
        self._launch_script = launch_script
        self._startup_file = startup_file if startup_file is not None else _startup_path()
        self._scale        = scale
        self._zip_path     = zip_path
        self._settings     = settings
        self._keep_awake   = False
        self._dragging     = False
        self._drag_started = False
        self._feed_pose     = None
        self._drag_mouse   = QPoint()
        self._drag_start_x = 0.0
        self._drag_start_y = 0.0

        tw, th = int(TILE_W * scale), int(TILE_H * scale)
        self._name, self._frames, self._anims = self.load_character(zip_path)
        self.setWindowTitle(f"桌面宠物 · {self._name}")

        screen = QApplication.primaryScreen().availableGeometry()
        self._ps = PetState(
            sx=screen.x(), sy=screen.y(),
            sw=screen.width(), sh=screen.height(),
            tw=tw, th=th,
        )

        if self._settings.get("movement_enabled"):
            self._ps.set_moving(True)
        self._ps.set_personality(self._settings.get("personality_style", "friendly"))

        self.setFixedSize(tw, th)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint |
            Qt.Tool | Qt.NoDropShadowWindowHint
        )
        self.move(int(self._ps.x), int(self._ps.y))

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        if zip_path is not None:
            self._timer.start(TICK_MS)

    @property
    def has_character(self):
        return self._zip_path is not None

    def paintEvent(self, _event):
        ps      = self._ps
        row     = self._anims[ps.anim][0]
        pixmap  = self._frames[row][ps.fidx]
        if self._feed_pose == "watch":
            pixmap = self._frames[0][0]
        elif self._feed_pose in ("opening", "ready"):
            row, count, _fps = self._anims["jumping" if self.has_feed_mouth else "waiting"]
            frame = 2 if self._feed_pose == "ready" else 1
            pixmap = self._frames[row][min(frame, count - 1)]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.drawPixmap(0, 0, ps.tw, ps.th, pixmap)

    @property
    def has_feed_mouth(self):
        return (self._zip_path is not None and self._zip_path.name == "dimple.codex-pet.zip"
                and self._anims["jumping"][1] >= 3)

    def feed_anchor(self):
        top = QPointF(self.mapToGlobal(QPoint()))
        return top + QPointF(self.width() * .51, self.height() * (.57 if self.has_feed_mouth else .53))

    def set_feed_pose(self, pose, *, celebrate=False):
        if celebrate:
            self._ps.on_release()
        if self._feed_pose != pose:
            self._feed_pose = pose
            self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging     = True
            self._drag_started = False
            self._drag_mouse   = event.globalPosition().toPoint()
            self._drag_start_x = float(self._ps.x)
            self._drag_start_y = float(self._ps.y)
            event.accept()
        elif event.button() == Qt.RightButton:
            self.menu_requested.emit(event.globalPosition().toPoint())
            event.accept()

    def mouseMoveEvent(self, event):
        if not self._dragging:
            return
        if not self._drag_started:
            self._drag_started = True
            self._ps.on_drag_start()
        delta = event.globalPosition().toPoint() - self._drag_mouse
        self._ps.on_drag(self._drag_start_x + delta.x(), self._drag_start_y + delta.y())
        self.move(int(self._ps.x), int(self._ps.y))
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._dragging:
            self._dragging = False
            self._ps.on_release()
            event.accept()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = self._drag_started = self._ps.is_dragging = False
            QTimer.singleShot(0, self.note_library_requested.emit)
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def closeEvent(self, event):
        set_keep_awake(False)
        super().closeEvent(event)

    def character_paths(self) -> list[Path]:
        return list_pets(self.library)

    def build_settings_menu(self, parent, menu_type, select_character=None) -> QMenu:
        menu = menu_type(parent)

        # Switch Pet
        pet_group = QActionGroup(menu)
        pet_group.setExclusive(True)
        select = select_character or self._switch_pet
        for path in self.character_paths():
            action = QAction(pet_display_name(str(path)), menu)
            action.setCheckable(True)
            action.setChecked(path == self._zip_path)
            action.triggered.connect(lambda _c=False, p=path: select(p))
            pet_group.addAction(action)
            menu.addAction(action)

        menu.addSeparator()

        # Size submenu
        size_menu  = menu_type(menu)
        size_menu.setTitle("大小")
        size_group = QActionGroup(size_menu)
        size_group.setExclusive(True)
        for label, sc in _SCALES:
            action = QAction(label, size_menu)
            action.setCheckable(True)
            action.setChecked(abs(sc - self._scale) < 0.01)
            action.triggered.connect(lambda _c=False, s=sc: self._apply_scale(s))
            size_group.addAction(action)
            size_menu.addAction(action)
        menu.addMenu(size_menu)

        # Personality submenu
        pers_menu  = menu_type(menu)
        pers_menu.setTitle("性格")
        pers_group = QActionGroup(pers_menu)
        pers_group.setExclusive(True)
        for label, pname in _PERSONALITIES:
            action = QAction(label, pers_menu)
            action.setCheckable(True)
            action.setChecked(pname == self._ps.personality)
            action.triggered.connect(lambda _c=False, n=pname: self._apply_personality(n))
            pers_group.addAction(action)
            pers_menu.addAction(action)
        menu.addMenu(pers_menu)

        menu.addSeparator()

        movement = QAction("自动走动", menu)
        movement.setCheckable(True)
        movement.setChecked(self._ps.moving)
        movement.triggered.connect(self.apply_movement)
        menu.addAction(movement)

        startup = QAction("开机启动", menu)
        startup.setCheckable(True)
        startup.setChecked(self._startup_file.is_file())
        startup.triggered.connect(self._toggle_autostart)
        menu.addAction(startup)

        awake = QAction("保持屏幕常亮", menu)
        awake.setCheckable(True)
        awake.setChecked(self._keep_awake)
        awake.triggered.connect(self._apply_keep_awake)
        menu.addAction(awake)

        return menu

    def load_character(self, zip_path: Path | None, *, scale=None):
        scale = self._scale if scale is None else scale
        if zip_path is not None:
            return _load_pet(zip_path, scale)
        empty = QPixmap(max(1, int(TILE_W * scale)), max(1, int(TILE_H * scale)))
        empty.fill(Qt.GlobalColor.transparent)
        anims = {name: (row, 1, fps) for name, (row, fps) in ANIM_DEFS.items()}
        return "未导入角色", [[empty] for _ in range(ROWS)], anims

    def _switch_pet(self, zip_path: Path | None, *, loaded=None, persist=True) -> None:
        self._name, self._frames, self._anims = self.load_character(zip_path) if loaded is None else loaded
        self._zip_path = zip_path
        if zip_path is None:
            self._timer.stop()
            self.hide()
        elif not self._timer.isActive():
            self._timer.start(TICK_MS)
        self.setWindowTitle(f"桌面宠物 · {self._name}")
        self._ps.enter("idle")
        self.update()
        if persist:
            self._save_settings()
        self.character_changed.emit()

    def _apply_scale(self, scale: float) -> None:
        if self._zip_path is not None:
            self._name, self._frames, self._anims = _load_pet(self._zip_path, scale)
        self.resize_character(scale)
        self._save_settings()

    def resize_character(self, scale):
        self._scale = scale
        tw, th = int(TILE_W * scale), int(TILE_H * scale)
        self._ps.resize(tw, th)
        self.setFixedSize(tw, th)
        self.move(int(self._ps.x), int(self._ps.y))
        self.update()

    def backup_preferences(self):
        return self._settings.copy()

    def apply_restored_preferences(self, preferences, path, loaded):
        self._settings = preferences
        self._ps.set_personality(preferences["personality_style"])
        self._ps.set_moving(preferences["movement_enabled"])
        self.resize_character(preferences["pet_scale"])
        self._switch_pet(path, loaded=loaded, persist=False)
        self.setVisible(path is not None)

    def _apply_personality(self, name: str) -> None:
        self._ps.set_personality(name)
        self._save_settings()

    def apply_movement(self, enabled: bool) -> None:
        self._ps.set_moving(enabled)
        self._save_settings()

    def preference(self, key, default=None):
        return self._settings.get(key, default)

    def set_preference(self, key, value):
        self._settings[key] = value
        self._save_settings()

    def _save_settings(self) -> None:
        ps   = self._ps
        data = {
            **self._settings,
            "pet_path":          str(self._zip_path) if self._zip_path is not None else None,
            "pet_scale":         self._scale,
            "movement_enabled":  ps.moving,
            "personality_style": ps.personality,
        }
        save_settings(self._settings_file, data)
        self._settings = data

    def _toggle_autostart(self, enabled: bool) -> None:
        if enabled:
            self._startup_file.parent.mkdir(parents=True, exist_ok=True)
            launcher = "" if getattr(sys, "frozen", False) else f' "{self._launch_script}"'
            self._startup_file.write_text(
                f'@echo off\nstart "" "{sys.executable}"{launcher}\n',
                encoding="utf-8",
            )
        else:
            self._startup_file.unlink(missing_ok=True)

    def _apply_keep_awake(self, enabled: bool) -> None:
        self._keep_awake = enabled
        set_keep_awake(enabled)

    def _tick(self) -> None:
        if self._feed_pose is not None:
            return
        pos = QCursor.pos()
        self._ps.update_cursor(float(pos.x()), float(pos.y()))

        position_changed = self._ps.tick(TICK_MS / 1000.0, self._anims)
        if position_changed:
            self.move(int(self._ps.x), int(self._ps.y))
        self.update()

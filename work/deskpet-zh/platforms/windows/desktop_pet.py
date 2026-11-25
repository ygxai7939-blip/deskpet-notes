"""DeskPet's transparent Windows pet window, adapted for 桌宠便签."""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
import sys
from time import monotonic

from PIL import Image
from PySide6.QtCore import QPoint, QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QCursor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QWidget

from core.bundle import list_pets, load_pet_pil, pet_display_name
from core.state import PetState
from core.constants import TILE_W, TILE_H
from core.settings import save as save_settings
from pet_packages import LEGACY_ACTIONS

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
    name, pil_frames, anims = load_pet_pil(zip_path, scale)
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
        self._feed_started = 0.0
        self._painted_frame = None
        self._last_tick = monotonic()
        self._drag_mouse   = QPoint()
        self._drag_start_x = 0.0
        self._drag_start_y = 0.0
        self._rub_last = None
        self._rub_started = self._rub_until = 0.0
        self._rub_distance = self._rub_direction = self._rub_turns = 0

        tw, th = int(TILE_W * scale), int(TILE_H * scale)
        self._name, self._frames, self._anims = self.load_character(zip_path)
        self.setWindowTitle(f"桌面宠物 · {self._name}")

        screen = QApplication.primaryScreen().availableGeometry()
        self._ps = PetState(
            sx=screen.x(), sy=screen.y(),
            sw=screen.width(), sh=screen.height(),
            tw=tw, th=th,
            anims=self._anims,
        )

        if self._settings.get("movement_enabled"):
            self._ps.set_moving(True)
        self._ps.set_personality(self._settings.get("personality_style", "friendly"))

        self.setFixedSize(tw, th)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint |
            Qt.Tool | Qt.NoDropShadowWindowHint
        )
        self.move(int(self._ps.x), int(self._ps.y))

        self._click_timer = QTimer(self, singleShot=True)
        self._click_timer.timeout.connect(lambda: self.react("action"))
        self._timer = QTimer(self, interval=TICK_MS, timerType=Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._tick)

    @property
    def has_character(self):
        return self._zip_path is not None

    def paintEvent(self, _event):
        row, index = self._painted_frame = self._display_frame()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.drawPixmap(0, 0, self.width(), self.height(), self._frames[row][index])

    def _display_frame(self):
        pose = self._feed_pose
        if pose == "watch":
            return 0, 0
        if pose in ("opening", "ready"):
            action = "feed_ready" if pose == "ready" else "feed_open"
            if action in self._anims:
                row, count, fps = self._anims[action]
                frame = int((monotonic() - self._feed_started) * fps)
            elif pose == "ready" and "feed_open" in self._anims:
                row, count, _fps = self._anims["feed_open"]
                frame = count - 1
            else:
                row, count, _fps = self._anims["jumping" if self._legacy_feed_mouth else "waiting"]
                frame = 2 if pose == "ready" else 1
            return row, min(frame, count - 1)
        return self._anims[self._ps.anim][0], self._ps.fidx

    @property
    def has_feed_mouth(self):
        return self._legacy_feed_mouth or "feed_open" in self._anims or "feed_ready" in self._anims

    @property
    def _legacy_feed_mouth(self):
        return (self._zip_path is not None and self._zip_path.name == "dimple.codex-pet.zip"
                and self._anims["jumping"][1] >= 3)

    def feed_anchor(self):
        top = QPointF(self.mapToGlobal(QPoint()))
        return top + QPointF(self.width() * .51, self.height() * (.57 if self.has_feed_mouth else .53))

    def set_feed_pose(self, pose, *, celebrate=False):
        if self._feed_pose != pose:
            self._feed_pose = pose
            self._feed_started = monotonic()
            self._click_timer.stop()
            self.update()
        if celebrate:
            self.react("celebrate")

    def react(self, response):
        if self.has_character and self.isVisible() and not self._dragging and self._feed_pose is None:
            self._ps.on_release(response)
            self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging     = True
            self._drag_started = False
            self._rub_last     = None
            self._drag_mouse   = event.globalPosition().toPoint()
            self._drag_start_x = float(self._ps.x)
            self._drag_start_y = float(self._ps.y)
            event.accept()
        elif event.button() == Qt.RightButton:
            self.menu_requested.emit(event.globalPosition().toPoint())
            event.accept()

    def mouseMoveEvent(self, event):
        if not self._dragging:
            self._track_head_rub(event.position())
            return
        point = event.globalPosition().toPoint()
        delta = point - self._drag_mouse
        if not self._drag_started:
            if delta.manhattanLength() < QApplication.startDragDistance():
                return
            self._click_timer.stop()
            self._drag_started = True
            self._ps.on_drag_start()
            self.update()
        screen = QApplication.screenAt(point) or self.screen()
        bounds = screen.availableGeometry()
        self._ps.sx, self._ps.sy = bounds.x(), bounds.y()
        self._ps.sw, self._ps.sh = bounds.width(), bounds.height()
        self._ps.on_drag(self._drag_start_x + delta.x(), self._drag_start_y + delta.y())
        self.move(int(self._ps.x), int(self._ps.y))
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._dragging:
            self._dragging = False
            if self._drag_started:
                self._drag_started = False
                self._ps.on_release()
                self.update()
            else:
                self._click_timer.start(QApplication.doubleClickInterval())
            event.accept()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._click_timer.stop()
            self._dragging = self._drag_started = self._ps.is_dragging = False
            QTimer.singleShot(0, self.note_library_requested.emit)
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def _track_head_rub(self, point):
        now = monotonic()
        x, y = point.x() / self.width(), point.y() / self.height()
        if (not 0.12 <= x <= 0.85 or not 0.06 <= y <= 0.56
                or not self._ps.can_pet or self._feed_pose is not None
                or self._click_timer.isActive() or now < self._rub_until):
            self._rub_last = None
            return
        if self._rub_last is None or now - self._rub_started > 0.85:
            self._rub_last = point.x()
            self._rub_started = now
            self._rub_distance = self._rub_direction = self._rub_turns = 0
            return
        dx = point.x() - self._rub_last
        if abs(dx) < 3:
            return
        self._rub_last = point.x()
        direction = 1 if dx > 0 else -1
        if self._rub_direction and direction != self._rub_direction:
            self._rub_turns += 1
        self._rub_direction = direction
        self._rub_distance += abs(dx)
        if self._rub_turns and self._rub_distance >= max(12, self.width() * 0.16):
            self._rub_until = now + 2.0
            self.react("petting")

    def leaveEvent(self, event):
        self._rub_last = None
        super().leaveEvent(event)

    def showEvent(self, event):
        self._last_tick = monotonic()
        if self.has_character:
            self._timer.start()
        super().showEvent(event)

    def hideEvent(self, event):
        self._timer.stop()
        self._click_timer.stop()
        self._rub_last = None
        if self._drag_started:
            self._ps.on_release()
        self._dragging = self._drag_started = False
        super().hideEvent(event)

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
        anims = {name: (row, 1, fps) for name, (row, fps) in LEGACY_ACTIONS.items()}
        return "未导入角色", [[empty] for _ in anims], anims

    def _switch_pet(self, zip_path: Path | None, *, loaded=None, persist=True) -> None:
        self._name, self._frames, self._anims = self.load_character(zip_path) if loaded is None else loaded
        self._zip_path = zip_path
        self._click_timer.stop()
        self._rub_last = None
        self._rub_until = 0.0
        self._dragging = self._drag_started = False
        self._ps.reset_animations(self._anims)
        if zip_path is None:
            self._timer.stop()
            self.hide()
        elif self.isVisible() and not self._timer.isActive():
            self._last_tick = monotonic()
            self._timer.start()
        self.setWindowTitle(f"桌面宠物 · {self._name}")
        self.update()
        if persist:
            self._save_settings()
        self.character_changed.emit()

    def _apply_scale(self, scale: float) -> None:
        if self._zip_path is not None:
            self._name, self._frames, anims = _load_pet(self._zip_path, scale)
            if self._anims != anims:
                self._anims = anims
                self._ps.reset_animations(anims)
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
        now = monotonic()
        dt = min(now - self._last_tick, 0.1)
        self._last_tick = now
        if self._feed_pose is not None:
            if self._display_frame() != self._painted_frame:
                self.update()
            return
        if self._ps.moving and self._ps.personality == "playful":
            pos = QCursor.pos()
            self._ps.update_cursor(float(pos.x()), float(pos.y()))
        if self._ps.tick(dt, pressed=self._dragging or self._click_timer.isActive()):
            point = QPoint(int(self._ps.x), int(self._ps.y))
            if point != self.pos():
                self.move(point)
        if self._display_frame() != self._painted_frame:
            self.update()

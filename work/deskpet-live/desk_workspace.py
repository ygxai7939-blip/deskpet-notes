"""The common DeskPet window, note controller, tray, and pet context menu."""
import ctypes
from ctypes import wintypes
from dataclasses import replace
from pathlib import Path
from shutil import copyfile

from PySide6.QtCore import QAbstractNativeEventFilter, QEvent, QPoint, QRect, QRectF, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QImage, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QScrollArea, QSizeGrip, QSizePolicy, QSpacerItem, QStackedWidget, QSystemTrayIcon,
    QVBoxLayout, QWidget, QWidgetAction,
)

from app_version import APP_PUBLISHER
from core.bundle import CHARACTER_LOAD_ERRORS
from data_backup import (
    RestorePendingError, apply_backup, backup_filename, stage_backup, staging_folder, write_backup,
)
from desk_style import (
    ChoiceButton, DragArea, GlideHighlight, RoundedMenu, SheetDialog, SoftButton, SoftSwitch, STYLE,
    button, icon, label, show_warning,
)
from edge_notes import EdgeNotes
from file_picker import pick_file
from paper_feed import PaperFeed
from pet_packages import read_package
from pixel_snow import PixelSnow
from sticky_store import Note, NoteStore, TAG_NAME_LENGTH, normalize_tag, tag_key
from sticky_window import StickyWindow, fit_to_desktop
from workspace_style import WORKSPACE_STYLE


def frame(name):
    return QFrame(objectName=name)


def clear_widgets(layout):
    while layout.count():
        entry = layout.takeAt(0)
        widget = entry.widget()
        if widget is not None:
            widget.hide()
            widget.deleteLater()


def note_state(note):
    if note.archived:
        return "已归档"
    if note.visible:
        return "在桌面 · 置顶" if note.topmost else "在桌面"
    if note.collapsed:
        return "已收起"
    if note.edge:
        return "已贴边"
    return "已隐藏"


def show_note_tags(widget, tags):
    text = "   ".join(f"#{name}" for name in tags)
    widget.setText(text)
    widget.setToolTip("、".join(tags))
    widget.setVisible(bool(tags))


class ElidedLabel(QLabel):
    def __init__(self, text, role):
        super().__init__(text)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setObjectName(role)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def paintEvent(self, _event):
        rect = self.contentsRect()
        text = self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, rect.width())
        painter = QPainter(self)
        painter.setFont(self.font())
        painter.setPen(self.palette().color(self.foregroundRole()))
        painter.drawText(rect, self.alignment(), text)


class TagEditor(SheetDialog):
    def __init__(self, note, known_tags, parent):
        super().__init__("编辑标签", parent)
        self.setFixedWidth(454)
        self.known_tags = known_tags
        self.tags = {tag_key(tag): tag for tag in note.tags}
        title = ElidedLabel(note.label, "muted")
        title.setToolTip(note.label)
        self.body.addWidget(title)

        controls = QHBoxLayout()
        self.entry = QLineEdit(objectName="tagEntry")
        self.entry.setPlaceholderText("输入标签，回车添加")
        self.entry.setAccessibleName("标签名称")
        self.entry.setMaxLength(TAG_NAME_LENGTH)
        self.entry.returnPressed.connect(self.add_entry)
        controls.addWidget(self.entry, 1)
        add = button("添加", self.add_entry, "secondary")
        add.setAutoDefault(False)
        controls.addWidget(add)
        self.existing = button("已有标签", self.choose_existing, "secondary")
        self.existing.setAutoDefault(False)
        controls.addWidget(self.existing)
        self.body.addLayout(controls)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.viewport().setAutoFillBackground(False)
        scroll.setFixedHeight(113)
        contents = QWidget(objectName="noteList")
        scroll.setWidget(contents)
        self.chips = QGridLayout(contents)
        self.chips.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.chips.setContentsMargins(0, 1, 5, 1)
        self.chips.setSpacing(6)
        self.body.addWidget(scroll)

        actions = QHBoxLayout()
        actions.addStretch()
        cancel = button("取消", self.reject, "secondary")
        cancel.setAutoDefault(False)
        actions.addWidget(cancel)
        save = button("保存", self.accept, "primary")
        save.setAutoDefault(False)
        actions.addWidget(save)
        self.body.addLayout(actions)
        self.refresh_chips()
        self.entry.setFocus()

    def add_entry(self):
        name = normalize_tag(self.entry.text())
        if name:
            self.add_tag(name)
        self.entry.clear()
        self.entry.setFocus()

    def add_tag(self, name):
        key = tag_key(name)
        self.tags.setdefault(key, self.known_tags.get(key, name))
        self.refresh_chips()

    def remove_tag(self, key):
        self.tags.pop(key)
        self.refresh_chips()

    def choose_existing(self):
        menu = RoundedMenu(self.existing)
        for key, name in self.known_tags.items():
            if key not in self.tags:
                menu.addAction(name.replace("&", "&&"), lambda _, tag=name: self.add_tag(tag))
        try:
            menu.exec(self.existing.mapToGlobal(QPoint(0, self.existing.height() + 4)))
        finally:
            menu.deleteLater()

    def refresh_chips(self):
        clear_widgets(self.chips)
        self.existing.setEnabled(any(key not in self.tags for key in self.known_tags))
        if not self.tags:
            self.chips.addWidget(label("还没有标签", "muted"), 0, 0)
        for index, (key, name) in enumerate(self.tags.items()):
            chip = button("", lambda _, value=key: self.remove_tag(value), "tagChip", tip=f"移除标签 {name}")
            chip.setAutoDefault(False)
            chip.setText(chip.fontMetrics().elidedText(name, Qt.TextElideMode.ElideRight, 142) + "  ×")
            self.chips.addWidget(chip, index // 2, index % 2)

    def accept(self):
        name = normalize_tag(self.entry.text())
        if name:
            self.add_tag(name)
        super().accept()


class WorkspaceShell(QFrame):
    def __init__(self):
        super().__init__()
        self.outline = QPainterPath()
        self.snow = PixelSnow(self)

    def showEvent(self, event):
        super().showEvent(event)
        self.snow.sync()

    def hideEvent(self, event):
        super().hideEvent(event)
        self.snow.sync()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.outline = QPainterPath()
        self.outline.addRoundedRect(QRectF(self.rect()), 12, 12)
        self.snow.resize()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(event.rect(), Qt.GlobalColor.transparent)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillPath(self.outline, QColor("#191919"))
        painter.setClipPath(self.outline)
        self.snow.paint(painter)


class NoteCard(QFrame):
    def __init__(self, studio, note, select):
        super().__init__(objectName="libraryCard")
        self.note, self.select = note, select
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(f"{note.label}，{note_state(note)}")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        panel = QVBoxLayout(self)
        panel.setContentsMargins(11, 9, 11, 9)
        panel.setSpacing(7)
        title = ElidedLabel(note.label, "libraryCardTitle")
        title.setToolTip(note.label)
        title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        heading = QHBoxLayout()
        heading.setSpacing(6)
        heading.addWidget(title, 1)
        self.mark = button("", lambda: self.select(self.note), "libraryMark", "select-empty",
                           color="#d8d8d8")
        self.mark.setFixedSize(20, 20)
        self.mark.setCheckable(True)
        self.mark.hide()
        heading.addWidget(self.mark)
        panel.addLayout(heading)
        self.batch_mode = False
        self.batch_checked = None
        preview = label(note.textContent.strip()[:380] or "空白便签", "libraryPreview")
        preview.setWordWrap(True)
        preview.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        preview.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        preview.setFixedHeight(89 if note.tags else 111)
        preview.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        panel.addWidget(preview)
        if note.tags:
            tags = ElidedLabel("", "libraryTags")
            tags.setFixedHeight(15)
            show_note_tags(tags, note.tags)
            tags.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            panel.addWidget(tags)
        actions = QHBoxLayout()
        actions.setSpacing(5)
        state = label(note_state(note), "libraryMeta")
        state.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        state.setMinimumHeight(26)
        actions.addWidget(state, 1)
        self.open_button = button("打开", lambda: studio.show_note(note), "librarySecondary")
        self.open_button.setAccessibleName(f"打开便签 {note.label}")
        actions.addWidget(self.open_button)
        self.more_button = button("", lambda: studio.note_actions(note, self.more_button),
                                  "libraryIcon", "more", "便签选项", color="#bdbdbd")
        self.more_button.setFixedSize(29, 26)
        actions.addWidget(self.more_button)
        panel.addLayout(actions)

    def set_selected(self, selected):
        if self.property("selected") != selected:
            self.setProperty("selected", selected)
            self.style().unpolish(self)
            self.style().polish(self)
            self.update()

    def set_batch_selection(self, enabled, checked):
        if self.batch_mode != enabled:
            self.batch_mode = enabled
            self.mark.setVisible(enabled)
            self.open_button.setVisible(not enabled)
            self.more_button.setVisible(not enabled)
        if self.batch_checked == checked:
            return
        self.batch_checked = checked
        self.mark.setChecked(checked)
        glyph = "select" if checked else "select-empty"
        self.mark.setIcon(icon(glyph, "#ededed" if checked else "#bdbdbd", 17))
        action = "取消选择" if checked else "选择"
        self.mark.setAccessibleName(f"{action}便签 {self.note.label}")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.select(self.note)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and not self.batch_mode:
            self.open_button.click()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space or (self.batch_mode and event.key() in
                                               (Qt.Key.Key_Return, Qt.Key.Key_Enter)):
            self.select(self.note)
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.open_button.click()
        else:
            super().keyPressEvent(event)
            return
        event.accept()


class DesktopHotkeys(QAbstractNativeEventFilter):
    def __init__(self, studio):
        super().__init__()
        self.studio = studio
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        self.user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        modifiers = 0x0001 | 0x0002 | 0x4000
        self.keys = {}
        for key, vk, action in ((0x701, 0x4E, studio.new_note), (0x702, 0x22, studio.next_note)):
            if self.user32.RegisterHotKey(None, key, modifiers, vk):
                self.keys[key] = action
        studio.app.installNativeEventFilter(self)

    def nativeEventFilter(self, event_type, message):
        if bytes(event_type) in {b"windows_generic_MSG", b"windows_dispatcher_MSG"}:
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == 0x0312 and msg.wParam in self.keys:
                QTimer.singleShot(0, self.keys[msg.wParam])
                return True, 0
        return False, 0

    def close(self):
        self.studio.app.removeNativeEventFilter(self)
        for key in self.keys:
            self.user32.UnregisterHotKey(None, key)
        self.keys.clear()


class PetArtwork(QWidget):
    def __init__(self, pet, size=136):
        super().__init__()
        self.pet = pet
        self.setFixedSize(size, size)
        self.setAccessibleName(pet._name)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        sprite = self.pet._frames[0][0]
        scaled = sprite.scaled(self.size(),
                               Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        painter.drawPixmap(self.rect().center() - scaled.rect().center(), scaled)


def character_pixmap(tile, size):
    raw = tile.tobytes("raw", "RGBA")
    pixels = QImage(raw, tile.width, tile.height, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(pixels).scaled(
        size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)


class CharacterCard(SoftButton):
    def __init__(self, path, studio):
        super().__init__("")
        self.setObjectName("characterCard")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 12)
        layout.setSpacing(4)
        badge_row = QHBoxLayout()
        badge_row.addStretch()
        self.active_badge = label("使用中", "characterActive")
        badge_size = self.active_badge.sizePolicy()
        badge_size.setRetainSizeWhenHidden(True)
        self.active_badge.setSizePolicy(badge_size)
        badge_row.addWidget(self.active_badge)
        self.more_button = button("", lambda: studio.character_actions(path, name, self.more_button),
                                  "characterMore", "more", "角色操作", color="#e6e6e6")
        self.more_button.setFixedSize(29, 26)
        badge_row.addWidget(self.more_button)
        layout.addLayout(badge_row)
        sprite = label()
        sprite.setFixedSize(106, 94)
        sprite.setAlignment(Qt.AlignmentFlag.AlignCenter)
        try:
            package = read_package(path)
            name, description = package.name, package.description
            sprite.setPixmap(character_pixmap(package.idle_frames[0], sprite.size()))
        except (OSError, ValueError):
            name = path.name.removesuffix(".codex-pet.zip")
            description = "预览不可用"
            sprite.setPixmap(icon("pet", "#777777", 36).pixmap(36, 36))
        layout.addWidget(sprite, alignment=Qt.AlignmentFlag.AlignHCenter)
        title = ElidedLabel(name, "libraryCardTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        detail = label(description, "characterDescription")
        detail.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        detail.setContentsMargins(10, 0, 10, 0)
        detail.setWordWrap(True)
        detail.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        detail.setFixedHeight(36)
        layout.addWidget(detail)
        layout.addStretch()
        self.setAccessibleName(name)
        self.more_button.setAccessibleName(f"{name}的角色操作")
        self.setToolTip(f"{name}\n{description}" if description else name)
        for item in self.findChildren(QLabel):
            item.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.clicked.connect(lambda: studio.select_character(path))
        self.set_active(False)

    def set_active(self, active):
        self.setChecked(active)
        self.active_badge.setVisible(active)


class CharacterGrid(QWidget):
    def __init__(self, studio):
        super().__init__()
        self.studio = studio
        self.cards = {}
        self.snapshot = None
        self.columns = 0
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(9)

    def refresh(self, paths):
        entries = []
        for path in paths:
            try:
                modified = path.stat()
            except OSError:
                continue
            entries.append((path, modified.st_mtime_ns, modified.st_size))
        if entries != self.snapshot:
            clear_widgets(self.grid)
            self.snapshot = entries
            self.cards = {path: CharacterCard(path, self.studio) for path, _, _ in entries}
            self.arrange(self.width(), rebuild=True)

    def arrange(self, width, *, rebuild=False):
        columns = 3 if width >= 580 else 2 if width >= 315 else 1
        if columns == self.columns and not rebuild:
            return
        self.columns = columns
        for i in range(3):
            self.grid.setColumnStretch(i, int(i < self.columns))
        for i, card in enumerate(self.cards.values()):
            self.grid.removeWidget(card)
            self.grid.addWidget(card, i // self.columns, i % self.columns)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.arrange(event.size().width())

    def set_active(self, active):
        for path, card in self.cards.items():
            card.set_active(path == active)


class SpritePreview(QLabel):
    finished = Signal()

    def __init__(self, size):
        super().__init__()
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.advance)
        self.frames = []
        self.position = 0
        self.loop = True
        self.loop_start = 0
        self.ended = False

    def set_clip(self, tiles, fps, *, loop=True, loop_start=0):
        self.timer.stop()
        self.frames = [character_pixmap(tile, self.size()) for tile in tiles]
        self.loop = loop
        self.loop_start = loop_start
        self.timer.setInterval(round(1000 / fps))
        self.restart()

    def restart(self):
        self.position = 0
        self.ended = False
        self.setPixmap(self.frames[0])
        if len(self.frames) > 1:
            self.timer.start()

    def advance(self):
        if not self.loop and self.position == len(self.frames) - 1:
            self.timer.stop()
            self.ended = True
            self.finished.emit()
            return
        self.position += 1
        if self.position == len(self.frames):
            self.position = self.loop_start
        self.setPixmap(self.frames[self.position])


def preview_surface(player):
    surface = frame("feature")
    artwork = QVBoxLayout(surface)
    artwork.addWidget(player, alignment=Qt.AlignmentFlag.AlignCenter)
    return surface


class CharacterPreview(SheetDialog):
    def __init__(self, pack, updating, parent):
        super().__init__("角色预览", parent)
        self.setMinimumWidth(372)
        self.save_as_new = False
        sprite = SpritePreview(140)
        self.body.addWidget(preview_surface(sprite))
        name = label(pack.name, "section")
        name.setWordWrap(True)
        self.body.addWidget(name)
        if pack.description:
            detail = label(pack.description, "muted")
            detail.setWordWrap(True)
            self.body.addWidget(detail)
        caption = "此角色 ID 已存在。可以更新原角色，或保留两份。" if updating else "待机预览"
        notice = label(caption, "caption")
        notice.setWordWrap(True)
        self.body.addWidget(notice)
        sprite.set_clip(pack.idle_frames, pack.animations["idle"][2])
        self.finished.connect(sprite.timer.stop)
        actions = QHBoxLayout()
        actions.addStretch()
        cancel = button("取消", self.reject)
        cancel.setDefault(True)
        actions.addWidget(cancel)
        if updating:
            actions.addWidget(button("更新并使用", self.accept))
            actions.addWidget(button("另存为新角色", self.accept_as_new, "primary"))
        else:
            actions.addWidget(button("安装并使用", self.accept, "primary"))
        self.body.addLayout(actions)

    def accept_as_new(self):
        self.save_as_new = True
        self.accept()


class CharacterActions(SheetDialog):
    ACTIONS = (
        ("待机", "idle"), ("向右走", "run_right"), ("向左走", "run_left"),
        ("点击回应", "waving"), ("跳跃", "jumping"), ("失落 / 睡觉", "failed"),
        ("等待", "waiting"), ("忙碌", "running"), ("好奇", "review"),
        ("摸头", "petting"), ("被提起", "lifted"), ("放下", "landing"),
        ("睡觉", "sleeping"), ("醒来", "waking"), ("伸懒腰", "stretching"),
        ("庆祝", "celebrate"), ("张嘴", "feed_open"), ("接纸团", "feed_ready"),
    )

    def __init__(self, pack, parent):
        super().__init__("动作预览", parent)
        self.setFixedWidth(416)
        self.setStyleSheet(STYLE + WORKSPACE_STYLE)
        self.pack = pack
        name = label(pack.name, "muted")
        name.setWordWrap(True)
        self.body.addWidget(name)
        self.sprite = SpritePreview(186)
        self.body.addWidget(preview_surface(self.sprite))
        controls = QHBoxLayout()
        options = [(label, action) for label, action in self.ACTIONS if action in pack.animations]
        self.choice = ChoiceButton("预览动作", options, self.show_action)
        controls.addWidget(self.choice)
        self.frame_info = label("", "caption")
        controls.addWidget(self.frame_info)
        controls.addStretch()
        self.play_button = button("暂停", self.toggle_playback, "secondary")
        self.sprite.finished.connect(lambda: self.play_button.setText("重播"))
        self.play_button.setMinimumWidth(60)
        controls.addWidget(self.play_button)
        self.body.addLayout(controls)
        self.show_action(self.choice.value)
        self.finished.connect(self.sprite.timer.stop)

    def show_action(self, action):
        _, _, fps = self.pack.animations[action]
        frames = self.pack.action_frames(action)
        loop = action in ("idle", "run_left", "run_right", "lifted", "sleeping", "running")
        loop_start = self.pack.lifted_loop_start if action == "lifted" else 0
        self.sprite.set_clip(frames, fps, loop=loop, loop_start=loop_start)
        animated = len(frames) > 1
        self.frame_info.setText(f"{len(frames)} 帧 · {fps} fps" if animated else "单帧")
        self.play_button.setEnabled(animated)
        self.play_button.setText("暂停" if animated else "播放")

    def toggle_playback(self):
        if self.sprite.timer.isActive():
            self.sprite.timer.stop()
            self.play_button.setText("播放")
        else:
            if self.sprite.ended:
                self.sprite.restart()
            else:
                self.sprite.timer.start()
            self.play_button.setText("暂停")


class Workspace(QWidget):
    def __init__(self, studio):
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.studio = studio
        self.pet_names = []
        self.note_cards = {}
        self.selected_note_id = None
        self.checked_notes = set()
        self.filter_index = 0
        self.tag_filter = None
        self.setWindowTitle("桌宠便签")
        self.setWindowIcon(icon("note", "#dedede", 32))
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAcceptDrops(True)
        self.setStyleSheet(STYLE + WORKSPACE_STYLE)
        screen = studio.app.primaryScreen().availableGeometry()
        self.setMinimumSize(min(screen.width(), 884), min(screen.height(), 568))
        self.resize(min(screen.width(), 1080), min(screen.height(), 700))

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.shell = WorkspaceShell()
        shell = self.shell
        outer.addWidget(shell)
        layout = QVBoxLayout(shell)
        layout.setContentsMargins(9, 0, 8, 8)
        layout.setSpacing(0)
        layout.addLayout(self.title_bar())
        body = QHBoxLayout()
        body.setSpacing(9)
        body.addWidget(self.sidebar())
        self.pages = QStackedWidget()
        self.pages.addWidget(self.note_page())
        self.pages.addWidget(self.pet_page())
        body.addWidget(self.pages, 1)
        layout.addLayout(body, 1)
        self.size_grip = QSizeGrip(self)
        self.size_grip.setFixedSize(18, 16)
        self.move(screen.center() - QPoint(self.width() // 2, self.height() // 2))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.size_grip.move(self.width() - self.size_grip.width() - 2, self.height() - self.size_grip.height() - 2)
        self.size_grip.raise_()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            self.shell.snow.sync()

    def title_bar(self):
        row = QHBoxLayout()
        row.setContentsMargins(3, 0, 0, 0)
        row.setSpacing(4)
        drag = DragArea()
        drag.setFixedHeight(43)
        drag_layout = QHBoxLayout(drag)
        drag_layout.setContentsMargins(6, 0, 0, 0)
        drag_layout.setSpacing(8)
        mark = label()
        mark.setPixmap(icon("note", "#dedede", 18).pixmap(18, 18))
        name = label("桌宠便签", "libraryTitle")
        for item in (mark, name):
            item.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            drag_layout.addWidget(item)
        drag_layout.addStretch()
        row.addWidget(drag, 1)
        for glyph, text, action, role in (("hide", "最小化", self.showMinimized, "libraryIcon"),
                                          ("close", "关闭面板", self.close, "libraryClose")):
            control = button("", action, role, glyph, text, color="#bdbdbd")
            control.setFixedSize(34, 28)
            row.addWidget(control)
        return row

    def sidebar(self):
        rail = QWidget()
        rail.setFixedWidth(188)
        layout = QVBoxLayout(rail)
        layout.setContentsMargins(1, 12, 1, 1)
        layout.setSpacing(9)
        title = label("工作区", "libraryMeta")
        title.setContentsMargins(10, 1, 0, 2)
        layout.addWidget(title)
        nav_zone = QWidget()
        nav_layout = QVBoxLayout(nav_zone)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(4)
        self.nav_glide = GlideHighlight(nav_zone, radius=10)
        self.group = QButtonGroup(self)
        for page, (text, glyph) in enumerate((("全部便签", "list"), ("桌宠设置", "pet"))):
            nav = button(" " + text, lambda _, p=page: self.change_page(p),
                         "libraryNav", glyph, color="#bdbdbd")
            nav.setCheckable(True)
            nav.setAccessibleName(text)
            self.group.addButton(nav, page)
            nav_layout.addWidget(nav)
            self.nav_glide.watch(nav)
        self.group.button(0).setChecked(True)
        layout.addWidget(nav_zone)
        layout.addStretch()

        shortcut = frame("libraryPetShortcut")
        row = QHBoxLayout(shortcut)
        row.setContentsMargins(10, 9, 8, 9)
        row.setSpacing(7)
        self.sidebar_avatar = label()
        self.sidebar_avatar.setFixedSize(28, 28)
        self.sidebar_avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self.sidebar_avatar)
        pet_info = QVBoxLayout()
        pet_info.setSpacing(1)
        pet_info.addWidget(self.character_name("libraryText"))
        self.pet_status = label("", "libraryMeta")
        pet_info.addWidget(self.pet_status)
        row.addLayout(pet_info, 1)
        self.pet_toggle = button("", self.studio.toggle_pet, "librarySecondary")
        row.addWidget(self.pet_toggle)
        layout.addWidget(shortcut)
        credit = label(APP_PUBLISHER, "publisherCredit")
        credit.setContentsMargins(10, 0, 0, 0)
        layout.addWidget(credit)
        return rail

    def note_page(self):
        page = QWidget()
        columns = QHBoxLayout(page)
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(8)
        center = frame("libraryCenter")
        root = QVBoxLayout(center)
        root.setContentsMargins(12, 11, 12, 9)
        root.setSpacing(10)
        bar = QHBoxLayout()
        bar.setSpacing(8)
        bar.addWidget(label("便签库", "libraryTitle"))
        bar.addStretch()
        self.search = QLineEdit(objectName="librarySearch")
        self.search.setPlaceholderText("搜索标题、正文或标签")
        self.search.setAccessibleName("搜索便签")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(126)
        self.search.setMaximumWidth(240)
        self.search.addAction(icon("search", "#bdbdbd", 16), QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(self.refresh)
        bar.addWidget(self.search, 1)
        add = button("新建便签", self.studio.new_note, "libraryAction", "plus", color="#dedede")
        bar.addWidget(add)
        root.addLayout(bar)

        toolbar = QHBoxLayout()
        tabs = frame("libraryTabs")
        toggle = QHBoxLayout(tabs)
        toggle.setContentsMargins(3, 3, 3, 3)
        toggle.setSpacing(2)
        self.note_filters = QButtonGroup(self)
        for index, text in enumerate(("全部", "在桌面", "未显示", "已归档")):
            tab = button(text, lambda _, i=index: self.filter_notes(i), "libraryTab")
            tab.setCheckable(True)
            self.note_filters.addButton(tab, index)
            toggle.addWidget(tab)
        self.note_filters.button(0).setChecked(True)
        toolbar.addWidget(tabs)
        self.tag_filter_button = button("标签 · 全部", self.choose_tag_filter, "libraryTagFilter",
                                        "tag", "按标签筛选", color="#d6d6d6")
        toolbar.addWidget(self.tag_filter_button)
        toolbar.addStretch()
        self.summary = label("", "libraryMeta")
        toolbar.addWidget(self.summary)
        root.addLayout(toolbar)

        scroll = QScrollArea(objectName="libraryScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.viewport().setAutoFillBackground(False)
        self.notes_container = QWidget(objectName="noteList")
        self.note_list = QGridLayout(self.notes_container)
        self.note_list.setContentsMargins(0, 2, 3, 2)
        self.note_list.setHorizontalSpacing(10)
        self.note_list.setVerticalSpacing(10)
        self.note_list.setColumnStretch(0, 1)
        self.note_list.setColumnStretch(1, 1)
        self.note_glide = GlideHighlight(self.notes_container, radius=14)
        scroll.setWidget(self.notes_container)
        root.addWidget(scroll, 1)
        local = QHBoxLayout()
        local.setSpacing(6)
        dot = frame("localIndicator")
        dot.setFixedSize(5, 5)
        dot.setStyleSheet("background: #939393; border: none; border-radius: 2px;")
        local.addWidget(dot)
        local.addWidget(label("本地保存", "libraryMeta"))
        local.addStretch()
        self.selection_count = label("", "libraryMeta")
        self.selection_count.hide()
        local.addWidget(self.selection_count)
        self.selection_button = button("", self.toggle_selection, "librarySelect", "select", "选择便签",
                                       color="#dedede")
        self.selection_button.setCheckable(True)
        self.delete_button = button("", self.delete_checked_notes, "libraryDelete", "trash", "删除选中的便签",
                                    color="#dedede")
        self.delete_button.setEnabled(False)
        for control in (self.selection_button, self.delete_button):
            control.setFixedSize(36, 31)
            local.addWidget(control)
        root.addLayout(local)
        details = self.note_details()
        columns.addWidget(center, 1)
        columns.addWidget(details)
        return page

    def note_details(self):
        aside = frame("libraryDetails")
        aside.setFixedWidth(228)
        layout = QVBoxLayout(aside)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)
        layout.addWidget(label("便签详情", "libraryTitle"))
        self.detail_pages = QStackedWidget()
        no_selection = QWidget()
        empty_layout = QVBoxLayout(no_selection)
        empty_layout.setSpacing(8)
        empty_layout.addStretch()
        mark = label()
        mark.setPixmap(icon("note", "#727272", 32).pixmap(32, 32))
        empty_layout.addWidget(mark, alignment=Qt.AlignmentFlag.AlignHCenter)
        empty_layout.addWidget(label("选择一张便签", "libraryMeta"), alignment=Qt.AlignmentFlag.AlignHCenter)
        empty_layout.addStretch()
        self.detail_pages.addWidget(no_selection)

        selected = QWidget()
        detail = QVBoxLayout(selected)
        detail.setContentsMargins(0, 0, 0, 0)
        detail.setSpacing(9)
        rule = frame("libraryRule")
        rule.setFixedHeight(1)
        detail.addWidget(rule)
        self.detail_title = label("", "libraryDetailTitle")
        self.detail_title.setWordWrap(True)
        detail.addWidget(self.detail_title)
        self.detail_status = label("", "libraryMeta")
        detail.addWidget(self.detail_status)
        self.detail_tags = ElidedLabel("", "libraryTags")
        detail.addWidget(self.detail_tags)
        self.detail_text = QPlainTextEdit(objectName="libraryDetailText")
        self.detail_text.setReadOnly(True)
        self.detail_text.viewport().setAutoFillBackground(False)
        self.detail_text.setAccessibleName("便签正文预览")
        detail.addWidget(self.detail_text, 1)
        actions = QHBoxLayout()
        actions.addWidget(button("打开便签", self.open_selected_note, "libraryAction", "open", color="#dedede"), 1)
        edit_tags = button("", self.edit_selected_tags, "libraryAction", "tag", "编辑标签", color="#dedede")
        edit_tags.setFixedWidth(35)
        actions.addWidget(edit_tags)
        detail.addLayout(actions)
        self.detail_pages.addWidget(selected)
        layout.addWidget(self.detail_pages, 1)
        return aside

    def pet_page(self):
        page = frame("libraryPet")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(24, 18, 24, 16)
        outer.setSpacing(8)
        heading = QHBoxLayout()
        heading.addWidget(label("桌宠设置", "libraryHeading"), 1)
        self.active_pet_toggle = button("", self.studio.toggle_pet, "characterControl")
        heading.addWidget(self.active_pet_toggle)
        outer.addLayout(heading)
        scroll = QScrollArea(objectName="characterPageScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.viewport().setAutoFillBackground(False)
        body = QWidget(objectName="characterPageBody")
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        root = QVBoxLayout(body)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(11)
        preview = QVBoxLayout()
        preview.setContentsMargins(0, 12, 0, 20)
        preview.setSpacing(3)
        self.active_artwork = PetArtwork(self.studio.pet, 140)
        preview.addWidget(self.active_artwork, alignment=Qt.AlignmentFlag.AlignHCenter)
        name = self.character_name("libraryDetailTitle")
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview.addWidget(name)
        self.active_pet_status = label("", "libraryMeta")
        preview.addWidget(self.active_pet_status, alignment=Qt.AlignmentFlag.AlignHCenter)
        root.addLayout(preview)

        library_header = QHBoxLayout()
        library_header.setSpacing(8)
        library_header.addWidget(label("我的桌宠", "libraryTitle"))
        self.character_count = label("", "libraryMeta")
        library_header.addWidget(self.character_count)
        library_header.addStretch()
        library_header.addWidget(button("导出角色工具包", self.studio.export_character_toolkit, "characterControl"))
        library_header.addWidget(button("导入角色 ZIP", self.studio.choose_character_file, "characterControl",
                                        "plus", "导入角色 ZIP，也可拖入此窗口", color="#dedede"))
        root.addLayout(library_header)
        self.character_grid = CharacterGrid(self.studio)
        root.addWidget(self.character_grid)
        self.empty_library = label("把角色 ZIP 拖到这里，或点击「导入角色 ZIP」", "characterEmpty")
        self.empty_library.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_library.setFixedHeight(84)
        root.addWidget(self.empty_library)

        root.addWidget(label("行为设置", "libraryTitle"))
        settings = frame("characterBehavior")
        grid = QVBoxLayout(settings)
        grid.setContentsMargins(14, 10, 14, 10)
        grid.setSpacing(7)
        pet = self.studio.pet
        self.pet_options = {}
        for key, caption, values, apply in (
            ("size", "桌宠大小", [("小（25%）", .25), ("中（50%）", .5), ("大（75%）", .75)], pet._apply_scale),
            ("personality", "桌宠性格", [("友好", "friendly"), ("安静", "focused"), ("活泼", "playful")], pet._apply_personality),
        ):
            line = QHBoxLayout()
            line.addWidget(label(caption, "libraryText"), 1)
            control = ChoiceButton(caption, values, apply)
            line.addWidget(control)
            grid.addLayout(line)
            rule = frame("libraryRule")
            rule.setFixedHeight(1)
            grid.addWidget(rule)
            self.pet_options[key] = control
        moving = SoftSwitch("自动走动")
        moving.toggled.connect(pet.apply_movement)
        self.pet_options["moving"] = moving
        grid.addWidget(moving, alignment=Qt.AlignmentFlag.AlignLeft)
        root.addWidget(settings)

        root.addWidget(label("备份与恢复", "libraryTitle"))
        backup = frame("characterBehavior")
        actions = QHBoxLayout(backup)
        actions.setContentsMargins(14, 12, 14, 12)
        actions.setSpacing(8)
        caption = label("便签、桌宠和设置一起带走。", "libraryMeta")
        caption.setWordWrap(True)
        actions.addWidget(caption, 1)
        actions.addWidget(button("导出备份", self.studio.export_backup, "characterControl"))
        actions.addWidget(button("从备份还原", self.studio.restore_backup, "characterControl"))
        root.addWidget(backup)
        root.addStretch()
        return page

    def change_page(self, page):
        self.pages.setCurrentIndex(page)
        self.group.button(page).setChecked(True)
        if page == 1:
            self.refresh_library()
        self.refresh()

    def filter_notes(self, index):
        self.filter_index = index
        self.refresh()

    def set_tag_filter(self, key):
        self.tag_filter = key
        self.refresh()

    def choose_tag_filter(self):
        anchor = self.tag_filter_button
        menu = RoundedMenu(anchor)
        tags = self.studio.known_tags()
        options = [(None, "全部标签"), *tags.items()]
        for key, name in options:
            action = menu.addAction(name.replace("&", "&&"), lambda _, value=key: self.set_tag_filter(value))
            action.setCheckable(True)
            action.setChecked(key == self.tag_filter)
        if not tags:
            menu.addAction("还没有标签").setEnabled(False)
        try:
            menu.exec(anchor.mapToGlobal(QPoint(0, anchor.height() + 4)))
        finally:
            menu.deleteLater()

    def refresh_tag_filter(self):
        tags = self.studio.known_tags()
        if self.tag_filter not in tags:
            self.tag_filter = None
        caption = "标签 · " + tags.get(self.tag_filter, "全部")
        control = self.tag_filter_button
        control.setText(control.fontMetrics().elidedText(caption, Qt.TextElideMode.ElideRight, 88))
        control.setToolTip(caption if self.tag_filter else "按标签筛选")
        control.setAccessibleName(caption)

    def character_name(self, role):
        widget = ElidedLabel(self.studio.pet._name, role)
        self.pet_names.append(widget)
        return widget

    def refresh_character(self):
        pet = self.studio.pet
        for widget in self.pet_names:
            widget.setText(pet._name)
            widget.setToolTip(pet._name)
        self.active_artwork.setAccessibleName(pet._name)
        self.active_artwork.update()
        self.sidebar_avatar.setPixmap(pet._frames[0][0].scaled(
            27, 27, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        self.character_grid.set_active(pet._zip_path)
        visible = pet.isVisible()
        self.pet_status.setText("在桌面上" if visible else "已收起" if pet.has_character else "可导入 ZIP")
        self.pet_toggle.setText("收起" if visible else "显示" if pet.has_character else "导入")
        toggle = "收起桌宠" if visible else "显示桌宠" if pet.has_character else "导入角色"
        self.pet_toggle.setAccessibleName(toggle)
        self.active_pet_toggle.setText(toggle)
        self.active_pet_toggle.setVisible(pet.has_character)
        self.active_pet_status.setText("在桌面上" if visible else "已收起" if pet.has_character else "导入后可在桌面显示")

    def refresh_library(self):
        self.character_grid.refresh(self.studio.pet.character_paths())
        count = len(self.character_grid.cards)
        self.character_count.setText(f"{count} 个角色")
        self.character_grid.setVisible(count > 0)
        self.empty_library.setVisible(count == 0)
        self.character_grid.set_active(self.studio.pet._zip_path)

    def open_selected_note(self):
        note = self.studio.store.records.get(self.selected_note_id)
        if note is not None:
            self.studio.show_note(note)

    def edit_selected_tags(self):
        note = self.studio.store.records.get(self.selected_note_id)
        if note is not None:
            self.studio.edit_note_tags(note)

    def select_note(self, note):
        self.selected_note_id = note.id if note is not None else None
        self.update_selection()
        self.detail_pages.setCurrentIndex(1 if note is not None else 0)
        if note is not None:
            self.detail_title.setText(note.label)
            self.detail_status.setText(note_state(note))
            show_note_tags(self.detail_tags, note.tags)
            text = note.textContent or "空白便签"
            if self.detail_text.toPlainText() != text:
                self.detail_text.setPlainText(text)

    def activate_note(self, note):
        if self.selection_button.isChecked():
            if note.id in self.checked_notes:
                self.checked_notes.remove(note.id)
            else:
                self.checked_notes.add(note.id)
        self.select_note(note)

    def toggle_selection(self, enabled):
        if not enabled:
            self.checked_notes.clear()
        self.update_selection()

    def update_selection(self):
        selecting = self.selection_button.isChecked()
        for note_id, card in self.note_cards.items():
            checked = note_id in self.checked_notes
            card.set_batch_selection(selecting, checked)
            card.set_selected(checked if selecting else note_id == self.selected_note_id)
        count = len(self.checked_notes)
        self.selection_count.setText(f"已选 {count} 张")
        self.selection_count.setVisible(selecting)
        self.delete_button.setEnabled(selecting and count > 0)
        text = "退出选择" if selecting else "选择便签"
        self.selection_button.setToolTip(text)
        self.selection_button.setAccessibleName(text)

    def delete_checked_notes(self):
        selected = [card.note for note_id, card in self.note_cards.items() if note_id in self.checked_notes]
        if self.studio.ask_delete_notes(selected):
            self.selection_button.setChecked(False)
            self.toggle_selection(False)

    @staticmethod
    def dropped_zip(event):
        mime = event.mimeData()
        urls = mime.urls() if mime.hasUrls() else []
        if len(urls) == 1 and urls[0].isLocalFile():
            path = Path(urls[0].toLocalFile())
            if path.suffix.lower() == ".zip":
                return path
        return None

    def dragEnterEvent(self, event):
        if self.dropped_zip(event) is not None:
            event.acceptProposedAction()

    def dropEvent(self, event):
        path = self.dropped_zip(event)
        if path is not None:
            event.acceptProposedAction()
            self.change_page(1)
            self.studio.inspect_character(path)

    def refresh(self):
        self.refresh_character()
        self.refresh_tag_filter()
        notes = self.studio.sorted_notes()
        search = tag_key(self.search.text().strip())
        def matches_filter(note):
            state = (True, note.visible, not note.visible and not note.archived, note.archived)[self.filter_index]
            return state and (self.tag_filter is None or any(tag_key(name) == self.tag_filter for name in note.tags))

        shown = [note for note in notes
                 if matches_filter(note)
                 and (not search or search in tag_key("\n".join((note.label, note.textContent, *note.tags))))]
        filtering = bool(search or self.filter_index or self.tag_filter)
        self.checked_notes.intersection_update(note.id for note in shown)
        self.summary.setText(f"{len(shown)} / {len(notes)} 张" if filtering else f"{len(notes)} 张便签")
        self.note_glide.clear()
        clear_widgets(self.note_list)
        self.note_cards.clear()
        if not shown:
            message = "没有匹配的便签" if filtering else "还没有便签"
            empty = label(message, "libraryMeta")
            empty.setContentsMargins(0, 30, 0, 6)
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.note_list.addWidget(empty, 0, 0, 1, 2)
        else:
            for index, note in enumerate(shown):
                card = NoteCard(self.studio, note, self.activate_note)
                self.note_cards[note.id] = card
                self.note_list.addWidget(card, index // 2, index % 2)
                for target in (card, card.open_button, card.more_button):
                    self.note_glide.watch(target)
        rows = max(1, (len(shown) + 1) // 2)
        self.note_list.addItem(QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding),
                               rows, 0, 1, 2)
        selected = self.studio.store.records.get(self.selected_note_id) if self.selected_note_id in self.note_cards else None
        self.select_note(selected)

        for key, value in (("size", self.studio.pet._scale), ("personality", self.studio.pet._ps.personality)):
            self.pet_options[key].select(value)
        movement = self.pet_options["moving"]
        movement.blockSignals(True)
        movement.setChecked(self.studio.pet._ps.moving)
        movement.blockSignals(False)

    def closeEvent(self, event):
        if not self.studio.quitting:
            event.ignore()
            self.hide()
        else:
            event.accept()


class DeskWorkspace:
    def __init__(self, app, pet, notes_file, tray=True, hotkeys=True):
        self.app, self.pet = app, pet
        self.pet.menu_requested.connect(self.show_pet_menu)
        self.pet.note_library_requested.connect(self.open_note_library)
        self.store = NoteStore(notes_file)
        self.windows = {}
        self.quitting = False
        self.current_id = None
        self.dirty = False
        self.last_fed_note = None
        self.undo_popup = None
        self.undo_timer = QTimer(interval=7500, singleShot=True)
        self.undo_timer.timeout.connect(self.hide_feed_undo)
        self.paper_feed = PaperFeed(self)
        self.edge_notes = EdgeNotes(self)
        self.panel = Workspace(self)
        self.pet.character_changed.connect(self.panel.refresh_character)
        self.commit = QTimer(interval=360, singleShot=True)
        self.commit.timeout.connect(self.flush)
        self.refresh_timer = QTimer(interval=110, singleShot=True)
        self.refresh_timer.timeout.connect(self.refresh_notes)
        self.hotkeys = DesktopHotkeys(self) if hotkeys else None
        self.tray = None
        self.tray_menu = None
        if tray and QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(icon("note", "#d1d1d1", 32), app)
            self.tray.setToolTip("桌宠便签")
            self.tray.activated.connect(self.tray_activated)
            self.refresh_tray()
            self.tray.show()
        self.edge_notes.refresh()
        for note in self.active_notes():
            if note.visible:
                self.show_note(note, focus=False)
        self.app.aboutToQuit.connect(self.shutdown)
        self.panel.refresh()

    def sorted_notes(self):
        return sorted(self.store.records.values(), key=lambda note: note.updatedAt, reverse=True)

    def known_tags(self):
        tags = {}
        for note in self.store.records.values():
            for name in note.tags:
                tags.setdefault(tag_key(name), name)
        return dict(sorted(tags.items()))

    def active_notes(self):
        return [note for note in self.sorted_notes() if not note.archived]

    def changed(self, refresh=True):
        self.dirty = True
        self.commit.start()
        if refresh:
            self.refresh_timer.start()

    def refresh_notes(self):
        self.refresh_timer.stop()
        self.panel.refresh()
        self.edge_notes.refresh()

    def flush(self):
        if not self.dirty:
            return True
        if not self.save_notes():
            return False
        self.refresh_tray()
        return True

    def save_notes(self, records=None):
        try:
            self.store.save(records)
        except OSError as error:
            show_warning(self.panel, "便签保存失败", str(error))
            return False
        self.commit.stop()
        self.dirty = False
        for window in self.windows.values():
            window.set_save_pending(False)
        return True

    def commit_records(self, records):
        if not self.save_notes(records):
            return False
        self.store.records = records
        return True

    def new_note(self, *, edge=None, screen=None):
        screen = screen or self.app.screenAt(QCursor.pos()) or self.app.primaryScreen()
        if edge is None:
            home_screen, home_edge = self.edge_notes.home_rail()
            edge = home_edge if screen is home_screen else "right"
        area = screen.availableGeometry()
        offset = (len(self.store.records) % 8) * 22
        note = Note(x=area.right() - 520, y=area.top() + 52 + offset, edge=edge, edgeScreen=screen.name())
        self.store.records[note.id] = note
        self.show_note(note).set_save_pending(True)
        self.changed()
        return note

    def show_note(self, note, focus=True):
        if note.id not in self.windows:
            self.windows[note.id] = StickyWindow(self, note)
        window = self.windows[note.id]
        needs_save = not note.visible or note.collapsed or note.archived
        note.visible = True
        note.collapsed = note.archived = False
        if note.edge and not window.isVisible():
            self.edge_notes.refresh()
            self.edge_notes.position(window, reveal_tab=True)
        if focus:
            self.current_id = note.id
        if not focus:
            window.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        window.show()
        window.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
        self.edge_notes.update_tab(note)
        if focus:
            window.raise_()
            window.activateWindow()
            window.editor.setFocus()
        if needs_save:
            self.changed()
        return window

    def next_note(self):
        notes = self.active_notes()
        if not notes:
            self.new_note()
            return
        ids = [note.id for note in notes]
        index = (ids.index(self.current_id) + 1) % len(ids) if self.current_id in ids else 0
        self.show_note(notes[index])

    def open_note_library(self):
        self.open_panel(page=0)

    def ask_delete(self, note, parent=None):
        return self.ask_delete_notes((note,), parent)

    def ask_delete_notes(self, notes, parent=None):
        if not notes:
            return False
        dialog = SheetDialog("删除便签", parent or self.panel)
        dialog.setFixedWidth(397)
        message = QHBoxLayout()
        message.setSpacing(10)
        badge = label("", "alertBadge")
        badge.setFixedSize(30, 30)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setPixmap(icon("alert", "#414141", 18).pixmap(18, 18))
        message.addWidget(badge, alignment=Qt.AlignmentFlag.AlignTop)
        copy = QVBoxLayout()
        copy.setSpacing(5)
        if len(notes) == 1:
            title = notes[0].label
            caption = title[:45] + ("…" if len(title) > 45 else "")
            prompt = f"要删除「{caption}」吗？"
        else:
            prompt = f"要删除选中的 {len(notes)} 张便签吗？"
        text = label(prompt, "dialogBody")
        text.setWordWrap(True)
        copy.addWidget(text)
        copy.addWidget(label("删除后无法恢复。", "dialogDetail"))
        message.addLayout(copy, 1)
        dialog.body.addLayout(message)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addStretch()
        cancel = button("取消", dialog.reject, "secondary")
        cancel.setMinimumWidth(72)
        cancel.setDefault(True)
        row.addWidget(cancel)
        delete = button("删除", dialog.accept, "danger")
        delete.setMinimumWidth(72)
        row.addWidget(delete)
        dialog.body.addLayout(row)
        try:
            accepted = bool(dialog.exec())
        finally:
            dialog.deleteLater()
        return accepted and self.delete_notes(notes)

    def delete_notes(self, notes):
        records = self.store.records.copy()
        removed = [note for note in notes if records.get(note.id) is note]
        if not removed:
            return False
        for note in removed:
            records.pop(note.id)
        if not self.commit_records(records):
            return False
        for note in removed:
            self.close_note_window(note)
        self.refresh_notes()
        self.refresh_tray()
        return True

    def archive_note(self, note):
        note.archived = True
        note.clear_dock()
        window = self.windows.get(note.id)
        if window:
            window.update_style()
            window.close()
        note.visible = note.collapsed = False
        self.edge_notes.refresh()
        self.changed()

    def collapse_notes(self, notes):
        records = self.store.records.copy()
        updates = []
        for note in notes:
            if records.get(note.id) is not note or not note.on_desktop:
                continue
            window = self.windows.get(note.id)
            changes = {"visible": False, "collapsed": True}
            if window is not None and window.isVisible():
                x, y, width, height = window.geometry().getRect()
                changes.update(x=x, y=y, width=width, height=height)
            records[note.id] = replace(note, **changes)
            updates.append((note, window, changes))
        if not updates or not self.save_notes(records):
            return
        self.paper_feed.cancel()
        for note, window, changes in updates:
            for key, value in changes.items():
                setattr(note, key, value)
            if window is not None:
                window.hide()
        self.refresh_notes()
        self.refresh_tray()

    def collapse_desktop_notes(self):
        self.collapse_notes(self.store.records.values())

    def close_note_window(self, note):
        window = self.windows.pop(note.id, None)
        if window:
            window.hide()
            window.deleteLater()
        if self.current_id == note.id:
            self.current_id = None

    def save_feed_change(self, note, *, restoring):
        # Prepare the new state before saving, including the original tab order if saving fails.
        records = self.store.records.copy()
        if restoring:
            records[note.id] = note
        else:
            records.pop(note.id)
        return self.commit_records(records)

    def feed_note(self, note):
        if self.store.records.get(note.id) is not note or not self.save_feed_change(note, restoring=False):
            return False
        self.last_fed_note = note
        self.close_note_window(note)
        self.refresh_notes()
        self.refresh_tray()
        return True

    def undo_feed(self):
        note = self.last_fed_note
        if note is None or not self.save_feed_change(note, restoring=True):
            return
        self.last_fed_note = None
        self.hide_feed_undo()
        if note.visible:
            self.show_note(note, focus=False)
        self.refresh_notes()
        self.refresh_tray()

    def show_feed_undo(self):
        if self.last_fed_note is None or not self.pet.isVisible():
            return
        if self.undo_popup is None:
            popup = self.undo_popup = QWidget(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                                               Qt.WindowType.WindowStaysOnTopHint |
                                               Qt.WindowType.WindowDoesNotAcceptFocus)
            popup.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            popup.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
            popup.setStyleSheet(STYLE + WORKSPACE_STYLE)
            outer = QVBoxLayout(popup)
            outer.setContentsMargins(0, 0, 0, 0)
            panel = frame("feedUndo")
            row = QHBoxLayout(panel)
            row.setContentsMargins(10, 5, 5, 5)
            row.setSpacing(8)
            row.addWidget(label("便签已删除", "libraryText"))
            row.addWidget(button("撤销", self.undo_feed, "librarySecondary"))
            outer.addWidget(panel)
        popup = self.undo_popup
        popup.adjustSize()
        area = self.pet.screen().availableGeometry()
        target = self.pet.geometry()
        x = min(max(area.left(), target.center().x() - popup.width() // 2), area.right() + 1 - popup.width())
        y = target.top() - popup.height() - 7
        if y < area.top():
            y = min(target.bottom() + 8, area.bottom() + 1 - popup.height())
        popup.move(x, y)
        popup.show()
        self.undo_timer.start()

    def hide_feed_undo(self):
        self.undo_timer.stop()
        if self.undo_popup is not None:
            self.undo_popup.hide()

    def note_actions(self, note, anchor):
        menu = RoundedMenu(anchor)
        menu.addAction("恢复并打开" if note.archived else "打开便签", lambda: self.show_note(note))
        menu.addAction(icon("tag", "#dedede", 17), "编辑标签", lambda: self.edit_note_tags(note))
        if note.on_desktop:
            menu.addAction("收起便签", lambda: self.collapse_notes((note,)))
        menu.addSeparator()
        menu.addAction("删除便签", lambda: self.ask_delete(note))
        menu.exec(anchor.mapToGlobal(QPoint(0, anchor.height() + 4)))
        menu.deleteLater()

    def edit_note_tags(self, note, parent=None):
        dialog = TagEditor(note, self.known_tags(), parent or self.panel)
        try:
            if not dialog.exec():
                return
            tags = list(dialog.tags.values())
        finally:
            dialog.deleteLater()
        if tags == note.tags or self.store.records.get(note.id) is not note:
            return
        records = {**self.store.records, note.id: replace(note, tags=tags)}
        if self.save_notes(records):
            note.tags = tags
            self.refresh_notes()

    def open_panel(self, *, page=None):
        if page is None:
            self.panel.refresh()
        else:
            self.panel.change_page(page)
        self.panel.showNormal()
        self.panel.raise_()
        self.panel.activateWindow()

    def choose_character_file(self):
        selected = pick_file(self.panel, "导入角色 ZIP", "角色压缩包 (*.zip)")
        if selected:
            self.inspect_character(Path(selected))

    def character_actions(self, path, name, anchor):
        menu = RoundedMenu(anchor)
        menu.addAction("动作预览", lambda: self.preview_character_actions(path))
        menu.addSeparator()
        menu.addAction(icon("trash", "#dedede", 17), "删除角色",
                       lambda: self.ask_delete_character(path, name))
        try:
            menu.exec(anchor.mapToGlobal(QPoint(0, anchor.height() + 4)))
        finally:
            menu.deleteLater()

    def preview_character_actions(self, path):
        try:
            package = read_package(path)
        except ValueError as error:
            show_warning(self.panel, "无法预览角色", str(error))
            return
        preview = CharacterActions(package, self.panel)
        try:
            preview.exec()
        finally:
            preview.deleteLater()

    def ask_delete_character(self, path, name):
        paths = self.pet.character_paths()
        if path not in paths:
            self.panel.refresh_library()
            return False

        active = path == self.pet._zip_path
        next_path, next_character = None, None
        if active:
            index = paths.index(path)
            for candidate in (*paths[index + 1:], *reversed(paths[:index])):
                try:
                    next_character = self.pet.load_character(candidate)
                except CHARACTER_LOAD_ERRORS:
                    continue
                next_path = candidate
                break
            if next_path is not None:
                outcome = f"删除后将切换到「{next_character[0]}」。"
            else:
                outcome = "删除后没有可使用的角色，桌宠会收起。"
        else:
            outcome = "当前使用的角色不会改变。"

        dialog = SheetDialog("删除角色", self.panel)
        dialog.setFixedWidth(416)
        prompt = label(f"要删除「{name}」吗？", "dialogBody")
        prompt.setWordWrap(True)
        dialog.body.addWidget(prompt)
        detail = label(outcome + "\n将移除角色库中的 ZIP。其他位置的 ZIP 和便签会保留。", "dialogDetail")
        detail.setWordWrap(True)
        dialog.body.addWidget(detail)
        actions = QHBoxLayout()
        actions.addStretch()
        cancel = button("取消", dialog.reject, "secondary")
        cancel.setDefault(True)
        actions.addWidget(cancel)
        actions.addWidget(button("删除角色", dialog.accept, "danger"))
        dialog.body.addLayout(actions)
        try:
            accepted = bool(dialog.exec())
        finally:
            dialog.deleteLater()
        if not accepted:
            return False

        try:
            path.unlink()
        except OSError as error:
            show_warning(self.panel, "角色删除失败", str(error))
            return False
        if active:
            self.paper_feed.cancel()
            self.pet._switch_pet(next_path, loaded=next_character)
        self.panel.refresh_library()
        self.refresh_tray()
        return True

    def export_character_toolkit(self):
        root = Path(__file__).resolve().parent
        source = root / "角色制作工具包.zip"
        if not source.is_file():
            source = root.parents[1] / "outputs" / "角色制作工具包.zip"
        selected = pick_file(self.panel, "导出角色工具包", "ZIP (*.zip)", suggested_name=source.name)
        if selected:
            try:
                copyfile(source, selected)
            except OSError as error:
                show_warning(self.panel, "工具包导出失败", str(error))

    def save_backup_file(self, destination):
        write_backup(destination, self.store.records, self.pet.backup_preferences(),
                     self.pet.character_paths(), self.pet._zip_path)

    def export_backup(self):
        chosen = pick_file(self.panel, "导出备份", "桌宠便签备份 (*.zip)", suggested_name=backup_filename())
        if not chosen or not self.flush():
            return
        destination = Path(chosen)
        try:
            if destination.suffix.lower() != ".zip":
                raise ValueError("备份文件名请使用 .zip 后缀。")
            if destination.resolve().is_relative_to(self.pet.library.resolve()):
                raise ValueError("请把备份保存到角色库以外的文件夹。")
            self.save_backup_file(destination)
        except (OSError, ValueError) as error:
            show_warning(self.panel, "导出备份失败", str(error))
            return
        show_warning(self.panel, "备份已导出", str(destination))

    def confirm_restore(self, snapshot):
        dialog = SheetDialog("从备份还原", self.panel)
        dialog.setFixedWidth(408)
        date = snapshot.created_at.astimezone().strftime("%Y-%m-%d %H:%M")
        dialog.body.addWidget(label(f"{len(snapshot.records)} 张便签  ·  {len(snapshot.roles)} 个角色", "section"))
        dialog.body.addWidget(label(f"备份日期  {date}", "muted"))
        warning = label("整套还原会替换当前的便签、角色和设置。确认后会先自动保存一份还原前备份。", "dialogBody")
        warning.setWordWrap(True)
        dialog.body.addWidget(warning)
        row = QHBoxLayout()
        row.addStretch()
        cancel = button("取消", dialog.reject, "secondary")
        cancel.setDefault(True)
        row.addWidget(cancel)
        row.addWidget(button("确认还原", dialog.accept, "danger"))
        dialog.body.addLayout(row)
        try:
            return bool(dialog.exec())
        finally:
            dialog.deleteLater()

    def fit_restored_notes(self, records):
        screens = {screen.name(): screen for screen in self.app.screens()}
        primary = self.app.primaryScreen()
        # Keep imported integers in range before constructing Qt geometry.
        limit = 1 << 28
        for note in records.values():
            x, y = (max(-limit, min(limit, value)) for value in (note.x, note.y))
            screen = screens.get(note.edgeScreen) or self.app.screenAt(QPoint(x, y)) or primary
            rect = fit_to_desktop(QRect(x, y, min(limit, note.width), min(limit, note.height)), screen)
            note.x, note.y, note.width, note.height = rect.getRect()
            if note.edge:
                note.edgeScreen = screen.name()

    def restore_backup(self):
        chosen = pick_file(self.panel, "选择桌宠便签备份", "桌宠便签备份 (*.zip)")
        if not chosen:
            return
        data_dir = self.pet.library.parent
        try:
            with staging_folder(data_dir) as folder:
                snapshot = stage_backup(Path(chosen), Path(folder))
                if not self.confirm_restore(snapshot) or not self.flush():
                    return
                self.fit_restored_notes(snapshot.records)
                incoming = snapshot.root / "incoming" / "library"
                selected = snapshot.selected
                loaded = self.pet.load_character(incoming / selected if selected else None,
                                                 scale=snapshot.preferences["pet_scale"])
                safety_folder = data_dir / "backups"
                safety_folder.mkdir(exist_ok=True)
                safety = safety_folder / backup_filename("还原前备份", unique=True)
                self.save_backup_file(safety)
                apply_backup(data_dir, snapshot)
        except RestorePendingError as error:
            show_warning(self.panel, "还原中断", str(error))
            self.app.quit()
            return
        except CHARACTER_LOAD_ERRORS as error:
            show_warning(self.panel, "无法还原备份", str(error))
            return
        self.reload_restored_data(snapshot, loaded)
        show_warning(self.panel, "备份已还原", f"还原前的数据已保存在\n{safety}")

    def reload_restored_data(self, snapshot, loaded):
        self.paper_feed.cancel()
        self.hide_feed_undo()
        self.last_fed_note = None
        self.edge_notes.hide()
        for note in self.store.records.values():
            self.close_note_window(note)
        self.store.records = snapshot.records
        self.current_id = None
        self.commit.stop()
        self.dirty = False
        selected = self.pet.library / snapshot.selected if snapshot.selected else None
        self.pet.apply_restored_preferences(snapshot.preferences, selected, loaded)
        self.edge_notes.load_layout()
        self.edge_notes.refresh()
        for note in self.active_notes():
            if note.visible:
                self.show_note(note, focus=False)
        self.panel.character_grid.snapshot = None
        self.panel.refresh_library()
        self.panel.selected_note_id = None
        self.panel.selection_button.setChecked(False)
        self.panel.checked_notes.clear()
        self.refresh_notes()
        self.refresh_tray()

    def inspect_character(self, path):
        try:
            package = read_package(path)
            preview = CharacterPreview(package, package.target(self.pet.library).exists(), self.panel)
            try:
                accepted = bool(preview.exec())
                save_as_new = preview.save_as_new
            finally:
                preview.deleteLater()
            if accepted:
                if save_as_new:
                    package = package.as_new(self.pet.library)
                installed = package.install(self.pet.library)
                self.panel.refresh_library()
                self.select_character(installed, reload=True)
        except (ValueError, OSError) as error:
            show_warning(self.panel, "角色导入失败", str(error))

    def select_character(self, path, *, reload=False):
        try:
            if reload or path != self.pet._zip_path:
                self.paper_feed.cancel()
                self.pet._switch_pet(path)
            self.pet.show()
        except CHARACTER_LOAD_ERRORS as error:
            show_warning(self.panel, "角色切换失败", str(error))
        self.panel.refresh_character()
        self.refresh_tray()

    def toggle_pet(self):
        if not self.pet.has_character:
            self.choose_character_file()
            return
        self.paper_feed.cancel()
        self.hide_feed_undo()
        self.pet.setVisible(not self.pet.isVisible())
        self.panel.refresh_character()
        self.refresh_tray()

    def tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.open_panel()

    def refresh_tray(self):
        if self.tray is None:
            return
        old_menu = self.tray_menu
        menu = RoundedMenu()
        self.populate_menu(menu, header=False)
        self.tray.setContextMenu(menu)
        self.tray_menu = menu
        if old_menu is not None:
            old_menu.deleteLater()

    def pet_menu(self):
        menu = RoundedMenu(self.pet)
        self.populate_menu(menu, header=True)
        return menu

    def show_pet_menu(self, position):
        menu = self.pet_menu()
        try:
            menu.exec(position)
        finally:
            menu.deleteLater()

    def populate_menu(self, menu, header):
        if header:
            hero = QWidget()
            hero_layout = QHBoxLayout(hero)
            hero_layout.setContentsMargins(8, 4, 8, 8)
            hero_layout.setSpacing(8)
            avatar = label()
            avatar.setPixmap(self.pet._frames[0][0].scaled(30, 32, Qt.AspectRatioMode.KeepAspectRatio,
                                                           Qt.TransformationMode.SmoothTransformation))
            hero_layout.addWidget(avatar)
            info = QVBoxLayout()
            info.setSpacing(2)
            info.addWidget(label(self.pet._name, "menuTitle"))
            info.addWidget(label("桌宠便签", "menuCaption"))
            hero_layout.addLayout(info, 1)
            item = QWidgetAction(menu)
            item.setDefaultWidget(hero)
            menu.addAction(item)
            menu.addSeparator()
        menu.addAction(icon("plus", "#dedede", 18), "新建便签", self.new_note)
        menu.addAction(icon("open", "#dedede", 17), "打开管理面板", self.open_panel)
        sub = menu.submenu("我的便签", icon("list", "#dedede", 17))
        self.populate_note_choices(sub)
        if self.last_fed_note is not None:
            menu.addAction("撤销上次投喂", self.undo_feed)
        menu.addSeparator()
        if header:
            options = self.pet.build_settings_menu(menu, RoundedMenu, self.select_character)
            options.setIcon(icon("pet", "#dedede", 17))
            options.setTitle("宠物设置")
            menu.addMenu(options)
        text = "收起桌宠" if self.pet.isVisible() else "显示桌宠" if self.pet.has_character else "导入角色"
        menu.addAction(text, self.toggle_pet)
        menu.addAction("收起便签", self.collapse_desktop_notes)
        menu.addSeparator()
        menu.addAction("退出应用", self.quit)

    def populate_note_choices(self, menu):
        notes = self.active_notes()
        if not notes:
            menu.addAction("还没有便签").setEnabled(False)
        for note in notes:
            title = note.label[:31] + ("…" if len(note.label) > 31 else "")
            accent = "#f0f0f0" if note.collapsed else "#c9c9c9"
            action = menu.addAction(icon("note", accent, 17), title.replace("&", "&&"))
            action.setToolTip(note.label)
            action.triggered.connect(lambda _, n=note: self.show_note(n))

    def quit(self):
        if self.flush():
            self.app.quit()

    def shutdown(self):
        if self.quitting:
            return
        self.quitting = True
        self.paper_feed.cancel()
        self.hide_feed_undo()
        self.edge_notes.hide()
        self.commit.stop()
        self.flush()
        if self.hotkeys is not None:
            self.hotkeys.close()
        if self.tray is not None:
            self.tray.hide()

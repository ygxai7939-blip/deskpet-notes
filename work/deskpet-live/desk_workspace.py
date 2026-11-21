"""The common DeskPet window, note controller, tray, and pet context menu."""
import ctypes
from ctypes import wintypes
from pathlib import Path
from shutil import copyfile

from PySide6.QtCore import QAbstractNativeEventFilter, QEvent, QPoint, QRectF, QTimer, Qt
from PySide6.QtGui import QColor, QCursor, QImage, QPainter, QPainterPath, QPixmap, QRadialGradient
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QScrollArea, QSizeGrip, QSizePolicy, QSpacerItem, QStackedWidget, QSystemTrayIcon,
    QVBoxLayout, QWidget, QWidgetAction,
)

from desk_style import (
    ChoiceButton, DragArea, GlideHighlight, RoundedMenu, SheetDialog, SoftSwitch, STYLE,
    button, icon, label, show_warning,
)
from edge_notes import EdgeNotes
from file_picker import pick_file
from paper_feed import PaperFeed
from pet_packages import read_package
from pixel_snow import PixelSnow
from sticky_store import Note, NoteStore
from sticky_window import StickyWindow
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
    if note.edge:
        return "已贴边"
    return "已收回" if note.collapsed else "已隐藏"


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
        painter.drawText(rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)


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
        preview.setFixedHeight(111)
        preview.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        panel.addWidget(preview)
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
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        size = self.width()
        circle = QRectF(size * .10, size * .09, size * .80, size * .80)
        halo = QRadialGradient(circle.center(), size * .42)
        halo.setColorAt(0, QColor("#484848"))
        halo.setColorAt(1, QColor("#353535"))
        painter.setBrush(halo)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(circle)
        sprite = self.pet._frames[0][0]
        scaled = sprite.scaled(round(size * .68), round(size * .74),
                               Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        painter.drawPixmap((size - scaled.width()) // 2, (size - scaled.height()) // 2 - 2, scaled)


class CharacterPreview(SheetDialog):
    def __init__(self, pack, updating, parent):
        super().__init__("角色预览", parent)
        self.setMinimumWidth(372)
        surface = frame("feature")
        artwork = QVBoxLayout(surface)
        sprite = label()
        sprite.setFixedSize(136, 140)
        sprite.setAlignment(Qt.AlignmentFlag.AlignCenter)
        artwork.addWidget(sprite, alignment=Qt.AlignmentFlag.AlignCenter)
        self.body.addWidget(surface)
        name = label(pack.name, "section")
        name.setWordWrap(True)
        self.body.addWidget(name)
        if pack.description:
            detail = label(pack.description, "muted")
            detail.setWordWrap(True)
            self.body.addWidget(detail)
        caption = "待机预览 · 更新同一角色" if updating else "待机预览"
        self.body.addWidget(label(caption, "caption"))
        pixmaps = []
        for tile in pack.idle_frames:
            raw = tile.tobytes("raw", "RGBA")
            pixels = QImage(raw, tile.width, tile.height, QImage.Format.Format_RGBA8888).copy()
            pixmaps.append(QPixmap.fromImage(pixels).scaled(
                sprite.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        position = 0
        sprite.setPixmap(pixmaps[position])

        def advance():
            nonlocal position
            position = (position + 1) % len(pixmaps)
            sprite.setPixmap(pixmaps[position])

        self.timer = QTimer(self, interval=165)
        self.timer.timeout.connect(advance)
        self.finished.connect(lambda _: self.timer.stop())
        if len(pixmaps) > 1:
            self.timer.start()
        actions = QHBoxLayout()
        actions.addStretch()
        cancel = button("取消", self.reject)
        cancel.setDefault(True)
        actions.addWidget(cancel)
        actions.addWidget(button("更新并使用" if updating else "安装并使用", self.accept, "primary"))
        self.body.addLayout(actions)


class Workspace(QWidget):
    def __init__(self, studio):
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.studio = studio
        self.pet_names = []
        self.artworks = []
        self.note_cards = {}
        self.selected_note_id = None
        self.checked_notes = set()
        self.filter_index = 0
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
        self.search.setPlaceholderText("搜索便签标题或正文")
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
        toolbar.addStretch()
        self.summary = label("", "libraryMeta")
        toolbar.addWidget(self.summary)
        root.addLayout(toolbar)

        scroll = QScrollArea()
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
        self.detail_text = QPlainTextEdit(objectName="libraryDetailText")
        self.detail_text.setReadOnly(True)
        self.detail_text.viewport().setAutoFillBackground(False)
        self.detail_text.setAccessibleName("便签正文预览")
        detail.addWidget(self.detail_text, 1)
        detail.addWidget(button("打开便签", self.open_selected_note, "libraryAction", "open", color="#dedede"))
        self.detail_pages.addWidget(selected)
        layout.addWidget(self.detail_pages, 1)
        return aside

    def pet_page(self):
        page = frame("libraryPet")
        root = QVBoxLayout(page)
        root.setContentsMargins(17, 16, 17, 16)
        root.setSpacing(14)
        root.addWidget(label("桌宠设置", "libraryHeading"))
        card = frame("librarySettings")
        content = QHBoxLayout(card)
        content.setContentsMargins(13, 8, 18, 8)
        content.addWidget(self.artwork(157))
        info = QVBoxLayout()
        info.setSpacing(6)
        info.addStretch()
        info.addWidget(self.character_name("libraryDetailTitle"))
        info.addWidget(label("双击桌宠打开便签卡片", "libraryMeta"))
        info.addSpacing(5)
        info.addWidget(button("导入角色 ZIP", self.studio.choose_character_file, "libraryAction", "plus", color="#dedede"),
                       alignment=Qt.AlignmentFlag.AlignLeft)
        info.addWidget(button("导出角色工具包", self.studio.export_character_toolkit, "librarySecondary"),
                       alignment=Qt.AlignmentFlag.AlignLeft)
        info.addWidget(label("也可以把 ZIP 拖到这里", "libraryMeta"))
        info.addStretch()
        content.addLayout(info, 1)
        root.addWidget(card)
        root.addWidget(label("行为设置", "libraryTitle"))
        settings = frame("librarySettings")
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
        root.addStretch()
        return page

    def change_page(self, page):
        self.pages.setCurrentIndex(page)
        self.group.button(page).setChecked(True)
        self.refresh()

    def filter_notes(self, index):
        self.filter_index = index
        self.refresh()

    def artwork(self, size):
        widget = PetArtwork(self.studio.pet, size)
        self.artworks.append(widget)
        return widget

    def character_name(self, role):
        widget = ElidedLabel(self.studio.pet._name, role)
        self.pet_names.append(widget)
        return widget

    def refresh_character(self):
        pet = self.studio.pet
        for widget in self.pet_names:
            widget.setText(pet._name)
            widget.setToolTip(pet._name)
        for widget in self.artworks:
            widget.setAccessibleName(pet._name)
            widget.update()
        self.sidebar_avatar.setPixmap(pet._frames[0][0].scaled(
            27, 27, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def open_selected_note(self):
        note = self.studio.store.records.get(self.selected_note_id)
        if note is not None:
            self.studio.show_note(note)

    def select_note(self, note):
        self.selected_note_id = note.id if note is not None else None
        self.update_selection()
        self.detail_pages.setCurrentIndex(1 if note is not None else 0)
        if note is not None:
            self.detail_title.setText(note.label)
            self.detail_status.setText(note_state(note))
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
        visible = self.studio.pet.isVisible()
        self.pet_status.setText("在桌面上" if visible else "已收起" if self.studio.pet.has_character else "可导入 ZIP")
        self.pet_toggle.setText("收起" if visible else "显示" if self.studio.pet.has_character else "导入")
        self.pet_toggle.setAccessibleName("收起桌宠" if visible else "显示桌宠" if self.studio.pet.has_character else "导入角色")
        notes = self.studio.sorted_notes()
        search = self.search.text().strip().casefold()
        def matches_filter(note):
            return (True, note.visible, not note.visible and not note.archived, note.archived)[self.filter_index]

        shown = [note for note in notes
                 if matches_filter(note)
                 and (not search or search in (note.label + "\n" + note.textContent).casefold())]
        self.checked_notes.intersection_update(note.id for note in shown)
        self.summary.setText(f"{len(shown)} / {len(notes)} 张" if search or self.filter_index else f"{len(notes)} 张便签")
        self.note_glide.clear()
        clear_widgets(self.note_list)
        self.note_cards.clear()
        if not shown:
            message = "没有匹配的便签" if search or self.filter_index else "还没有便签"
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
        if note.visible:
            menu.addAction("隐藏到列表", lambda: self.windows[note.id].close())
            menu.addAction("折叠回宠物", lambda: self.windows[note.id].fold_into_pet())
        menu.addSeparator()
        menu.addAction("删除便签", lambda: self.ask_delete(note))
        menu.exec(anchor.mapToGlobal(QPoint(0, anchor.height() + 4)))
        menu.deleteLater()

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

    def inspect_character(self, path):
        try:
            package = read_package(path)
            preview = CharacterPreview(package, package.target(self.pet.library).exists(), self.panel)
            try:
                accepted = bool(preview.exec())
            finally:
                preview.deleteLater()
            if accepted:
                self.pet._switch_pet(package.install(self.pet.library))
                if not self.pet.isVisible():
                    self.pet.show()
                self.panel.refresh()
                self.refresh_tray()
        except (ValueError, OSError) as error:
            show_warning(self.panel, "角色导入失败", str(error))

    def toggle_pet(self):
        if not self.pet.has_character:
            self.choose_character_file()
            return
        self.paper_feed.cancel()
        self.hide_feed_undo()
        self.pet.setVisible(not self.pet.isVisible())
        self.panel.refresh()
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
            options = self.pet.build_settings_menu(menu, RoundedMenu)
            options.setIcon(icon("pet", "#dedede", 17))
            options.setTitle("宠物设置")
            menu.addMenu(options)
        text = "收起桌宠" if self.pet.isVisible() else "显示桌宠" if self.pet.has_character else "导入角色"
        menu.addAction(text, self.toggle_pet)
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

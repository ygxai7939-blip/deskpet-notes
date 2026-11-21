"""Desktop-edge tabs for notes that have been docked."""
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFilter
from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFontMetrics, QImage, QLinearGradient, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QApplication, QAbstractButton, QScrollArea, QVBoxLayout, QWidget

from desk_style import button
from edge_drag import EdgeDragPreview


TAB_WIDTH = 46
TAB_HEIGHT = 178
TAB_STEP = 130
SNAP_DISTANCE = 30
LAYOUT_PREFERENCE = "note_edge_layout"
TAB_RADIUS = 12


def tab_face(right):
    return QRectF(12 if right else -13, 5, TAB_WIDTH + 1, TAB_HEIGHT - 11)


@lru_cache(maxsize=2)
def tab_shadow(right):
    padding = 15
    mask = Image.new("L", (TAB_WIDTH + padding * 2, TAB_HEIGHT + padding * 2))
    face = tab_face(right).translated(padding + (-2 if right else 2), padding + 3)
    ImageDraw.Draw(mask).rounded_rectangle(
        (int(face.left()), int(face.top()), int(face.right()), int(face.bottom())), TAB_RADIUS, fill=110)
    alpha = mask.filter(ImageFilter.GaussianBlur(4.5)).crop(
        (padding, padding, padding + TAB_WIDTH, padding + TAB_HEIGHT))
    image = Image.new("RGBA", alpha.size)
    image.putalpha(alpha)
    qt_image = QImage(image.tobytes(), TAB_WIDTH, TAB_HEIGHT, QImage.Format.Format_RGBA8888).copy()
    return QPixmap.fromImage(qt_image)


class NoteTab(QAbstractButton):
    def __init__(self, note, edge, activate, parent):
        super().__init__(parent)
        self.edge = edge
        self.setFixedSize(TAB_WIDTH, TAB_HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(activate)
        self.update_note(note)

    def update_note(self, note):
        self.title = note.label
        self.tone = QColor(note.paper_tone)
        self.opened = note.visible
        self.setAccessibleName(f"{'收起' if self.opened else '打开'}便签 {self.title}")
        self.setToolTip(f"{self.title}\n拖动可移动标签栏")
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        width, height = self.width(), self.height()
        right = self.edge == "right"
        center = QPoint(width // 2, height // 2)
        painter.translate(center)
        painter.rotate(-3 if right else 3)
        painter.translate(-center)
        inward = -1 if right else 1
        painter.drawPixmap(0, 0, tab_shadow(right))
        path = QPainterPath()
        path.addRoundedRect(tab_face(right), TAB_RADIUS, TAB_RADIUS)
        fill = QLinearGradient(0, 0, width, 0)
        tone = self.tone.lighter(107) if self.underMouse() else self.tone
        fill.setColorAt(0 if right else 1, tone.lighter(104))
        fill.setColorAt(1 if right else 0, tone.darker(110))
        painter.fillPath(path, fill)
        painter.translate(width / 2 - inward * 6, TAB_STEP / 2)
        painter.rotate(90 if right else -90)
        font = self.font()
        font.setPixelSize(12)
        font.setBold(self.opened or self.underMouse())
        painter.setFont(font)
        painter.setPen(QColor("#332c3b"))
        title = QFontMetrics(font).elidedText(self.title, Qt.TextElideMode.ElideRight, TAB_STEP - 26)
        painter.drawText(QRectF(-TAB_STEP / 2, -11, TAB_STEP, 22), Qt.AlignmentFlag.AlignCenter, title)


class EdgeRail(QWidget):
    def __init__(self, controller, screen, edge):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.NoDropShadowWindowHint)
        self.controller, self.screen_ref, self.edge = controller, screen, edge
        self.setWindowTitle("桌面边缘便签")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedWidth(TAB_WIDTH)
        self.pressed_button = None
        self.dragging = False
        self.previewing = False
        body = QVBoxLayout(self)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(7)
        self.scroll = QScrollArea()
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.viewport().setAutoFillBackground(False)
        self.track = QWidget()
        self.scroll.setWidget(self.track)
        self.track.setAutoFillBackground(False)
        body.addWidget(self.scroll)
        self.add_note = button("＋", lambda: controller.studio.new_note(edge=self.edge, screen=self.screen_ref),
                               tip="新建贴边便签 · 拖动可移动标签栏")
        self.add_note.setAccessibleName("新建贴边便签")
        self.add_note.setFixedSize(29, 29)
        self.add_note.installEventFilter(self)
        self.add_note.setStyleSheet("""
            QPushButton { color:#e9e9e9; background:#343434; border:1px solid #585858;
                          border-radius:14px; font: 600 17px "Segoe UI"; padding:0; }
            QPushButton:hover { background:#494949; }
        """)
        body.addWidget(self.add_note, alignment=Qt.AlignmentFlag.AlignRight if edge == "right"
                       else Qt.AlignmentFlag.AlignLeft)
        self.tabs = {}

    def eventFilter(self, watched, event):
        kind = event.type()
        if (kind in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick)
                and event.button() == Qt.MouseButton.LeftButton):
            self.pressed_button = watched
            self.press_point = event.globalPosition().toPoint()
            self.drag_offset = self.press_point - self.pos()
        elif watched is self.pressed_button:
            if kind == QEvent.Type.MouseMove and event.buttons() & Qt.MouseButton.LeftButton:
                return self.drag_to(event.globalPosition().toPoint())
            if kind == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
                point = event.globalPosition().toPoint()
                moved = self.drag_to(point)
                self.end_drag()
                if moved:
                    self.controller.rail_dropped(self, point)
                    return True
            elif kind in (QEvent.Type.UngrabMouse, QEvent.Type.Hide):
                moved = self.dragging
                self.end_drag()
                if moved:
                    QTimer.singleShot(0, self.controller.refresh)
        return super().eventFilter(watched, event)

    def drag_to(self, point):
        if not self.dragging:
            if (point - self.press_point).manhattanLength() < QApplication.startDragDistance():
                return False
            self.dragging = True
            self.original_cursor = self.pressed_button.cursor()
            self.pressed_button.setCursor(Qt.CursorShape.ClosedHandCursor)
            self.pressed_button.setDown(False)
            self.previewing = self.controller.drag_preview.begin(self.controller.studio, self, self.pressed_button, point)
            if self.previewing:
                self.setWindowOpacity(.04)
        if self.previewing:
            self.controller.drag_preview.follow(point)
        else:
            self.move(point - self.drag_offset)
        return True

    def end_drag(self):
        if self.dragging:
            self.pressed_button.setCursor(self.original_cursor)
        if self.previewing:
            self.controller.drag_preview.finish()
            self.setWindowOpacity(1.)
            self.previewing = False
        self.pressed_button = None
        self.dragging = False

    def update_notes(self, notes):
        if self.dragging:
            return
        order = tuple(note.id for note in notes)
        if order != tuple(self.tabs):
            for tab in self.tabs.values():
                tab.hide()
                tab.deleteLater()
            self.tabs.clear()
            for index, note in enumerate(notes):
                tab = NoteTab(note, self.edge,
                              lambda _=False, note_id=note.id: self.controller.open_tab(note_id), self.track)
                tab.installEventFilter(self)
                self.tabs[note.id] = tab
                tab.move(0, index * TAB_STEP)
                tab.show()
        else:
            for note in notes:
                self.tabs[note.id].update_note(note)
        area = self.screen_ref.availableGeometry()
        track_height = (len(notes) - 1) * TAB_STEP + TAB_HEIGHT if notes else 0
        # The scroll area starts empty, so its track must be sized as tabs arrive.
        self.track.setFixedSize(TAB_WIDTH, track_height)
        self.scroll.setVisible(bool(notes))
        if notes:
            self.scroll.setFixedHeight(min(track_height, max(80, area.height() - 94)))
        self.adjustSize()
        self.layout().activate()
        self.snap_to_edge()
        if not self.isVisible():
            self.show()

    def snap_to_edge(self):
        area = self.screen_ref.availableGeometry()
        anchor = self.controller.anchor(self.screen_ref, self.edge)
        center = area.top() + round(anchor * (area.height() - 1))
        y = min(max(area.top(), center - self.height() // 2), area.bottom() + 1 - self.height())
        x = area.left() if self.edge == "left" else area.right() + 1 - self.width()
        self.move(x, max(area.top(), y))


class EdgeNotes:
    def __init__(self, studio):
        self.studio = studio
        self.rails = {}
        self.drag_preview = EdgeDragPreview()
        layout = studio.pet.preference(LAYOUT_PREFERENCE)
        self.layout = layout if isinstance(layout, dict) else {}
        anchors = self.layout.get("anchors")
        self.anchors = {name: sides.copy() for name, sides in anchors.items() if isinstance(sides, dict)} \
            if isinstance(anchors, dict) else {}
        app = studio.app
        app.screenAdded.connect(self.watch_screen)
        app.screenRemoved.connect(lambda _: QTimer.singleShot(0, self.refresh))
        app.primaryScreenChanged.connect(lambda _: self.refresh())
        for screen in app.screens():
            self.watch_screen(screen)

    def watch_screen(self, screen):
        screen.availableGeometryChanged.connect(lambda _: self.refresh())

    def screen_for(self, note):
        return next((screen for screen in self.studio.app.screens() if screen.name() == note.edgeScreen),
                    self.studio.app.screenAt(QPoint(note.x, note.y)) or self.studio.app.primaryScreen())

    def home_rail(self):
        app = self.studio.app
        screen = next((item for item in app.screens() if item.name() == self.layout.get("screen")),
                      app.primaryScreen())
        edge = "left" if self.layout.get("edge") == "left" else "right"
        return screen, edge

    def anchor(self, screen, edge):
        value = self.anchors.get(screen.name(), {}).get(edge)
        return value if isinstance(value, (float, int)) and 0 <= value <= 1 else .5

    def note_rail(self, note):
        return self.screen_for(note), note.edge

    def refresh(self):
        if self.studio.quitting:
            return
        primary = self.studio.app.primaryScreen()
        if primary is None:
            return
        groups = {self.home_rail(): []}
        for note in self.studio.store.records.values():
            if note.edge and not note.archived:
                groups.setdefault(self.note_rail(note), []).append(note)
        for key in self.rails.keys() - groups.keys():
            rail = self.rails.pop(key)
            rail.end_drag()
            rail.hide()
            rail.deleteLater()
        for (screen, side), notes in groups.items():
            key = screen, side
            if key not in self.rails:
                self.rails[key] = EdgeRail(self, screen, side)
            self.rails[key].update_notes(notes)

    def open_tab(self, note_id):
        note = self.studio.store.records.get(note_id)
        if note is None or not note.edge or note.archived:
            return
        window = self.studio.windows.get(note_id)
        if window is not None and window.isVisible():
            window.close()
        else:
            self.studio.show_note(note)

    def update_tab(self, note):
        if note.edge:
            rail = self.rails.get(self.note_rail(note))
            tab = rail.tabs.get(note.id) if rail is not None else None
            if tab is not None:
                tab.update_note(note)

    def rail_dropped(self, rail, point):
        previous = rail.screen_ref, rail.edge
        screen = self.studio.app.screenAt(point) or rail.screen_ref
        area = screen.availableGeometry()
        edge = "left" if point.x() < area.center().x() else "right"
        target = screen, edge
        center = point.y() - rail.drag_offset.y() + rail.height() // 2
        fraction = (center - area.top()) / max(1, area.height() - 1)
        self.anchors.setdefault(screen.name(), {})[edge] = min(1., max(0., fraction))
        if previous == self.home_rail():
            self.layout.update(screen=screen.name(), edge=edge)
        self.layout["anchors"] = self.anchors
        self.studio.pet.set_preference(LAYOUT_PREFERENCE, self.layout)

        changed = False
        if target != previous:
            for note in self.studio.store.records.values():
                if not note.archived and note.edge and self.note_rail(note) == previous:
                    note.edge, note.edgeScreen = edge, screen.name()
                    changed = True
                    window = self.studio.windows.get(note.id)
                    if window is not None:
                        window.update_style()
        self.refresh()
        for note in self.studio.store.records.values():
            window = self.studio.windows.get(note.id)
            if note.visible and note.edge and window is not None and self.note_rail(note) == target:
                self.position(window)
        if changed:
            self.studio.changed()

    def dropped(self, window, point):
        screen = self.studio.app.screenAt(point) or window.screen()
        area = screen.availableGeometry()
        rect = window.geometry()
        # Measure inward from the dock line. Crossing it still counts as touching it.
        left_gap = max(0, min(point.x() - area.left(), rect.left() - (area.left() + TAB_WIDTH)))
        right_gap = max(0, min(area.right() - point.x(), (area.right() - TAB_WIDTH) - rect.right()))
        if min(left_gap, right_gap) > SNAP_DISTANCE:
            window.detach()
            return
        if left_gap == right_gap:
            edge = "left" if point.x() <= area.center().x() else "right"
        else:
            edge = "left" if left_gap < right_gap else "right"
        self.attach(window, edge, screen)

    def attach(self, window, edge, screen):
        note = window.note
        note.edge, note.edgeScreen = edge, screen.name()
        window.update_style()
        self.refresh()
        self.position(window, reveal_tab=True)
        self.studio.changed()

    def position(self, window, *, reveal_tab=False):
        note = window.note
        if not note.edge:
            return
        screen = self.screen_for(note)
        area = screen.availableGeometry()
        width = min(window.width(), max(window.minimumWidth(), area.width() - TAB_WIDTH))
        height = min(window.height(), area.height())
        rail = self.rails.get((screen, note.edge))
        tab = rail.tabs.get(note.id) if rail else None
        if tab is not None and reveal_tab:
            rail.scroll.ensureWidgetVisible(tab, 0, 4)
        y = tab.mapToGlobal(QPoint(TAB_WIDTH // 2, TAB_STEP // 2)).y() - 38 if tab and tab.visibleRegion() else note.y
        x = area.left() + TAB_WIDTH if note.edge == "left" else area.right() + 1 - TAB_WIDTH - width
        window.setGeometry(QRect(x, min(max(y, area.top()), area.bottom() + 1 - height), width, height))

    def hide(self):
        for rail in self.rails.values():
            rail.end_drag()
            rail.hide()

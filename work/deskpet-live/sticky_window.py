"""Qt desktop note, adapted to the DeskStickyNotes model and window behavior."""
from math import pi, sin
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QPointF, QRect, QRectF, Qt, Signal, QVariantAnimation
from PySide6.QtGui import (
    QColor, QFont, QFontMetrics, QMouseEvent, QPainter, QPalette, QPen, QShortcut, QKeySequence,
    QTextBlockFormat, QTextCursor, QTextListFormat,
)
from PySide6.QtWidgets import (
    QApplication, QAbstractButton, QFrame, QHBoxLayout, QLineEdit, QPlainTextEdit,
    QSizeGrip, QTextEdit, QVBoxLayout, QWidget,
)

from desk_style import (
    DragArea, RoundedMenu, SheetDialog, STYLE, button, icon, icon_button, label,
    neutral_font, paint_paper_spine, show_warning,
)
from file_picker import pick_file
from sticky_store import MIN_HEIGHT, MIN_WIDTH, NOTE_TONES, PASTEL_TONES, normalize_title, now


PAPER_STYLE = """
QLineEdit#noteHeading {
  color: #302739; background: transparent; border: none; border-radius: 7px;
  font-size: 15px; font-weight: 700; padding: 0 2px;
}
QLineEdit#noteHeading:focus { background: rgba(255, 255, 255, 48); }
QTextEdit#noteBody {
  color: #302739; background: transparent; border: none; padding: 0;
  selection-color: #302739; selection-background-color: rgba(255, 255, 255, 144);
}
QPushButton#noteAction {
  background: rgba(48, 36, 59, 16); border: none; border-radius: 6px; padding: 0;
}
QPushButton#noteAction:hover, QPushButton#noteAction:pressed { background: rgba(48, 36, 59, 38); }
QFrame#noteToolbar { background: rgba(255, 255, 255, 49); border: none; border-radius: 8px; }
QLineEdit#noteSearch {
  color: #302739; background: rgba(255, 255, 255, 110); border: none;
  border-radius: 7px; min-height: 24px; padding: 0 6px;
}
"""


def fit_to_desktop(rect, screen):
    """Port of DeskStickyNotes NoteWindowGeometry.FitToWorkArea."""
    work = screen.availableGeometry()
    width, height = min(rect.width(), work.width()), min(rect.height(), work.height())
    x = min(max(rect.x(), work.x()), work.x() + work.width() - width)
    y = min(max(rect.y(), work.y()), work.y() + work.height() - height)
    return QRect(x, y, width, height)


class RichEditor(QTextEdit):
    checklist_completed = Signal()
    unchecked = QTextBlockFormat.MarkerType.Unchecked
    checked = QTextBlockFormat.MarkerType.Checked

    def __init__(self):
        super().__init__()
        self.pressed_checkbox = None
        self.spring_block = None
        self.spring = QVariantAnimation(self, duration=250)
        curve = QEasingCurve(QEasingCurve.Type.OutBack)
        curve.setOvershoot(1.05)
        self.spring.setEasingCurve(curve)
        self.spring.valueChanged.connect(lambda _value: self.viewport().update())
        self.spring.finished.connect(self.finish_spring)

    def finish_spring(self):
        self.spring_block = None
        self.viewport().update()

    def checklist_at_cursor(self):
        selection = self.textCursor()
        block = selection.block()
        cursor = QTextCursor(block)
        fmt = cursor.blockFormat()
        if fmt.marker() in (self.unchecked, self.checked):
            self.toggle_check(cursor)
        else:
            cursor.beginEditBlock()
            if not cursor.currentList():
                options = QTextListFormat()
                options.setStyle(QTextListFormat.Style.ListDisc)
                cursor.createList(options)
            fmt = cursor.blockFormat()
            fmt.setMarker(self.unchecked)
            cursor.setBlockFormat(fmt)
            cursor.endEditBlock()
        self.setTextCursor(selection)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.pressed_checkbox = self.checkbox_at(event.position())
            if self.pressed_checkbox is not None:
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.pressed_checkbox is not None and event.buttons() & Qt.MouseButton.LeftButton:
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.pressed_checkbox = self.checkbox_at(event.position())
            if self.pressed_checkbox is not None:
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            super().mouseReleaseEvent(event)
            return
        pressed = self.pressed_checkbox
        self.pressed_checkbox = None
        if pressed is not None:
            if pressed == self.checkbox_at(event.position()):
                self.toggle_check(QTextCursor(pressed))
            event.accept()
            return

        # Qt also toggles native markers on release. Its hit area reaches the
        # first character, so forward text releases just past that area.
        horizontal = self.horizontalScrollBar()
        x = horizontal.maximum() - horizontal.value() if self.isRightToLeft() else horizontal.value()
        point = event.position() + QPointF(x, self.verticalScrollBar().value())
        layout = self.document().documentLayout()
        if not layout.blockWithMarkerAt(point).isValid():
            super().mouseReleaseEvent(event)
            return
        step = 1
        while layout.blockWithMarkerAt(point + QPointF(step, 0)).isValid():
            step *= 2
        delta = QPointF(step, 0)
        release = QMouseEvent(event.type(), event.position() + delta, event.scenePosition() + delta,
                              event.globalPosition(), event.button(), event.buttons(), event.modifiers(),
                              event.source(), event.pointingDevice())
        release.setTimestamp(event.timestamp())
        super().mouseReleaseEvent(release)
        event.setAccepted(release.isAccepted())

    def checkbox_at(self, point):
        cursor = self.cursorForPosition(point.toPoint())
        block = cursor.block()
        if block.blockFormat().marker() not in (self.unchecked, self.checked):
            return None
        caret = self.cursorRect(QTextCursor(block))
        box = self.check_box(block, caret)
        rtl = block.textDirection() == Qt.LayoutDirection.RightToLeft
        if box is None:
            x = caret.right() + 1 if rtl else caret.left() - 24
            hit = QRectF(x, caret.top(), 24, caret.height())
        else:
            hit = box.adjusted(-2, 0, 2, 0)
        if rtl:
            hit.setLeft(max(hit.left(), caret.right() + 1))
        else:
            hit.setRight(min(hit.right(), caret.left() - 1))
        return block if hit.contains(point) else None

    def toggle_check(self, cursor):
        block = cursor.block()
        fmt = cursor.blockFormat()
        was_checked = fmt.marker() == self.checked
        start = self.spring.currentValue() if self.spring_block == block else float(was_checked)
        self.spring.stop()
        self.spring_block = None
        fmt.setMarker(self.unchecked if was_checked else self.checked)
        cursor.setBlockFormat(fmt)
        if QApplication.isEffectEnabled(Qt.UIEffect.UI_General):
            self.spring_block = block
            self.spring.setStartValue(start)
            self.spring.setEndValue(float(not was_checked))
            self.spring.start()
        self.viewport().update()
        if not was_checked and not self.has_unchecked_item():
            self.checklist_completed.emit()

    def has_unchecked_item(self):
        block = self.document().begin()
        while block.isValid():
            if block.blockFormat().marker() == self.unchecked:
                return True
            block = block.next()
        return False

    def check_box(self, block, caret):
        text_list = block.textList()
        layout = block.layout()
        if text_list is None or not layout.lineCount() or text_list.format().style() not in (
            QTextListFormat.Style.ListDisc, QTextListFormat.Style.ListSquare, QTextListFormat.Style.ListCircle,
        ):
            return None
        metrics = QFontMetrics(block.charFormat().font(), self.viewport())
        line = layout.lineAt(0)
        gap = metrics.horizontalAdvance(" ") + metrics.lineSpacing() / 3
        rhs = block.textDirection() == Qt.LayoutDirection.RightToLeft
        x = caret.x() + gap if rhs else caret.x() - gap
        y = caret.top() + line.ascent() - metrics.ascent() + metrics.height() / 2
        side = max(14., metrics.lineSpacing() * .84)
        return QRectF(x - side / 2, y - side / 2, side, side)

    def paintEvent(self, event):
        super().paintEvent(event)
        dirty = event.rect()
        block = self.cursorForPosition(QPoint(0, max(0, dirty.top() - 20))).block()
        painter = QPainter(self.viewport())
        painter.setClipRect(dirty)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        while block.isValid():
            caret = self.cursorRect(QTextCursor(block))
            if caret.y() > dirty.bottom() + 14:
                break
            marker = block.blockFormat().marker()
            if marker in (self.unchecked, self.checked):
                box = self.check_box(block, caret)
                if box is not None:
                    progress = self.spring.currentValue() if self.spring_block == block else float(marker == self.checked)
                    self.paint_check(painter, block, caret, box, progress)
            block = block.next()

    def paint_check(self, painter, block, caret, box, progress):
        fill = min(1., max(0., progress))
        background = block.blockFormat().background()
        if background.style() == Qt.BrushStyle.NoBrush:
            background = self.viewport().palette().brush(QPalette.ColorRole.Base)
        painter.fillRect(box.adjusted(-1, -1, 1, 1), background)
        bounce = .08 * sin(pi * fill) + min(.08, abs(progress - fill))
        stretch = box.width() * bounce / 2
        box.adjust(-stretch, -stretch, stretch, stretch)
        painter.setPen(QPen(QColor("#6a6a6a"), 1.15))
        painter.setBrush(background)
        painter.drawRoundedRect(box, box.width() * .27, box.width() * .27)
        if fill <= 0:
            return
        painter.save()
        painter.setOpacity(fill)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#383838"))
        painter.drawRoundedRect(box, box.width() * .27, box.width() * .27)
        painter.restore()
        painter.setPen(QPen(QColor("#ffffff"), max(1.4, box.width() * .10), Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap))
        a = QPointF(box.left() + .25 * box.width(), box.top() + .52 * box.height())
        b = QPointF(box.left() + .43 * box.width(), box.top() + .68 * box.height())
        c = QPointF(box.left() + .76 * box.width(), box.top() + .32 * box.height())
        painter.drawLine(a, a + (b - a) * min(1., fill / .36))
        if fill > .36:
            painter.drawLine(b, b + (c - b) * ((fill - .36) / .64))

        painter.setPen(QPen(QColor(71, 71, 71, round(203 * fill)), 1.2))
        layout = block.layout()
        line = layout.lineAt(0)
        dx = caret.x() - line.cursorToX(0)[0]
        dy = caret.top() - line.y()
        for index in range(layout.lineCount()):
            line = layout.lineAt(index)
            text = line.naturalTextRect()
            x = text.left() + dx
            y = line.y() + dy + line.ascent() * .71
            painter.drawLine(QPointF(x, y), QPointF(x + text.width() * fill, y))


class NoteSpine(DragArea):
    def __init__(self, note):
        super().__init__(snap=True)
        self.note = note
        self.setObjectName("noteSpine")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setFixedWidth(30)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip("拖动到屏幕左右边缘可贴边 · 按住滚轮可投喂")
        self.setAccessibleName("拖动便签")

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        paint_paper_spine(painter, QRectF(self.rect()), self.note.label, right=self.note.edge == "left")


class ToneDot(QAbstractButton):
    def __init__(self, name, swatch, apply):
        super().__init__()
        self.setFixedSize(17, 24)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(name)
        self.setAccessibleName(f"底色 {name}")
        self.swatch = QColor(swatch)
        self.clicked.connect(apply)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center = QPointF(self.width() / 2, self.height() / 2)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.swatch.lighter(110) if self.underMouse() else self.swatch)
        painter.drawEllipse(center, 4.7, 4.7)
        if self.isChecked() or self.hasFocus():
            painter.setPen(QPen(self.swatch.darker(122), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(center, 7, 7)


class StickyWindow(QWidget):
    def __init__(self, studio, note):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.NoDropShadowWindowHint)
        self.studio, self.note = studio, note
        self.assigning_geometry = True
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle(note.label)
        self.setStyleSheet(STYLE + PAPER_STYLE)
        self.setWindowIcon(icon("note"))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.paper = QFrame()
        self.paper.setObjectName("stickyPaper")
        layout.addWidget(self.paper)
        self.paper_layout = QHBoxLayout(self.paper)
        self.paper_layout.setContentsMargins(0, 0, 0, 0)
        self.paper_layout.setSpacing(0)
        grip = self.drag_grip = NoteSpine(note)
        grip.move_finished.connect(lambda point: self.studio.edge_notes.dropped(self, point))
        self.paper_layout.addWidget(grip)
        content = QWidget()
        self.paper_layout.addWidget(content, 1)
        body = QVBoxLayout(content)
        body.setContentsMargins(12, 8, 9, 8)
        body.setSpacing(5)
        top = QHBoxLayout()
        top.setSpacing(1)
        self.title_field = QLineEdit(note.title)
        self.title_field.setObjectName("noteHeading")
        self.title_field.setMaxLength(80)
        self.title_field.setPlaceholderText("新便签")
        self.title_field.setToolTip("编辑便签标题")
        self.title_field.textEdited.connect(self.update_content)
        top.addWidget(self.title_field, 1)
        self.saved = label()
        self.saved.setFixedSize(24, 24)
        self.saved.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_save_pending(False)
        top.addWidget(self.saved)
        self.pin = icon_button("pin", "始终置顶", self.toggle_pin)
        self.pin.setCheckable(True)
        self.pin.setChecked(note.topmost)
        top.addWidget(self.pin)
        check = icon_button("list", "在当前行插入清单或切换勾选",
                            lambda: self.editor.checklist_at_cursor())
        check.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        top.addWidget(check)
        top.addWidget(icon_button("search", "搜索便签正文", self.toggle_search))
        self.options = icon_button("more", "更多便签选项", self.show_options)
        top.addWidget(self.options)
        body.addLayout(top)

        self.search_field = QLineEdit(objectName="noteSearch")
        self.search_field.setPlaceholderText("查找正文 · 回车查找下一处")
        self.search_field.setClearButtonEnabled(True)
        self.search_field.returnPressed.connect(self.find_text)
        self.search_field.hide()
        body.addWidget(self.search_field)
        self.find_shortcut = QShortcut(QKeySequence.StandardKey.Find, self)
        self.find_shortcut.activated.connect(self.toggle_search)

        self.editor = RichEditor()
        self.editor.setObjectName("noteBody")
        self.editor.viewport().setAutoFillBackground(False)
        self.editor.setPlaceholderText("写点什么…")
        self.editor.setAccessibleName("便签正文")
        self.editor.document().setDefaultFont(neutral_font(QFont("Microsoft YaHei UI", 11)))
        if note.richContent.lstrip().startswith(("<!DOCTYPE", "<html")):
            self.editor.setHtml(note.richContent)
        else:
            self.editor.setPlainText(note.textContent)
        self.editor.textChanged.connect(self.update_content)
        self.editor.checklist_completed.connect(lambda: self.studio.pet.react("celebrate"))
        body.addWidget(self.editor, 1)

        self.format_bar = QFrame(objectName="noteToolbar")
        tools = QHBoxLayout(self.format_bar)
        tools.setContentsMargins(4, 0, 4, 0)
        tools.setSpacing(3)
        for title, tip, action in (("B", "加粗", self.bold),
                                   ("I", "斜体", self.italic), ("U", "下划线", self.underline)):
            toggle = button(title, action, "flat", tip=tip)
            toggle.setFixedSize(26, 24)
            toggle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            tools.addWidget(toggle)
        self.clip_button = button("", self.show_clips, "flat", tip="管理文本片段")
        tools.addWidget(self.clip_button)
        tools.addStretch()
        self.format_bar.hide()
        body.addWidget(self.format_bar)

        footer = QHBoxLayout()
        footer.setSpacing(2)
        self.dots = {}
        for name, (_tone, swatch) in PASTEL_TONES.items():
            dot = ToneDot(name, swatch, lambda _checked=False, key=name: self.set_color(key))
            self.dots[name] = dot
            footer.addWidget(dot)
        footer.addStretch()
        for glyph, text, action in (
            ("archive", "归档便签", lambda: studio.archive_note(note)),
            ("trash", "删除便签", lambda: studio.ask_delete(note, self)),
        ):
            control = icon_button(glyph, text, action, "noteAction")
            control.setFixedSize(28, 24)
            footer.addWidget(control)
        grip = QSizeGrip(self.paper)
        grip.setFixedSize(13, 13)
        grip.setToolTip("拖动调整便签大小")
        footer.addWidget(grip, alignment=Qt.AlignmentFlag.AlignBottom)
        body.addLayout(footer)
        self.paper.installEventFilter(self)
        for widget in self.paper.findChildren(QWidget):
            if widget is not self.editor and not self.editor.isAncestorOf(widget):
                widget.installEventFilter(self)
        self.update_style()
        self.update_clips_label()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, note.topmost)
        self.setMinimumSize(MIN_WIDTH, MIN_HEIGHT)
        screen = self.studio.app.screenAt(QPoint(note.x, note.y)) or self.studio.app.primaryScreen()
        self.setGeometry(fit_to_desktop(QRect(note.x, note.y, note.width, note.height), screen))
        self.assigning_geometry = False

    def eventFilter(self, watched, event):
        if (watched is self.drag_grip and event.type() == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.MiddleButton):
            center = QPointF(self.mapToGlobal(self.rect().center()))
            if self.studio.paper_feed.begin(watched, self.note, event.globalPosition(), center,
                                            self.grab, self.set_feed_folded):
                return True
        if event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick) and self.editor.hasFocus():
            self.editor.clearFocus()
        return super().eventFilter(watched, event)

    def set_feed_folded(self, folded):
        self.setWindowOpacity(.14 if folded else 1.)

    def bold(self):
        weight = QFont.Weight.Normal if self.editor.fontWeight() >= QFont.Weight.Bold else QFont.Weight.Bold
        self.editor.setFontWeight(weight)

    def italic(self):
        self.editor.setFontItalic(not self.editor.fontItalic())

    def underline(self):
        self.editor.setFontUnderline(not self.editor.fontUnderline())

    def update_content(self):
        self.note.title = normalize_title(self.title_field.text())
        self.note.textContent = self.editor.toPlainText()
        self.note.richContent = self.editor.toHtml()
        self.note.updatedAt = now()
        self.setWindowTitle(self.note.label)
        self.drag_grip.update()
        self.set_save_pending(True)
        self.studio.changed()

    def set_save_pending(self, pending):
        text = "保存中…" if pending else "已保存"
        if self.saved.accessibleName() != text:
            graphic = icon("saving" if pending else "saved", "#554c62", 16)
            self.saved.setPixmap(graphic.pixmap(16, 16))
            self.saved.setAccessibleName(text)
            self.saved.setToolTip(text)

    def fold_into_pet(self):
        self.save_geometry()
        self.note.collapsed = True
        self.note.clear_dock()
        self.close()
        self.studio.pet.react("fold")

    def save_geometry(self):
        if self.assigning_geometry or not self.isVisible():
            return
        self.note.x, self.note.y = self.x(), self.y()
        self.note.width, self.note.height = self.width(), self.height()
        self.studio.changed(refresh=False)

    def moveEvent(self, event):
        super().moveEvent(event)
        self.save_geometry()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.save_geometry()

    def toggle_pin(self, checked):
        self.note.topmost = checked
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, checked)
        if self.note.visible:
            self.show()
        self.studio.changed()

    def update_style(self):
        color = QColor(self.note.paper_tone)
        opacity = round(self.note.backgroundOpacity * 255)
        sheen = color.lighter(102)
        top = f"rgba({sheen.red()}, {sheen.green()}, {sheen.blue()}, {opacity})"
        base = f"rgba({color.red()}, {color.green()}, {color.blue()}, {opacity})"
        spine_position = "right" if self.note.edge == "left" else "left"
        inner_position = "left" if spine_position == "right" else "right"
        edge_fill = color.darker(109)
        side = f"rgba({edge_fill.red()}, {edge_fill.green()}, {edge_fill.blue()}, {opacity})"
        self.paper.setStyleSheet(f"""
            QFrame#stickyPaper {{
              background: qlineargradient(x1:0,y1:0,x2:0.78,y2:1,stop:0 {top},stop:1 {base});
              border: none; border-radius: 16px;
            }}
            QWidget#noteSpine {{
              background: {side}; border-top-{spine_position}-radius: 16px;
              border-bottom-{spine_position}-radius: 16px;
              border-top-{inner_position}-radius: 0; border-bottom-{inner_position}-radius: 0;
            }}
        """)
        self.paper_layout.setDirection(QHBoxLayout.Direction.RightToLeft if self.note.edge == "left"
                                       else QHBoxLayout.Direction.LeftToRight)
        for name, dot in self.dots.items():
            dot.setChecked(name == self.note.color)
            dot.update()

    def set_color(self, name):
        self.note.color = name
        self.update_style()
        self.studio.changed()

    def set_opacity(self, opacity):
        self.note.backgroundOpacity = opacity
        self.update_style()
        self.studio.changed()

    def options_menu(self):
        menu = RoundedMenu(self)
        menu.addAction("格式与文本片段", lambda: self.format_bar.setVisible(self.format_bar.isHidden()))
        menu.addAction(icon("tag", "#dedede", 17), "编辑标签", lambda: self.studio.edit_note_tags(self.note, self))
        dock = menu.submenu("桌面边缘")
        for side, caption in (("left", "贴到左边缘"), ("right", "贴到右边缘")):
            dock.addAction(caption, lambda _=False, value=side: self.studio.edge_notes.attach(self, value, self.screen()))
        if self.note.edge:
            dock.addAction("取消贴边", self.detach)
        menu.addAction("折叠回宠物", self.fold_into_pet)
        choices = menu.submenu("便签底色")
        for name, (caption, _) in NOTE_TONES.items():
            act = choices.addAction(caption)
            act.setCheckable(True)
            act.setChecked(name == self.note.color)
            act.triggered.connect(lambda _, n=name: self.set_color(n))
        opacity = menu.submenu("背景透明度")
        for number in (1., .85, .65, .45):
            act = opacity.addAction(f"背景浓度 {round(number * 100)}%")
            act.setCheckable(True)
            act.setChecked(self.note.backgroundOpacity == number)
            act.triggered.connect(lambda _, n=number: self.set_opacity(n))
        menu.addSeparator()
        menu.addAction("关闭便签", self.close)
        menu.addAction("删除便签", lambda: self.studio.ask_delete(self.note, self))
        return menu

    def detach(self):
        self.note.clear_dock()
        self.update_style()
        self.studio.changed()

    def toggle_search(self):
        shown = self.search_field.isHidden()
        self.search_field.setVisible(shown)
        if shown:
            self.search_field.setFocus()
            self.search_field.selectAll()
        else:
            self.editor.setFocus()

    def find_text(self):
        query = self.search_field.text().strip()
        if query and not self.editor.find(query):
            prior = self.editor.textCursor()
            self.editor.moveCursor(QTextCursor.MoveOperation.Start)
            if not self.editor.find(query):
                self.editor.setTextCursor(prior)
                self.studio.app.beep()

    def show_options(self):
        menu = self.options_menu()
        menu.exec(self.options.mapToGlobal(QPoint(0, self.options.height() + 4)))
        menu.deleteLater()

    def update_clips_label(self):
        count = len(self.note.textClips)
        self.clip_button.setText(f"文本片段 · {count}" if count else "文本片段")

    def show_clips(self):
        menu = RoundedMenu(self)
        menu.addAction("从文件加入片段…", self.add_clip)
        if self.note.textClips:
            menu.addSeparator()
        for clip in self.note.textClips:
            menu.addAction(clip["title"], lambda _, c=clip: self.open_clip(c))
        menu.exec(self.clip_button.mapToGlobal(QPoint(0, self.clip_button.height() + 4)))
        menu.deleteLater()

    def add_clip(self):
        if len(self.note.textClips) >= 200:
            show_warning(self, "片段数量已满", "每张便签可保留 200 个片段。")
            return
        filename = pick_file(self, "加入文本片段", "文本文件 (*.txt *.md *.log *.csv)")
        if not filename:
            return
        limit = 8 * 1024 * 1024
        try:
            path = Path(filename)
            with path.open("rb") as file:
                data = file.read(limit + 1)
            if len(data) > limit:
                raise ValueError("请选择小于 8 MiB 的文本文件。")
            try:
                content = data.decode("utf-8-sig")
            except UnicodeError:
                content = data.decode("gb18030")
        except (ValueError, OSError) as error:
            show_warning(self, "无法打开文本", str(error))
            return
        self.note.textClips.append({"title": normalize_title(path.name), "content": content})
        self.note.updatedAt = now()
        self.update_clips_label()
        self.studio.changed()

    def open_clip(self, clip):
        dialog = SheetDialog(clip["title"], self)
        dialog.resize(540, 380)
        editor = QPlainTextEdit(clip["content"])
        editor.setReadOnly(True)
        dialog.body.addWidget(editor, 1)
        more = QHBoxLayout()
        more.addWidget(button("复制", lambda: self.studio.app.clipboard().setText(clip["content"])))
        more.addStretch()
        more.addWidget(button("关闭", dialog.accept))
        dialog.body.addLayout(more)
        dialog.exec()

    def closeEvent(self, event):
        if not self.studio.quitting:
            event.ignore()
            self.hide()
            self.note.visible = False
            self.studio.edge_notes.update_tab(self.note)
            self.studio.changed()
        else:
            event.accept()

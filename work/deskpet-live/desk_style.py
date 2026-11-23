import os
import sys

from PySide6.QtCore import (
    QEasingCurve, QEvent, QLibraryInfo, QObject, QPoint, QPointF, QRect, QRectF, QSize,
    QTimer, QTranslator, Qt, Signal, QVariantAnimation,
)
from PySide6.QtGui import QColor, QContextMenuEvent, QCursor, QFont, QFontMetrics, QIcon, QLinearGradient, QPainter, QPainterPath, QPalette, QPen, QPixmap, QRegion
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel,
    QLineEdit, QMenu, QMessageBox, QPlainTextEdit, QPushButton, QStyle, QStyleOptionButton, QTextEdit, QVBoxLayout, QWidget,
)
from shiboken6 import isValid


INK = "#292929"


def neutral_font(font):
    font.setStyleStrategy(font.styleStrategy() | QFont.StyleStrategy.NoSubpixelAntialias)
    return font


def paint_paper_spine(painter, area, title, *, right=False):
    painter.save()
    x = area.left() + 1.5 if right else area.right() - 1.5
    toward_paper = -1. if right else 1.
    pen = QPen(QColor(), 1., Qt.PenStyle.CustomDashLine, Qt.PenCapStyle.RoundCap)
    pen.setDashPattern([2.6, 3.4])
    for line_x, color in ((x + toward_paper, QColor(255, 255, 255, 120)),
                          (x, QColor(61, 46, 78, 126))):
        pen.setColor(color)
        painter.setPen(pen)
        painter.drawLine(QPointF(line_x, area.top() + 5), QPointF(line_x, area.bottom() - 5))
    painter.translate(area.center())
    painter.rotate(-90 if right else 90)
    font = neutral_font(QFont("Microsoft YaHei UI"))
    font.setPixelSize(12)
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(QColor("#453751"))
    title = QFontMetrics(font).elidedText(title, Qt.TextElideMode.ElideRight, int(area.height()) - 24)
    painter.drawText(QRectF(-area.height() / 2, -12, area.height(), 24), Qt.AlignmentFlag.AlignCenter, title)
    painter.restore()


def create_ui_application(name):
    args = [name]
    if sys.platform == "win32" and os.environ.get("QT_QPA_PLATFORM", "windows") == "windows":
        args += ["-platform", "windows:fontengine=freetype"]
    app = QApplication(args)
    app.setFont(neutral_font(app.font()))
    translator = QTranslator(app)
    if translator.load("qtbase_zh_CN", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(translator)
    palette = app.palette()
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#5a5a5a"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Link, QColor("#4a4a4a"))
    palette.setColor(QPalette.ColorRole.LinkVisited, QColor("#6a6a6a"))
    app.setPalette(palette)
    app.installEventFilter(RoundedUi(app))
    return app


STYLE = """
QWidget { color: #292929; font-family: "Microsoft YaHei UI", "Segoe UI"; font-size: 13px; }
QFrame#feature { background: #eeeeee; border: none; border-radius: 19px; }
QFrame#paper { background: #f7f7f7; border: none; border-radius: 16px; }
QFrame#dialogSurface { background: #fcfcfc; border: none; border-radius: 20px; }
QLabel#section { font-size: 16px; font-weight: 700; }
QLabel#muted { color: #484848; font-size: 12px; }
QLabel#caption { color: #4d4d4d; font-size: 11px; }
QLabel#dialogBody { color: #333333; font-size: 13px; }
QLabel#dialogDetail { color: #515151; font-size: 12px; }
QLabel#alertBadge { background: #eaeaea; border-radius: 8px; }
QPushButton {
  border: none; border-radius: 11px; background: #fafafa;
  padding: 5px 12px; min-height: 24px; font-size: 12px;
}
QPushButton:hover { background: #e9e9e9; }
QPushButton:pressed { background: #dedede; }
QPushButton:disabled { color: #828282; background: #ededed; }
QPushButton#primary { background: #3b3b3b; color: #ffffff; font-weight: 700; }
QPushButton#primary:hover { background: #4a4a4a; }
QPushButton#secondary { background: #eaeaea; color: #2d2d2d; }
QPushButton#secondary:hover { background: #dfdfdf; }
QPushButton#tagChip {
  background: #eaeaea; border-radius: 9px; color: #292929; text-align: left; padding: 2px 8px;
}
QPushButton#tagChip:hover { background: #dedede; }
QPushButton#danger { background: #252525; color: #ffffff; font-weight: 700; }
QPushButton#danger:hover { background: #444444; }
QPushButton#flat, QPushButton#close, QPushButton#iconButton {
  background: transparent; border: none; border-radius: 9px;
  padding: 0px; min-height: 24px;
}
QPushButton#flat:hover, QPushButton#iconButton:hover { background: rgba(0,0,0,20); }
QPushButton#close:hover { background: rgba(0,0,0,26); }
QPushButton#iconButton:checked { background: rgba(0,0,0,34); }
QLineEdit {
  background: #fafafa; border: none; border-radius: 11px; placeholder-text-color: #5f5f5f;
  padding: 6px 10px; min-height: 24px; selection-background-color: #575757; selection-color: #ffffff;
}
QLineEdit:focus { background: #ffffff; }
QTextEdit, QPlainTextEdit {
  background: #fafafa; border: none; border-radius: 11px; padding: 8px;
  selection-background-color: #575757; selection-color: #ffffff;
  color: #282828; placeholder-text-color: #5f5f5f;
}
QScrollArea { background: transparent; border: none; }
QWidget#noteList { background: transparent; }
QScrollBar:vertical { background: transparent; width: 9px; margin: 2px; }
QScrollBar::handle:vertical { background: #b9b9b9; min-height: 26px; border-radius: 3px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""

MENU_STYLE = """
QMenu { background: #2b2b2b; border: none; border-radius: 15px; padding: 7px;
        color: #f5f5f5; font-family: "Microsoft YaHei UI"; font-size: 13px; menu-scrollable: 1; }
QMenu::item { background: transparent; padding: 7px 23px 7px 11px; border-radius: 6px; min-width: 118px; }
QMenu::item:selected { background: transparent; color: #ffffff; }
QMenu::item:disabled { color: #aaaaaa; }
QMenu::separator { height: 1px; background: rgba(255,255,255,40); margin: 5px 5px; }
QMenu::icon { margin-left: 10px; }
QMenu::indicator { width: 13px; height: 13px; margin-left: 6px; }
QLabel#menuTitle { color: #ffffff; font-size: 13px; font-weight: 700; }
QLabel#menuCaption { color: #c0c0c0; font-size: 11px; }
"""


class HoverTip(QWidget):
    def __init__(self):
        super().__init__(None, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.NoDropShadowWindowHint | Qt.WindowType.WindowTransparentForInput |
                         Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 7, 12, 8)
        self.text = QLabel()
        self.text.setTextFormat(Qt.TextFormat.PlainText)
        self.text.setWordWrap(True)
        self.text.setStyleSheet("color: #eeeeee; background: transparent;")
        font = neutral_font(QFont("Microsoft YaHei UI"))
        font.setWeight(QFont.Weight.Medium)
        font.setPixelSize(12)
        self.text.setFont(font)
        layout.addWidget(self.text)

    def present(self, text, anchor, area):
        self.text.setText(text)
        longest = max(self.text.fontMetrics().horizontalAdvance(line) for line in text.split("\n"))
        self.text.setFixedWidth(max(1, min(longest + 1, 300, area.width() - 28)))
        self.adjustSize()
        x = anchor.center().x() - self.width() // 2
        y = anchor.top() - self.height() - 7
        if y < area.top():
            y = anchor.bottom() + 8
        self.move(min(max(x, area.left()), area.right() + 1 - self.width()),
                  min(max(y, area.top()), area.bottom() + 1 - self.height()))
        self.show()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        face = QRectF(self.rect()).adjusted(.5, .5, -.5, -1.5)
        painter.setPen(QPen(QColor("#3b3b3b"), 1))
        painter.setBrush(QColor("#262626"))
        painter.drawRoundedRect(face, 12, 12)


class RoundedUi(QObject):
    """Route the application's hover hints and editor actions into its own surfaces."""

    def __init__(self, app):
        super().__init__(app)
        self.tip = None
        self.tip_owner = None
        self.tip_area = QRect()
        app.aboutToQuit.connect(self.hide_tip)

    def hide_tip(self):
        if self.tip_owner is not None:
            self.tip_owner = None
            if isValid(self.tip):
                self.tip.hide()

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind in (QEvent.Type.Polish, QEvent.Type.Show, QEvent.Type.Resize) and isinstance(watched, QWidget):
            self.style_native_popup(watched, kind)
        if kind == QEvent.Type.ToolTip and isinstance(watched, QWidget):
            text = watched.toolTip()
            anchor = watched.rect()
            if isinstance(watched, QMenu) and watched.toolTipsVisible():
                action = watched.actionAt(event.pos())
                if action is not None:
                    text, anchor = action.toolTip(), watched.actionGeometry(action)
            if text:
                screen = QApplication.screenAt(event.globalPos()) or watched.screen()
                if anchor.width() > 200 or anchor.height() > 72:
                    anchor = QRect(event.pos() - QPoint(3, 3), QSize(6, 6))
                if self.tip is None:
                    self.tip = HoverTip()
                self.tip_owner, self.tip_area = watched, anchor
                self.tip.present(text, QRect(watched.mapToGlobal(anchor.topLeft()), anchor.size()),
                                 screen.availableGeometry())
                return True
        if self.tip_owner is not None:
            if (kind in (QEvent.Type.MouseButtonPress, QEvent.Type.ContextMenu, QEvent.Type.Wheel,
                         QEvent.Type.KeyPress, QEvent.Type.ApplicationDeactivate)
                    or watched is self.tip_owner and kind in (QEvent.Type.Leave, QEvent.Type.Hide, QEvent.Type.Destroy)
                    or watched is self.tip_owner and kind == QEvent.Type.MouseMove
                    and not self.tip_area.contains(event.position().toPoint())):
                self.hide_tip()
        if kind == QEvent.Type.ContextMenu and isinstance(watched, QWidget):
            editor = watched
            if not isinstance(watched, (QTextEdit, QPlainTextEdit, QLineEdit)):
                editor = watched.parentWidget()
                if not isinstance(editor, (QTextEdit, QPlainTextEdit)) or watched is not editor.viewport():
                    return False
            if editor.contextMenuPolicy() != Qt.ContextMenuPolicy.DefaultContextMenu:
                return False
            if isinstance(editor, QLineEdit) or event.reason() == QContextMenuEvent.Reason.Keyboard:
                actions = editor.createStandardContextMenu()
            else:
                actions = editor.createStandardContextMenu(editor.viewport().mapFromGlobal(event.globalPos()))
            menu = RoundedMenu(editor)
            menu.addActions(actions.actions())
            try:
                menu.exec(event.globalPos())
            finally:
                menu.deleteLater()
                actions.deleteLater()
            return True
        return False

    def style_native_popup(self, widget, kind):
        raw_menu = isinstance(widget, QMenu) and not isinstance(widget, RoundedMenu)
        message = isinstance(widget, QMessageBox)
        if not (raw_menu or message or widget.inherits("QComboBoxPrivateContainer")):
            return
        if kind == QEvent.Type.Polish:
            if raw_menu or message:
                widget.setWindowFlag(Qt.WindowType.FramelessWindowHint)
                if raw_menu:
                    widget.setStyleSheet(MENU_STYLE + "\nQMenu::item:selected { background: #444444; }")
                else:
                    widget.setStyleSheet(STYLE + "\nQMessageBox { background: #fcfcfc; }")
        else:
            outline = QPainterPath()
            outline.addRoundedRect(QRectF(widget.rect()), 12, 12)
            widget.setMask(QRegion(outline.toFillPolygon().toPolygon()))

class GlideHighlight(QWidget):
    """A shared hover/focus highlight with no effect on its owner's layout or hit targets."""
    def __init__(self, parent, *, radius=10):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.radius = radius
        self.target = QRect()
        self.glide = QVariantAnimation(self, duration=140)
        self.glide.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.glide.valueChanged.connect(self.setGeometry)
        parent.installEventFilter(self)
        self.hide()

    def watch(self, widget):
        widget.installEventFilter(self)

    def point_at(self, rect):
        if rect == self.target:
            return
        self.target = QRect(rect)
        self.glide.stop()
        if rect.isEmpty():
            self.hide()
            return
        moving = not self.isHidden() and QApplication.isEffectEnabled(Qt.UIEffect.UI_General)
        if moving:
            self.glide.setStartValue(self.geometry())
            self.glide.setEndValue(rect)
            self.glide.start()
        else:
            self.setGeometry(rect)
        self.raise_()
        self.show()

    def clear(self):
        self.point_at(QRect())

    def clear_after_focus(self):
        parent = self.parentWidget()
        focused = QApplication.focusWidget()
        if not parent.underMouse() and (focused is None or not parent.isAncestorOf(focused)):
            self.clear()

    def eventFilter(self, watched, event):
        kind = event.type()
        if watched is self.parentWidget():
            if kind in (QEvent.Type.Leave, QEvent.Type.Hide, QEvent.Type.Resize):
                self.clear()
        elif kind in (QEvent.Type.Enter, QEvent.Type.FocusIn):
            row = watched
            while row is not None and row.parentWidget() is not self.parentWidget():
                row = row.parentWidget()
            if row is not None:
                self.point_at(row.geometry())
        elif kind == QEvent.Type.FocusOut:
            QTimer.singleShot(0, self, self.clear_after_focus)
        return super().eventFilter(watched, event)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(.7, .7, -.7, -.7)
        light = QLinearGradient(rect.topLeft(), rect.bottomRight())
        light.setColorAt(0, QColor(255, 255, 255, 26))
        light.setColorAt(1, QColor(255, 255, 255, 10))
        painter.setBrush(light)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(rect, self.radius, self.radius)


class RoundedMenu(QMenu):
    radius = 15

    def __init__(self, parent=None, title=""):
        super().__init__(title, parent)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(MENU_STYLE)
        self.highlight = GlideHighlight(self, radius=8)
        self.corner = QPoint()
        self.reveal = QVariantAnimation(self, duration=110, startValue=.87, endValue=1.)
        self.reveal.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.reveal.valueChanged.connect(self.set_corner_mask)
        self.hovered.connect(lambda _action: self.update_highlight())

    def submenu(self, title, graphic=None):
        menu = RoundedMenu(self, title)
        if graphic is not None:
            menu.setIcon(graphic)
        self.addMenu(menu)
        return menu

    def set_corner_mask(self, fraction=1.0):
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), self.radius, self.radius)
        shape = QRegion(path.toFillPolygon().toPolygon())
        if fraction < 1:
            width, height = round(self.width() * fraction), round(self.height() * fraction)
            x = self.width() - width if self.corner.x() > self.width() / 2 else 0
            y = self.height() - height if self.corner.y() > self.height() / 2 else 0
            shape &= QRegion(x, y, width, height)
        self.setMask(shape)

    def update_highlight(self):
        action = self.activeAction()
        rect = QRect()
        if action is not None and action.isEnabled() and not action.isSeparator():
            rect = self.actionGeometry(action).adjusted(1, 1, -1, -1)
        self.highlight.point_at(rect)

    def showEvent(self, event):
        super().showEvent(event)
        parent = self.parentWidget()
        anchor = QCursor.pos()
        if isinstance(parent, QMenu):
            anchor = parent.mapToGlobal(parent.actionGeometry(self.menuAction()).center())
        elif isinstance(parent, QPushButton):
            anchor = parent.mapToGlobal(parent.rect().center())
        self.corner = self.mapFromGlobal(anchor)
        self.reveal.stop()
        if QApplication.isEffectEnabled(Qt.UIEffect.UI_General):
            self.set_corner_mask(.87)
            self.reveal.start()
        else:
            self.set_corner_mask()

    def hideEvent(self, event):
        self.reveal.stop()
        self.highlight.clear()
        super().hideEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.isVisible() and self.reveal.state() != QVariantAnimation.State.Running:
            self.set_corner_mask()

    def paintEvent(self, event):
        super().paintEvent(event)
        self.update_highlight()

class SoftButton(QPushButton):
    """Replace native focus chrome with a subtle highlight for keyboard users."""
    def __init__(self, text):
        super().__init__(text)
        self.keyboard_focus = False

    def focusInEvent(self, event):
        self.keyboard_focus = event.reason() in (
            Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason, Qt.FocusReason.ShortcutFocusReason,
        )
        super().focusInEvent(event)

    def mousePressEvent(self, event):
        self.keyboard_focus = False
        super().mousePressEvent(event)

    def paintEvent(self, _event):
        painter = QPainter(self)
        option = QStyleOptionButton()
        self.initStyleOption(option)
        option.state &= ~QStyle.StateFlag.State_HasFocus
        self.style().drawControl(QStyle.ControlElement.CE_PushButton, option, painter, self)
        if self.hasFocus() and self.keyboard_focus:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            light = self.objectName().startswith(("library", "character")) or self.objectName() in {"primary", "danger"}
            shade = 255 if light else 0
            painter.setBrush(QColor(shade, shade, shade, 36))
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 9, 9)


class ChoiceButton(SoftButton):
    def __init__(self, caption, options, apply):
        super().__init__("")
        self.caption = caption
        self.options = {value: text for text, value in options}
        self.apply = apply
        self.value = None
        self.setObjectName("choice")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(146, 34)
        self.clicked.connect(self.open_choices)
        self.select(options[0][1])

    def select(self, value, notify=False):
        if value not in self.options or value == self.value:
            return
        self.value = value
        self.setText(self.options[value])
        self.setAccessibleName(f"{self.caption}：{self.text()}")
        if notify:
            self.apply(value)

    def choices_menu(self):
        menu = RoundedMenu(self)
        menu.setMinimumWidth(self.width())
        selected = None
        for value, title in self.options.items():
            action = menu.addAction(title)
            action.setCheckable(True)
            action.setChecked(value == self.value)
            action.triggered.connect(lambda _, v=value: self.select(v, notify=True))
            if value == self.value:
                selected = action
        menu.setActiveAction(selected)
        return menu

    def open_choices(self):
        menu = self.choices_menu()
        try:
            menu.exec(self.mapToGlobal(QPoint(0, self.height() + 4)))
        finally:
            menu.deleteLater()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up):
            self.open_choices()
            event.accept()
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#bdbdbd"), 1.45, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        x, y = self.width() - 17, self.height() / 2
        path = QPainterPath(QPointF(x - 4, y - 1.8))
        path.lineTo(x, y + 2.2)
        path.lineTo(x + 4, y - 1.8)
        painter.drawPath(path)


class SoftSwitch(QCheckBox):
    def __init__(self, text):
        super().__init__(text)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.slide = 0.0
        self.glide = QVariantAnimation(self, duration=125)
        self.glide.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.glide.valueChanged.connect(self.move_thumb)
        self.toggled.connect(self.animate_thumb)

    def setChecked(self, checked):
        super().setChecked(checked)
        if self.signalsBlocked():
            self.glide.stop()
            self.move_thumb(float(bool(checked)))

    def animate_thumb(self, checked):
        self.glide.stop()
        self.glide.setStartValue(self.slide)
        self.glide.setEndValue(float(checked))
        if QApplication.isEffectEnabled(Qt.UIEffect.UI_General):
            self.glide.start()
        else:
            self.move_thumb(float(checked))

    def move_thumb(self, value):
        self.slide = value
        self.update()

    def sizeHint(self):
        return QSize(47 + self.fontMetrics().horizontalAdvance(self.text()), 30)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QRectF(2, (self.height() - 19) / 2, 35, 19)
        track_color = "#777777" if self.isChecked() else "#494949" if self.hasFocus() else "#383838"
        painter.setBrush(QColor(track_color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(track, 9.5, 9.5)
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(QPointF(track.left() + 9.5 + 16 * self.slide, track.center().y()), 6.7, 6.7)
        painter.setPen(QColor("#dedede"))
        painter.drawText(QRectF(47, 0, self.width() - 47, self.height()),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text())


def icon(name, color=INK, size=22):
    art = QPixmap(size * 2, size * 2)
    art.fill(Qt.GlobalColor.transparent)
    painter = QPainter(art)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(size / 12, size / 12)
    pen = QPen(QColor(color), 1.55, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)

    def line(x, y, end_x, end_y):
        painter.drawLine(QPointF(x, y), QPointF(end_x, end_y))

    if name == "note":
        path = QPainterPath(QPointF(6, 3.5))
        path.lineTo(18, 3.5)
        path.quadTo(20, 3.5, 20, 5.5)
        path.lineTo(20, 14.5)
        path.lineTo(14.5, 20)
        path.lineTo(6, 20)
        path.quadTo(4, 20, 4, 18)
        path.lineTo(4, 5.5)
        path.quadTo(4, 3.5, 6, 3.5)
        painter.drawPath(path)
        line(14.5, 20, 14.5, 14.5)
        line(14.5, 14.5, 20, 14.5)
        line(8, 8, 16, 8)
        line(8, 12, 12, 12)
    elif name == "pet":
        for x, y in ((5.5, 8), (10, 5), (14.5, 5.5), (18.6, 9)):
            painter.drawEllipse(QPointF(x, y), 1.7, 2.1)
        painter.drawRoundedRect(QRectF(6.5, 12, 11, 7), 3.4, 3.4)
    elif name == "plus":
        line(6, 12, 18, 12)
        line(12, 6, 12, 18)
    elif name == "close":
        line(7, 7, 17, 17)
        line(17, 7, 7, 17)
    elif name == "hide":
        line(6, 12, 18, 12)
    elif name == "archive":
        painter.drawRoundedRect(QRectF(4, 5, 16, 4.5), 1.5, 1.5)
        painter.drawRoundedRect(QRectF(5.5, 9.5, 13, 10), 1.4, 1.4)
        line(10, 13, 14, 13)
    elif name == "trash":
        line(5, 7, 19, 7)
        painter.drawRoundedRect(QRectF(9, 4, 6, 3), 1, 1)
        painter.drawRoundedRect(QRectF(7, 7, 10, 13), 1.5, 1.5)
        line(10.5, 10.5, 10.5, 16.5)
        line(13.5, 10.5, 13.5, 16.5)
    elif name in ("select", "select-empty"):
        painter.drawRoundedRect(QRectF(4.5, 4.5, 15, 15), 3, 3)
        if name == "select":
            line(8, 12, 11, 15)
            line(11, 15, 16, 9)
    elif name in ("saved", "saving"):
        painter.drawEllipse(QPointF(12, 12), 8, 8)
        if name == "saved":
            line(8.5, 12, 11, 14.5)
            line(11, 14.5, 15.5, 10)
        else:
            line(12, 8, 12, 12)
            line(12, 12, 15, 13.5)
    elif name == "pin":
        path = QPainterPath(QPointF(8, 5))
        for x, y in ((16, 5), (15, 11), (18, 14), (6, 14), (9, 11), (8, 5)):
            path.lineTo(x, y)
        painter.drawPath(path)
        line(12, 14, 12, 20)
    elif name == "more":
        painter.setBrush(QColor(color))
        for x in (6.5, 12, 17.5):
            painter.drawEllipse(QPointF(x, 12), .75, .75)
    elif name == "open":
        painter.drawRoundedRect(QRectF(4, 5, 16, 14), 2, 2)
        line(4, 9, 20, 9)
    elif name == "list":
        painter.drawRoundedRect(QRectF(4.5, 6, 4, 4), .6, .6)
        painter.drawRoundedRect(QRectF(4.5, 14, 4, 4), .6, .6)
        line(12, 8, 19, 8)
        line(12, 16, 19, 16)
    elif name == "search":
        painter.drawEllipse(QPointF(10, 10), 5.1, 5.1)
        line(14, 14, 19, 19)
    elif name == "tag":
        path = QPainterPath(QPointF(4.5, 5))
        path.lineTo(12, 5)
        path.lineTo(20, 13)
        path.quadTo(21, 14, 20, 15)
        path.lineTo(15, 20)
        path.quadTo(14, 21, 13, 20)
        path.lineTo(4.5, 12)
        path.closeSubpath()
        painter.drawPath(path)
        painter.drawEllipse(QPointF(8, 8.5), 1, 1)
    elif name == "alert":
        painter.drawEllipse(QPointF(12, 12), 8, 8)
        line(12, 8, 12, 12.6)
        painter.drawPoint(QPointF(12, 15.5))
    painter.end()
    art.setDevicePixelRatio(2)
    return QIcon(art)


def label(text="", role=None):
    result = QLabel(text)
    result.setTextFormat(Qt.TextFormat.PlainText)
    if role:
        result.setObjectName(role)
    return result


def button(text, handler, role=None, graphic=None, tip=None, color=INK):
    result = SoftButton(text)
    result.setCursor(Qt.CursorShape.PointingHandCursor)
    if role:
        result.setObjectName(role)
    if graphic:
        result.setIcon(icon(graphic, color, 17))
    if tip:
        result.setToolTip(tip)
        result.setAccessibleName(tip)
    result.clicked.connect(handler)
    return result


def icon_button(name, tip, handler, role="iconButton"):
    result = button("", handler, role, name, tip)
    result.setFixedSize(29, 28)
    return result


class DragArea(QWidget):
    """One dedicated draggable title area, leaving editor buttons interactive."""
    move_finished = Signal(QPoint)

    def __init__(self, parent=None, *, snap=False):
        super().__init__(parent)
        self.delta = None
        self.snap = snap
        self.drag_origin = QPoint()
        self.drag_started = False

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_origin = event.globalPosition().toPoint()
            self.drag_started = False
            if self.snap or not (self.window().windowHandle() and self.window().windowHandle().startSystemMove()):
                self.delta = self.drag_origin - self.window().pos()
            event.accept()

    def mouseMoveEvent(self, event):
        if self.delta is not None:
            point = event.globalPosition().toPoint()
            if (self.drag_started or not self.snap or
                    (point - self.drag_origin).manhattanLength() >= QApplication.startDragDistance()):
                self.drag_started = True
                self.window().move(point - self.delta)
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.delta is not None:
            point = event.globalPosition().toPoint()
            offset, self.delta = self.delta, None
            dragged = self.drag_started or (point - self.drag_origin).manhattanLength() >= QApplication.startDragDistance()
            self.drag_started = False
            if self.snap and dragged:
                self.window().move(point - offset)
                self.move_finished.emit(point)
            event.accept()


class SheetDialog(QDialog):
    def __init__(self, title, parent):
        super().__init__(parent, Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.NoDropShadowWindowHint)
        self.setWindowTitle(title)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(STYLE)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 23)
        self.surface = QFrame(objectName="dialogSurface")
        shadow = QGraphicsDropShadowEffect(self.surface)
        shadow.setBlurRadius(25)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 88))
        self.surface.setGraphicsEffect(shadow)
        outer.addWidget(self.surface)
        self.body = QVBoxLayout(self.surface)
        self.body.setContentsMargins(19, 14, 19, 17)
        self.body.setSpacing(13)
        bar = QHBoxLayout()
        drag = DragArea()
        headline = QHBoxLayout(drag)
        headline.setContentsMargins(0, 0, 0, 0)
        heading = label(title, "section")
        heading.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        headline.addWidget(heading)
        headline.addStretch()
        bar.addWidget(drag, 1)
        bar.addWidget(icon_button("close", "关闭", self.reject, "close"))
        self.body.addLayout(bar)


def show_warning(parent, title, message):
    dialog = SheetDialog(title, parent)
    dialog.setFixedWidth(416)
    text = label(message, "dialogBody")
    text.setWordWrap(True)
    text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    dialog.body.addWidget(text)
    confirm = button("确定", dialog.accept, "primary")
    confirm.setDefault(True)
    dialog.body.addWidget(confirm, alignment=Qt.AlignmentFlag.AlignRight)
    try:
        dialog.exec()
    finally:
        dialog.deleteLater()

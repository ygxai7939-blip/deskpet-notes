"""The transient stack shown while moving a desktop note rail."""
from dataclasses import dataclass

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, QSizeF, QTimer, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from sticky_window import StickyWindow


MAX_PREVIEW_CARDS = 4


@dataclass
class DragCard:
    label: QPixmap
    paper: QPixmap
    source: QRectF
    destination: QRectF
    angle: float


class EdgeDragPreview(QWidget):
    def __init__(self):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowTransparentForInput |
                         Qt.WindowType.WindowDoesNotAcceptFocus | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.cards = []
        self.frames = []
        self.pointer = QPointF()
        self.origin = QPointF()
        self.motion = QVariantAnimation(self, startValue=0., endValue=1., duration=210)
        self.motion.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.motion.valueChanged.connect(self.update_frame)
        self.movement = QTimer(self, interval=16, singleShot=True, timerType=Qt.TimerType.PreciseTimer)
        self.movement.timeout.connect(self.update_frame)

    def begin(self, studio, rail, pressed, pointer):
        tabs = list(rail.tabs.items())
        front = next((index for index, (_, tab) in enumerate(tabs) if tab is pressed), 0)
        ordered = tabs[front:] + tabs[:front][::-1]
        self.pointer = QPointF(pointer)
        anchor = QPointF(rail.press_point)
        side = 1 if rail.edge == "right" else -1
        for note_id, tab in ordered[:MAX_PREVIEW_CARDS]:
            note = studio.store.records.get(note_id)
            if note is None:
                continue
            window = studio.windows.get(note_id)
            temporary = window is None
            if temporary:
                window = StickyWindow(studio, note)
            paper = window.grab().scaled(600, 440, Qt.AspectRatioMode.KeepAspectRatio,
                                         Qt.TransformationMode.SmoothTransformation)
            if temporary:
                window.deleteLater()
            if paper.isNull():
                continue
            depth = len(self.cards)
            width, height = paper.width() / 2, paper.height() / 2
            x = 18 - width if side == 1 else -18
            target = QRectF(x + side * depth * 14, -height * .43 + depth * 11, width, height)
            source = QRectF(QPointF(tab.mapToGlobal(tab.rect().topLeft())) - anchor, QSizeF(tab.size()))
            angle = side * (depth * 3.4 - 2.0)
            self.cards.append(DragCard(tab.grab(), paper, source, target, angle))
        if not self.cards:
            return False
        self.motion.setCurrentTime(0)
        self.update_frame()
        self.show()
        self.motion.start()
        return True

    def follow(self, point):
        self.pointer = QPointF(point)
        if not self.movement.isActive():
            self.movement.start()

    def update_frame(self, _value=None):
        if not self.cards:
            return
        progress = float(self.motion.currentValue() or 0.)
        self.frames = []
        bounds = QRectF()
        for card in self.cards:
            start, end = card.source, card.destination
            rect = QRectF(start.topLeft() + (end.topLeft() - start.topLeft()) * progress,
                          start.bottomRight() + (end.bottomRight() - start.bottomRight()) * progress)
            self.frames.append((card, rect))
            bounds = bounds.united(rect)
        projected = bounds.adjusted(-16, -16, 16, 20).translated(self.pointer).toAlignedRect()
        screen = QApplication.screenAt(self.pointer.toPoint()) or QApplication.primaryScreen()
        area = screen.availableGeometry()
        fitted = projected.topLeft()
        if projected.width() <= area.width():
            fitted.setX(min(max(area.left(), projected.left()), area.right() + 1 - projected.width()))
        if projected.height() <= area.height():
            fitted.setY(min(max(area.top(), projected.top()), area.bottom() + 1 - projected.height()))
        self.origin = self.pointer - QPointF(projected.topLeft())
        projected.moveTopLeft(fitted)
        if self.geometry() != projected:
            self.setGeometry(projected)
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        progress = float(self.motion.currentValue() or 0.)
        blend = min(1., progress * 2.3)
        for card, rect in reversed(self.frames):
            painter.save()
            painter.translate(self.origin + rect.center())
            painter.rotate(card.angle * progress)
            local = rect.translated(-rect.center())
            if blend < 1.:
                label = QRectF(local)
                label.setWidth(card.source.width())
                if card.destination.center().x() < 0:
                    label.moveRight(local.right())
                painter.setOpacity(1. - blend)
                painter.drawPixmap(label, card.label, QRectF(card.label.rect()))
            if blend:
                painter.setOpacity(blend)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(0, 0, 0, 30))
                painter.drawRoundedRect(local.translated(0, 5), 12, 12)
                painter.drawPixmap(local, card.paper, QRectF(card.paper.rect()))
            painter.restore()

    def finish(self):
        self.motion.stop()
        self.movement.stop()
        self.hide()
        self.cards.clear()
        self.frames.clear()

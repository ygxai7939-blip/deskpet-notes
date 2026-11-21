"""Middle-button paper drag, desktop drop target, and folding animation."""
import math
import random

from PySide6.QtCore import QElapsedTimer, QEvent, QObject, QPointF, QRectF, QTimer, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap, QPolygonF, QTransform
from PySide6.QtWidgets import QApplication, QWidget
from shiboken6 import isValid


FOLD_MS = 225
HOLD_MS = 700
SWALLOW_MS = 190
BALL_SIZE = 43


def interpolate(start, end, amount):
    return start + (end - start) * amount


def make_folds():
    """Give each shared vertex a fixed position and each fold a lighting value."""
    rng = random.Random(56)
    columns, rows = 6, 5
    vertices = []
    for row in range(rows):
        for column in range(columns):
            x = column / (columns - 1) - .5
            y = row / (rows - 1) - .5
            flat = QPointF(x, y)
            rounded = 1. - .34 * (abs(x) + abs(y))
            crumpled = QPointF(x * rounded + rng.uniform(-.07, .07),
                               y * rounded + rng.uniform(-.10, .10))
            vertices.append((flat, crumpled))
    folds = []
    for row in range(rows - 1):
        for column in range(columns - 1):
            a = row * columns + column
            b, c, d = a + 1, a + columns, a + columns + 1
            faces = ((a, b, c), (b, d, c)) if (row + column) % 2 else ((a, b, d), (a, d, c))
            for indices in faces:
                folds.append((indices, rng.randint(162, 247)))
    rim = [*range(columns), *(row * columns - 1 for row in range(2, rows)),
           *range(columns * rows - 1, columns * (rows - 1) - 1, -1),
           *(row * columns for row in range(rows - 2, 0, -1))]
    return vertices, folds, rim


VERTICES, FOLDS, RIM = make_folds()


def texture_transform(original, folded):
    a, b, c = original
    p, q, r = folded
    u, v = b - a, c - a
    s, t = q - p, r - p
    determinant = u.x() * v.y() - u.y() * v.x()
    x = (s * v.y() - t * u.y()) / determinant
    y = (t * u.x() - s * v.x()) / determinant
    offset = p - x * a.x() - y * a.y()
    return QTransform(x.x(), x.y(), y.x(), y.y(), offset.x(), offset.y())


class PaperGhost(QWidget):
    """Small top-level surface that stays with the cursor across desktop windows."""
    def __init__(self):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowTransparentForInput |
                         Qt.WindowType.WindowDoesNotAcceptFocus | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.center = QPointF()
        self.mouth = None
        self.hold = self.fold = 0.
        self.scale = 1.
        self.texture = None
        self.sheet = QRectF(0, 0, 1, 1)
        self.ball = QPixmap(64, 64)
        self.ball.fill(Qt.GlobalColor.transparent)
        painter = QPainter(self.ball)
        painter.translate(32, 32)
        self.paint_folds(painter, 1.)
        painter.end()

    def set_texture(self, texture):
        self.texture = texture
        size = texture.deviceIndependentSize()
        self.sheet = QRectF(0, 0, size.width(), size.height())

    def present(self, center, fold, mouth=None, hold=0., scale=1.):
        self.center, self.fold = center, fold
        self.mouth, self.hold, self.scale = mouth, hold, scale
        if fold < 1.:
            radius = interpolate(max(self.sheet.width(), self.sheet.height()) * .57, 33., fold)
        else:
            radius = 35.
        bounds = QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2)
        if mouth is not None:
            bounds = bounds.united(QRectF(mouth.x() - 27, mouth.y() - 27, 54, 54))
        geometry = bounds.toAlignedRect()
        if geometry != self.geometry():
            self.setGeometry(geometry)
        if not self.isVisible():
            self.show()
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        origin = QPointF(self.geometry().topLeft())
        if self.mouth is not None:
            spot = self.mouth - origin
            circle = QRectF(spot.x() - 18, spot.y() - 18, 36, 36)
            painter.setPen(QPen(QColor(25, 25, 25, 175), 3.5))
            painter.drawEllipse(circle)
            painter.setPen(QPen(QColor(239, 239, 239, 125), 1.4))
            painter.drawEllipse(circle)
            painter.setPen(QPen(QColor("#ffffff"), 2.1, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawArc(circle, 90 * 16, round(-self.hold * 360 * 16))
        painter.translate(self.center - origin)
        painter.scale(self.scale, self.scale)
        if self.fold < 1.:
            self.paint_folds(painter, self.fold)
        else:
            painter.setOpacity(min(1., self.scale * 2))
            painter.drawPixmap(-32, -32, self.ball)

    def paint_folds(self, painter, fold):
        width, height = self.sheet.width(), self.sheet.height()
        texture_coords = [QPointF((flat.x() + .5) * width, (flat.y() + .5) * height)
                          for flat, _point in VERTICES]
        coords = []
        for flat, point in VERTICES:
            start = QPointF(flat.x() * width, flat.y() * height)
            target = QPointF(point.x() * BALL_SIZE * 1.30, point.y() * BALL_SIZE * 1.04)
            coords.append(interpolate(start, target, fold))
        outline = QPainterPath()
        rim = [coords[index] for index in RIM]
        outline.moveTo(interpolate(rim[-1], rim[0], .80))
        for index, corner in enumerate(rim):
            outline.lineTo(interpolate(corner, rim[index - 1], .20))
            outline.quadTo(corner, interpolate(corner, rim[(index + 1) % len(rim)], .20))
        outline.closeSubpath()
        painter.setClipPath(outline, Qt.ClipOperation.IntersectClip)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        facet_alpha = round(255 * min(1., max(0., (fold - .18) / .70)) ** 1.5)
        for indices, shade in FOLDS:
            triangle = QPolygonF([coords[i] for i in indices])
            path = QPainterPath()
            path.addPolygon(triangle)
            path.closeSubpath()
            if fold < .88:
                painter.save()
                painter.setClipPath(path)
                transform = texture_transform([texture_coords[i] for i in indices], triangle)
                painter.setTransform(transform, True)
                painter.drawPixmap(self.sheet, self.texture, QRectF(self.texture.rect()))
                painter.restore()
            color = QColor(shade, shade, shade, facet_alpha)
            painter.fillPath(path, color)


class PaperFeed(QObject):
    def __init__(self, studio):
        super().__init__(studio.app)
        self.studio = studio
        self.pet = studio.pet
        self.ghost = PaperGhost()
        self.source = None
        self.dwell = QElapsedTimer()
        self.motion = QElapsedTimer()
        self.timer = QTimer(self, interval=16, timerType=Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self.animate)
        self.swallow = None

    def begin(self, source, note, origin, center, snapshot, set_folded):
        if self.source is not None or self.swallow is not None or not self.pet.isVisible():
            return False
        self.source, self.note = source, note
        self.press = self.pointer = origin
        self.offset = center - origin
        self.snapshot, self.set_folded = snapshot, set_folded
        self.motion.invalidate()
        self.dwell.invalidate()
        self.studio.app.installEventFilter(self)
        source.grabMouse()
        return True

    def eventFilter(self, watched, event):
        source = self.source
        if source is None or not isValid(self.ghost):
            return False
        kind = event.type()
        if kind == QEvent.Type.MouseMove:
            self.move_paper(event.globalPosition())
            return True
        if kind == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.MiddleButton:
            self.pointer = event.globalPosition()
            self.release()
            return True
        if kind in (QEvent.Type.KeyPress, QEvent.Type.ShortcutOverride) and event.key() == Qt.Key.Key_Escape:
            event.accept()
            if kind == QEvent.Type.KeyPress:
                self.cancel()
            return True
        if ((watched is source and kind in (QEvent.Type.Hide, QEvent.Type.UngrabMouse)) or
                (watched is self.pet and kind == QEvent.Type.Hide) or
                kind == QEvent.Type.ApplicationDeactivate):
            self.cancel()
        return False

    def move_paper(self, point):
        self.pointer = point
        if self.motion.isValid():
            if not self.over_mouth():
                self.dwell.invalidate()
                self.pet.set_feed_pose("watch")
            return
        if (point - self.press).manhattanLength() < QApplication.startDragDistance():
            return
        self.ghost.set_texture(self.snapshot())
        self.set_folded(True)
        self.motion.start()
        self.timer.start()
        self.animate()

    def over_mouth(self):
        delta = self.pointer - self.pet.feed_anchor()
        radius = max(23., self.pet.width() * .29)
        return self.pet.isVisible() and math.hypot(delta.x(), delta.y()) <= radius

    def animate(self):
        if self.swallow is not None:
            start, end = self.swallow
            progress = min(1., self.motion.elapsed() / SWALLOW_MS)
            self.ghost.present(interpolate(start, end, progress), 1., scale=max(.02, 1. - progress))
            if progress >= 1.:
                self.finish_animation(celebrate=True)
            return
        if not self.pet.isVisible():
            self.cancel()
            return
        fraction = min(1., self.motion.elapsed() / FOLD_MS)
        fold = 1. - (1. - fraction) ** 2
        inside = self.over_mouth()
        if inside and not self.dwell.isValid():
            self.dwell.start()
        elif not inside:
            self.dwell.invalidate()
        held = min(1., self.dwell.elapsed() / HOLD_MS) if inside else 0.
        pose = "watch"
        if held >= 1.:
            pose = "ready"
        elif held >= .88:
            pose = "opening"
        self.pet.set_feed_pose(pose)
        center = self.pointer + interpolate(self.offset, QPointF(12., 12.), fold)
        self.ghost.present(center, fold, self.pet.feed_anchor() if inside else None, held)

    def detach_source(self):
        source, self.source = self.source, None
        self.timer.stop()
        self.studio.app.removeEventFilter(self)
        if isValid(source) and source.mouseGrabber() is source:
            source.releaseMouse()
        if isValid(source) and self.motion.isValid():
            self.set_folded(False)
        self.snapshot = self.set_folded = None

    def release(self):
        accepted = (self.motion.isValid() and self.dwell.isValid() and
                    self.dwell.elapsed() >= HOLD_MS and self.over_mouth())
        self.detach_source()
        if not accepted:
            self.finish_animation()
            return
        note = self.note
        start, end = self.ghost.center, self.pet.feed_anchor()
        if self.studio.feed_note(note):
            self.swallow = start, end
            self.motion.restart()
            self.timer.start()
        else:
            self.finish_animation()

    def cancel(self):
        if self.source is not None:
            self.detach_source()
        self.finish_animation()

    def finish_animation(self, celebrate=False):
        self.timer.stop()
        self.ghost.hide()
        self.ghost.texture = None
        self.swallow = self.note = None
        self.motion.invalidate()
        self.dwell.invalidate()
        self.pet.set_feed_pose(None, celebrate=celebrate)
        if celebrate:
            self.studio.show_feed_undo()

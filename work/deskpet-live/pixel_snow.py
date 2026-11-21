"""Pointer-reactive pixel snow for the workspace background."""
from dataclasses import dataclass
import math
import random

from PySide6.QtCore import QElapsedTimer, QPointF, QRect, QTimer, Qt
from PySide6.QtGui import QColor, QCursor, QPainter, QPixmap, QRadialGradient, QRegion


SPRITE_RADII = (1, 5, 8, 15)
DEPTH_WEIGHTS = (32, 28, 24, 16)
DOT = ("#",)
CROSS = (".#.", "###", ".#.")
DIAGONAL = ("#...#", ".#.#.", "..#..", ".#.#.", "#...#")
STAR = ("#..#..#", ".#.#.#.", "..###..", "#######", "..###..", ".#.#.#.", "#..#..#")
SNOWFLAKE = (
    "..#..#..#..",
    "...#.#.#...",
    "#...###...#",
    ".#...#...#.",
    "..#..#..#..",
    "###########",
    "..#..#..#..",
    ".#...#...#.",
    "#...###...#",
    "...#.#.#...",
    "..#..#..#..",
)


def make_sprite(pattern, cell, tone, glow, radius):
    extent = 2 * radius + 1
    sprite = QPixmap(extent, extent)
    sprite.fill(Qt.GlobalColor.transparent)
    painter = QPainter(sprite)
    if glow:
        halo = QRadialGradient(radius + .5, radius + .5, radius + .5)
        halo.setColorAt(0, QColor(222, 222, 222, glow))
        halo.setColorAt(.56, QColor(222, 222, 222, glow // 3))
        halo.setColorAt(1, QColor(222, 222, 222, 0))
        painter.fillRect(sprite.rect(), halo)
    inset = (extent - len(pattern) * cell) // 2
    color = QColor(tone)
    for row, line in enumerate(pattern):
        for column, pixel in enumerate(line):
            if pixel == "#":
                painter.fillRect(inset + column * cell, inset + row * cell, cell, cell, color)
    painter.end()
    return sprite


@dataclass
class Flake:
    x: float
    y: float
    depth: int
    phase: float
    vx: float = 0.
    vy: float = 0.

    def bounds(self):
        radius = SPRITE_RADII[self.depth]
        extent = 2 * radius + 1
        return QRect(round(self.x) - radius, round(self.y) - radius, extent, extent)


class PixelSnow:
    RADIUS = 68.

    def __init__(self, surface):
        self.surface = surface
        self.flakes = []
        self.pointer = None
        self.sway = 0.
        self.sprites = (
            (make_sprite(DOT, 2, "#686868", 0, SPRITE_RADII[0]),),
            (make_sprite(CROSS, 2, "#969696", 18, SPRITE_RADII[1]),),
            (make_sprite(DIAGONAL, 2, "#b4b4b4", 26, SPRITE_RADII[2]),
             make_sprite(STAR, 1, "#b4b4b4", 26, SPRITE_RADII[2])),
            (make_sprite(SNOWFLAKE, 2, "#d3d3d3", 47, SPRITE_RADII[3]),
             make_sprite(STAR, 2, "#cccccc", 38, SPRITE_RADII[3])),
        )
        self.clock = QElapsedTimer()
        self.timer = QTimer(surface, interval=33, timerType=Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self.advance)

    def resize(self):
        width, height = self.surface.width(), self.surface.height()
        count = min(380, max(34, width * height // 2850))
        self.flakes = [Flake(random.uniform(0, width), random.uniform(0, height),
                             random.choices(range(len(self.sprites)), weights=DEPTH_WEIGHTS)[0],
                             random.uniform(0, math.tau)) for _ in range(count)]

    def sync(self):
        active = self.surface.isVisible() and not self.surface.window().isMinimized()
        if active and not self.timer.isActive():
            if not self.flakes:
                self.resize()
            self.clock.start()
            self.timer.start()
        elif not active and self.timer.isActive():
            self.timer.stop()
            self.pointer = None

    def advance(self):
        dt = min(.07, self.clock.restart() / 1000.)
        self.sway += dt
        width, height = self.surface.width(), self.surface.height()
        local = self.surface.mapFromGlobal(QCursor.pos())
        previous = self.pointer
        movement = QPointF(local - previous) if previous is not None else QPointF()
        self.pointer = local if self.surface.rect().contains(local) else None
        strength = min(105., movement.manhattanLength() * 5.)
        damping = math.exp(-3.8 * dt)
        dirty = QRegion()
        for flake in self.flakes:
            old = flake.bounds()
            if self.pointer is not None and strength:
                dx, dy = flake.x - local.x(), flake.y - local.y()
                distance = math.hypot(dx, dy)
                if distance < self.RADIUS:
                    push = strength * (1 - distance / self.RADIUS) ** 2
                    flake.vx += push * dx / max(5., distance)
                    flake.vy += push * dy / max(5., distance)
            flake.vx *= damping
            flake.vy *= damping
            flake.x += (math.sin(self.sway * .62 + flake.phase) * (5 + flake.depth * 2) + flake.vx) * dt
            flake.y += (11 + flake.depth * 8 + flake.vy) * dt
            margin = SPRITE_RADII[flake.depth] + 1
            if flake.y < -margin:
                flake.y = -margin
                flake.vy = 0.
            elif flake.y > height + margin:
                flake.y, flake.x = -margin, random.uniform(0, width)
                flake.vx = flake.vy = 0.
            flake.x = (flake.x + margin) % (width + 2 * margin) - margin
            new = flake.bounds()
            if old != new:
                dirty += old
                dirty += new
        self.surface.update(dirty)

    def paint(self, painter):
        if not self.timer.isActive():
            return
        for flake in self.flakes:
            sprites = self.sprites[flake.depth]
            sprite = sprites[-1] if flake.phase > math.pi else sprites[0]
            radius = SPRITE_RADII[flake.depth]
            painter.drawPixmap(round(flake.x) - radius, round(flake.y) - radius, sprite)

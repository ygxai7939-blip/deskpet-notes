import math
import random
import time
from .constants import WALK_SPEED, SLEEP_AFTER

# Personality bias tables: (cumulative_probability, next_state)
# Scanned in order — first threshold that exceeds random() wins.
_BIASES: dict[str, dict[str, list[tuple[float, str]]]] = {
    "friendly": {
        "moving": [(0.55, "walking"), (0.90, "idle"), (0.95, "stretch"), (0.98, "jump"), (1.0, "special")],
        "still":  [(0.90, "idle"),    (0.96, "stretch"), (0.98, "jump"), (1.0, "special")],
    },
    "focused": {
        # Stays mostly idle; nudge fires on a separate timer (see tick)
        "moving": [(0.10, "walking"), (0.95, "idle"), (0.98, "stretch"), (1.0, "special")],
        "still":  [(0.95, "idle"),    (0.98, "stretch"), (1.0, "special")],
    },
    "playful": {
        # Chases cursor when movement is on; very active otherwise
        "moving": [(0.38, "walking"), (0.60, "idle"), (0.76, "chasing"), (0.84, "stretch"), (0.93, "jump"), (1.0, "special")],
        "still":  [(0.65, "idle"),    (0.82, "stretch"), (0.90, "jump"),  (1.0, "special")],
    },
}

_RESPONSES = {
    "action": ("waving",),
    "nudge": ("waiting",),
    "jump": ("jumping",),
    "special": ("review",),
    "petting": ("petting", "review"),
    "landing": ("landing", "jumping"),
    "waking": ("waking", "waiting"),
    "stretch": ("stretching", "waiting"),
    "celebrate": ("celebrate", "review"),
}


class PetState:
    """Platform-agnostic animation, movement, and personality state machine.

    Coordinates use whatever system the platform provides — PetState does not
    assume a top-left origin.  Pass sx/sy as the minimum x/y of the usable
    screen area and sw/sh as its width/height.  macOS uses a bottom-left
    origin, so callers pass the visibleFrame values directly and supply an
    explicit start_y (sy + 80) to position the pet near the bottom.
    """

    def __init__(
        self,
        sx: float, sy: float,
        sw: float, sh: float,
        tw: int,   th: int,
        start_x: float | None = None,
        start_y: float | None = None,
        *,
        anims: dict,
    ):
        self.sx, self.sy = sx, sy
        self.sw, self.sh = sw, sh
        self.tw, self.th = tw, th

        self.x = start_x if start_x is not None else float(sx + sw - tw - 120)
        self.y = start_y if start_y is not None else float(sy + sh - th - 80)

        self.anim        = "idle"
        self.fidx        = 0
        self.is_dragging = False
        self.moving      = False
        self.personality = "friendly"
        self.anims = anims

        self._ftimer        = 0.0
        self._state         = "idle"
        self._stimer        = random.uniform(4.0, 8.0)
        self._target_x      = self.x
        self._target_y      = self.y
        self._last_interact = time.monotonic()
        self._cursor_x      = self.x
        self._cursor_y      = self.y
        # Focused nudge: fire a "waiting" animation every 60–180 s
        self._nudge_timer   = random.uniform(60.0, 180.0)

    # ── Cursor tracking (Playful mouse-chase) ─────────────────────────────────

    def update_cursor(self, x: float, y: float) -> None:
        self._cursor_x = x
        self._cursor_y = y

    # ── Personality ───────────────────────────────────────────────────────────

    def set_personality(self, name: str) -> None:
        self.personality  = name
        self._nudge_timer = random.uniform(60.0, 180.0)
        if self._state == "chasing" and name != "playful":
            self.enter("idle")

    # ── Hot-resize (scale change without restart) ─────────────────────────────

    def resize(self, tw: int, th: int) -> None:
        self.tw, self.th = tw, th
        self.x = max(self.sx, min(self.sx + self.sw - tw, self.x))
        self.y = max(self.sy, min(self.sy + self.sh - th, self.y))

    # ── Drag & click events ───────────────────────────────────────────────────

    def reset_animations(self, anims: dict) -> None:
        self.anims = anims
        self.is_dragging = False
        self.enter("idle", restart=True)

    def on_drag_start(self) -> None:
        self.is_dragging = True
        self._set_animation("lifted" if "lifted" in self.anims else "jumping", restart=True)
        if self.anim == "jumping":
            self.fidx = self.anims["jumping"][1] // 2

    def on_drag(self, x: float, y: float) -> None:
        """Update position during drag, clamped to screen bounds."""
        self.x = max(self.sx, min(self.sx + self.sw - self.tw, x))
        self.y = max(self.sy, min(self.sy + self.sh - self.th, y))

    @property
    def can_pet(self) -> bool:
        return not self.is_dragging and self._state not in _RESPONSES

    def on_release(self, response="action") -> None:
        landing_frame = None
        if self.is_dragging:
            response = "landing"
            if "landing" not in self.anims:
                landing_frame = self.anims["jumping"][1] // 2
        elif self._state == "sleeping" and response in ("action", "petting"):
            response = "waking"
        self.is_dragging = False
        self._last_interact = time.monotonic()
        if self._state != response or response == "landing":
            self.enter(response, restart=True)
        if landing_frame is not None:
            self.fidx = landing_frame

    # ── Movement toggle ───────────────────────────────────────────────────────

    def set_moving(self, val: bool) -> None:
        self.moving = val
        if val:
            self.enter("walking")
        elif self._state in ("walking", "chasing"):
            self.enter("idle")

    # ── Tick ──────────────────────────────────────────────────────────────────

    def _set_animation(self, animation, *, restart=False, keep_phase=False):
        if animation == self.anim and not restart:
            return
        phase = 0.0
        if keep_phase:
            _, count, fps = self.anims[self.anim]
            phase = (self.fidx + self._ftimer * fps) / count
        self.anim = animation
        _, count, fps = self.anims[animation]
        position = phase * count
        self.fidx = min(count - 1, int(position))
        self._ftimer = (position - self.fidx) / fps

    def tick(self, dt: float, *, pressed=False) -> bool:
        """Advance using elapsed seconds and return whether the pet moved."""
        _, count, fps = self.anims[self.anim]
        held = self.is_dragging and self.anim != "lifted"
        if not held:
            self._ftimer += dt
            elapsed_frames = int(self._ftimer * fps + 1e-9)
            self._ftimer = max(0.0, self._ftimer - elapsed_frames / fps)
            next_frame = self.fidx + elapsed_frames
            if not self.is_dragging and self._state in _RESPONSES and next_frame >= count:
                self.enter("idle")
                return False
            if self._state == "sleeping" and self.anim == "failed":
                self.fidx = min(count - 1, next_frame)
            else:
                self.fidx = next_frame % count

        if self.is_dragging or pressed:
            return False

        if self.personality == "focused":
            self._nudge_timer -= dt
            if self._nudge_timer <= 0:
                self._nudge_timer = random.uniform(60.0, 180.0)
                if self._state in ("idle", "sleeping"):
                    self.enter("nudge")

        self._stimer -= dt

        if self._state == "walking":
            return self._step_toward(self._target_x, self._target_y, dt)

        if self._state == "chasing":
            return self._step_toward(self._cursor_x, self._cursor_y, dt, stop_dist=WALK_SPEED * 4)

        if self._state in ("idle", "sleeping") and self._stimer <= 0:
            self._pick_next()

        return False

    def _step_toward(self, tx, ty, dt, stop_dist=WALK_SPEED * 2):
        max_x = max(self.sx, self.sx + self.sw - self.tw)
        max_y = max(self.sy, self.sy + self.sh - self.th)
        dx = min(max_x, max(self.sx, tx)) - self.x
        dy = min(max_y, max(self.sy, ty)) - self.y
        dist = math.hypot(dx, dy)
        if dist <= stop_dist:
            self.enter("idle")
            return False
        if abs(dx) > max(4, self.tw * 0.07):
            self._set_animation("run_right" if dx > 0 else "run_left", keep_phase=True)
        step = min(dist, WALK_SPEED * min(dt, 0.032) / 0.016)
        self.x += dx / dist * step
        self.y += dy / dist * step
        return True

    # ── State machine ─────────────────────────────────────────────────────────

    def enter(self, state: str, *, restart=False) -> None:
        restart = restart or state != self._state
        self._state = state
        if state == "idle":
            self._set_animation("idle", restart=restart)
            self._stimer = random.uniform(4.0, 10.0)
        elif state == "walking":
            mx = max(0, min(80, (self.sw - self.tw) / 2))
            my = max(0, min(80, (self.sh - self.th) / 2))
            self._target_x = random.uniform(self.sx + mx, self.sx + self.sw - self.tw - mx)
            self._target_y = random.uniform(self.sy + my, self.sy + self.sh - self.th - my)
            self._set_animation("run_right" if self._target_x >= self.x else "run_left", restart=restart)
        elif state == "chasing":
            self._set_animation("run_right" if self._cursor_x >= self.x else "run_left", restart=restart)
        elif state == "sleeping":
            self._set_animation("sleeping" if "sleeping" in self.anims else "failed", restart=restart)
            self._stimer = random.uniform(10.0, 20.0)
        else:
            animation = next(name for name in _RESPONSES[state] if name in self.anims)
            self._set_animation(animation, restart=restart)

    def _pick_next(self) -> None:
        if time.monotonic() - self._last_interact > SLEEP_AFTER:
            self.enter("sleeping")
            return
        key    = "moving" if self.moving else "still"
        biases = _BIASES[self.personality][key]
        r      = random.random()
        chosen = biases[-1][1]
        for threshold, state_name in biases:
            if r < threshold:
                chosen = state_name
                break
        # "chasing" only valid in Playful with movement enabled
        if chosen == "chasing" and not self.moving:
            chosen = "walking"
        self.enter(chosen)

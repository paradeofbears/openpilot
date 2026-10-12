"""
Drive map for the trip card: the drive's GPS path, with each judged bend, launch and stop marked clean or not.

This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

The point is to show where: "12 of 14 corners clean" becomes "these two bends". The path is sampled every
STEP_M while there is a fix, bright where the driver set the speed and faint where openpilot or cruise did.
Marks come from the scorer as (kind, clean, seconds ago) and are placed on the position from that long ago, so
a bend sits at its peak load rather than where it ended. Memory stays bounded: past MAX_POINTS the path is
thinned to every other point and sampled half as often. North is up. Display only.
"""
import math
from collections import deque
from dataclasses import dataclass

import numpy as np
import pyray as rl

from openpilot.system.ui.lib.text_measure import measure_text_cached

STEP_M = 25.0
MAX_POINTS = 4000
MAX_MARKS = 600
RECENT_T = 20.0            # s of positions kept to place marks that refer back in time
MIN_SPAN_M = 150.0         # a trace smaller than this is not worth a map
EARTH_R = 6371000.0

PATH_W = 5.0
MARK_R = 10.0
SMALL_R = 7.0
DRIVER = rl.Color(255, 255, 255, 215)
ASSISTED = rl.Color(255, 255, 255, 60)
CLEAN = rl.Color(128, 216, 166, 255)
SLOPPY = rl.Color(255, 176, 0, 255)
OUTLINE = rl.Color(20, 20, 22, 255)


@dataclass
class Mark:
  kind: str     # bend, launch, stop, brake
  clean: bool
  lat: float
  lon: float


def meters(lat0: float, lon0: float, lat: float, lon: float) -> tuple[float, float]:
  """(east, north) of a point from an origin, equirectangular: plenty for a city-sized drive."""
  return (math.radians(lon - lon0) * EARTH_R * math.cos(math.radians(lat0)), math.radians(lat - lat0) * EARTH_R)


class DriveTrace:
  def __init__(self):
    self.points: list[tuple[float, float, bool]] = []  # (lat, lon, driver set the speed)
    self.marks: list[Mark] = []
    self._step = STEP_M
    self._recent: deque[tuple[float, float, float]] = deque()  # (t, lat, lon)
    self._t = 0.0
    self.version = 0  # bumps whenever there is something new to draw
    self._span, self._span_version = 0.0, -1

  def update(self, dt: float, fix: bool, lat: float, lon: float, driver: bool) -> None:
    self._t += dt
    if not fix:
      return
    self._recent.append((self._t, lat, lon))
    while self._recent and self._t - self._recent[0][0] > RECENT_T:
      self._recent.popleft()
    if self.points:
      last = self.points[-1]
      e, n = meters(last[0], last[1], lat, lon)
      if math.hypot(e, n) < self._step and last[2] == driver:
        return
    self.points.append((lat, lon, driver))
    self.version += 1
    if len(self.points) > MAX_POINTS:
      self.points = self.points[::2]
      self._step *= 2

  def mark(self, kind: str, clean: bool, ago: float) -> None:
    """Place a judged moment at where the car was `ago` seconds back; dropped when there was no fix then."""
    if not self._recent or len(self.marks) >= MAX_MARKS:
      return
    want = self._t - ago
    t, lat, lon = min(self._recent, key=lambda r: abs(r[0] - want))
    if abs(t - want) > 2.0:
      return
    self.marks.append(Mark(kind, clean, lat, lon))
    self.version += 1

  def span(self) -> float:
    if len(self.points) < 2:
      return 0.0
    if self._span_version != self.version:
      lat0, lon0 = self.points[0][0], self.points[0][1]
      xy = np.array([meters(lat0, lon0, p[0], p[1]) for p in self.points])
      self._span, self._span_version = float(np.ptp(xy, axis=0).max()), self.version
    return self._span

  @property
  def drawable(self) -> bool:
    return self.span() >= MIN_SPAN_M


def fit(points_xy: np.ndarray, box: rl.Rectangle, pad: float = 24.0) -> tuple[float, float, float]:
  """Scale and offset that fit (east, north) metres into the box, north up, keeping the aspect: (scale, x0, y0)
  so that screen = (x0 + e * scale, y0 - n * scale)."""
  lo, hi = points_xy.min(axis=0), points_xy.max(axis=0)
  span = np.maximum(hi - lo, 1.0)
  scale = min((box.width - 2 * pad) / span[0], (box.height - 2 * pad) / span[1])
  cx, cy = box.x + box.width / 2, box.y + box.height / 2
  mid = (lo + hi) / 2
  return float(scale), float(cx - mid[0] * scale), float(cy + mid[1] * scale)


class DriveMap:
  """Draws a DriveTrace into a box; screen positions are cached until the trace or the box changes."""

  def __init__(self):
    self._key = None
    self._runs: list[tuple[np.ndarray, bool]] = []
    self._marks: list[tuple[float, float, Mark]] = []
    self._ends: tuple | None = None

  def _layout(self, trace: DriveTrace, box: rl.Rectangle) -> None:
    key = (trace.version, len(trace.points), box.x, box.y, box.width, box.height)
    if key == self._key:
      return
    self._key = key
    lat0, lon0 = trace.points[0][0], trace.points[0][1]
    xy = np.array([meters(lat0, lon0, p[0], p[1]) for p in trace.points], dtype=np.float64)
    scale, x0, y0 = fit(xy, box)
    screen = np.column_stack((x0 + xy[:, 0] * scale, y0 - xy[:, 1] * scale)).astype(np.float32)
    # split into runs of the same driver flag, overlapping by a point so the path stays joined
    self._runs = []
    start = 0
    for i in range(1, len(trace.points) + 1):
      if i == len(trace.points) or trace.points[i][2] != trace.points[start][2]:
        end = min(i + 1, len(trace.points))
        self._runs.append((np.ascontiguousarray(screen[start:end]), trace.points[start][2]))
        start = i
    self._marks = []
    for m in trace.marks:
      e, n = meters(lat0, lon0, m.lat, m.lon)
      self._marks.append((x0 + e * scale, y0 - n * scale, m))
    self._ends = (tuple(screen[0]), tuple(screen[-1]))

  def render(self, trace: DriveTrace, box: rl.Rectangle, alpha: float) -> None:
    if len(trace.points) < 2:
      return
    self._layout(trace, box)
    for pts, driver in self._runs:
      if len(pts) >= 2:
        color = _fade(DRIVER if driver else ASSISTED, alpha)
        rl.draw_spline_linear(rl.ffi.cast("Vector2 *", rl.ffi.from_buffer(pts)), len(pts), PATH_W, color)
    start, end = self._ends
    rl.draw_circle_v(rl.Vector2(*start), 9, _fade(OUTLINE, alpha))
    rl.draw_ring(rl.Vector2(*start), 6, 9, 0, 360, 24, _fade(DRIVER, alpha))
    rl.draw_circle_v(rl.Vector2(*end), 9, _fade(DRIVER, alpha))
    # sloppy marks last so they are never hidden under clean ones
    for x, y, m in sorted(self._marks, key=lambda t: t[2].clean, reverse=True):
      draw_mark(x, y, m.kind, m.clean, alpha)


def draw_mark(x: float, y: float, kind: str, clean: bool, alpha: float) -> None:
  color = _fade(CLEAN if clean else SLOPPY, alpha)
  if kind == "bend":
    rl.draw_circle_v(rl.Vector2(x, y), MARK_R + 2, _fade(OUTLINE, alpha))
    rl.draw_circle_v(rl.Vector2(x, y), MARK_R, color)
  else:  # launches, stops and brakes: rings, so they read apart from bends
    rl.draw_circle_v(rl.Vector2(x, y), SMALL_R + 2, _fade(OUTLINE, alpha))
    rl.draw_ring(rl.Vector2(x, y), SMALL_R - 3, SMALL_R, 0, 360, 24, color)


def render_legend(x: float, y: float, font: rl.Font, size: int, label: rl.Color, alpha: float) -> None:
  """Two lines under the map: colour is clean or not, shape is a corner or a launch/stop."""
  rows = (((("bend", True), "clean"), (("bend", False), "to work on")),
          ((("bend", True), "corner"), (("stop", True), "launch / stop")))
  for r, row in enumerate(rows):
    cx = x
    for (kind, clean), text in row:
      cy = y + r * (size + 14) + size / 2
      draw_mark(cx + MARK_R, cy, kind, clean if r == 0 else True, alpha)
      rl.draw_text_ex(font, text, rl.Vector2(cx + 2 * MARK_R + 10, cy - size / 2), size, 0, _fade(label, alpha))
      cx += 2 * MARK_R + 10 + measure_text_cached(font, text, size).x + 34


def _fade(c: rl.Color, a: float) -> rl.Color:
  return rl.Color(c.r, c.g, c.b, int(c.a * a))

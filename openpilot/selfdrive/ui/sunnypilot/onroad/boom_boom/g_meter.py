"""
G-force meter: a friction-circle dot with a short trail and the drive's peak.

This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

Source: locationd's deviceMotion. Its accelerationDevice is the rate of change of device velocity
with gravity removed, and the pose filter carries the centripetal part (omega x v) separately
(locationd/models/pose_kf.py), so cornering G is a_y + yaw_rate * v_x. Device frame: x forward,
y right, z down. When deviceMotion is not valid the meter falls back to carState.aEgo and
controlsState.curvature * v^2. The device's few degrees of mounting yaw are not rotated out.

The dot shows which way the car is accelerating: up when speeding up, down when braking, toward
the inside of a turn. Display only.
"""
from collections import deque

import numpy as np
import pyray as rl

from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.system.ui.lib.application import FontWeight, gui_app
from openpilot.system.ui.lib.text_measure import measure_text_cached

G = 9.81
FULL_SCALE_G = 0.6       # the circle's edge
RINGS_G = (0.2, 0.4)
TRAIL_T = 1.5            # s of trail
RADIUS = 115
MARGIN = 50              # px from the view's edges
TEXT_SIZE = 46
LABEL_SIZE = 30
BG = rl.Color(0, 0, 0, 140)
RING = rl.Color(255, 255, 255, 60)
CROSS = rl.Color(255, 255, 255, 40)
DOT = rl.Color(255, 255, 255, 255)
PEAK = rl.Color(255, 176, 0, 220)


def g_from_device_motion(dm) -> tuple[float, float] | None:
  """(longitudinal, lateral right-positive) in g, or None when locationd's output is not usable."""
  acc, omega, vel = dm.accelerationDevice, dm.angularVelocityDevice, dm.velocityDevice
  if not (dm.inputsOK and dm.sensorsOK and acc.valid and omega.valid and vel.valid):
    return None
  return acc.x / G, (acc.y + omega.z * vel.x) / G


def g_from_car(a_ego: float, curvature: float, v_ego: float) -> tuple[float, float]:
  # controlsState.curvature is left-positive; lateral here is right-positive
  return a_ego / G, -curvature * v_ego ** 2 / G


def dot_offset(g_long: float, g_lat: float, radius: float) -> tuple[float, float]:
  """Screen offset of the dot from the centre, clipped to the circle: right is +x, forward is up."""
  x, y = g_lat / FULL_SCALE_G * radius, -g_long / FULL_SCALE_G * radius
  r = np.hypot(x, y)
  if r > radius:
    x, y = x * radius / r, y * radius / r
  return float(x), float(y)


class GMeter:
  def __init__(self):
    self._long = FirstOrderFilter(0.0, 0.15, 1 / gui_app.target_fps)
    self._lat = FirstOrderFilter(0.0, 0.15, 1 / gui_app.target_fps)
    self._trail: deque[tuple[float, float, float]] = deque()  # (age s, long, lat)
    self.peak = 0.0
    self.from_device = False

  def reset(self) -> None:
    self._long.x = self._lat.x = 0.0
    self._trail.clear()
    self.peak = 0.0

  def update(self, sm, device_motion, dt: float) -> None:
    g = g_from_device_motion(device_motion) if device_motion is not None else None
    self.from_device = g is not None
    if g is None:
      cs = sm['carState']
      g = g_from_car(cs.aEgo, sm['controlsState'].curvature, cs.vEgo)
    g_long = self._long.update(g[0])
    g_lat = self._lat.update(g[1])
    self.peak = max(self.peak, float(np.hypot(g_long, g_lat)))

    self._trail = deque((age + dt, lo, la) for age, lo, la in self._trail if age + dt < TRAIL_T)
    self._trail.append((0.0, g_long, g_lat))

  @property
  def total(self) -> float:
    return float(np.hypot(self._long.x, self._lat.x))

  def render(self, rect: rl.Rectangle, on_left: bool = False) -> None:
    font = gui_app.font(FontWeight.SEMI_BOLD)
    text_h = TEXT_SIZE + 8
    cx = rect.x + MARGIN + RADIUS if on_left else rect.x + rect.width - MARGIN - RADIUS
    cy = rect.y + rect.height - MARGIN - text_h - RADIUS
    center = rl.Vector2(cx, cy)

    rl.draw_circle_v(center, RADIUS + 10, BG)
    for g in RINGS_G:
      rl.draw_ring(center, g / FULL_SCALE_G * RADIUS - 1.5, g / FULL_SCALE_G * RADIUS + 1.5, 0, 360, 72, RING)
    rl.draw_ring(center, RADIUS - 2, RADIUS + 2, 0, 360, 72, RING)
    rl.draw_line_ex(rl.Vector2(cx - RADIUS, cy), rl.Vector2(cx + RADIUS, cy), 2, CROSS)
    rl.draw_line_ex(rl.Vector2(cx, cy - RADIUS), rl.Vector2(cx, cy + RADIUS), 2, CROSS)

    # the drive's peak, as a ring at that radius
    if self.peak > 0.05:
      pr = min(self.peak / FULL_SCALE_G, 1.0) * RADIUS
      rl.draw_ring(center, pr - 2, pr + 2, 0, 360, 72, PEAK)

    for age, lo, la in self._trail:
      x, y = dot_offset(lo, la, RADIUS)
      fade = 1.0 - age / TRAIL_T
      rl.draw_circle_v(rl.Vector2(cx + x, cy + y), 4 + 6 * fade, rl.Color(255, 255, 255, int(110 * fade)))

    x, y = dot_offset(self._long.x, self._lat.x, RADIUS)
    rl.draw_circle_v(rl.Vector2(cx + x, cy + y), 14, DOT)

    text = f"{self.total:.2f} g"
    size = measure_text_cached(font, text, TEXT_SIZE)
    rl.draw_text_ex(font, text, rl.Vector2(cx - size.x / 2, cy + RADIUS + 14), TEXT_SIZE, 0, DOT)
    if self.peak > 0.05:
      peak_text = f"{self.peak:.2f}"
      psize = measure_text_cached(font, peak_text, LABEL_SIZE)
      rl.draw_text_ex(font, peak_text, rl.Vector2(cx + RADIUS - psize.x + 6, cy - RADIUS - 4), LABEL_SIZE, 0, PEAK)

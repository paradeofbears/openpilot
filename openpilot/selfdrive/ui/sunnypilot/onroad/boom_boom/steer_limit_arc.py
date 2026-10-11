"""
Steering limit arc: a calmer replacement for the steering arc that only shows up near the EPS limit.

This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

The stock arc draws all the time while lateral is active. This one stays invisible in ordinary
steering and fades in as delivered torque approaches the rail the EPS can apply at this speed
(EPS_CEILING_LOOKUP / STEER_MAX, via get_steer_rail_schedule). Past the rail it draws in red the part
of the request that was cut off (carControl.actuators.torque beyond carOutput.actuatorsOutput.torque),
and a red outline while the torque controller reports saturation: the moment behind
"Turn Exceeds Steering Limit". Display only.
"""
from dataclasses import dataclass

import numpy as np
import pyray as rl

from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.system.ui.lib.application import gui_app

SHOW_BP = [0.45, 0.65]   # fraction of the rail: invisible below the first, fully drawn from the second
WARN_BP = [0.75, 0.95]   # white to amber across this band; red from the end of it
OVERFLOW_MAX = 0.5       # cut-off request drawn up to half the arc again
OVERFLOW_MIN = 0.03      # ignore rounding-size differences between request and output

RADIUS = 3600            # px; same far-below centre as the stock arc at scale 3, so it sits in the same place
HALF_SPAN_DEG = 6.0      # the rail sits this far either side of the top
THICKNESS = 22
DASH_DEG = 0.7           # dash pitch of the cut-off request
BOTTOM_OFFSET = 70       # px from the bottom of the view to the arc's outer edge
TRACK = rl.Color(255, 255, 255, 46)
WHITE = rl.Color(255, 255, 255, 235)
AMBER = rl.Color(255, 176, 0, 255)
RED = rl.Color(235, 40, 40, 255)


@dataclass
class ArcLevels:
  level: float = 0.0       # signed delivered torque as a fraction of the rail, + is left
  overflow: float = 0.0    # cut-off request beyond the rail, same units, >= 0
  visible: float = 0.0     # 0..1 target opacity
  saturated: bool = False


def arc_levels(lat_active: bool, requested: float, delivered: float, rail: float, saturated: bool,
               steering_pressed: bool) -> ArcLevels:
  if not lat_active or rail <= 0:
    return ArcLevels()
  level = float(np.clip(delivered / rail, -1.0, 1.0))
  overflow = 0.0
  limited = not steering_pressed  # a driver steering against the wheel is not the EPS limit
  if limited and requested * delivered >= 0:
    overflow = abs(requested) / rail - 1.0
    overflow = float(np.clip(overflow, 0.0, OVERFLOW_MAX)) if overflow > OVERFLOW_MIN else 0.0
  sat = saturated and limited
  visible = float(np.interp(max(abs(level), abs(requested) / rail), SHOW_BP, [0.0, 1.0]))
  if sat or overflow > 0:
    visible = 1.0
  return ArcLevels(level, overflow, visible, sat)


def fill_color(level: float) -> rl.Color:
  x = abs(level)
  if x >= WARN_BP[1]:
    return RED
  t = float(np.interp(x, WARN_BP, [0.0, 1.0]))
  white = (WHITE.r, WHITE.g, WHITE.b, WHITE.a)
  amber = (AMBER.r, AMBER.g, AMBER.b, AMBER.a)
  return rl.Color(*(int(a + (b - a) * t) for a, b in zip(white, amber, strict=True)))


class SteerLimitArc:
  def __init__(self):
    self._level = FirstOrderFilter(0.0, 0.1, 1 / gui_app.target_fps)
    self._overflow = FirstOrderFilter(0.0, 0.1, 1 / gui_app.target_fps)
    self._alpha = FirstOrderFilter(0.0, 0.2, 1 / gui_app.target_fps)
    self._saturated = False
    self._t = 0.0

  def reset(self) -> None:
    for f in (self._level, self._overflow, self._alpha):
      f.x = 0.0
    self._saturated = False

  def update(self, sm, rail_schedule, dt: float) -> None:
    cs = sm['carState']
    cc = sm['carControl']
    rail = float(np.interp(cs.vEgo, rail_schedule[0], rail_schedule[1])) if rail_schedule is not None else 1.0
    lat_state = sm['controlsState'].lateralControlState
    saturated = lat_state.which() == 'torqueState' and lat_state.torqueState.saturated
    lv = arc_levels(cc.latActive, cc.actuators.torque, sm['carOutput'].actuatorsOutput.torque, rail, saturated,
                    cs.steeringPressed)
    self._level.update(lv.level)
    self._overflow.update(lv.overflow)
    self._alpha.update(lv.visible)
    self._saturated = lv.saturated
    self._t += dt

  def render(self, rect: rl.Rectangle) -> None:
    a = self._alpha.x
    if a < 0.02:
      return
    mid_r = RADIUS + THICKNESS / 2
    center = rl.Vector2(rect.x + rect.width / 2, rect.y + rect.height - BOTTOM_OFFSET + RADIUS + THICKNESS)
    top = -90.0

    # faint track out to the rail, with end ticks marking the limit
    _arc(center, mid_r, top - HALF_SPAN_DEG, top + HALF_SPAN_DEG, _fade(TRACK, a), caps=False)
    for side in (-1, 1):
      _tick(center, mid_r, top + side * HALF_SPAN_DEG, _fade(WHITE, a * 0.6))

    level = self._level.x
    direction = -1.0 if level >= 0 else 1.0  # left (positive) torque grows counter-clockwise, to the left
    end = top + direction * HALF_SPAN_DEG * abs(level)
    if abs(level) > 0.01:
      _arc(center, mid_r, top, end, _fade(fill_color(level), a))

    over = self._overflow.x
    if over > 0.01:
      # dashed, so the request that never reached the wheel reads differently from delivered torque
      rail_end = top + direction * HALF_SPAN_DEG
      span = HALF_SPAN_DEG * over
      n = max(1, int(span / DASH_DEG))
      for i in range(n):
        a0 = rail_end + direction * (span * i / n + DASH_DEG * 0.35)
        a1 = rail_end + direction * span * (i + 1) / n
        _arc(center, mid_r, a0, a1, _fade(RED, a * 0.75), caps=False)

    if self._saturated:
      pulse = 0.55 + 0.45 * abs(np.sin(self._t * 6.0))
      half = HALF_SPAN_DEG * (1.0 + OVERFLOW_MAX)
      inner, outer = mid_r - THICKNESS / 2 - 6, mid_r + THICKNESS / 2 + 6
      color = _fade(RED, a * pulse)
      rl.draw_ring(center, outer, outer + 4, top - half, top + half, 96, color)
      rl.draw_ring(center, inner - 4, inner, top - half, top + half, 96, color)


def _arc(center: rl.Vector2, mid_r: float, a0: float, a1: float, color: rl.Color, caps: bool = True) -> None:
  lo, hi = min(a0, a1), max(a0, a1)
  rl.draw_ring(center, mid_r - THICKNESS / 2, mid_r + THICKNESS / 2, lo, hi, 64, color)
  if caps:  # round end caps; only on opaque fills, where the overlap does not show
    for ang in (lo, hi):
      rl.draw_circle_v(_point(center, mid_r, ang), THICKNESS / 2, color)


def _tick(center: rl.Vector2, mid_r: float, ang: float, color: rl.Color) -> None:
  rl.draw_line_ex(_point(center, mid_r - THICKNESS, ang), _point(center, mid_r + THICKNESS, ang), 4, color)


def _point(center: rl.Vector2, r: float, ang_deg: float) -> rl.Vector2:
  rad = np.radians(ang_deg)
  return rl.Vector2(center.x + r * float(np.cos(rad)), center.y + r * float(np.sin(rad)))


def _fade(c: rl.Color, a: float) -> rl.Color:
  return rl.Color(c.r, c.g, c.b, int(c.a * max(0.0, min(1.0, a))))

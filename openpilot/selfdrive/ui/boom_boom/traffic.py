"""
Traffic box: a small top-down map of the cars openpilot knows about, after Daytona USA's TRAFFIC box.

This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

What it can show depends on what the car reports:
  - ahead in your lane: radarState's two leads (distance, offset, closing speed). Under openpilot
    longitudinal (alpha long) the stock radar is silenced, so these come from the driving model;
  - ahead in other lanes: the stock radar's tracks (radarTracks, up to four on a Mazda), only with
    stock cruise, because alpha long silences the radar;
  - beside and behind: the blind-spot monitor's one bit per side, drawn as a zone, not a position.
Nothing reports a car directly behind. Lane lines come from the model. Display only.

Sign conventions: radarState / radarTracks yRel is left-positive; modelV2 lane lines are in the device
frame, y right-positive. Screen x grows to the right.
"""
from dataclasses import dataclass

import numpy as np
import pyray as rl

from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.system.ui.lib.application import FontWeight, gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.lib.text_measure import measure_text_cached

from .compat import sp

# forward distance (m) to height fraction, compressed so near traffic gets most of the box
D_BP = [-12.0, 0.0, 15.0, 40.0, 80.0]
D_FRAC = [0.0, 0.17, 0.45, 0.73, 1.0]
LAT_RANGE = 6.0          # m either side of centre, about a lane and a half
TRACK_MATCH = 2.5        # m; a radar track this close to a drawn lead is that lead
CLOSING = -1.0           # m/s; below this a car is coming back toward us
TTC_WARN = 3.0           # s

BOX_W = 280
BOX_H = 440
MIN_BOX_H = 300
MARGIN = 50
TOP_CLEAR = 270          # below the experimental-mode button in the top-right corner
TITLE_SIZE = 32
CAR_W, CAR_H = 30, 50   # our own car
LEAD_R = 17             # radarState's leads
TRACK_R = 11            # raw radar tracks

BG = rl.Color(0, 0, 0, 150)
FRAME = rl.Color(255, 255, 255, 90)
LANE = rl.Color(255, 255, 255, 200)
EGO = rl.Color(128, 216, 166, 255)
EGO_IDLE = rl.Color(220, 220, 220, 255)
CAR = rl.Color(255, 255, 255, 240)
TRACK = rl.Color(170, 170, 170, 220)
AMBER = rl.Color(255, 176, 0, 255)
RED = rl.Color(235, 40, 40, 255)
ZONE = rl.Color(255, 176, 0, 150)
ZONE_WARN = rl.Color(235, 40, 40, 200)


@dataclass
class Car:
  d: float        # m ahead of the front bumper
  y: float        # m, left-positive
  v_rel: float    # m/s, negative when closing
  lead: bool      # one of radarState's leads (else a raw radar track)


def car_color(c: Car) -> rl.Color:
  if c.v_rel < CLOSING and c.d > 0 and c.d / -c.v_rel < TTC_WARN:
    return RED
  if c.v_rel < CLOSING:
    return AMBER
  return CAR if c.lead else TRACK


def gather_cars(radar_state, radar_tracks) -> list[Car]:
  """radarState's leads, plus any radar track that is not one of them."""
  cars = [Car(l.dRel, l.yRel, l.vRel, True) for l in (radar_state.leadOne, radar_state.leadTwo) if l.present]
  # leadTwo is often the same car as leadOne; keep one of them
  if len(cars) == 2 and abs(cars[0].d - cars[1].d) < TRACK_MATCH and abs(cars[0].y - cars[1].y) < TRACK_MATCH:
    cars.pop()
  if radar_tracks is not None:
    for p in radar_tracks.points:
      if not any(abs(p.dRel - c.d) < TRACK_MATCH and abs(p.yRel - c.y) < TRACK_MATCH for c in cars):
        cars.append(Car(p.dRel, p.yRel, p.vRel, False))
  return cars


def box_rect(view: rl.Rectangle, right_inset: float, below_g_meter: float) -> "rl.Rectangle | None":
  """The box's place on the right, above the G-meter when it is on; None when there is no room."""
  bottom = view.y + view.height - MARGIN - below_g_meter
  top_limit = view.y + TOP_CLEAR
  h = min(BOX_H, bottom - top_limit)
  if h < MIN_BOX_H:
    return None
  return rl.Rectangle(view.x + view.width - MARGIN - right_inset - BOX_W, bottom - h, BOX_W, h)


class Mapper:
  """Metres (forward d, left-positive y) to screen pixels inside the box's map area."""

  def __init__(self, area: rl.Rectangle):
    self.area = area

  def __call__(self, d: float, y_left: float) -> tuple[float, float]:
    frac = float(np.interp(d, D_BP, D_FRAC))
    sx = self.area.x + self.area.width / 2 - y_left / LAT_RANGE * self.area.width / 2
    sy = self.area.y + self.area.height * (1.0 - frac)
    return sx, sy

  def inside(self, d: float, y_left: float) -> bool:
    return D_BP[0] <= d <= D_BP[-1] and abs(y_left) <= LAT_RANGE


class TrafficBox:
  def __init__(self):
    self.cars: list[Car] = []
    self.lanes: list[tuple[np.ndarray, np.ndarray, float]] = []  # (x fwd, y left, prob)
    self.blind_left = False
    self.blind_right = False
    self.blink_left = False
    self.blink_right = False
    self.engaged = False
    self._alpha = FirstOrderFilter(0.0, 0.2, 1 / gui_app.target_fps)

  def reset(self) -> None:
    self.cars = []
    self.lanes = []
    self._alpha.x = 0.0

  def update(self, sm, radar_tracks, engaged: bool) -> None:
    cs = sm['carState']
    self.cars = gather_cars(sm['radarState'], radar_tracks)
    model = sm['modelV2']
    probs = list(model.laneLineProbs)
    self.lanes = []
    for i, line in enumerate(model.laneLines):
      prob = probs[i] if i < len(probs) else 0.0
      if prob > 0.2 and len(line.x):
        self.lanes.append((np.asarray(line.x), -np.asarray(line.y), prob))
    self.blind_left, self.blind_right = cs.leftBlindspot, cs.rightBlindspot
    self.blink_left, self.blink_right = cs.leftBlinker, cs.rightBlinker
    self.engaged = engaged
    # the green-light and lead-departure circles sit on the right too; they win
    plan_sp = sp(sm, 'longitudinalPlanSP')
    alerts = plan_sp.e2eAlerts if plan_sp is not None else None
    self._alpha.update(0.0 if alerts is not None and (alerts.greenLightAlert or alerts.leadDepartAlert) else 1.0)

  def render(self, rect: rl.Rectangle) -> None:
    a = self._alpha.x
    if a < 0.02:
      return
    font = gui_app.font(FontWeight.BOLD)
    rl.draw_rectangle_rounded(rect, 0.08, 10, _fade(BG, a))
    rl.draw_rectangle_rounded_lines_ex(rect, 0.08, 10, 3, _fade(FRAME, a))
    title = tr("TRAFFIC")
    tsize = measure_text_cached(font, title, TITLE_SIZE)
    rl.draw_text_ex(font, title, rl.Vector2(rect.x + (rect.width - tsize.x) / 2, rect.y + rect.height - TITLE_SIZE - 10),
                    TITLE_SIZE, 0, _fade(FRAME, a * 2))

    area = rl.Rectangle(rect.x + 14, rect.y + 14, rect.width - 28, rect.height - TITLE_SIZE - 34)
    to_px = Mapper(area)
    rl.begin_scissor_mode(int(area.x), int(area.y), int(area.width), int(area.height))

    for xs, ys, prob in self.lanes:
      keep = (xs >= 0) & (xs <= D_BP[-1])
      if not keep.any():
        continue
      # the model starts at the device; carry each line straight back past our car to the box's edge
      xs, ys = np.r_[D_BP[0], xs[keep]], np.r_[ys[keep][0], ys[keep]]
      pts = [rl.Vector2(*to_px(float(x), float(y))) for x, y in zip(xs, ys, strict=True)]
      for p0, p1 in zip(pts, pts[1:], strict=False):
        rl.draw_line_ex(p0, p1, 3, _fade(LANE, a * min(1.0, prob)))

    for left, on, blink in ((True, self.blind_left, self.blink_left), (False, self.blind_right, self.blink_right)):
      if on:
        side = 1.0 if left else -1.0
        x0, y0 = to_px(4.0, side * 2.0)
        x1, y1 = to_px(-10.0, side * 5.2)
        zone = rl.Rectangle(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))
        rl.draw_rectangle_rounded(zone, 0.3, 8, _fade(ZONE_WARN if blink else ZONE, a))

    for c in sorted(self.cars, key=lambda c: -c.d):
      if not to_px.inside(c.d, c.y):
        continue
      x, y = to_px(c.d + 2.0, c.y)  # dRel is the bumper; draw the car's middle
      # dots, not car shapes: a block reads as part of the lane lines it sits between
      rl.draw_circle_v(rl.Vector2(x, y), LEAD_R if c.lead else TRACK_R, _fade(car_color(c), a))
    rl.end_scissor_mode()

    # our car, nose at d = 0
    ex, ey = to_px(-2.2, 0.0)
    ego = rl.Rectangle(ex - CAR_W / 2, ey - CAR_H / 2, CAR_W, CAR_H)
    rl.draw_rectangle_rounded(ego, 0.35, 8, _fade(EGO if self.engaged else EGO_IDLE, a))
    rl.draw_rectangle_rounded(rl.Rectangle(ego.x + 6, ego.y + 8, CAR_W - 12, 12), 0.4, 6, _fade(BG, a))


def _fade(c: rl.Color, a: float) -> rl.Color:
  return rl.Color(c.r, c.g, c.b, int(min(255, c.a * a)))

"""
Trip card: a summary of the drive, shown when the car is put in Park.

This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

Accumulates from the moment the device goes onroad: distance, time, speeds, how much of the
distance openpilot steered and drove, disengagements, hard brakes and starts, a smoothness share,
and from GPS the climb, descent and how often there was a fix. There is no fuel data without the
car's CAN, so the card says nothing about economy. Display only.
"""
from dataclasses import dataclass

import pyray as rl

from opendbc.car.structs import car
from openpilot.common.constants import CV
from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.system.ui.lib.application import FontWeight, gui_app
from openpilot.system.ui.lib.multilang import tr

GearShifter = car.CarState.GearShifter

MOVING_SPEED = 0.5        # m/s
DISENGAGE_SPEED = 2.0     # m/s; a disengagement at a crawl or a stop is parking, not a takeover
HARD_BRAKE = -3.0         # m/s^2, entering a hard-brake event
HARD_BRAKE_EXIT = -2.0
HARD_ACCEL = 2.5          # m/s^2, entering a hard-start event
HARD_ACCEL_EXIT = 1.8
SMOOTH_ACCEL = 1.0        # m/s^2; moving time inside +/- this counts as smooth
CLIMB_STEP = 5.0          # m; altitude must move this far before it counts, so GPS noise does not
GPS_MAX_VACC = 15.0       # m vertical accuracy; worse fixes are not used for altitude
MIN_SHOW_DISTANCE = 50.0  # m; a few metres in a car park is not a trip
METERS_PER_MILE = 1609.344
FEET_PER_METER = 3.28084

PANEL_W = 1240
ROW_H = 132
PAD = 44
TITLE_SIZE = 56
VALUE_SIZE = 64
LABEL_SIZE = 30
PANEL_BG = rl.Color(20, 20, 22, 245)
TITLE = rl.Color(255, 255, 255, 255)
VALUE = rl.Color(255, 255, 255, 255)
LABEL = rl.Color(255, 255, 255, 150)
ACCENT = rl.Color(128, 216, 166, 255)


@dataclass
class TripStats:
  total_t: float = 0.0
  moving_t: float = 0.0
  smooth_t: float = 0.0
  distance: float = 0.0       # m
  lat_distance: float = 0.0   # m with openpilot steering
  long_distance: float = 0.0  # m with openpilot driving speed
  max_speed: float = 0.0      # m/s
  hard_brakes: int = 0
  hard_accels: int = 0
  disengagements: int = 0
  climb: float = 0.0          # m
  descent: float = 0.0        # m
  gps_t: float = 0.0          # moving time with a fix
  gps_seen: bool = False

  _braking: bool = False
  _accelerating: bool = False
  _engaged: bool = False
  _alt_ref: float | None = None

  def update(self, dt: float, v_ego: float, a_ego: float, lat_active: bool, long_active: bool, engaged: bool,
             gps_fix: bool = False, altitude: float = 0.0, vertical_accuracy: float = 0.0) -> None:
    self.total_t += dt
    moving = v_ego > MOVING_SPEED
    if moving:
      self.moving_t += dt
      step = v_ego * dt
      self.distance += step
      self.lat_distance += step if lat_active else 0.0
      self.long_distance += step if long_active else 0.0
      self.max_speed = max(self.max_speed, v_ego)
      if abs(a_ego) < SMOOTH_ACCEL:
        self.smooth_t += dt

      if not self._braking and a_ego < HARD_BRAKE:
        self._braking = True
        self.hard_brakes += 1
      if not self._accelerating and a_ego > HARD_ACCEL:
        self._accelerating = True
        self.hard_accels += 1
    if self._braking and a_ego > HARD_BRAKE_EXIT:
      self._braking = False
    if self._accelerating and a_ego < HARD_ACCEL_EXIT:
      self._accelerating = False

    if self._engaged and not engaged and v_ego > DISENGAGE_SPEED:
      self.disengagements += 1
    self._engaged = engaged

    if gps_fix:
      self.gps_seen = True
      if moving:
        self.gps_t += dt
      if vertical_accuracy <= GPS_MAX_VACC:  # 0 when the source does not report it
        self._track_altitude(altitude)

  def _track_altitude(self, altitude: float) -> None:
    if self._alt_ref is None:
      self._alt_ref = altitude
      return
    delta = altitude - self._alt_ref
    if delta >= CLIMB_STEP:
      self.climb += delta
      self._alt_ref = altitude
    elif delta <= -CLIMB_STEP:
      self.descent += -delta
      self._alt_ref = altitude

  def share(self, part: float, whole: float) -> float:
    return part / whole if whole > 0 else 0.0


def fmt_duration(seconds: float) -> str:
  m = int(seconds // 60)
  return f"{m // 60}h {m % 60:02d}m" if m >= 60 else f"{m} min"


class TripCard:
  def __init__(self):
    self.stats = TripStats()
    self._alpha = FirstOrderFilter(0.0, 0.25, 1 / gui_app.target_fps)
    self._show = False
    self._has_long = False

  def reset(self) -> None:
    self.stats = TripStats()
    self._alpha.x = 0.0
    self._show = False

  def update(self, sm, engaged: bool, has_long_control: bool, gps, dt: float) -> None:
    cs = sm['carState']
    cc = sm['carControl']
    self._has_long = has_long_control
    fix = gps is not None and gps.hasFix
    self.stats.update(dt, cs.vEgo, cs.aEgo, cc.latActive, cc.longActive, engaged,
                      fix, gps.altitude if fix else 0.0, gps.verticalAccuracy if fix else 0.0)
    parked = cs.gearShifter == GearShifter.park
    self._show = parked and self.stats.distance >= MIN_SHOW_DISTANCE
    self._alpha.update(1.0 if self._show else 0.0)

  def rows(self, is_metric: bool) -> list[tuple[tuple[str, str], tuple[str, str]]]:
    s = self.stats
    dist_unit, speed_unit = ("km", "km/h") if is_metric else ("mi", "mph")
    dist = s.distance / 1000 if is_metric else s.distance / METERS_PER_MILE
    speed_conv = CV.MS_TO_KPH if is_metric else CV.MS_TO_MPH
    avg = s.distance / s.moving_t * speed_conv if s.moving_t > 0 else 0.0
    height_conv, height_unit = (1.0, "m") if is_metric else (FEET_PER_METER, "ft")

    steered = f"{100 * s.share(s.lat_distance, s.distance):.0f}%"
    if self._has_long:
      steered += f" / {100 * s.share(s.long_distance, s.distance):.0f}%"
    if s.gps_seen:
      climb = f"+{s.climb * height_conv:.0f} / -{s.descent * height_conv:.0f} {height_unit}"
      fix = f"{100 * s.share(s.gps_t, s.moving_t):.0f}%"
    else:
      climb, fix = "-", tr("no fix")

    return [
      ((f"{dist:.1f} {dist_unit}", tr("distance")), (fmt_duration(s.total_t), tr("drive time"))),
      ((f"{avg:.0f} {speed_unit}", tr("average moving speed")), (f"{s.max_speed * speed_conv:.0f} {speed_unit}", tr("top speed"))),
      ((steered, tr("openpilot steered") + (tr(" / drove") if self._has_long else "")),
       (str(s.disengagements), tr("disengagements while moving"))),
      ((f"{s.hard_brakes} / {s.hard_accels}", tr("hard brakes / hard starts")),
       (f"{100 * s.share(s.smooth_t, s.moving_t):.0f}%", tr("smooth driving"))),
      ((climb, tr("climb / descent (GPS)")), (fix, tr("GPS fix while moving"))),
    ]

  def render(self, rect: rl.Rectangle, is_metric: bool) -> None:
    a = self._alpha.x
    if a < 0.02:
      return
    rows = self.rows(is_metric)
    h = PAD * 2 + TITLE_SIZE + 24 + ROW_H * len(rows)
    x = rect.x + (rect.width - PANEL_W) / 2
    y = rect.y + (rect.height - h) / 2
    rl.draw_rectangle_rounded(rl.Rectangle(x, y, PANEL_W, h), 0.06, 12, _fade(PANEL_BG, a))

    bold = gui_app.font(FontWeight.BOLD)
    semi = gui_app.font(FontWeight.SEMI_BOLD)
    medium = gui_app.font(FontWeight.MEDIUM)
    title = tr("This drive")
    rl.draw_text_ex(bold, title, rl.Vector2(x + PAD, y + PAD), TITLE_SIZE, 0, _fade(TITLE, a))
    rl.draw_rectangle(int(x + PAD), int(y + PAD + TITLE_SIZE + 10), 90, 6, _fade(ACCENT, a))

    col_w = (PANEL_W - 2 * PAD) / 2
    row_y = y + PAD + TITLE_SIZE + 24
    for left, right in rows:
      for i, (value, label) in enumerate((left, right)):
        cx = x + PAD + i * col_w
        rl.draw_text_ex(semi, value, rl.Vector2(cx, row_y + 14), VALUE_SIZE, 0, _fade(VALUE, a))
        rl.draw_text_ex(medium, label, rl.Vector2(cx, row_y + 14 + VALUE_SIZE + 4), LABEL_SIZE, 0, _fade(LABEL, a))
      row_y += ROW_H


def _fade(c: rl.Color, a: float) -> rl.Color:
  return rl.Color(c.r, c.g, c.b, int(c.a * a))

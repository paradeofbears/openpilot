"""
This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
from openpilot.cereal import log
from openpilot.common.test import OpenpilotTestCase
from openpilot.selfdrive.ui.sunnypilot.onroad.boom_boom.trip_card import (
  CLIMB_STEP, MIN_SHOW_DISTANCE, TripCard, TripStats, fmt_duration,
)

DT = 0.05


def svc(name, fields):
  return getattr(log.Event.new_message(**{name: fields}).as_reader(), name)


def drive(stats, seconds, v=20.0, a=0.0, lat=False, long=False, engaged=False, **gps):
  for _ in range(round(seconds / DT)):
    stats.update(DT, v, a, lat, long, engaged, **gps)


class TestTripStats(OpenpilotTestCase):
  def test_distance_time_and_speeds(self):
    s = TripStats()
    drive(s, 60, v=20.0)
    drive(s, 30, v=0.0)
    assert abs(s.distance - 1200) < 1 and abs(s.moving_t - 60) < 0.1 and abs(s.total_t - 90) < 0.1
    assert s.max_speed == 20.0

  def test_openpilot_share_by_distance(self):
    s = TripStats()
    drive(s, 30, v=20.0, lat=True, long=True)
    drive(s, 30, v=20.0, lat=True)
    drive(s, 60, v=10.0)
    assert abs(s.share(s.lat_distance, s.distance) - 2 / 3) < 0.01
    assert abs(s.share(s.long_distance, s.distance) - 1 / 3) < 0.01

  def test_hard_events_count_once_each(self):
    s = TripStats()
    drive(s, 2, a=-4.0)      # one long hard brake
    drive(s, 1, a=-2.5)      # still above the exit threshold: same event
    drive(s, 1, a=0.0)
    drive(s, 1, a=-3.5)      # a second one
    drive(s, 1, a=3.0)       # a hard start
    assert s.hard_brakes == 2 and s.hard_accels == 1

  def test_smooth_share(self):
    s = TripStats()
    drive(s, 30, a=0.5)
    drive(s, 10, a=1.5)
    assert abs(s.share(s.smooth_t, s.moving_t) - 0.75) < 0.01

  def test_disengagements_only_while_moving(self):
    s = TripStats()
    drive(s, 5, engaged=True)
    drive(s, 5, engaged=False)       # a takeover at speed
    drive(s, 5, v=0.0, engaged=True)
    drive(s, 5, v=0.0, engaged=False)  # disengaging parked does not count
    assert s.disengagements == 1

  def test_climb_ignores_gps_noise(self):
    s = TripStats()
    for i in range(400):  # +-2 m of noise on flat ground
      s.update(DT, 20.0, 0.0, False, False, False, True, 100.0 + (2.0 if i % 2 else -2.0), 3.0)
    assert s.climb == 0.0 and s.descent == 0.0
    for alt in (100, 103, 106, 110, 114, 108, 101):
      s.update(DT, 20.0, 0.0, False, False, False, True, float(alt), 3.0)
    assert s.climb >= 2 * CLIMB_STEP and s.descent >= CLIMB_STEP

  def test_poor_vertical_accuracy_is_ignored(self):
    s = TripStats()
    s.update(DT, 20.0, 0.0, False, False, False, True, 100.0, 3.0)
    s.update(DT, 20.0, 0.0, False, False, False, True, 200.0, 50.0)
    assert s.climb == 0.0 and s.gps_seen


class TestTripCard(OpenpilotTestCase):
  def sm(self, v, gear):
    return {"carState": svc("carState", {"vEgo": v, "gearShifter": gear}),
            "carControl": svc("carControl", {"latActive": True})}

  def test_shows_only_in_park_after_a_real_trip(self):
    card = TripCard()
    for _ in range(100):
      card.update(self.sm(20.0, "drive"), True, False, None, DT)
    assert not card._show
    card.update(self.sm(0.0, "park"), True, False, None, DT)
    assert card._show and card.stats.distance >= MIN_SHOW_DISTANCE

    short = TripCard()
    short.update(self.sm(5.0, "drive"), True, False, None, DT)
    short.update(self.sm(0.0, "park"), True, False, None, DT)
    assert not short._show

  def test_rows_render_text(self):
    card = TripCard()
    gps = svc("gpsLocation", {"hasFix": True, "altitude": 50.0})
    for _ in range(200):
      card.update(self.sm(25.0, "drive"), True, True, gps, DT)
    rows = card.rows(is_metric=False)
    assert rows[0][0][0] == "0.2 mi"
    assert rows[2][0][0] == "100% / 0%"  # steered all of it, drove none (longActive false)
    assert rows[4][1][0] == "100%"
    assert card.rows(is_metric=True)[0][0][0] == "0.2 km"

  def test_no_gps(self):
    card = TripCard()
    card.update(self.sm(20.0, "drive"), False, False, None, DT)
    assert card.rows(True)[4][0][0] == "-"

  def test_durations(self):
    assert fmt_duration(59) == "0 min"
    assert fmt_duration(61 * 60) == "1h 01m"

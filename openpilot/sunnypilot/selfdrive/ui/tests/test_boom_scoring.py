"""
This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
from openpilot.cereal import log
from openpilot.common.test import OpenpilotTestCase
from openpilot.selfdrive.ui.sunnypilot.onroad.boom_boom.scoring import (
  CHAOS, CLEAN_POINTS, LAUNCH_POINTS, MIN_RANK_DISTANCE, SAFETY, STOP_POINTS, STREAK_MAX, TAILGATE_HOLD,
  TAILGATE_POINTS, DriveScore,
  driver_in_control, rank_letter,
)
from openpilot.selfdrive.ui.sunnypilot.onroad.boom_boom.trip_card import TripCard

DT = 0.05


def drive(s, seconds, v=20.0, a=0.0, driver=True, lead=False, d_rel=100.0):
  for _ in range(round(seconds / DT)):
    s.update(DT, v, a, driver, lead, d_rel)


class TestWhoIsDriving(OpenpilotTestCase):
  def test_control(self):
    assert driver_in_control(False, False, False)        # no cruise: the driver
    assert not driver_in_control(True, False, False)     # the car's cruise
    assert not driver_in_control(True, True, False)      # openpilot long
    assert driver_in_control(True, True, True)           # the driver's foot on the gas overrides


class TestEvents(OpenpilotTestCase):
  def test_one_event_per_excursion_and_only_while_driving(self):
    s = DriveScore(flavour=SAFETY)
    drive(s, 1.0, a=-4.0)
    drive(s, 1.0, a=-2.5)   # still braking hard enough to be the same event
    drive(s, 1.0, a=0.0)
    drive(s, 1.0, a=3.0)
    drive(s, 1.0, a=0.0)
    drive(s, 1.0, a=-4.0, driver=False)  # openpilot's stop is not the driver's
    assert (s.hard_brakes, s.hard_launches) == (1, 1)

  def test_tailgating_needs_speed_and_time_and_counts_once(self):
    s = DriveScore(flavour=CHAOS)
    drive(s, TAILGATE_HOLD - 0.5, v=25.0, lead=True, d_rel=15.0)  # 0.6 s gap, not long enough yet
    assert s.tailgates == 0
    drive(s, 5.0, v=25.0, lead=True, d_rel=15.0)
    assert s.tailgates == 1 and s.points == TAILGATE_POINTS  # tailgating costs points in chaos too
    drive(s, 10.0, v=8.0, lead=True, d_rel=5.0)  # town crawl: not tailgating
    drive(s, 2.0, v=25.0, lead=True, d_rel=50.0)  # gap opens: episode over
    drive(s, 5.0, v=25.0, lead=True, d_rel=15.0)
    assert s.tailgates == 2


class TestPoints(OpenpilotTestCase):
  def test_safety_smooth_distance_with_a_streak(self):
    s = DriveScore(flavour=SAFETY)
    drive(s, 5.0, v=20.0)  # 100 m, streak x1
    assert s.points == CLEAN_POINTS
    drive(s, 60.0, v=20.0)
    assert s.streak == 2
    drive(s, 600.0, v=20.0)
    assert s.streak == STREAK_MAX

  def test_safety_hard_event_breaks_the_streak(self):
    s = DriveScore(flavour=SAFETY)
    drive(s, 130.0)
    assert s.streak == 3
    drive(s, 0.5, a=-4.0)
    drive(s, 0.5)
    assert s.streak == 1 and any("STREAK LOST" in p.text for p in s.popups)

  def test_chaos_scores_events_and_chains_combos(self):
    s = DriveScore(flavour=CHAOS)
    drive(s, 0.5, a=3.0)
    drive(s, 0.5)
    first = s.points
    assert first == 3 * LAUNCH_POINTS == 30_000  # arcade-sized: a 3 m/s^2 launch is 30,000
    assert s.popups[-1].text == "+30,000 LAUNCH"
    drive(s, 2.0)
    drive(s, 0.5, a=-4.0)
    drive(s, 0.5)
    assert s.points == first + 4 * STOP_POINTS * 2  # x2 combo
    drive(s, 30.0)  # combo window lapses
    drive(s, 0.5, a=3.0)
    drive(s, 0.5)
    assert s.points == first + 4 * STOP_POINTS * 2 + first

  def test_chaos_never_scores_speed(self):
    s = DriveScore(flavour=CHAOS)
    drive(s, 60.0, v=45.0)
    assert s.points == 0


class TestRank(OpenpilotTestCase):
  def test_letters(self):
    assert [rank_letter(x) for x in (100, 92, 85, 70, 50, 10)] == ["S", "S", "A", "B", "C", "D"]

  def test_needs_enough_of_your_own_driving(self):
    s = DriveScore(flavour=SAFETY)
    drive(s, (MIN_RANK_DISTANCE - 100) / 20.0)
    assert s.rank() is None
    drive(s, 10.0)
    assert s.rank() == "S"

  def test_flavours_disagree_about_the_same_drive(self):
    calm, wild = DriveScore(flavour=SAFETY), DriveScore(flavour=CHAOS)
    for s in (calm, wild):
      drive(s, 100.0)  # 2 km smooth
    assert (calm.rank(), wild.rank()) == ("S", "D")
    for s in (calm, wild):
      for _ in range(5):
        drive(s, 0.5, a=3.5)
        drive(s, 0.5, a=-4.5)
        drive(s, 5.0)
    assert calm.rank() in ("C", "D") and wild.rank() in ("S", "A")


class TestTripCardScore(OpenpilotTestCase):
  def test_score_follows_flavour_and_control(self):
    def svc(name, fields):
      return getattr(log.Event.new_message(**{name: fields}).as_reader(), name)
    sm = {"carState": svc("carState", {"vEgo": 20.0, "aEgo": 3.0, "gearShifter": "drive",
                                       "cruiseState": {"enabled": False}}),
          "carControl": svc("carControl", {}), "radarState": svc("radarState", {})}
    card = TripCard()
    for _ in range(20):
      card.update(sm, False, True, None, DT, CHAOS)
    assert card.score.hard_launches == 1 and card.score.flavour == CHAOS
    card.reset()
    assert card.score.flavour == CHAOS and card.score.points == 0

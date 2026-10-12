"""
This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
from openpilot.cereal import log
from openpilot.common.test import OpenpilotTestCase
from openpilot.selfdrive.ui.sunnypilot.onroad.boom_boom.scoring import (
  BLIND_SPOT_POINTS, SPIRITED, CLEAN_POINTS, DISTRACTED_POINTS, LAUNCH_POINTS, LIMITER_POINTS, MIN_RANK_DISTANCE, MPH,
  PERFECT_SHIFT_POINTS, SAFETY, SMOOTH_STOP_POINTS, STOP_POINTS, STREAK_MAX, TAILGATE_HOLD, TAILGATE_POINTS, WEAK_LINK,
  DriveScore, Extra, driver_in_control, rank_letter,
)
from openpilot.selfdrive.ui.sunnypilot.onroad.boom_boom.trip_card import TripCard

DT = 0.05


def drive(s, seconds, v=20.0, a=0.0, driver=True, lead=False, d_rel=100.0, x=None):
  for _ in range(round(seconds / DT)):
    s.update(DT, v, a, driver, lead, d_rel, x)


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
    s = DriveScore(flavour=SPIRITED)
    drive(s, TAILGATE_HOLD - 0.5, v=25.0, lead=True, d_rel=15.0)  # 0.6 s gap, not long enough yet
    assert s.tailgates == 0
    drive(s, 5.0, v=25.0, lead=True, d_rel=15.0)
    assert s.tailgates == 1 and s.points == TAILGATE_POINTS  # tailgating costs points in spirited too
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

  def test_spirited_scores_events_and_chains_combos(self):
    s = DriveScore(flavour=SPIRITED)
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

  def test_spirited_never_scores_speed(self):
    s = DriveScore(flavour=SPIRITED)
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
    calm, wild = DriveScore(flavour=SAFETY), DriveScore(flavour=SPIRITED)
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
      card.update(sm, False, True, None, DT, SPIRITED)
    assert card.score.hard_launches == 1 and card.score.flavour == SPIRITED
    card.reset()
    assert card.score.flavour == SPIRITED and card.score.points == 0


class TestRicherMetrics(OpenpilotTestCase):
  def test_smooth_and_harsh_stops(self):
    s = DriveScore(flavour=SAFETY)
    drive(s, 10.0, v=10.0)
    v = 10.0
    for i in range(400):  # easing into the brake, then -1.5 m/s^2 down to a stop
      a = -1.5 * min(1.0, i / 30)
      v = max(0.0, v + a * DT)
      s.update(DT, v, a, True, False, 100.0)
      if v == 0.0:
        break
    drive(s, 1.0, v=0.0)
    assert (s.stops, s.smooth_stops) == (1, 1)
    assert s.points >= SMOOTH_STOP_POINTS

    drive(s, 10.0, v=10.0)
    drive(s, 1.0, v=5.0, a=-4.0)  # stamping on it
    drive(s, 1.0, v=0.0)
    assert (s.stops, s.smooth_stops) == (2, 1)

  def test_hard_corner_and_peak_g(self):
    s = DriveScore(flavour=SPIRITED)
    drive(s, 0.3, x=Extra(lat_g=0.4))  # too short to count
    drive(s, 1.0, x=Extra(lat_g=0.1))
    assert s.hard_corners == 0
    drive(s, 1.0, x=Extra(lat_g=0.4))
    drive(s, 1.0, x=Extra(lat_g=0.1))
    assert s.hard_corners == 1 and abs(s.peak_lat_g - 0.4) < 1e-6
    assert s.points == 16_000 and any("CORNER" in p.text for p in s.popups)

  def test_following_gap_and_ttc(self):
    s = DriveScore(flavour=SAFETY)
    drive(s, 60.0, v=20.0, lead=True, d_rel=50.0, x=Extra(v_rel=-10.0))  # 2.5 s gap, but 5 s to collision
    assert abs(s.gap_sum / s.gap_t - 2.5) < 1e-6 and abs(s.min_ttc - 5.0) < 1e-6
    assert s.following() == 100.0
    close = DriveScore(flavour=SAFETY)
    drive(close, 60.0, v=20.0, lead=True, d_rel=24.0, x=Extra(v_rel=-12.0))  # 1.2 s gap, 2 s to collision
    assert close.following() < 80.0

  def test_distraction_episodes(self):
    s = DriveScore(flavour=SAFETY)
    drive(s, 1.0, x=Extra(distracted=True))  # a glance
    drive(s, 1.0, x=Extra(distracted=False))
    assert s.distractions == 0
    drive(s, 2.5, x=Extra(distracted=True))
    assert s.distractions == 1 and any(p.text == f"{DISTRACTED_POINTS:,} EYES UP" for p in s.popups)
    drive(s, 60.0, x=Extra(distracted=None))  # monitoring off: not counted either way
    assert abs(s.dm_t - 4.5) < 0.1

  def test_signalling_into_an_occupied_blind_spot(self):
    s = DriveScore(flavour=SPIRITED)
    drive(s, 1.0, x=Extra(blinker_left=True))  # nothing there
    drive(s, 1.0, x=Extra())
    drive(s, 1.0, x=Extra(blinker_right=True, blind_spot_right=True))  # held on: counts once
    assert s.blind_spot_signals == 1 and s.points == BLIND_SPOT_POINTS

  def test_speed_over_a_known_limit(self):
    s = DriveScore(flavour=SAFETY)
    drive(s, 60.0, v=20.0, x=Extra())  # limit unknown: nothing counted
    assert s.limit_t == 0.0
    drive(s, 60.0, v=20.0, x=Extra(speed_limit=20.0))
    drive(s, 60.0, v=20.0 + 10 * MPH, x=Extra(speed_limit=20.0))
    assert abs(s.over_limit_t / s.limit_t - 0.5) < 0.01

  def test_eco_limiter_and_perfect_shifts(self):
    s = DriveScore(flavour=SPIRITED)
    drive(s, 10.0, x=Extra(rpm=1800.0, pedal=300.0, gear=3, manual=True))
    assert abs(s.eco_t - 10.0) < 0.1
    drive(s, 0.5, x=Extra(rpm=5400.0, pedal=2000.0, gear=3, manual=True))
    drive(s, 0.1, x=Extra(rpm=3900.0, pedal=2000.0, gear=4, manual=True))  # upshift from 5,400
    assert (s.upshifts, s.perfect_shifts) == (1, 1) and s.points == PERFECT_SHIFT_POINTS
    drive(s, 0.5, x=Extra(rpm=5850.0, gear=4, manual=True))  # on the limiter
    drive(s, 0.1, x=Extra(rpm=4300.0, gear=5, manual=True))  # too late to be perfect
    assert (s.limiter_hits, s.perfect_shifts) == (1, 1)
    assert s.points == PERFECT_SHIFT_POINTS + LIMITER_POINTS

  def test_launch_times(self):
    s = DriveScore(flavour=SPIRITED)
    drive(s, 1.0, v=0.0)
    for i in range(200):  # 3 m/s^2 from a standstill
      s.update(DT, (i + 1) * DT * 3.0, 3.0, True, False, 100.0)
    # timed from MOVING, so the first fraction of a second of creep is not counted
    assert abs(s.best_0_30 - 30 * MPH / 3.0) < 0.2
    assert abs(s.best_0_60 - 60 * MPH / 3.0) < 0.2
    blocked = DriveScore(flavour=SPIRITED)
    drive(blocked, 1.0, v=0.0, lead=True, d_rel=8.0)  # pulling away behind a car is not a launch run
    drive(blocked, 20.0, v=20.0)
    assert blocked.best_0_30 is None


class TestSubScores(OpenpilotTestCase):
  def test_missing_data_is_left_out_and_the_weakest_link_caps(self):
    s = DriveScore(flavour=SAFETY)
    drive(s, 100.0, v=20.0)  # 2 km of calm driving, no lead, no monitoring, no engine data
    smooth, following, awareness, engine = s.sub_scores()
    assert smooth > 90 and following is None and awareness is None and engine is None
    assert s.rank() == "S"

    s = DriveScore(flavour=SAFETY)
    drive(s, 100.0, v=20.0, x=Extra(rpm=5850.0, pedal=2000.0))  # calm otherwise, but sat on the limiter
    drive(s, 100.0, v=20.0, x=Extra(rpm=1500.0, pedal=200.0))
    subs = s.sub_scores()
    assert subs[3] is not None and s.rank_score() <= min(x for x in subs if x is not None) + WEAK_LINK


class TestCardHighlights(OpenpilotTestCase):
  def test_highlights_follow_the_flavour_and_show_dashes_without_data(self):
    card = TripCard()
    card.score = DriveScore(flavour=SPIRITED)
    values = {label: value for value, label in card.highlights()}
    assert len(values) == 6 and values["peak cornering"] == "-" and values["perfect shifts"] == "-"
    card.score = DriveScore(flavour=SPIRITED, lat_t=10.0, peak_lat_g=0.41, manual_t=5.0, upshifts=4, perfect_shifts=3,
                            best_0_30=5.3, best_0_60=12.4)
    values = {label: value for value, label in card.highlights()}
    assert values["peak cornering"] == "0.41 g" and values["perfect shifts"] == "3/4" and values["best 0-60 mph"] == "12.4 s"
    card.score = DriveScore(flavour=SAFETY, stops=4, smooth_stops=3, dm_t=100.0, distracted_t=2.0)
    values = {label: value for value, label in card.highlights()}
    assert values["smooth stops"] == "3/4" and values["eyes on the road"] == "98%" and values["average gap"] == "-"

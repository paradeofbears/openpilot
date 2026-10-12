"""
This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
from openpilot.cereal import log
from openpilot.common.test import OpenpilotTestCase
from openpilot.selfdrive.ui.boom_boom.scoring import (
  BLIND_SPOT_POINTS, CLEAN_LAUNCH_POINTS, CLEAN_POINTS, CONTROLLED_STOP_POINTS, DISTRACTED_POINTS, LIMITER_POINTS, MIN_RANK_DISTANCE, MPH,
  PERFECT_SHIFT_POINTS, SAFETY, CLEAN_BEND_POINTS, SPIRITED_MIN_MOMENTS, SMOOTH_STOP_POINTS, SPIRITED, STREAK_MAX, TAILGATE_HOLD, TAILGATE_POINTS, WEAK_LINK,
  DriveScore, Extra, driver_in_control, rank_letter,
)
from openpilot.selfdrive.ui.boom_boom.trip_card import TripCard

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
    drive(s, 1.0, a=3.5)
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

  def test_spirited_scores_clean_launches_the_same_however_hard(self):
    gentle, hard = DriveScore(flavour=SPIRITED), DriveScore(flavour=SPIRITED)
    for s, a in ((gentle, 2.7), (hard, 4.0)):
      drive(s, 0.5, a=a)
      drive(s, 1.0)
      assert s.points == 0  # not yet: it depends on what follows
      drive(s, 3.0)
      assert s.points == CLEAN_LAUNCH_POINTS == 25_000 and s.popups[-1].text == "+25,000 CLEAN LAUNCH"
    assert (gentle.clean_launches, gentle.launches_judged) == (1, 1)

  def test_launching_into_a_hard_brake_is_not_clean_and_braking_never_scores(self):
    s = DriveScore(flavour=SPIRITED)
    drive(s, 0.5, a=3.5)
    drive(s, 1.0)
    drive(s, 0.5, a=-5.0)  # a panic stop straight after
    drive(s, 5.0)
    assert s.points == 0 and (s.clean_launches, s.launches_judged, s.panic_brakes) == (0, 1, 1)

  def test_controlled_stops_chain_and_panic_breaks_the_combo(self):
    s = DriveScore(flavour=SPIRITED)
    for _ in range(2):
      v = 15.0
      for i in range(400):  # a firm, progressive stop: easing in to -3 m/s^2
        a = -3.0 * min(1.0, i / 30)
        v = max(0.0, v + a * DT)
        s.update(DT, v, a, True, False, 100.0)
        if v == 0.0:
          break
      drive(s, 1.0, v=0.0)
    assert s.controlled_stops == 2 and s.points == CONTROLLED_STOP_POINTS * 3  # the second at x2
    drive(s, 0.5, a=-5.0)
    drive(s, 0.5)
    assert s._combo == 0 and any(p.text == "COMBO LOST" for p in s.popups)

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
    calm, brisk = DriveScore(flavour=SAFETY), DriveScore(flavour=SPIRITED)
    for s in (calm, brisk):
      drive(s, 100.0)  # 2 km smooth
    assert calm.rank() == "S" and brisk.rank() is None  # nothing spirited to judge yet
    for s in (calm, brisk):
      for _ in range(8):  # clean, brisk launches, rolling on and off the throttle
        for i in range(60):
          s.update(DT, 20.0, 3.5 * min(1.0, i / 15, (60 - i) / 15), True, False, 100.0)
        drive(s, 10.0)
    assert calm.rank_score() < 85 and brisk.rank() == "S"

  def test_spirited_needs_enough_spirited_driving_to_rank(self):
    s = DriveScore(flavour=SPIRITED)
    drive(s, 100.0)
    for _ in range(SPIRITED_MIN_MOMENTS - 1):
      drive(s, 1.0, a=3.0)
      drive(s, 10.0)
    assert s.sub_scores() is not None and s.rank() is None and s.points > 0  # points still count
    drive(s, 1.0, a=3.0)
    drive(s, 10.0)
    assert s.rank() is not None

  def test_spirited_rank_punishes_sloppy_launches(self):
    s = DriveScore(flavour=SPIRITED)
    drive(s, 100.0)
    for _ in range(8):  # launch, then stamp on the brake
      drive(s, 1.0, a=3.0)
      drive(s, 0.5, a=-5.0)
      drive(s, 10.0)
    assert s.sub_scores()[0] == 0.0 and s.rank() == "D"


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
    assert s.bends == 0  # too short to judge as a bend

  def test_spirited_bends_score_steadiness_not_load(self):
    s = DriveScore(flavour=SPIRITED)
    for g in (0.25, 0.45):  # a steady bend scores the same at any load
      drive(s, 2.0, x=Extra(lat_g=g))
      drive(s, 0.5, x=Extra(lat_g=0.0))
      assert "CLEAN CORNER" in s.popups[-1].text
    assert (s.clean_bends, s.bends) == (2, 2) and s.points == CLEAN_BEND_POINTS * 3  # the second at x2

    for g in (0.3, 0.3, 0.2, 0.2, 0.3, 0.3):  # unload and reload mid-corner: a correction
      drive(s, 0.4, x=Extra(lat_g=g))
    drive(s, 0.5, x=Extra(lat_g=0.0))
    assert (s.clean_bends, s.bends) == (2, 3) and s.points == CLEAN_BEND_POINTS * 3
    assert any(p.text == "COMBO LOST" for p in s.popups)

    drive(s, 1.0, x=Extra(lat_g=0.3))
    drive(s, 0.5, a=-4.0, x=Extra(lat_g=0.3))  # braking hard mid-corner
    drive(s, 1.0, x=Extra(lat_g=0.3))
    drive(s, 0.5, x=Extra(lat_g=0.0))
    assert (s.clean_bends, s.bends) == (2, 4)
    assert s.points == CLEAN_BEND_POINTS * 3  # neither the hard brake nor the sloppy bends scored

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
    assert len(values) == 6 and values["clean corners"] == "-" and values["perfect shifts"] == "-"
    card.score = DriveScore(flavour=SPIRITED, lat_t=10.0, peak_lat_g=0.41, manual_t=5.0, upshifts=4, perfect_shifts=3,
                            best_0_30=5.3, best_0_60=12.4, bends=5, clean_bends=4)
    values = {label: value for value, label in card.highlights()}
    assert values["clean corners, peak 0.41 g"] == "4/5" and values["perfect shifts"] == "3/4" and values["best 0-60 mph"] == "12.4 s"
    card.score = DriveScore(flavour=SAFETY, stops=4, smooth_stops=3, dm_t=100.0, distracted_t=2.0)
    values = {label: value for value, label in card.highlights()}
    assert values["smooth stops"] == "3/4" and values["eyes on the road"] == "98%" and values["average gap"] == "-"


class TestRealWorldArtefacts(OpenpilotTestCase):
  """Shapes seen on routes 00000017 and 00000018 that are not the driver."""

  def test_creeping_off_from_a_stop_is_not_a_harsh_jerk(self):
    s = DriveScore(flavour=SPIRITED)
    drive(s, 1.0, v=0.0)
    for v, a in ((0.0, 0.0), (0.27, 2.03), (0.54, 2.31), (0.72, 1.35), (0.8, 1.1)):  # aEgo jumps as it creeps
      s.update(DT, v, a, True, False, 100.0)
    assert s.harsh_jerks == 0

  def test_a_one_frame_bump_is_ignored_but_a_real_stab_counts(self):
    s = DriveScore(flavour=SAFETY)
    for a in (0.2, 0.4, 1.12, -0.29, -0.44, 0.14, 0.2):  # route 18 at 17 mph
      s.update(DT, 7.8, a, True, False, 100.0)
    assert s.harsh_jerks == 0
    for a in (0.0, -1.5, -3.0, -4.5, -4.5, -4.5, -4.5):  # stamping on the brake
      s.update(DT, 7.8, a, True, False, 100.0)
    assert s.harsh_jerks == 1

  def test_a_brisk_launch_is_spirited_not_unsafe(self):
    safety, spirited = DriveScore(flavour=SAFETY), DriveScore(flavour=SPIRITED)
    for s in (safety, spirited):
      drive(s, 1.0, a=2.6)  # ~40% throttle in the turbo
      drive(s, 5.0)
    assert safety.hard_launches == 0 and spirited.clean_launches == 1

  def test_one_slip_on_a_short_drive_is_not_ten(self):
    s = DriveScore(flavour=SAFETY)
    drive(s, 60.0, x=Extra(distracted=False))  # 1.2 km
    drive(s, 3.0, x=Extra(distracted=True))
    assert s.distractions == 1 and s.awareness() > 70

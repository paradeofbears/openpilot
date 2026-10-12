"""
This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import time
import unittest
from types import SimpleNamespace

from openpilot.cereal import log
from openpilot.common.test import OpenpilotTestCase
from openpilot.selfdrive.ui.boom_boom import lead_screen
from openpilot.selfdrive.ui.boom_boom.lane_awareness import (
  MIN_SPEED, T_FOLLOW, LaneAwareness, gap_state, side_level,
)


def svc(name, fields):
  return getattr(log.Event.new_message(**{name: fields}).as_reader(), name)


def sm(left_bs=False, left_blink=False, right_bs=False, d_rel=30.0, v_rel=0.0, a_lead=0.0, v_ego=20.0,
       personality="standard", present=True):
  return {
    "carState": svc("carState", {"vEgo": v_ego, "leftBlindspot": left_bs, "leftBlinker": left_blink,
                                 "rightBlindspot": right_bs}),
    "radarState": svc("radarState", {"leadOne": {"present": present, "dRel": d_rel, "vRel": v_rel, "aLeadK": a_lead}}),
    "selfdriveState": svc("selfdriveState", {"personality": personality}),
  }


class TestGap(OpenpilotTestCase):
  def test_seconds_and_target(self):
    g = gap_state(True, 29.0, 0.0, 0.0, 20.0, "standard")
    assert abs(g.seconds - 1.45) < 1e-6 and abs(g.frac - 1.0) < 1e-6 and not g.short
    assert gap_state(True, 20.0, 0.0, 0.0, 20.0, "relaxed").short  # 1.0 s against 1.75

  def test_trend_and_braking(self):
    assert gap_state(True, 30.0, -2.0, 0.0, 20.0, "standard").trend == -1
    assert gap_state(True, 30.0, 2.0, 0.0, 20.0, "standard").trend == 1
    assert gap_state(True, 30.0, 0.2, 0.0, 20.0, "standard").trend == 0
    assert gap_state(True, 30.0, 0.0, -2.0, 20.0, "standard").braking

  def test_none_without_lead_or_at_a_crawl(self):
    assert gap_state(False, 30.0, 0.0, 0.0, 20.0, "standard") is None
    assert gap_state(True, 5.0, 0.0, 0.0, MIN_SPEED - 0.1, "standard") is None

  def test_reads_personality_from_a_message(self):
    box = LaneAwareness()
    box.update(sm(personality="aggressive"), 0.05)
    assert box.gap.target == T_FOLLOW["aggressive"]

  def test_targets_match_the_planner(self):
    try:
      from openpilot.selfdrive.controls.lib.longitudinal_mpc_lib.long_mpc import get_T_FOLLOW
    except Exception as e:  # the MPC's solver is not built in every environment
      raise unittest.SkipTest(f"long_mpc unavailable: {e}") from e
    for name, t in T_FOLLOW.items():
      assert get_T_FOLLOW(getattr(log.LongitudinalPersonality, name)) == t


class TestSides(OpenpilotTestCase):
  def test_levels(self):
    assert side_level(False, True) == 0.0       # clear, blinker or not: nothing drawn
    assert 0.0 < side_level(True, False) < side_level(True, True) == 1.0

  def test_filters_follow_the_monitor(self):
    box = LaneAwareness()
    for _ in range(60):
      box.update(sm(left_bs=True, left_blink=True), 0.05)
    assert box._left.x > 0.95 and box._warn_left and box._right.x < 0.01
    for _ in range(60):
      box.update(sm(), 0.05)
    assert box._left.x < 0.05 and not box._warn_left


class TestLeadScreen(OpenpilotTestCase):
  def test_publish_and_go_stale(self):
    lv = [SimpleNamespace(chevron=[(130.0, 240.0), (100.0, 200.0), (70.0, 240.0)]), SimpleNamespace(chevron=[])]
    lead_screen.publish(lv)
    ch = lead_screen.lead_chevron(0)
    assert (ch.x, ch.y, ch.bottom, ch.size) == (100.0, 200.0, 240.0, 30.0)
    assert lead_screen.lead_chevron(1) is None
    lead_screen._t = time.monotonic() - lead_screen.STALE_T - 0.01
    assert lead_screen.lead_chevron(0) is None

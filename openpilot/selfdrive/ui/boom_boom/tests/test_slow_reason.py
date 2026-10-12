"""
This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
from openpilot.cereal import log
from openpilot.common.constants import CV
from openpilot.common.test import OpenpilotTestCase
from openpilot.selfdrive.ui.boom_boom.slow_reason import (
  CURVE, CURVE_MAP, FOLLOWING, HOLD_T, MODEL, SET_SPEED, SPEED_LIMIT, STOPPED_FOR_CAR, STOPPING, SWITCH_T,
  PlanSource, PlanSourceSP, ReasonDebouncer, SlowReasonPill, slowdown_reason,
)

SET_KPH = 100.0
SET_MS = SET_KPH * CV.KPH_TO_MS


def reason(long_active=True, v_ego=SET_MS - 5, v_cruise_kph=SET_KPH, a_target=0.0, should_stop=False,
           source=PlanSource.cruise, source_sp=PlanSourceSP.cruise):
  return slowdown_reason(long_active, v_ego, v_cruise_kph, a_target, should_stop, source, source_sp)


def fake_sm(v_ego, a_target, source="cruise", source_sp="cruise", long_active=True):
  def svc(name, fields):
    return getattr(log.Event.new_message(**{name: fields}).as_reader(), name)
  return {
    "carState": svc("carState", {"vEgo": v_ego, "vCruise": SET_KPH}),
    "carControl": svc("carControl", {"longActive": long_active}),
    "longitudinalPlan": svc("longitudinalPlan", {"aTarget": a_target, "longitudinalPlanSource": source}),
    "longitudinalPlanSP": svc("longitudinalPlanSP", {"longitudinalPlanSource": source_sp}),
  }


class TestSlowdownReason(OpenpilotTestCase):
  def test_hidden_without_openpilot_long(self):
    assert reason(long_active=False, source=PlanSource.lead0, a_target=-2.0) is None

  def test_hidden_at_set_speed(self):
    assert reason(v_ego=SET_MS, source=PlanSource.lead0) is None
    assert reason(v_ego=SET_MS - 1.0, source=PlanSource.lead0) is None  # inside the margin

  def test_lead(self):
    assert reason(source=PlanSource.lead0) == FOLLOWING
    assert reason(source=PlanSource.lead1, v_ego=SET_MS, a_target=-1.0) == FOLLOWING
    assert reason(source=PlanSource.lead0, v_ego=0.0) == STOPPED_FOR_CAR

  def test_stop(self):
    assert reason(should_stop=True) == STOPPING
    assert reason(should_stop=True, v_ego=0.0, source=PlanSource.lead0) == STOPPED_FOR_CAR
    assert reason(should_stop=True, source_sp=PlanSourceSP.sccVision) == STOPPING

  def test_sunnypilot_limits_win_over_lead(self):
    assert reason(source=PlanSource.lead0, source_sp=PlanSourceSP.speedLimitAssist) == SPEED_LIMIT
    assert reason(source=PlanSource.lead0, source_sp=PlanSourceSP.sccVision) == CURVE
    assert reason(source=PlanSource.lead0, source_sp=PlanSourceSP.sccMap) == CURVE_MAP

  def test_model_and_set_speed(self):
    assert reason(source=PlanSource.e2e) == MODEL
    assert reason(source=PlanSource.cruise, v_ego=SET_MS, a_target=-0.8) == SET_SPEED

  def test_climbing_back_to_set_speed_is_not_a_reason(self):
    assert reason(source=PlanSource.cruise, a_target=1.0) is None

  def test_no_set_speed(self):
    assert reason(v_cruise_kph=255, source=PlanSource.lead0) is None
    assert reason(v_cruise_kph=0, source=PlanSource.lead0) is None
    assert reason(v_cruise_kph=255, source=PlanSource.lead0, a_target=-1.0) == FOLLOWING


class TestReasonDebouncer(OpenpilotTestCase):
  def test_first_reason_shows_at_once(self):
    d = ReasonDebouncer()
    assert d.update(FOLLOWING, 0.05) == FOLLOWING

  def test_switch_needs_to_persist(self):
    d = ReasonDebouncer()
    d.update(FOLLOWING, 0.05)
    t = 0.0
    while t + 0.05 < SWITCH_T:
      assert d.update(CURVE, 0.05) == FOLLOWING
      t += 0.05
    for _ in range(3):
      d.update(CURVE, 0.05)
    assert d.shown == CURVE

  def test_flicker_does_not_switch(self):
    d = ReasonDebouncer()
    d.update(FOLLOWING, 0.05)
    for _ in range(20):
      d.update(CURVE, 0.05)
      d.update(FOLLOWING, 0.05)
    assert d.shown == FOLLOWING

  def test_lingers_then_clears(self):
    d = ReasonDebouncer()
    d.update(FOLLOWING, 0.05)
    assert d.update(None, HOLD_T / 2) == FOLLOWING
    assert d.update(None, HOLD_T / 2 + 0.01) is None


class TestSlowReasonPill(OpenpilotTestCase):
  def test_reads_messages(self):
    pill = SlowReasonPill()
    pill.update(fake_sm(SET_MS - 5, 0.0, source="lead0"), True, 0.05)
    assert pill._debouncer.shown == FOLLOWING

  def test_hidden_without_long_control(self):
    pill = SlowReasonPill()
    pill.update(fake_sm(SET_MS - 5, -1.0, source="lead0"), False, 0.05)
    assert pill._debouncer.shown is None
    pill.update(fake_sm(SET_MS - 5, -1.0, source="lead0", long_active=False), True, 0.05)
    assert pill._debouncer.shown is None

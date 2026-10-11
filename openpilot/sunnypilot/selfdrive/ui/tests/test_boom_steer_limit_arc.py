"""
This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
from openpilot.cereal import log
from openpilot.common.test import OpenpilotTestCase
from openpilot.selfdrive.ui.sunnypilot.onroad.boom_boom.steer_limit_arc import (
  AMBER, OVERFLOW_MAX, RED, WHITE, SteerLimitArc, arc_levels, fill_color,
)

RAIL = 0.6


def rgba(c):
  return (c.r, c.g, c.b, c.a)


def levels(lat_active=True, requested=0.0, delivered=0.0, rail=RAIL, saturated=False, pressed=False):
  return arc_levels(lat_active, requested, delivered, rail, saturated, pressed)


def fake_sm(v_ego, requested, delivered, saturated=False, lat_active=True, pressed=False):
  def svc(name, fields):
    return getattr(log.Event.new_message(**{name: fields}).as_reader(), name)
  return {
    "carState": svc("carState", {"vEgo": v_ego, "steeringPressed": pressed}),
    "carControl": svc("carControl", {"latActive": lat_active, "actuators": {"torque": requested}}),
    "carOutput": svc("carOutput", {"actuatorsOutput": {"torque": delivered}}),
    "controlsState": svc("controlsState", {"lateralControlState": {"torqueState": {"saturated": saturated}}}),
  }


class TestArcLevels(OpenpilotTestCase):
  def test_hidden_in_ordinary_steering(self):
    lv = levels(requested=0.2, delivered=0.2)
    assert lv.visible == 0.0 and lv.overflow == 0.0

  def test_fades_in_toward_the_rail(self):
    mid = levels(requested=0.55 * RAIL, delivered=0.55 * RAIL).visible
    assert 0.0 < mid < 1.0
    assert levels(requested=0.7 * RAIL, delivered=0.7 * RAIL).visible == 1.0

  def test_level_is_a_fraction_of_the_rail_with_sign(self):
    assert abs(levels(requested=0.3, delivered=0.3).level - 0.5) < 1e-6
    assert abs(levels(requested=-0.3, delivered=-0.3).level + 0.5) < 1e-6

  def test_cut_off_request_shows_as_overflow(self):
    lv = levels(requested=0.75, delivered=RAIL)
    assert abs(lv.overflow - 0.25) < 1e-6 and lv.visible == 1.0
    assert levels(requested=3.0, delivered=RAIL).overflow == OVERFLOW_MAX

  def test_rounding_is_not_overflow(self):
    assert levels(requested=RAIL * 1.02, delivered=RAIL).overflow == 0.0

  def test_driver_steering_is_not_the_limit(self):
    lv = levels(requested=0.9, delivered=RAIL, saturated=True, pressed=True)
    assert lv.overflow == 0.0 and not lv.saturated

  def test_saturation_forces_it_visible(self):
    lv = levels(requested=0.1, delivered=0.1, saturated=True)
    assert lv.saturated and lv.visible == 1.0

  def test_nothing_without_lateral(self):
    lv = levels(lat_active=False, requested=0.9, delivered=RAIL, saturated=True)
    assert lv.visible == 0.0 and not lv.saturated

  def test_colors(self):
    assert rgba(fill_color(0.2)) == rgba(WHITE)
    assert rgba(fill_color(-1.0)) == rgba(RED)
    mid = rgba(fill_color(0.85))
    assert mid not in (rgba(WHITE), rgba(RED)) and mid[1] < WHITE.g and mid[0] == AMBER.r


class TestSteerLimitArcWidget(OpenpilotTestCase):
  def test_uses_the_port_rail_by_speed(self):
    schedule = ([8.0, 14.5], [1148 / 1200, 620 / 1200])
    arc = SteerLimitArc()
    for _ in range(100):  # settle the filters
      arc.update(fake_sm(20.0, 0.7, 620 / 1200, saturated=True), schedule, 0.05)
    assert abs(arc._level.x - 1.0) < 0.01
    assert arc._overflow.x > 0.3
    assert arc._saturated and arc._alpha.x > 0.95

  def test_without_a_schedule_the_rail_is_full_scale(self):
    arc = SteerLimitArc()
    for _ in range(100):
      arc.update(fake_sm(20.0, 0.5, 0.5), None, 0.05)
    assert abs(arc._level.x - 0.5) < 0.01 and arc._alpha.x < 0.5

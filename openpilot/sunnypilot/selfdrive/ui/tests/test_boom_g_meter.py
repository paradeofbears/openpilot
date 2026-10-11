"""
This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import math

from openpilot.cereal import log
from openpilot.common.test import OpenpilotTestCase
from openpilot.selfdrive.ui.sunnypilot.onroad.boom_boom.g_meter import (
  FULL_SCALE_G, G, TRAIL_T, GMeter, dot_offset, g_from_car, g_from_device_motion,
)


def svc(name, fields):
  return getattr(log.Event.new_message(**{name: fields}).as_reader(), name)


def xyz(x=0.0, y=0.0, z=0.0, valid=True):
  return {"x": x, "y": y, "z": z, "valid": valid}


def device_motion(a_x=0.0, a_y=0.0, yaw_rate=0.0, v_x=0.0, ok=True):
  return svc("deviceMotion", {
    "accelerationDevice": xyz(a_x, a_y), "angularVelocityDevice": xyz(z=yaw_rate), "velocityDevice": xyz(v_x),
    "inputsOK": ok, "sensorsOK": ok,
  })


def car_sm(a_ego=0.0, curvature=0.0, v_ego=0.0):
  return {"carState": svc("carState", {"aEgo": a_ego, "vEgo": v_ego}),
          "controlsState": svc("controlsState", {"curvature": curvature})}


class TestGSources(OpenpilotTestCase):
  def test_braking(self):
    g_long, g_lat = g_from_device_motion(device_motion(a_x=-G * 0.3))
    assert abs(g_long + 0.3) < 1e-6 and g_lat == 0.0

  def test_steady_turn_is_centripetal(self):
    # a steady left turn: no change in device velocity, all the force is yaw rate x speed.
    # z is down, so a left turn is a negative yaw rate, and left is negative lateral.
    v, r = 20.0, 0.1
    g_long, g_lat = g_from_device_motion(device_motion(yaw_rate=-r, v_x=v))
    assert abs(g_lat + v * r / G) < 1e-6 and g_long == 0.0

  def test_not_ready_falls_back(self):
    assert g_from_device_motion(device_motion(ok=False)) is None
    dm = svc("deviceMotion", {"accelerationDevice": xyz(valid=False), "angularVelocityDevice": xyz(),
                              "velocityDevice": xyz(), "inputsOK": True, "sensorsOK": True})
    assert g_from_device_motion(dm) is None

  def test_car_fallback_agrees_in_sign(self):
    # curvature is left-positive; a left turn must come out left (negative lateral) like the sensors
    _, lat = g_from_car(0.0, 0.005, 20.0)
    assert lat < 0 and abs(lat + 0.005 * 400 / G) < 1e-6


class TestDot(OpenpilotTestCase):
  def test_directions(self):
    assert dot_offset(0.3, 0.0, 100)[1] < 0       # speeding up: dot moves up
    assert dot_offset(-0.3, 0.0, 100)[1] > 0      # braking: down
    assert dot_offset(0.0, -0.3, 100)[0] < 0      # left turn: left

  def test_clipped_to_the_circle(self):
    x, y = dot_offset(-2.0, 2.0, 100)
    assert abs(math.hypot(x, y) - 100) < 1e-6
    x, _ = dot_offset(0.0, FULL_SCALE_G / 2, 100)
    assert abs(x - 50) < 1e-6


class TestGMeter(OpenpilotTestCase):
  def test_peak_and_trail(self):
    m = GMeter()
    for _ in range(60):
      m.update(car_sm(), device_motion(a_x=-G * 0.4), 0.05)
    for _ in range(60):
      m.update(car_sm(), device_motion(), 0.05)
    assert m.from_device
    assert 0.38 < m.peak < 0.41
    assert m.total < 0.01
    assert all(age < TRAIL_T for age, _, _ in m._trail)
    assert len(m._trail) <= TRAIL_T / 0.05 + 1

  def test_falls_back_without_device_motion(self):
    m = GMeter()
    for _ in range(60):
      m.update(car_sm(a_ego=1.0), None, 0.05)
    assert not m.from_device and abs(m.total - 1.0 / G) < 0.01

  def test_reset_clears_the_drive(self):
    m = GMeter()
    m.update(car_sm(a_ego=-5.0), None, 0.05)
    m.reset()
    assert m.peak == 0.0 and not m._trail

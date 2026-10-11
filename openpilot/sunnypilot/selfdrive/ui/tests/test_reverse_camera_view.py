"""
This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import pyray as rl

from openpilot.common.test import OpenpilotTestCase
from openpilot.selfdrive.ui.sunnypilot.onroad.reverse_camera_view import (
  GAP, GearShifter, hides_alert, reverse_view_active, split_rects,
)


class TestReverseCameraView(OpenpilotTestCase):
  def test_only_in_reverse_with_switch_on_and_started(self):
    assert reverse_view_active(True, True, GearShifter.reverse)
    assert not reverse_view_active(False, True, GearShifter.reverse)
    assert not reverse_view_active(True, False, GearShifter.reverse)
    for gear in (GearShifter.drive, GearShifter.park, GearShifter.neutral, GearShifter.unknown):
      assert not reverse_view_active(True, True, gear), gear

  def test_hides_the_real_reverse_banner_only(self):
    from openpilot.cereal import log
    from openpilot.selfdrive.selfdrived.events import ET, Events
    reverse = log.OnroadEvent.EventName.reverseGear
    events = Events()
    events.add(reverse)
    events.event_counters[reverse] = 100  # past the banner's 0.5 s creation delay, as in a real drive
    banner = [a for a in events.create_alerts([ET.PERMANENT]) if a.alert_type.startswith("reverseGear")]
    assert len(banner) == 1
    assert hides_alert(True, banner[0].alert_type)
    assert not hides_alert(False, banner[0].alert_type)

  def test_other_alerts_still_draw(self):
    for alert_type in ("fcw/permanent", "steerSaturated/warning", "laneChangeBlocked/warning", ""):
      assert not hides_alert(True, alert_type), alert_type

  def test_split_fills_the_view(self):
    rect = rl.Rectangle(30, 30, 2100, 1020)
    left, right = split_rects(rect)
    assert left.x == rect.x and left.height == right.height == rect.height
    assert left.width == right.width
    assert right.x + right.width == rect.x + rect.width
    assert right.x - (left.x + left.width) == GAP

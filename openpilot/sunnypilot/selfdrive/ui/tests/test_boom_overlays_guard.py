"""
This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
from types import SimpleNamespace

import pyray as rl

from openpilot.cereal import log
from openpilot.common.test import OpenpilotTestCase
from openpilot.selfdrive.ui.sunnypilot.onroad.boom_boom import overlays as overlays_mod
from openpilot.selfdrive.ui.sunnypilot.onroad.boom_boom.toggles import G_METER, PARAMS, SLOW_REASON, STEER_LIMIT_ARC


def svc(name, fields=None):
  return getattr(log.Event.new_message(**{name: fields or {}}).as_reader(), name)


class FakeSM(dict):
  def __init__(self):
    names = ("carState", "carControl", "carOutput", "controlsState", "longitudinalPlan", "longitudinalPlanSP",
             "radarState", "modelV2", "selfdriveState", "driverMonitoringState", "gpsLocation", "gpsLocationExternal")
    super().__init__({n: svc(n) for n in names})
    self.alive = dict.fromkeys(self, True)
    self.valid = dict.fromkeys(self, True)
    self.seen = dict.fromkeys(self, True)
    self.recv_frame = dict.fromkeys(self, 10)

  def update(self, _):
    pass


class FakeParams:
  def __init__(self, on):
    self.on = on

  def get_bool(self, key):
    return key in self.on


def fake_ui_state(on):
  return SimpleNamespace(params=FakeParams(on), started=True, started_frame=0, sm=FakeSM(), CP=None,
                         has_longitudinal_control=True, engaged=True, is_metric=False, developer_ui=0, chevron_metrics=0)


class TestOverlayGuard(OpenpilotTestCase):
  def setUp(self):
    self._saved = (overlays_mod.ui_state, overlays_mod.messaging, overlays_mod.get_bottom_dev_ui_offset)
    overlays_mod.messaging = SimpleNamespace(SubMaster=lambda services: FakeSM())
    overlays_mod.get_bottom_dev_ui_offset = lambda: 0

  def tearDown(self):
    overlays_mod.ui_state, overlays_mod.messaging, overlays_mod.get_bottom_dev_ui_offset = self._saved

  def make(self, on):
    overlays_mod.ui_state = fake_ui_state(on)
    return overlays_mod.BoomBoomOverlays()

  def test_a_failing_update_switches_only_that_widget_off(self):
    ov = self.make({G_METER, SLOW_REASON})
    ov.g_meter.update = lambda *a: 1 / 0
    ov._update_state()
    assert G_METER in ov.failed and not ov.on(G_METER)
    assert ov.on(SLOW_REASON) and SLOW_REASON not in ov.failed

  def test_a_failing_draw_clears_clipping_and_does_not_raise(self):
    ov = self.make({SLOW_REASON})
    ov._update_state()
    ended = []
    saved = overlays_mod.rl.end_scissor_mode
    overlays_mod.rl.end_scissor_mode = lambda: ended.append(True)
    try:
      def broken(_rect):
        raise RuntimeError("draw failed")
      ov.slow_reason.render = broken
      ov._render(rl.Rectangle(0, 0, 2100, 1020))
    finally:
      overlays_mod.rl.end_scissor_mode = saved
    assert SLOW_REASON in ov.failed and ended

  def test_failed_arc_gives_the_stock_arc_back(self):
    ov = self.make({STEER_LIMIT_ARC})
    assert ov.replaces_torque_bar
    ov.steer_arc.update = lambda *a: 1 / 0
    ov._update_state()
    assert not ov.replaces_torque_bar

  def test_shared_failure_switches_everything_off(self):
    ov = self.make(set(PARAMS))
    ov._extra_sm = lambda: 1 / 0
    ov._update_state()
    assert not any(ov.on(p) for p in PARAMS)

  def test_next_drive_gets_a_fresh_chance(self):
    ov = self.make({G_METER})
    ov.failed.add(G_METER)
    overlays_mod.ui_state.started = False
    ov._update_state()
    overlays_mod.ui_state.started = True
    ov._update_state()
    assert G_METER not in ov.failed

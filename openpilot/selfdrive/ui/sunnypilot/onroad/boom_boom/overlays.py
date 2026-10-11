"""
boom-boom overlays: the one widget the HUD hooks, owning every experimental onroad widget.

This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

The HUD renders this before the alert renderer, so a real alert always draws over these widgets.
Each widget reads its own switch every PARAM_RELOAD_FRAMES and costs nothing while switched off.
"""
import time

import pyray as rl

from opendbc.sunnypilot.car.interfaces import get_steer_rail_schedule
from openpilot.selfdrive.ui.sunnypilot.onroad.boom_boom.slow_reason import SlowReasonPill
from openpilot.selfdrive.ui.sunnypilot.onroad.boom_boom.steer_limit_arc import SteerLimitArc
from openpilot.selfdrive.ui.sunnypilot.onroad.boom_boom.toggles import PARAMS, SLOW_REASON, STEER_LIMIT_ARC
from openpilot.selfdrive.ui.sunnypilot.onroad.developer_ui import get_bottom_dev_ui_offset
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.widgets import Widget

PARAM_RELOAD_FRAMES = 30
MAX_DT = 0.2  # s; a stalled frame must not count as a long stretch of driving


class BoomBoomOverlays(Widget):
  def __init__(self):
    super().__init__()
    self._frame = 0
    self._enabled: dict[str, bool] = {}
    self._reload_params()
    self._last_t = time.monotonic()
    self._started = False
    self._rail_cp = None
    self._rail_schedule = None

    self.slow_reason = SlowReasonPill()
    self.steer_arc = SteerLimitArc()

  def _reload_params(self) -> None:
    for p in PARAMS:
      self._enabled[p] = ui_state.params.get_bool(p)

  def on(self, param: str) -> bool:
    return self._enabled.get(param, False)

  @property
  def replaces_torque_bar(self) -> bool:
    """The HUD skips the stock steering arc while the calmer one is on."""
    return self.on(STEER_LIMIT_ARC)

  def _fresh(self) -> bool:
    return ui_state.started and ui_state.sm.recv_frame["carState"] >= ui_state.started_frame

  def _rail(self):
    if ui_state.CP is not self._rail_cp:
      self._rail_cp = ui_state.CP
      self._rail_schedule = get_steer_rail_schedule(ui_state.CP) if ui_state.CP is not None else None
    return self._rail_schedule

  def _update_state(self) -> None:
    self._frame += 1
    if self._frame % PARAM_RELOAD_FRAMES == 0:
      self._reload_params()

    now = time.monotonic()
    dt = min(max(now - self._last_t, 0.0), MAX_DT)
    self._last_t = now

    if not self._fresh():
      self._started = False
      return
    if not self._started:
      self._started = True
      self.slow_reason.reset()
      self.steer_arc.reset()

    sm = ui_state.sm
    if self.on(SLOW_REASON):
      self.slow_reason.update(sm, ui_state.has_longitudinal_control, dt)
    if self.on(STEER_LIMIT_ARC):
      self.steer_arc.update(sm, self._rail(), dt)

  def _render(self, rect: rl.Rectangle) -> None:
    if not self._fresh():
      return
    if self.on(STEER_LIMIT_ARC):
      self.steer_arc.render(rl.Rectangle(rect.x, rect.y, rect.width, rect.height - get_bottom_dev_ui_offset()))
    if self.on(SLOW_REASON):
      self.slow_reason.render(rect)

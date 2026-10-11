"""
boom-boom overlays: the one widget the HUD hooks, owning every experimental onroad widget.

This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

The HUD renders this before the alert renderer, so a real alert always draws over these widgets.
Each widget reads its own switch every PARAM_RELOAD_FRAMES and costs nothing while switched off.
"""
import time

import pyray as rl

from openpilot.selfdrive.ui.sunnypilot.onroad.boom_boom.slow_reason import SlowReasonPill
from openpilot.selfdrive.ui.sunnypilot.onroad.boom_boom.toggles import PARAMS, SLOW_REASON
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

    self.slow_reason = SlowReasonPill()

  def _reload_params(self) -> None:
    for p in PARAMS:
      self._enabled[p] = ui_state.params.get_bool(p)

  def on(self, param: str) -> bool:
    return self._enabled.get(param, False)

  def _fresh(self) -> bool:
    return ui_state.started and ui_state.sm.recv_frame["carState"] >= ui_state.started_frame

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

    sm = ui_state.sm
    if self.on(SLOW_REASON):
      self.slow_reason.update(sm, ui_state.has_longitudinal_control, dt)

  def _render(self, rect: rl.Rectangle) -> None:
    if not self._fresh():
      return
    if self.on(SLOW_REASON):
      self.slow_reason.render(rect)

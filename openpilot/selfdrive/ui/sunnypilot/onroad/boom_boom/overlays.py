"""
boom-boom overlays: the one widget the HUD hooks, owning every experimental onroad widget.

This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

The HUD renders this before the alert renderer, so a real alert always draws over these widgets.
Each widget reads its own switch every PARAM_RELOAD_FRAMES and costs nothing while switched off.

Failure containment: every widget call runs through _guard. An exception switches that widget off
for the rest of the drive and logs it, instead of taking down the onroad screen (and the alerts it
draws). A failure in the shared code here switches all of them off for the drive. Any clipping a
failed widget left on is cleared so it cannot hide what draws after it.
"""
import time
from collections.abc import Callable

import pyray as rl

from opendbc.sunnypilot.car.interfaces import get_steer_rail_schedule
from openpilot.cereal import messaging
from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.ui.sunnypilot.onroad.boom_boom.g_meter import FOOTPRINT_H as G_METER_H, GMeter
from openpilot.selfdrive.ui.sunnypilot.onroad.boom_boom.lane_awareness import LaneAwareness
from openpilot.selfdrive.ui.sunnypilot.onroad.boom_boom.lead_screen import lead_chevron
from openpilot.selfdrive.ui.sunnypilot.onroad.boom_boom.slow_reason import SlowReasonPill
from openpilot.selfdrive.ui.sunnypilot.onroad.boom_boom.steer_limit_arc import SteerLimitArc
from openpilot.selfdrive.ui.sunnypilot.onroad.boom_boom.toggles import (
  G_METER, LANE_AWARENESS, PARAMS, SLOW_REASON, STEER_LIMIT_ARC, TRAFFIC, TRIP_CARD,
)
from openpilot.selfdrive.ui.sunnypilot.onroad.chevron_metrics import ChevronOptions
from openpilot.selfdrive.ui.sunnypilot.onroad.boom_boom.traffic import TrafficBox, box_rect
from openpilot.selfdrive.ui.sunnypilot.onroad.boom_boom.trip_card import TripCard
from openpilot.selfdrive.ui.sunnypilot.onroad.developer_ui import DeveloperUiState, get_bottom_dev_ui_offset
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.widgets import Widget

PARAM_RELOAD_FRAMES = 30
MAX_DT = 0.2  # s; a stalled frame must not count as a long stretch of driving
STACK_GAP = 30  # px between the traffic box and the G-meter under it
DEV_UI_RIGHT_W = 230  # px the developer UI's right column takes
SHARED = "shared"  # the guard's name for this file's own code


class BoomBoomOverlays(Widget):
  def __init__(self):
    super().__init__()
    self._frame = 0
    self._enabled: dict[str, bool] = {}
    self.failed: set[str] = set()  # switched off for this drive after an exception
    self._reload_params()
    self._last_t = time.monotonic()
    self._started = False
    self._rail_cp = None
    self._rail_schedule = None

    # services ui_state does not subscribe to, opened only while a widget that needs them is on
    self._sm: messaging.SubMaster | None = None
    self._sm_services: tuple[str, ...] = ()

    self.slow_reason = SlowReasonPill()
    self.steer_arc = SteerLimitArc()
    self.g_meter = GMeter()
    self.trip_card = TripCard()
    self.traffic = TrafficBox()
    self.lane_awareness = LaneAwareness()
    self._widgets = (self.slow_reason, self.steer_arc, self.g_meter, self.trip_card, self.traffic, self.lane_awareness)

  def _reload_params(self) -> None:
    for p in PARAMS:
      self._enabled[p] = ui_state.params.get_bool(p)

  def on(self, param: str) -> bool:
    return self._enabled.get(param, False) and param not in self.failed and SHARED not in self.failed

  def _guard(self, name: str, fn: Callable, *args, drawing: bool = False):
    try:
      return fn(*args)
    except Exception:
      cloudlog.exception(f"boom-boom: {name} raised; switched off until the next drive")
      self.failed.add(name)
      if drawing:
        rl.end_scissor_mode()
      return None

  @property
  def replaces_torque_bar(self) -> bool:
    """The HUD skips the stock steering arc while the calmer one is on (and has not failed)."""
    return self.on(STEER_LIMIT_ARC)

  def _fresh(self) -> bool:
    return ui_state.started and ui_state.sm.recv_frame["carState"] >= ui_state.started_frame

  def _rail(self):
    if ui_state.CP is not self._rail_cp:
      self._rail_cp = ui_state.CP
      self._rail_schedule = get_steer_rail_schedule(ui_state.CP) if ui_state.CP is not None else None
    return self._rail_schedule

  def _extra_sm(self) -> messaging.SubMaster | None:
    services = []
    if self.on(G_METER):
      services.append('deviceMotion')
    if self.on(TRAFFIC) and not ui_state.has_longitudinal_control:
      services.append('radarTracks')  # alpha long silences the radar, so there are none to read
    if tuple(services) != self._sm_services:
      self._sm_services = tuple(services)
      self._sm = messaging.SubMaster(services) if services else None
    if self._sm is not None:
      self._sm.update(0)
    return self._sm

  @staticmethod
  def _extra(extra, service: str):
    if extra is None or service not in extra.seen or not extra.seen[service] or not extra.alive[service]:
      return None
    return extra[service]

  @staticmethod
  def _gps():
    """The best live GPS message, or None: one with a fix first, the external receiver before the modem's."""
    sm = ui_state.sm
    live = [sm[name] for name in ('gpsLocationExternal', 'gpsLocation') if sm.alive[name] and sm.valid[name]]
    return next((g for g in live if g.hasFix), live[0] if live else None)

  def _update_state(self) -> None:
    self._frame += 1
    if self._frame % PARAM_RELOAD_FRAMES == 0:
      self._guard(SHARED, self._reload_params)

    now = time.monotonic()
    dt = min(max(now - self._last_t, 0.0), MAX_DT)
    self._last_t = now

    if not self._fresh():
      self._started = False
      return
    if not self._started:
      self._started = True
      self.failed.clear()  # a new drive gets a fresh chance
      for w in self._widgets:
        self._guard(SHARED, w.reset)
    self._guard(SHARED, self._update_widgets, dt)

  def _update_widgets(self, dt: float) -> None:
    sm = ui_state.sm
    extra = self._extra_sm()
    if self.on(SLOW_REASON):
      self._guard(SLOW_REASON, self.slow_reason.update, sm, ui_state.has_longitudinal_control, dt)
    if self.on(STEER_LIMIT_ARC):
      self._guard(STEER_LIMIT_ARC, self.steer_arc.update, sm, self._rail(), dt)
    if self.on(G_METER):
      self._guard(G_METER, self.g_meter.update, sm, self._extra(extra, 'deviceMotion'), dt)
    if self.on(TRIP_CARD):
      self._guard(TRIP_CARD, self.trip_card.update, sm, ui_state.engaged, ui_state.has_longitudinal_control, self._gps(), dt)
    if self.on(TRAFFIC):
      self._guard(TRAFFIC, self.traffic.update, sm, self._extra(extra, 'radarTracks'), ui_state.engaged)
    if self.on(LANE_AWARENESS):
      self._guard(LANE_AWARENESS, self.lane_awareness.update, sm, dt)

  def _render(self, rect: rl.Rectangle) -> None:
    if self._fresh():
      self._guard(SHARED, self._render_widgets, rect, drawing=True)

  def _render_widgets(self, rect: rl.Rectangle) -> None:
    bottom = rl.Rectangle(rect.x, rect.y, rect.width, rect.height - get_bottom_dev_ui_offset())
    if self.on(LANE_AWARENESS):
      # edges first: everything else draws over the glow
      metric_lines = {ChevronOptions.OFF: 0, ChevronOptions.ALL: 3}.get(ui_state.chevron_metrics, 1)
      self._guard(LANE_AWARENESS, self._draw_lane_awareness, rect, metric_lines, drawing=True)
    # the driver monitoring icon takes the bottom corner on the driver's side
    g_meter_right = self.on(G_METER) and not ui_state.sm['driverMonitoringState'].isRHD
    if self.on(G_METER):
      self._guard(G_METER, self.g_meter.render, bottom, not g_meter_right, drawing=True)
    if self.on(TRAFFIC):
      inset = DEV_UI_RIGHT_W if ui_state.developer_ui in (DeveloperUiState.RIGHT, DeveloperUiState.BOTH) else 0
      box = box_rect(bottom, inset, G_METER_H + STACK_GAP if g_meter_right else 0)
      if box is not None:
        self._guard(TRAFFIC, self.traffic.render, box, drawing=True)
    if self.on(STEER_LIMIT_ARC):
      self._guard(STEER_LIMIT_ARC, self.steer_arc.render, bottom, drawing=True)
    if self.on(SLOW_REASON):
      self._guard(SLOW_REASON, self.slow_reason.render, rect, drawing=True)
    if self.on(TRIP_CARD):
      self._guard(TRIP_CARD, self.trip_card.render, rect, ui_state.is_metric, drawing=True)

  def _draw_lane_awareness(self, rect: rl.Rectangle, metric_lines: int) -> None:
    self.lane_awareness.render_edges(rect)
    self.lane_awareness.render_gap(rect, lead_chevron(0), metric_lines)

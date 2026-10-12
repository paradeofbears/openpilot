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
from openpilot.cereal import messaging
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

    # services ui_state does not subscribe to, opened only while a widget that needs them is on
    self._sm: messaging.SubMaster | None = None
    self._sm_services: tuple[str, ...] = ()

    self.slow_reason = SlowReasonPill()
    self.steer_arc = SteerLimitArc()
    self.g_meter = GMeter()
    self.trip_card = TripCard()
    self.traffic = TrafficBox()
    self.lane_awareness = LaneAwareness()

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
      self.g_meter.reset()
      self.trip_card.reset()
      self.traffic.reset()
      self.lane_awareness.reset()

    sm = ui_state.sm
    extra = self._extra_sm()
    if self.on(SLOW_REASON):
      self.slow_reason.update(sm, ui_state.has_longitudinal_control, dt)
    if self.on(STEER_LIMIT_ARC):
      self.steer_arc.update(sm, self._rail(), dt)
    if self.on(G_METER):
      self.g_meter.update(sm, self._extra(extra, 'deviceMotion'), dt)
    if self.on(TRIP_CARD):
      self.trip_card.update(sm, ui_state.engaged, ui_state.has_longitudinal_control, self._gps(), dt)
    if self.on(TRAFFIC):
      self.traffic.update(sm, self._extra(extra, 'radarTracks'), ui_state.engaged)
    if self.on(LANE_AWARENESS):
      self.lane_awareness.update(sm, dt)

  def _render(self, rect: rl.Rectangle) -> None:
    if not self._fresh():
      return
    bottom = rl.Rectangle(rect.x, rect.y, rect.width, rect.height - get_bottom_dev_ui_offset())
    if self.on(LANE_AWARENESS):
      # edges first: everything else draws over the glow
      self.lane_awareness.render_edges(rect)
      metric_lines = {ChevronOptions.OFF: 0, ChevronOptions.ALL: 3}.get(ui_state.chevron_metrics, 1)
      self.lane_awareness.render_gap(rect, lead_chevron(0), metric_lines)
    # the driver monitoring icon takes the bottom corner on the driver's side
    g_meter_right = self.on(G_METER) and not ui_state.sm['driverMonitoringState'].isRHD
    if self.on(G_METER):
      self.g_meter.render(bottom, on_left=not g_meter_right)
    if self.on(TRAFFIC):
      inset = DEV_UI_RIGHT_W if ui_state.developer_ui in (DeveloperUiState.RIGHT, DeveloperUiState.BOTH) else 0
      box = box_rect(bottom, inset, G_METER_H + STACK_GAP if g_meter_right else 0)
      if box is not None:
        self.traffic.render(box)
    if self.on(STEER_LIMIT_ARC):
      self.steer_arc.render(bottom)
    if self.on(SLOW_REASON):
      self.slow_reason.render(rect)
    if self.on(TRIP_CARD):
      self.trip_card.render(rect, ui_state.is_metric)

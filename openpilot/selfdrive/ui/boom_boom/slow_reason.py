"""
Slowdown reason: a small label under the speed saying what is holding the car below its set speed.

This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

Display only. It reads the planners' own "who is limiting speed" fields and never feeds anything
back. Only meaningful under openpilot longitudinal control: with stock MRCC the car's radar picks
the speed and openpilot's plan is not what the car does, so the label stays hidden.
"""
import pyray as rl

from openpilot.common.constants import CV
from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.system.ui.lib.application import FontWeight, gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.lib.text_measure import measure_text_cached

from .compat import PlanSourceSP, log, sp

PlanSource = log.LongitudinalPlan.LongitudinalPlanSource

V_CRUISE_UNSET_KPH = 255  # carState.vCruise when no set speed
DECEL_SHOW = -0.3         # m/s^2: a planned decel this firm is worth explaining
HELD_MARGIN = 1.5         # m/s below the set speed counts as held back
STOPPED_SPEED = 0.5       # m/s
SWITCH_T = 0.3            # s a new reason must hold before the label changes
HOLD_T = 1.5              # s the label stays after its reason clears

# Reasons, in the order they are checked. Values are the on-screen text.
STOPPING = "Stopping"
STOPPED_FOR_CAR = "Stopped for car"
SPEED_LIMIT = "Speed limit"
CURVE = "Curve ahead"
CURVE_MAP = "Curve (map)"
FOLLOWING = "Following car"
MODEL = "Model pace"
SET_SPEED = "Set speed"

PILL_CENTER_Y = 380       # under the speed unit, which the HUD centres on y = 290
PILL_FONT_SIZE = 52
PILL_PAD_X = 34
PILL_PAD_Y = 12
PILL_BG = rl.Color(0, 0, 0, 170)
PILL_TEXT = rl.Color(255, 255, 255, 235)
PILL_ACCENT = rl.Color(255, 200, 0, 255)


def slowdown_reason(long_active: bool, v_ego: float, v_cruise_kph: float, a_target: float, should_stop: bool,
                    source, source_sp) -> str | None:
  """What is holding the car below its set speed, or None when nothing is (or nothing we can name)."""
  if not long_active:
    return None
  v_cruise = v_cruise_kph * CV.KPH_TO_MS if 0 < v_cruise_kph < V_CRUISE_UNSET_KPH else None
  slowing = a_target < DECEL_SHOW
  held = v_cruise is not None and v_ego < v_cruise - HELD_MARGIN
  if not (slowing or held or should_stop):
    return None

  lead = source in (PlanSource.lead0, PlanSource.lead1, PlanSource.lead2)
  if should_stop:
    return STOPPED_FOR_CAR if lead and v_ego < STOPPED_SPEED else STOPPING
  if PlanSourceSP is not None and source_sp is not None:  # sunnypilot's own planners
    if source_sp == PlanSourceSP.speedLimitAssist:
      return SPEED_LIMIT
    if source_sp == PlanSourceSP.sccVision:
      return CURVE
    if source_sp == PlanSourceSP.sccMap:
      return CURVE_MAP
  if lead:
    return STOPPED_FOR_CAR if v_ego < STOPPED_SPEED else FOLLOWING
  if source == PlanSource.e2e:
    return MODEL
  if slowing:
    return SET_SPEED  # cruise source decelerating: the set speed came down
  return None  # climbing back up to the set speed


class ReasonDebouncer:
  """Steadies the label: a new reason must last SWITCH_T, and a cleared one lingers HOLD_T."""

  def __init__(self):
    self.shown: str | None = None
    self._candidate: str | None = None
    self._candidate_t = 0.0
    self._clear_t = 0.0

  def update(self, reason: str | None, dt: float) -> str | None:
    if reason is None:
      self._candidate = None
      self._candidate_t = 0.0
      if self.shown is not None:
        self._clear_t += dt
        if self._clear_t >= HOLD_T:
          self.shown = None
      return self.shown

    self._clear_t = 0.0
    if reason == self.shown:
      self._candidate = None
      return self.shown
    if reason != self._candidate:
      self._candidate = reason
      self._candidate_t = 0.0
    self._candidate_t += dt
    if self.shown is None or self._candidate_t >= SWITCH_T:
      self.shown = reason
      self._candidate = None
    return self.shown


class SlowReasonPill:
  def __init__(self):
    self._debouncer = ReasonDebouncer()
    self._alpha = FirstOrderFilter(0.0, 0.15, 1 / gui_app.target_fps)
    self._text = ""

  def reset(self) -> None:
    self._debouncer = ReasonDebouncer()
    self._alpha.x = 0.0

  def update(self, sm, has_long_control: bool, dt: float) -> None:
    cs = sm['carState']
    plan = sm['longitudinalPlan']
    long_active = has_long_control and sm['carControl'].longActive
    plan_sp = sp(sm, 'longitudinalPlanSP')
    reason = slowdown_reason(long_active, cs.vEgo, cs.vCruise, plan.aTarget, plan.shouldStop,
                             plan.longitudinalPlanSource, plan_sp.longitudinalPlanSource if plan_sp is not None else None)
    shown = self._debouncer.update(reason, dt)
    if shown is not None:
      self._text = shown
    self._alpha.update(1.0 if shown is not None else 0.0)

  def render(self, rect: rl.Rectangle) -> None:
    a = self._alpha.x
    if a < 0.02 or not self._text:
      return
    font = gui_app.font(FontWeight.SEMI_BOLD)
    text = tr(self._text)
    size = measure_text_cached(font, text, PILL_FONT_SIZE)
    dot = PILL_FONT_SIZE * 0.22
    w = size.x + 2 * PILL_PAD_X + dot * 3
    h = size.y + 2 * PILL_PAD_Y
    x = rect.x + (rect.width - w) / 2
    y = rect.y + PILL_CENTER_Y - h / 2
    rl.draw_rectangle_rounded(rl.Rectangle(x, y, w, h), 0.5, 12, _fade(PILL_BG, a))
    rl.draw_circle(int(x + PILL_PAD_X + dot), int(y + h / 2), dot, _fade(PILL_ACCENT, a))
    rl.draw_text_ex(font, text, rl.Vector2(x + PILL_PAD_X + dot * 3, y + PILL_PAD_Y), PILL_FONT_SIZE, 0, _fade(PILL_TEXT, a))


def _fade(c: rl.Color, a: float) -> rl.Color:
  return rl.Color(c.r, c.g, c.b, int(c.a * a))

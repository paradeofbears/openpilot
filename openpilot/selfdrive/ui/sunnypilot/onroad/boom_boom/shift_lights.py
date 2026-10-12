"""
Shift lights: a race-car row of dots that fills as the revs climb and flashes when it is time to shift.

This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

Shown only while the lever is in the M gate (mazda_can.Powertrain.manual): in D the gearbox shifts at
1,600-2,100 rpm in ordinary driving and the lights would never matter. The gear sits beside the row as "M3".

When to shift:
  - Auto (default): lead-time lights, as race cars use. Flash when the revs, at the rate they are climbing,
    would reach the rev limit within the lead time (Early/Normal/Late), so a fast climb in 1st or 2nd flashes
    early enough to shift before the limiter and a slow climb flashes closer to it. Never later than
    CAP_MARGIN below the limit.
  - A fixed rpm the driver picks: flash there (still capped at CAP_MARGIN below the limit).

The rev limit is where the revs actually stop in M, not the tach's red zone. On the 2022 CX-5 2.5 Turbo the
tach turns red at 6,300 but every hard pull on route 00000010 (2026-10-12) flattened from ~5,700 and topped
out at 5,750-5,985, and the driver's upshift came 0.05-0.3 s after reaching it: with a 6,300 target and a 0.6 s
lead most pulls never flashed before the limiter. Hence 5,900 and a 0.9 s Normal lead.

The dots fill green, amber, red over FILL_SPAN below the flash point and all flash blue while it is time to
shift. Optional chime: once at the start of each flash, never in top gear, re-armed when the revs fall
REARM_DROP below where it sounded (any upshift does that). The overlay passes the request to soundd
(shift_chime.py), which plays an existing sound only when no alert sound is playing. Display only.
"""
import numpy as np
import pyray as rl

from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.selfdrive.ui.sunnypilot.onroad.boom_boom.mazda_can import Powertrain
from openpilot.system.ui.lib.application import FontWeight, gui_app
from openpilot.system.ui.lib.text_measure import measure_text_cached

LEDS = 10
TOP_GEAR = 6
REV_LIMIT_OPTIONS = (5700, 5900, 6300)
DEFAULT_REV_LIMIT = 5900             # measured on the 2022 CX-5 2.5 Turbo in M; 6300 is its tach's red zone
AUTO = 0
SHIFT_POINT_OPTIONS = (AUTO, 4500, 5000, 5500, 6000)  # index 0 is Auto
LEAD_OPTIONS = (1.2, 0.9, 0.6)       # s, Early / Normal / Late: seeing the flash, reacting, the shift itself
DEFAULT_LEAD = 0.9
CAP_MARGIN = 400.0                   # rpm below the rev limit the flash comes at the latest
FILL_SPAN = 2000.0                   # rpm the dots fill over, below the flash point
FLASH_HOLD = 150.0                   # rpm the revs may sag without the flash stopping
HOLD_T = 0.4                         # s the flash outlasts the shift being due, so it does not flicker
REARM_DROP = 500.0                   # rpm below the chime's rpm before it can sound again
RATE_TAU = 0.12                      # s, smoothing of the rev rate
FLASH_HZ = 8.0

LED_R = 17
LED_GAP = 46
TOP_Y = 52          # centre of the row from the top of the view
LOW_Y = 335         # under the speed unit, when the road name takes the top
BADGE_SIZE = 50
PILL = rl.Color(0, 0, 0, 170)
OFF = rl.Color(255, 255, 255, 45)
GREEN = rl.Color(70, 220, 110, 255)
AMBER = rl.Color(255, 176, 0, 255)
RED = rl.Color(235, 40, 40, 255)
BLUE = rl.Color(60, 140, 255, 255)
WHITE = rl.Color(255, 255, 255, 235)


def flash_point(rev_limit: float, fixed: int) -> float:
  """The latest rpm the lights flash at: the fixed point if one is set, never past the limit's margin."""
  cap = rev_limit - CAP_MARGIN
  return min(float(fixed), cap) if fixed != AUTO else cap


def shift_due(rpm: float, rate: float, rev_limit: float, fixed: int, lead: float = DEFAULT_LEAD) -> bool:
  top = flash_point(rev_limit, fixed)
  if rpm >= top:
    return True
  # predict only once the dots are filling: a launch or a gear change spikes the rate at low revs
  return fixed == AUTO and rpm >= top - FILL_SPAN and rpm + max(rate, 0.0) * lead >= rev_limit


def lit(rpm: float, top: float) -> int:
  """How many dots are on, filling over FILL_SPAN below `top`."""
  if rpm >= top:
    return LEDS
  return int(np.clip((rpm - (top - FILL_SPAN)) / FILL_SPAN * LEDS, 0, LEDS))


def led_color(i: int) -> rl.Color:
  return GREEN if i < 4 else AMBER if i < 7 else RED


class ShiftLogic:
  """Rev rate, the flash and the chime, from a stream of rpm samples."""

  def __init__(self):
    self.rate = FirstOrderFilter(0.0, RATE_TAU, 0.05)
    self._prev_rpm: float | None = None
    self.flashing = False
    self._flash_from = 0.0
    self._flash_peak = 0.0
    self._since_due = 0.0
    self._chimed_at: float | None = None

  def update(self, rpm: float | None, dt: float, rev_limit: float, fixed: int, gear: int | None, manual: bool,
             lead: float = DEFAULT_LEAD) -> bool:
    """Returns True when the chime should sound now."""
    if rpm is None or dt <= 0:
      self._prev_rpm = None
      self.flashing = False
      return False
    if self._prev_rpm is not None:
      self.rate.dt = dt  # the UI's frame time varies; keep the smoothing in seconds
      self.rate.update_alpha(RATE_TAU)
      self.rate.update((rpm - self._prev_rpm) / dt)
    self._prev_rpm = rpm

    if self._chimed_at is not None and rpm < self._chimed_at - REARM_DROP:
      self._chimed_at = None
    if self.flashing:
      self._flash_peak = max(self._flash_peak, rpm)
      if rpm < self._flash_peak - REARM_DROP:  # the revs fell away: an upshift (or lifting hard)
        self.flashing = False
        self._chimed_at = None  # the next gear gets its own chime
        return False
    if shift_due(rpm, self.rate.x, rev_limit, fixed, lead):
      self._since_due = 0.0
      if not self.flashing:
        self.flashing = True
        self._flash_from = self._flash_peak = rpm
        if manual and gear is not None and gear < TOP_GEAR and self._chimed_at is None:
          self._chimed_at = rpm
          return True
    elif self.flashing:
      # ride out a wobble in the prediction; stop once it has not been due for a moment or the revs fell
      self._since_due += dt
      self.flashing = self._since_due < HOLD_T and rpm >= self._flash_from - FLASH_HOLD
    return False


class ShiftLights:
  def __init__(self):
    self._alpha = FirstOrderFilter(0.0, 0.15, 1 / gui_app.target_fps)
    self.logic = ShiftLogic()
    self.pt = Powertrain()
    self.rev_limit = DEFAULT_REV_LIMIT
    self.fixed = AUTO
    self.lead = DEFAULT_LEAD
    self._t = 0.0

  def reset(self) -> None:
    self._alpha.x = 0.0
    self.logic = ShiftLogic()
    self.pt = Powertrain()

  @property
  def showing(self) -> bool:
    return bool(self.pt.manual) and self.pt.rpm is not None

  def update(self, pt: Powertrain, rev_limit: int, fixed: int, dt: float, lead: float = DEFAULT_LEAD) -> bool:
    """Returns True when the chime should sound this frame."""
    self.pt = pt
    self.rev_limit = rev_limit if rev_limit in REV_LIMIT_OPTIONS else DEFAULT_REV_LIMIT
    self.fixed = fixed if fixed in SHIFT_POINT_OPTIONS else AUTO
    self.lead = lead if lead in LEAD_OPTIONS else DEFAULT_LEAD
    self._t += dt
    self._alpha.update(1.0 if self.showing else 0.0)
    return self.logic.update(pt.rpm, dt, self.rev_limit, self.fixed, pt.gear, bool(pt.manual), self.lead)

  def render(self, rect: rl.Rectangle, low: bool = False) -> None:
    a = self._alpha.x
    if a < 0.02:
      return
    rpm = self.pt.rpm or 0.0
    n = lit(rpm, flash_point(self.rev_limit, self.fixed))
    blink_on = int(self._t * FLASH_HZ * 2) % 2 == 0

    font = gui_app.font(FontWeight.BOLD)
    badge = f"M{self.pt.gear}" if self.pt.gear else "M"
    bsize = measure_text_cached(font, badge, BADGE_SIZE)
    row_w = (LEDS - 1) * LED_GAP + 2 * LED_R
    w = bsize.x + 24 + row_w + 40
    h = 2 * LED_R + 30
    cx = rect.x + rect.width / 2
    cy = rect.y + (LOW_Y if low else TOP_Y)
    x0 = cx - w / 2
    rl.draw_rectangle_rounded(rl.Rectangle(x0, cy - h / 2, w, h), 0.5, 12, _fade(PILL, a))
    rl.draw_text_ex(font, badge, rl.Vector2(x0 + 20, cy - bsize.y / 2), BADGE_SIZE, 0, _fade(WHITE, a))

    lx = x0 + 20 + bsize.x + 24 + LED_R
    for i in range(LEDS):
      if self.logic.flashing:
        color = BLUE if blink_on else OFF
      else:
        color = led_color(i) if i < n else OFF
      rl.draw_circle_v(rl.Vector2(lx + i * LED_GAP, cy), LED_R, _fade(color, a))


def _fade(c: rl.Color, a: float) -> rl.Color:
  return rl.Color(c.r, c.g, c.b, int(c.a * a))

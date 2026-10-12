"""
Shift lights: a race-car row of dots that fills as the revs climb and flashes at the shift point.

This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

Shown only while the lever is in the M gate (mazda_can.Powertrain.manual): in D the gearbox shifts at
1,600-2,100 rpm in ordinary driving and the lights would never matter. Ten dots, green then amber then
red, over the SPAN_RPM below the shift point; at the shift point every dot flashes blue. The gear sits
beside the row as "M3".

Optional chime: once per climb past the shift point, never in top gear, re-armed only after the revs
fall HYSTERESIS_RPM below it. The overlay passes the request to soundd (shift_chime.py), which plays an
existing sound only when no alert sound is playing. Display only.
"""
import numpy as np
import pyray as rl

from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.selfdrive.ui.sunnypilot.onroad.boom_boom.mazda_can import Powertrain
from openpilot.system.ui.lib.application import FontWeight, gui_app
from openpilot.system.ui.lib.text_measure import measure_text_cached

LEDS = 10
SPAN_RPM = 2000.0
HYSTERESIS_RPM = 300.0
TOP_GEAR = 6
SHIFT_RPM_OPTIONS = (4500, 5000, 5500, 6000)
DEFAULT_SHIFT_RPM = 5500
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


def lit(rpm: float, shift_rpm: float) -> int:
  """How many dots are on."""
  if rpm >= shift_rpm:
    return LEDS
  return int(np.clip((rpm - (shift_rpm - SPAN_RPM)) / SPAN_RPM * LEDS, 0, LEDS))


def led_color(i: int) -> rl.Color:
  return GREEN if i < 4 else AMBER if i < 7 else RED


class ChimeTrigger:
  def __init__(self):
    self._armed = True

  def update(self, rpm: float | None, gear: int | None, manual: bool, shift_rpm: float) -> bool:
    if rpm is None:
      return False
    if rpm < shift_rpm - HYSTERESIS_RPM:
      self._armed = True
      return False
    if rpm >= shift_rpm and self._armed and manual and gear is not None and gear < TOP_GEAR:
      self._armed = False
      return True
    return False


class ShiftLights:
  def __init__(self):
    self._alpha = FirstOrderFilter(0.0, 0.15, 1 / gui_app.target_fps)
    self._trigger = ChimeTrigger()
    self.pt = Powertrain()
    self.shift_rpm = DEFAULT_SHIFT_RPM
    self._t = 0.0

  def reset(self) -> None:
    self._alpha.x = 0.0
    self._trigger = ChimeTrigger()
    self.pt = Powertrain()

  @property
  def showing(self) -> bool:
    return bool(self.pt.manual) and self.pt.rpm is not None

  def update(self, pt: Powertrain, shift_rpm: int, dt: float) -> bool:
    """Returns True when the chime should sound this frame."""
    self.pt = pt
    self.shift_rpm = shift_rpm if shift_rpm in SHIFT_RPM_OPTIONS else DEFAULT_SHIFT_RPM
    self._t += dt
    self._alpha.update(1.0 if self.showing else 0.0)
    return self._trigger.update(pt.rpm, pt.gear, bool(pt.manual), self.shift_rpm)

  def render(self, rect: rl.Rectangle, low: bool = False) -> None:
    a = self._alpha.x
    if a < 0.02:
      return
    rpm = self.pt.rpm or 0.0
    n = lit(rpm, self.shift_rpm)
    flashing = rpm >= self.shift_rpm and int(self._t * FLASH_HZ * 2) % 2 == 0

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
      centre = rl.Vector2(lx + i * LED_GAP, cy)
      if rpm >= self.shift_rpm:
        color = BLUE if flashing else OFF
      else:
        color = led_color(i) if i < n else OFF
      rl.draw_circle_v(centre, LED_R, _fade(color, a))


def _fade(c: rl.Color, a: float) -> rl.Color:
  return rl.Color(c.r, c.g, c.b, int(c.a * a))

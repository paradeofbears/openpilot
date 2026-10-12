"""
Lane awareness: the three-lane idea drawn on the road view itself.

This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

Side lanes: an amber glow inside the left or right edge while the blind-spot monitor sees a car there,
brighter and pulsing when the blinker points into it. Nothing is drawn while a side is clear. The glow
sits on the lower part of the edge because those cars are beside or behind, out of the camera's view;
GLOW_CENTER is where a decoded blind-spot position would move it. Amber only: red on the screen edge
is the critical-alert border.

Our lane: a gap bar under the lead chevron, the time gap to the lead against the follow-distance target
of the current personality, with a closing / opening arrow and a BRAKING tag when the lead decelerates.
The chevron is only drawn under openpilot longitudinal control, so the bar is too. Display only.
"""
from dataclasses import dataclass

import numpy as np
import pyray as rl

from openpilot.common.filter_simple import FirstOrderFilter
from .lead_screen import Chevron
from openpilot.system.ui.lib.application import FontWeight, gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.lib.text_measure import measure_text_cached

# long_mpc.get_T_FOLLOW by personality name, mirrored: importing the MPC would pull its solver into the UI
# (a test checks the match). Keyed by name because a message's enum field does not hash like the constant.
T_FOLLOW = {"relaxed": 1.75, "standard": 1.45, "aggressive": 1.25}

MIN_SPEED = 3.0          # m/s; a time gap means little at a crawl
TREND_V = 0.5            # m/s of closing or opening speed before the arrow shows
BRAKING_A = -1.5         # m/s^2 lead acceleration for the BRAKING tag
SHORT_FRAC = 0.8         # of the target: the bar turns amber below this
BAR_RANGE = 1.5          # the bar spans 0 to 1.5x the target

GLOW_W = 170             # px into the screen
GLOW_TOP = 0.40          # fraction of the view height where the glow begins
GLOW_CENTER = 0.75       # where the glow is strongest, as a fraction of the height
GLOW_STRIPS = 48
AMBER = rl.Color(255, 176, 0, 255)
WHITE = rl.Color(255, 255, 255, 235)
PILL = rl.Color(0, 0, 0, 160)
TRACK = rl.Color(255, 255, 255, 60)

BAR_W, BAR_H = 200, 14
TEXT_SIZE = 40
TAG_SIZE = 30
PAD = 14
CHEVRON_METRIC_LINE = 50  # px per line of chevron metrics drawn under the chevron (chevron_metrics.py)


@dataclass
class Gap:
  seconds: float
  target: float
  trend: int        # -1 closing, 0 steady, +1 opening
  braking: bool

  @property
  def frac(self) -> float:
    return self.seconds / self.target

  @property
  def short(self) -> bool:
    return self.frac < SHORT_FRAC


def gap_state(present: bool, d_rel: float, v_rel: float, a_lead: float, v_ego: float, personality) -> Gap | None:
  if not present or v_ego < MIN_SPEED:
    return None
  trend = -1 if v_rel < -TREND_V else 1 if v_rel > TREND_V else 0
  return Gap(d_rel / v_ego, T_FOLLOW.get(str(personality), T_FOLLOW["standard"]), trend, a_lead < BRAKING_A)


def side_level(occupied: bool, blinker: bool) -> float:
  """0 clear, 0.6 occupied, 1.0 occupied with the blinker pointing into it."""
  return (1.0 if blinker else 0.6) if occupied else 0.0


class LaneAwareness:
  def __init__(self):
    self._left = FirstOrderFilter(0.0, 0.15, 1 / gui_app.target_fps)
    self._right = FirstOrderFilter(0.0, 0.15, 1 / gui_app.target_fps)
    self._warn_left = False
    self._warn_right = False
    self.gap: Gap | None = None
    self._t = 0.0

  def reset(self) -> None:
    self._left.x = self._right.x = 0.0
    self.gap = None

  def update(self, sm, dt: float) -> None:
    cs = sm['carState']
    self._left.update(side_level(cs.leftBlindspot, cs.leftBlinker))
    self._right.update(side_level(cs.rightBlindspot, cs.rightBlinker))
    self._warn_left = cs.leftBlindspot and cs.leftBlinker
    self._warn_right = cs.rightBlindspot and cs.rightBlinker
    lead = sm['radarState'].leadOne
    self.gap = gap_state(lead.present, lead.dRel, lead.vRel, lead.aLeadK, cs.vEgo, sm['selfdriveState'].personality)
    self._t += dt

  def render_edges(self, rect: rl.Rectangle) -> None:
    pulse = 0.75 + 0.25 * np.sin(self._t * 2 * np.pi * 2.5)
    for left, level, warn in ((True, self._left.x, self._warn_left), (False, self._right.x, self._warn_right)):
      if level < 0.02:
        continue
      _edge_glow(rect, left, level * (pulse if warn else 1.0))

  def render_gap(self, rect: rl.Rectangle, chevron: Chevron | None, metric_lines: int) -> None:
    g = self.gap
    if g is None or chevron is None:
      return
    font = gui_app.font(FontWeight.SEMI_BOLD)
    color = AMBER if g.short else WHITE
    text = f"{g.seconds:.1f}s"
    tsize = measure_text_cached(font, text, TEXT_SIZE)
    arrow = 22 if g.trend else 0
    w = PAD + BAR_W + PAD + arrow + (8 if arrow else 0) + tsize.x + PAD
    h = PAD * 2 + tsize.y
    tag_h = TAG_SIZE + 6 if g.braking else 0

    x = float(np.clip(chevron.x - w / 2, rect.x + 10, rect.x + rect.width - w - 10))
    y = chevron.bottom + 15 + metric_lines * CHEVRON_METRIC_LINE
    y = min(y, rect.y + rect.height - h - tag_h - 10)
    rl.draw_rectangle_rounded(rl.Rectangle(x, y, w, h + tag_h), 0.4, 10, PILL)

    # bar: 0 to BAR_RANGE x target, a tick at the target
    bx, by = x + PAD, y + (h - BAR_H) / 2
    rl.draw_rectangle_rounded(rl.Rectangle(bx, by, BAR_W, BAR_H), 1.0, 8, TRACK)
    fill = BAR_W * float(np.clip(g.frac / BAR_RANGE, 0.0, 1.0))
    if fill > 2:
      rl.draw_rectangle_rounded(rl.Rectangle(bx, by, fill, BAR_H), 1.0, 8, color)
    tick_x = bx + BAR_W / BAR_RANGE
    rl.draw_line_ex(rl.Vector2(tick_x, by - 7), rl.Vector2(tick_x, by + BAR_H + 7), 3, WHITE)

    tx = bx + BAR_W + PAD
    if g.trend:
      cy = y + h / 2
      if g.trend < 0:  # closing: the gap is shrinking, arrow down
        rl.draw_triangle(rl.Vector2(tx, cy - 9), rl.Vector2(tx + arrow / 2, cy + 11), rl.Vector2(tx + arrow, cy - 9), color)
      else:
        rl.draw_triangle(rl.Vector2(tx + arrow / 2, cy - 11), rl.Vector2(tx, cy + 9), rl.Vector2(tx + arrow, cy + 9), color)
      tx += arrow + 8
    rl.draw_text_ex(font, text, rl.Vector2(tx, y + PAD), TEXT_SIZE, 0, color)

    if g.braking:
      tag = tr("BRAKING")
      ts = measure_text_cached(font, tag, TAG_SIZE)
      rl.draw_text_ex(font, tag, rl.Vector2(x + (w - ts.x) / 2, y + h - 4), TAG_SIZE, 0, AMBER)


def _edge_glow(rect: rl.Rectangle, left: bool, strength: float) -> None:
  top = rect.y + rect.height * GLOW_TOP
  mid = rect.y + rect.height * GLOW_CENTER
  bottom = rect.y + rect.height
  x = rect.x if left else rect.x + rect.width - GLOW_W
  faint = rl.Color(AMBER.r, AMBER.g, AMBER.b, 0)
  # horizontal-gradient strips, each with its own strength: a four-corner gradient would be split into two
  # triangles by the GPU and show a diagonal seam where three corners are transparent
  step = (bottom - top) / GLOW_STRIPS
  line_x = rect.x if left else rect.x + rect.width - 8
  for i in range(GLOW_STRIPS):
    # whole-pixel boundaries so strips tile exactly; any overlap shows as a brighter line
    y0, y1 = int(top + i * step), int(top + (i + 1) * step)
    k = float(np.interp((y0 + y1) / 2, [top, mid, bottom], [0.0, 1.0, 1.0]))
    edge = rl.Color(AMBER.r, AMBER.g, AMBER.b, int(200 * strength * k * k))
    if left:
      rl.draw_rectangle_gradient_h(int(x), y0, GLOW_W, y1 - y0, edge, faint)
    else:
      rl.draw_rectangle_gradient_h(int(x), y0, GLOW_W, y1 - y0, faint, edge)
    rl.draw_rectangle(int(line_x), y0, 8, y1 - y0, edge)  # a crisp line on the edge itself

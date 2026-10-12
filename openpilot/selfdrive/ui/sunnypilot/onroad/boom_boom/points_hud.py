"""
Points HUD: the drive's running points, right of the speed, with short pops for what just scored.

This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

Reads scoring.DriveScore, which only counts the driver's own driving. Shown while a rank style is
selected; the safety flavour also shows the clean-streak multiplier. Display only.
"""
import pyray as rl

from openpilot.selfdrive.ui.sunnypilot.onroad.boom_boom.scoring import POPUP_T, SAFETY, DriveScore
from openpilot.system.ui.lib.application import FontWeight, gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.lib.text_measure import measure_text_cached

X_FROM_CENTRE = 270      # px right of the view's centre: clear of the speed and the right turn-signal icon
TOP = 80
POINTS_SIZE = 56
LABEL_SIZE = 28
POP_SIZE = 34
FADE_T = 0.5             # s a pop takes to fade at the end of its life
WHITE = rl.Color(255, 255, 255, 235)
GREY = rl.Color(255, 255, 255, 150)
GOLD = rl.Color(255, 200, 40, 255)
RED = rl.Color(235, 90, 70, 255)
SHADOW = rl.Color(0, 0, 0, 160)


def render(rect: rl.Rectangle, score: DriveScore) -> None:
  bold = gui_app.font(FontWeight.BOLD)
  semi = gui_app.font(FontWeight.SEMI_BOLD)
  x = rect.x + rect.width / 2 + X_FROM_CENTRE
  y = rect.y + TOP
  text = f"{score.points:,}"
  _text(bold, text, x, y, POINTS_SIZE, WHITE)
  size = measure_text_cached(bold, text, POINTS_SIZE)
  label = tr("PTS")
  if score.flavour == SAFETY and score.streak > 1:
    label += f"  x{score.streak}"
  _text(semi, label, x + size.x + 12, y + POINTS_SIZE - LABEL_SIZE - 8, LABEL_SIZE, GOLD if score.streak > 1 else GREY)

  py = y + POINTS_SIZE + 10
  for p in reversed(score.popups):  # newest on top
    fade = max(0.0, 1.0 - max(0.0, p.age - (POPUP_T - FADE_T)) / FADE_T)  # full, then fades out at the end
    color = RED if p.text.startswith("-") or p.text.startswith("STREAK") else GOLD
    _text(semi, p.text, x, py - 10 * min(p.age, 0.3), POP_SIZE, rl.Color(color.r, color.g, color.b, int(color.a * fade)))
    py += POP_SIZE + 6


def _text(font: rl.Font, text: str, x: float, y: float, size: int, color: rl.Color) -> None:
  rl.draw_text_ex(font, text, rl.Vector2(x + 2, y + 2), size, 0, rl.Color(SHADOW.r, SHADOW.g, SHADOW.b, min(SHADOW.a, color.a)))
  rl.draw_text_ex(font, text, rl.Vector2(x, y), size, 0, color)

"""
Reverse camera view: in reverse, the wide road camera and the cabin camera side by side.

This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

Neither camera looks behind the car. The wide road camera shows the front end swinging past
whatever is ahead while backing out; the cabin camera shows the cabin and, through the rear
window, a slice of what is behind. With ReverseCameraView on, these replace the full-screen
"Reverse Gear" banner. Any other alert still draws over them as usual.
"""
import pyray as rl
from opendbc.car.structs import car
try:
  from openpilot.cereal.visionipc import VisionStreamType
except ImportError:  # stock openpilot
  from msgq.visionipc import VisionStreamType  # type: ignore[no-redef]
from openpilot.selfdrive.ui.onroad.cameraview import CameraView
from openpilot.system.ui.lib.application import FontWeight, gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget

GearShifter = car.CarState.GearShifter

REVERSE_CAMERA_PARAM = "ReverseCameraView"
REVERSE_ALERT_PREFIX = "reverseGear/"
PARAM_RELOAD_FRAMES = 30

GAP = 16
PILL_FONT_SIZE = 48
PILL_PAD_X = 32
PILL_PAD_Y = 12
PILL_MARGIN = 24
PILL_BG = rl.Color(0, 0, 0, 160)
REVERSE_PILL_BG = rl.Color(201, 34, 49, 230)


def reverse_view_active(enabled: bool, started: bool, gear) -> bool:
  return enabled and started and gear == GearShifter.reverse


def hides_alert(view_active: bool, alert_type: str) -> bool:
  """Only the reverse banner gives way to the cameras; every other alert still draws."""
  return view_active and alert_type.startswith(REVERSE_ALERT_PREFIX)


def split_rects(rect: rl.Rectangle, gap: int = GAP) -> tuple[rl.Rectangle, rl.Rectangle]:
  half = (rect.width - gap) / 2
  left = rl.Rectangle(rect.x, rect.y, half, rect.height)
  right = rl.Rectangle(rect.x + half + gap, rect.y, half, rect.height)
  return left, right


class ReverseCameraView(Widget):
  def __init__(self, params):
    super().__init__()
    self._params = params
    self._enabled = params.get_bool(REVERSE_CAMERA_PARAM)
    self._frame = 0

    # CameraView connects lazily on first render and keeps only the newest frame (conflate),
    # so these cost nothing outside reverse
    self._road = CameraView("camerad", VisionStreamType.VISION_STREAM_WIDE_ROAD)
    self._cabin = CameraView("camerad", VisionStreamType.VISION_STREAM_CABIN)
    self._road._set_placeholder_color(rl.BLACK)
    self._cabin._set_placeholder_color(rl.BLACK)

  def update(self, sm, started: bool) -> bool:
    """Reload the switch now and then; returns whether the reverse view should draw this frame."""
    self._frame += 1
    if self._frame % PARAM_RELOAD_FRAMES == 0:
      self._enabled = self._params.get_bool(REVERSE_CAMERA_PARAM)
    return reverse_view_active(self._enabled, started, sm['carState'].gearShifter)

  def _render(self, rect: rl.Rectangle):
    rl.draw_rectangle_rec(rect, rl.BLACK)
    left, right = split_rects(rect)
    self._road.render(left)
    self._cabin.render(right)

    self._draw_pill(left, tr("front"), PILL_BG, top=False)
    self._draw_pill(right, tr("cabin"), PILL_BG, top=False)
    self._draw_pill(rect, tr("REVERSE"), REVERSE_PILL_BG, top=True)

  def _draw_pill(self, area: rl.Rectangle, text: str, color: rl.Color, top: bool):
    font = gui_app.font(FontWeight.BOLD)
    size = measure_text_cached(font, text, PILL_FONT_SIZE)
    w, h = size.x + 2 * PILL_PAD_X, size.y + 2 * PILL_PAD_Y
    x = area.x + (area.width - w) / 2
    y = area.y + PILL_MARGIN if top else area.y + area.height - h - PILL_MARGIN
    rl.draw_rectangle_rounded(rl.Rectangle(x, y, w, h), 0.5, 10, color)
    rl.draw_text_ex(font, text, rl.Vector2(x + PILL_PAD_X, y + PILL_PAD_Y), PILL_FONT_SIZE, 0, rl.WHITE)

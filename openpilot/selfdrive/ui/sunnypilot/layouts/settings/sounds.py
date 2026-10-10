"""
Sounds settings for the comma 3X, ported from FrogPilot's "Alert Volumes".

This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
from openpilot.common.params import Params
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.sunnypilot.selfdrive.ui.alert_volume import AUTO_PCT, CATEGORIES, CONTROL_PARAM, MAX_PCT, TEST_PARAM
from openpilot.system.ui.lib.multilang import tr, tr_noop
from openpilot.system.ui.sunnypilot.widgets.list_view import toggle_item_sp, option_item_sp
from openpilot.system.ui.widgets.scroller_tici import Scroller
from openpilot.system.ui.widgets import Widget

VOLUME_STEP = 5

VOLUME_ITEMS = {
  "engage": (
    tr_noop("Engage Volume"),
    tr_noop("The chime when openpilot starts driving."),
  ),
  "disengage": (
    tr_noop("Disengage Volume"),
    tr_noop("The chime when openpilot stops driving, whether you cancelled it or it handed the car back."),
  ),
  "refuse": (
    tr_noop("Won't Engage Volume"),
    tr_noop("The sound when you try to engage and openpilot can't, for example with a door open or the brake held."),
  ),
  "prompt": (
    tr_noop("Prompt Volume"),
    tr_noop("Quick chimes that need your attention, like a car in your blind spot when you signal or a turn too " +
            "sharp to steer through. Can't go below 25% so it always reaches you."),
  ),
  "promptDistracted": (
    tr_noop("Distracted Driver Volume"),
    tr_noop("The sound when the driver camera thinks you've stopped watching the road. " +
            "Can't go below 25% so it always reaches you."),
  ),
  "warningSoft": (
    tr_noop("Soft Warning Volume"),
    tr_noop("openpilot's serious warnings, such as \"TAKE CONTROL\" or a collision risk. " +
            "Can't go below 25% so it always reaches you."),
  ),
  "warningImmediate": (
    tr_noop("Urgent Warning Volume"),
    tr_noop("\"DISENGAGE IMMEDIATELY\". It starts at this volume and still rises to full over four seconds, " +
            "the same as stock. Can't go below 25%."),
  ),
}


def volume_value_map(floor: int) -> dict[int, int]:
  """Option index -> stored percent: floor..100 in steps of 5, then Auto."""
  values = list(range(floor, MAX_PCT + 1, VOLUME_STEP)) + [AUTO_PCT]
  return dict(enumerate(values))


def volume_label(value: int) -> str:
  if value >= AUTO_PCT:
    return tr("Auto")
  if value <= 0:
    return tr("Muted")
  return f"{value}%"


class SoundsLayout(Widget):
  def __init__(self):
    super().__init__()

    self._params = Params()
    items = self._initialize_items()
    self._scroller = Scroller(items, line_separator=True, spacing=0)

  def _initialize_items(self):
    self._volume_control = toggle_item_sp(
      param=CONTROL_PARAM,
      title=lambda: tr("Alert Volumes"),
      description=lambda: tr("Set your own volume for each kind of alert instead of letting openpilot pick. " +
                             "\"Auto\" is the stock behavior: louder when the cabin is noisy, quieter when it isn't. " +
                             "Changing a volume plays that sound so you can hear it. " +
                             "Turning this off puts every alert back on Auto and keeps your settings for later."),
      initial_state=ui_state.params.get_bool(CONTROL_PARAM),
    )

    self._volume_items = {}
    for category, (param, floor) in CATEGORIES.items():
      title, desc = VOLUME_ITEMS[category]
      value_map = volume_value_map(floor)
      self._volume_items[category] = option_item_sp(
        param=param,
        title=lambda title=title: tr(title),
        description=lambda desc=desc: tr(desc),
        min_value=0,
        max_value=len(value_map) - 1,
        value_map=value_map,
        label_callback=volume_label,
        on_value_changed=lambda _, category=category: self._preview(category),
        inline=True,
      )

    return [self._volume_control, *self._volume_items.values()]

  def _preview(self, category: str):
    # soundd picks this up within a quarter second and plays the sound once, offroad only
    self._params.put(TEST_PARAM, category)

  def _update_state(self):
    super()._update_state()

    enabled = self._volume_control.action_item.get_state()
    for item in self._volume_items.values():
      item.set_visible(enabled)

  def _render(self, rect):
    self._scroller.render(rect)

  def show_event(self):
    self._scroller.show_event()

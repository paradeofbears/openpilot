"""
The Boom-boom settings page: every boom-boom feature in one place, grouped, saved to boom-boom's own store.

This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

Built only from openpilot's stock list widgets (toggle_item, multiple_button_item), so it works in any build
that has the raylib settings UI. A build registers it as a settings panel; see INTEGRATION.md.
"""
import pyray as rl

from openpilot.system.ui.lib.application import FontWeight, gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.list_view import multiple_button_item, toggle_item
from openpilot.system.ui.widgets.scroller_tici import Scroller

from .store import Store, settings
from .toggles import CHIME_VOLUMES, SECTIONS, SHIFT_CHIME_VOLUME, choice_text, toggle_text

HEADER_H = 110
HEADER_SIZE = 44
HEADER_COLOR = rl.Color(128, 216, 166, 255)
CHOICE_BUTTON_W = 210


class SectionHeader(Widget):
  def __init__(self, title: str):
    super().__init__()
    self.title = title
    self._rect = rl.Rectangle(0, 0, 0, HEADER_H)

  def set_parent_rect(self, parent_rect: rl.Rectangle) -> None:
    super().set_parent_rect(parent_rect)
    self._rect.width = parent_rect.width

  def _render(self, _):
    font = gui_app.font(FontWeight.BOLD)
    rl.draw_text_ex(font, self.title, rl.Vector2(self._rect.x + 20, self._rect.y + HEADER_H - HEADER_SIZE - 16),
                    HEADER_SIZE, 0, HEADER_COLOR)


def selected_index(store: Store, key: str, n: int) -> int:
  if key == SHIFT_CHIME_VOLUME:
    pct = store.get(key, return_default=True)
    return min(range(len(CHIME_VOLUMES)), key=lambda i: abs(CHIME_VOLUMES[i] - pct))
  value = store.get(key, return_default=True)
  return value if 0 <= value < n else 0


def store_choice(store: Store, key: str, index: int) -> None:
  store.put(key, CHIME_VOLUMES[index] if key == SHIFT_CHIME_VOLUME else index)


def build_items(store: Store) -> list[Widget]:
  toggles, choices = toggle_text(), choice_text()
  items: list[Widget] = []
  for section, keys in SECTIONS:
    items.append(SectionHeader(tr(section)))
    for key in keys:
      if key in toggles:
        title, desc = toggles[key]
        items.append(toggle_item(title, desc, initial_state=store.get_bool(key),
                                 callback=lambda state, key=key: store.put_bool(key, state)))
      else:
        title, desc, buttons = choices[key]
        width = CHOICE_BUTTON_W if len(buttons) <= 3 else CHOICE_BUTTON_W - 40
        items.append(multiple_button_item(title, desc, buttons, selected_index(store, key, len(buttons)), width,
                                          callback=lambda index, key=key: store_choice(store, key, index)))
  return items


class BoomBoomLayout(Widget):
  def __init__(self, store: Store | None = None):
    super().__init__()
    self._store = store or settings()
    self._scroller = Scroller(build_items(self._store), line_separator=True, spacing=0)

  def show_event(self):
    self._scroller.show_event()

  def _render(self, rect: rl.Rectangle):
    self._scroller.render(rect)

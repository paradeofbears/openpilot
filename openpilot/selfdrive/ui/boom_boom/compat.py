"""
Everything boom-boom borrows from a particular openpilot build, in one place, with stand-ins where it is missing.

This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

boom-boom grew up in sunnypilot (zoompilot is a sunnypilot fork). Stock openpilot lacks sunnypilot's extra
services and widgets and imports cereal as `cereal` rather than `openpilot.cereal`. Each import below tries this
build's way first and falls back, and the features that need what is missing switch themselves off:
  - longitudinalPlanSP, carStateSP, liveMapDataSP (sunnypilot services): read through sp(); None without them
  - the steering rail schedule (sunnypilot's opendbc): the calmer steering arc needs it
  - the chevron metrics and developer UI layout (sunnypilot): only used to keep out of their way
  - Mazda CAN: the shift lights and engine data decode Mazda frames, so they run only on a Mazda
"""
try:
  from openpilot.cereal import log, messaging
except ImportError:  # stock openpilot
  from cereal import log, messaging  # type: ignore[no-redef]

try:
  from openpilot.cereal import custom
  PlanSourceSP = custom.LongitudinalPlanSP.LongitudinalPlanSource
except (ImportError, AttributeError):
  custom = None
  PlanSourceSP = None

try:
  from opendbc.sunnypilot.car.interfaces import get_steer_rail_schedule
except ImportError:
  def get_steer_rail_schedule(CP):  # type: ignore[misc]
    return None

try:
  from openpilot.selfdrive.ui.sunnypilot.onroad.chevron_metrics import ChevronOptions
except ImportError:
  class ChevronOptions:  # type: ignore[no-redef]
    OFF = 0
    ALL = 4

try:
  from openpilot.selfdrive.ui.sunnypilot.onroad.developer_ui import DeveloperUiState, get_bottom_dev_ui_offset
except ImportError:
  class DeveloperUiState:  # type: ignore[no-redef]
    OFF, BOTTOM, RIGHT, BOTH = 0, 1, 2, 3

  def get_bottom_dev_ui_offset() -> int:  # type: ignore[misc]
    return 0

SUNNYPILOT = custom is not None


def sp(sm, service: str):
  """A sunnypilot-only service's latest message, or None in a build (or a SubMaster) without it."""
  try:
    return sm[service]
  except (KeyError, AttributeError):
    return None


def is_mazda(CP) -> bool:
  """Whether the car is a Mazda; False until carParams arrive. The CAN decoding is Mazda's."""
  return CP is not None and getattr(CP, "brand", "") == "mazda"


__all__ = ["log", "messaging", "custom", "PlanSourceSP", "get_steer_rail_schedule", "ChevronOptions", "DeveloperUiState",
           "get_bottom_dev_ui_offset", "SUNNYPILOT", "sp", "is_mazda"]

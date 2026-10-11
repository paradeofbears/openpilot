"""
boom-boom experimental onroad widgets: their params and their Settings > Visuals toggles.

This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

Every widget is display only and off by default (params_keys.h). Real alerts draw over all of them.
"""
from openpilot.system.ui.lib.multilang import tr

SLOW_REASON = "SlowdownReason"

PARAMS = (SLOW_REASON,)


def toggle_defs() -> dict:
  """Entries in the visuals layout's (title, description, callback) format."""
  return {
    SLOW_REASON: (
      lambda: tr("Show Why the Car Is Slowing"),
      tr("Under openpilot longitudinal control, show a small label under the speed naming what is holding " +
         "the car below its set speed: a car ahead, a curve, the speed limit, a stop, the model's own pace " +
         "or a lowered set speed. Display only; hidden with stock cruise."),
      None,
    ),
  }

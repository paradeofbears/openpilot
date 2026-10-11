"""
boom-boom experimental onroad widgets: their params and their Settings > Visuals toggles.

This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

Every widget is display only and off by default (params_keys.h). Real alerts draw over all of them.
"""
from openpilot.system.ui.lib.multilang import tr

SLOW_REASON = "SlowdownReason"
STEER_LIMIT_ARC = "SteerLimitArc"

PARAMS = (SLOW_REASON, STEER_LIMIT_ARC)


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
    STEER_LIMIT_ARC: (
      lambda: tr("Steering Arc: Only Near the Limit"),
      tr("Replaces the steering arc with a calmer one that stays hidden in ordinary steering and fades in " +
         "as steering torque nears what the EPS can deliver at this speed. Turns amber, then red at the limit, " +
         "draws the request that was cut off past the end of the arc, and pulses red while the controller " +
         "is saturated. Display only."),
      None,
    ),
  }

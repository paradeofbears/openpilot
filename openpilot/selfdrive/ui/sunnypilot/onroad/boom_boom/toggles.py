"""
boom-boom experimental onroad widgets: their params and their Settings > Visuals toggles.

This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

Every widget is display only and off by default (params_keys.h). Real alerts draw over all of them.
"""
from openpilot.system.ui.lib.multilang import tr

SLOW_REASON = "SlowdownReason"
STEER_LIMIT_ARC = "SteerLimitArc"
G_METER = "GForceMeter"
TRIP_CARD = "TripSummary"
TRAFFIC = "TrafficBox"
LANE_AWARENESS = "LaneAwareness"
MINI_MAP = "MiniMap"
RANK_STYLE = "TripRankStyle"  # 0 off, 1 safety, 2 chaos (scoring.py)

PARAMS = (SLOW_REASON, STEER_LIMIT_ARC, G_METER, TRIP_CARD, TRAFFIC, LANE_AWARENESS, MINI_MAP)


def extra_items(params) -> list:
  """Settings items that are not on/off toggles, appended after the visuals layout's own."""
  from openpilot.system.ui.sunnypilot.widgets.list_view import multiple_button_item_sp
  selected = params.get(RANK_STYLE, return_default=True) or 0
  return [
    multiple_button_item_sp(
      title=lambda: tr("Drive Rank and Points"),
      description=lambda: tr("Rank your own driving S to D and score points while you drive. Safety rewards smooth " +
                             "driving; Chaos rewards hard launches and stops, never speed. Tailgating costs points in " +
                             "both. Only stretches where you set the speed count, not openpilot or cruise. The rank " +
                             "shows on the Park summary; the points to the right of the speed."),
      buttons=[lambda: tr("Off"), lambda: tr("Safety"), lambda: tr("Chaos")],
      selected_index=int(selected),
      param=RANK_STYLE,
      inline=False,
    ),
  ]


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
    G_METER: (
      lambda: tr("G-Force Meter"),
      tr("Show a friction circle in the bottom corner: a dot for the car's current acceleration, braking and " +
         "cornering force, a short trail, and a ring at the drive's peak. Uses the device's motion sensors, " +
         "or the car's speed and steering when those are not ready."),
      None,
    ),
    TRIP_CARD: (
      lambda: tr("Trip Summary in Park"),
      tr("When you shift into Park, show a card for the drive: distance, time, average and top speed, how much " +
         "openpilot steered (and drove), disengagements, hard brakes and starts, how smooth it was, and the " +
         "climb and descent from GPS. Counts from the moment the device goes onroad."),
      None,
    ),
    TRAFFIC: (
      lambda: tr("Traffic Box"),
      tr("A small top-down map on the right of the cars openpilot knows about. With openpilot longitudinal " +
         "(alpha long) it shows the lead cars the camera sees and the blind-spot zones; the stock radar is " +
         "silenced then, so cars in other lanes ahead are not shown. With stock cruise it also shows the radar's " +
         "tracks ahead. Nothing reports cars directly behind. Needs blind-spot monitoring for the side zones."),
      None,
    ),
    LANE_AWARENESS: (
      lambda: tr("Lane Awareness: Edge Glows and Gap Bar"),
      tr("An amber glow on the left or right edge of the screen while the blind-spot monitor sees a car on that " +
         "side, pulsing when your blinker points into it; nothing while a side is clear. Under the lead car's " +
         "chevron, a bar of the time gap to it against your follow-distance setting, with a closing or opening " +
         "arrow and BRAKING when it slows hard. The gap bar needs openpilot longitudinal (alpha long), which is " +
         "what draws the chevron."),
      None,
    ),
    MINI_MAP: (
      lambda: tr("Mini-Map"),
      tr("A small round heading-up map in the bottom-left corner, drawn from the OpenStreetMap data downloaded " +
         "in the OSM panel, with the road you are on highlighted and the zoom widening with speed. Needs a " +
         "map download for the area and a GPS fix; it says NO GPS or NO MAP DATA rather than guess. Display only."),
      None,
    ),
  }

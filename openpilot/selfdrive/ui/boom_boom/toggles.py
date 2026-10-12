"""
boom-boom's settings: their keys (store.py) and how the Boom-boom settings page describes them.

This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

Every feature is display only and off by default. Real alerts draw over all of them.
"""
from openpilot.system.ui.lib.multilang import tr

SLOW_REASON = "SlowdownReason"
STEER_LIMIT_ARC = "SteerLimitArc"
G_METER = "GForceMeter"
TRIP_CARD = "TripSummary"
TRAFFIC = "TrafficBox"
LANE_AWARENESS = "LaneAwareness"
MINI_MAP = "MiniMap"
REVERSE_CAMERA = "ReverseCameraView"
RANK_STYLE = "TripRankStyle"  # 0 off, 1 safety, 2 spirited (scoring.py)
SHIFT_LIGHTS = "ShiftLights"
SHIFT_CHIME = "ShiftChime"            # read by soundd too (shift_chime.py)
SHIFT_REV_LIMIT = "ShiftRevLimit"     # index into shift_lights.REV_LIMIT_OPTIONS
SHIFT_LEAD = "ShiftLead"              # index into shift_lights.LEAD_OPTIONS (Early, Normal, Late)
SHIFT_POINT = "ShiftPoint"            # index into shift_lights.SHIFT_POINT_OPTIONS (0 = Auto)
SHIFT_CHIME_VOLUME = "ShiftChimeVolume"
SHIFT_CHIME_REQUEST = "ShiftChimeRequest"

# on/off switches the onroad overlay reads
PARAMS = (SLOW_REASON, STEER_LIMIT_ARC, G_METER, TRIP_CARD, TRAFFIC, LANE_AWARENESS, MINI_MAP, SHIFT_LIGHTS, SHIFT_CHIME)

CHIME_VOLUMES = (20, 40, 60, 80, 100)


def toggle_text() -> dict:
  """(title, description) for each on/off switch."""
  return {
    SLOW_REASON: (
      tr("Why the Car Is Slowing"),
      tr("Under openpilot longitudinal control, show a small label under the speed naming what is holding " +
         "the car below its set speed: a car ahead, a curve, the speed limit, a stop, the model's own pace " +
         "or a lowered set speed. Hidden with stock cruise."),
    ),
    STEER_LIMIT_ARC: (
      tr("Steering Arc: Only Near the Limit"),
      tr("Replaces the steering arc with a calmer one that stays hidden in ordinary steering and fades in " +
         "as steering torque nears what the EPS can deliver at this speed. Turns amber, then red at the limit, " +
         "draws the request that was cut off past the end of the arc, and pulses red while the controller " +
         "is saturated."),
    ),
    G_METER: (
      tr("G-Force Meter"),
      tr("A friction circle in the bottom corner: a dot for the car's current acceleration, braking and " +
         "cornering force, a short trail, and a ring at the drive's peak. Uses the device's motion sensors, " +
         "or the car's speed and steering when those are not ready."),
    ),
    TRAFFIC: (
      tr("Traffic Box"),
      tr("A small top-down map on the right of the cars openpilot knows about. With openpilot longitudinal " +
         "(alpha long) it shows the lead cars the camera sees and the blind-spot zones; the stock radar is " +
         "silenced then, so cars in other lanes ahead are not shown. With stock cruise it also shows the radar's " +
         "tracks ahead. Nothing reports cars directly behind. Needs blind-spot monitoring for the side zones."),
    ),
    LANE_AWARENESS: (
      tr("Lane Awareness: Edge Glows and Gap Bar"),
      tr("An amber glow on the left or right edge of the screen while the blind-spot monitor sees a car on that " +
         "side, pulsing when your blinker points into it. Under the lead car's chevron, a bar of the time gap to " +
         "it against your follow-distance setting, with a closing or opening arrow and BRAKING when it slows hard. " +
         "The gap bar needs openpilot longitudinal (alpha long), which is what draws the chevron."),
    ),
    MINI_MAP: (
      tr("Mini-Map"),
      tr("A small round heading-up map in the bottom-left corner, drawn from the OpenStreetMap data downloaded " +
         "in the OSM panel, with the road you are on highlighted and the zoom widening with speed. Needs a " +
         "map download for the area and a GPS fix; it says NO GPS or NO MAP DATA rather than guess."),
    ),
    REVERSE_CAMERA: (
      tr("Cameras in Reverse"),
      tr("In reverse, show the wide road camera and the cabin camera side by side instead of the " +
         "full-screen Reverse banner. Neither camera looks behind the car: the road camera shows your " +
         "front end while backing out, and the cabin camera catches a slice of the rear window. " +
         "Use your car's backup camera and mirrors for reversing."),
    ),
    TRIP_CARD: (
      tr("Trip Summary in Park"),
      tr("When you shift into Park, show a card for the drive: distance, time, average and top speed, how much " +
         "openpilot steered (and drove), disengagements, hard brakes and starts, how smooth it was, and the " +
         "climb and descent from GPS. Counts from the moment the device goes onroad."),
    ),
    SHIFT_LIGHTS: (
      tr("Shift Lights (Manual Mode)"),
      tr("With the lever in the M gate, a race-style row of dots above the speed fills green, amber and red as the " +
         "revs climb toward your shift point and flashes blue at it, with the gear beside it. Hidden in D, where the " +
         "gearbox shifts for you. Reads the engine speed and gear from the car's CAN bus: Mazda only."),
    ),
    SHIFT_CHIME: (
      tr("Chime at the Shift Point"),
      tr("A short beep when the shift lights flash, once per climb and never in top gear. It plays only when no " +
         "alert sound is playing, and any real alert cuts it off."),
    ),
  }


def choice_text() -> dict:
  """(title, description, button labels) for each multiple-choice setting."""
  return {
    RANK_STYLE: (
      tr("Drive Rank and Points"),
      tr("Rank your own driving S to D and score points while you drive. Safety rewards smooth driving; Spirited " +
         "rewards clean launches, controlled stops, steady cornering and well-timed shifts, never speed or hard " +
         "braking. Tailgating costs points in both. Only stretches where you set the speed count, not openpilot " +
         "or cruise. The rank, sub-scores and a map of the drive show on the Park summary; the points to the " +
         "right of the speed."),
      [tr("Off"), tr("Safety"), tr("Spirited")],
    ),
    SHIFT_REV_LIMIT: (
      tr("Rev Limit"),
      tr("Where the revs actually stop in manual mode. On the 2022 CX-5 Turbo that is about 5900 rpm, measured " +
         "from drive logs, even though the tach turns red at 6300."),
      ["5700", "5900", "6300"],
    ),
    SHIFT_LEAD: (
      tr("Warning Time"),
      tr("How long before the rev limit Auto flashes: time to see it, react and shift. Early 1.2 s, Normal " +
         "0.9 s, Late 0.6 s."),
      [tr("Early"), tr("Normal"), tr("Late")],
    ),
    SHIFT_POINT: (
      tr("Shift Point"),
      tr("Auto flashes when the revs, at the rate they are climbing, would reach the rev limit within the " +
         "warning time: early in 1st and 2nd, closer to the limit in higher gears. Or pick a fixed rpm. Either " +
         "way it flashes no later than 400 rpm below the rev limit."),
      [tr("Auto"), "4500", "5000", "5500", "6000"],
    ),
    SHIFT_CHIME_VOLUME: (
      tr("Chime Volume"),
      tr("Volume of the shift chime."),
      [f"{v}%" for v in CHIME_VOLUMES],
    ),
  }


SECTIONS = (
  ("On the road", (SLOW_REASON, STEER_LIMIT_ARC, G_METER, TRAFFIC, LANE_AWARENESS, MINI_MAP, REVERSE_CAMERA)),
  ("Trip summary and rank", (TRIP_CARD, RANK_STYLE)),
  ("Shift lights", (SHIFT_LIGHTS, SHIFT_REV_LIMIT, SHIFT_LEAD, SHIFT_POINT, SHIFT_CHIME, SHIFT_CHIME_VOLUME)),
)

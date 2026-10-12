"""
Where the model renderer drew the lead chevrons this frame, for widgets in the HUD that attach to them.

This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

The chevron's screen position lives in the model renderer, which draws before the HUD. sunnypilot's
chevron metrics already receive the chevrons every frame they are drawn; that call publishes them
here. A chevron not republished within STALE_T is gone (no lead, or no openpilot longitudinal).
"""
import time
from dataclasses import dataclass

STALE_T = 0.25  # s


@dataclass
class Chevron:
  x: float        # tip, screen px
  y: float
  bottom: float   # y of the chevron's base
  size: float     # half-width of the base


_chevrons: list[Chevron | None] = [None, None]
_t = 0.0


def publish(lead_vehicles) -> None:
  """lead_vehicles: the model renderer's LeadVehicle list; chevron is [base right, tip, base left]."""
  global _t
  for i in range(2):
    ch = lead_vehicles[i].chevron if i < len(lead_vehicles) else None
    _chevrons[i] = Chevron(ch[1][0], ch[1][1], ch[0][1], ch[0][0] - ch[1][0]) if ch and len(ch) == 3 else None
  _t = time.monotonic()


def lead_chevron(i: int = 0) -> Chevron | None:
  if time.monotonic() - _t > STALE_T:
    return None
  return _chevrons[i]

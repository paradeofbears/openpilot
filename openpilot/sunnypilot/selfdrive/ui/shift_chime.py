"""
Shift chime: soundd's side of the boom-boom shift lights.

This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

The UI asks for a chime by writing REQUEST_PARAM when the revs reach the shift point in manual mode.
soundd plays an existing one-shot sound (prompt_single_high.wav) through the same path as the alert
volume test, so a real alert cuts it short, and only when no alert sound is playing or pending. It has
its own volume and a minimum gap between chimes. No alert, event or priority changes.
"""
import time

ENABLE_PARAM = "ShiftChime"
VOLUME_PARAM = "ShiftChimeVolume"
REQUEST_PARAM = "ShiftChimeRequest"
DEFAULT_VOLUME_PCT = 60
MIN_GAP_S = 1.0


class ShiftChime:
  RELOAD_FRAMES = 50  # 2.5 s at soundd's 20 Hz
  POLL_FRAMES = 2     # 0.1 s, so the chime lands with the lights

  def __init__(self, params):
    self.params = params
    self.enabled = False
    self.volume = DEFAULT_VOLUME_PCT / 100.0
    self.playing = False
    self._frame = 0
    self._last = -1e9
    self.reload()

  def reload(self) -> None:
    self.enabled = self.params.get_bool(ENABLE_PARAM)
    try:
      pct = int(self.params.get(VOLUME_PARAM, return_default=True))
    except (TypeError, ValueError):
      pct = DEFAULT_VOLUME_PCT
    self.volume = max(0, min(100, pct)) / 100.0

  def poll(self) -> bool:
    """True when a chime was asked for and may play now; the request is consumed either way."""
    self._frame += 1
    if self._frame % self.RELOAD_FRAMES == 0:
      self.reload()
    if self._frame % self.POLL_FRAMES != 0:
      return False
    if not self.params.get(REQUEST_PARAM):
      return False
    self.params.remove(REQUEST_PARAM)
    now = time.monotonic()
    if not self.enabled or self.volume <= 0 or now - self._last < MIN_GAP_S:
      return False
    self._last = now
    return True

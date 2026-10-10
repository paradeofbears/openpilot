"""
Per-alert volume control, ported from FrogPilot's "Alert Volumes" settings.

This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

Each alert category gets its own volume, stored as an integer percent:
  0..100  a fixed volume (0 mutes; only offered for engage, disengage and won't-engage)
  101     "Auto": openpilot's ambient-noise volume, which is what every alert uses stock

Alerts that ask the driver to act (prompts, the distracted-driver prompt and both warning
levels) never go below SAFETY_FLOOR_PCT, whatever is stored. With AlertVolumeControl off,
every alert plays at Auto and the stored values are kept for when it is switched back on.
"""
from openpilot.cereal import log, custom

AudibleAlert = log.SelfdriveState.AudibleAlert
AudibleAlertSP = custom.SelfdriveStateSP.AudibleAlert

AUTO_PCT = 101
SAFETY_FLOOR_PCT = 25
MAX_PCT = 100

CONTROL_PARAM = "AlertVolumeControl"
TEST_PARAM = "AlertVolumeTest"

# category -> (param, floor). Order is the order the settings page lists them in.
CATEGORIES: dict[str, tuple[str, int]] = {
  "engage": ("EngageVolume", 0),
  "disengage": ("DisengageVolume", 0),
  "refuse": ("RefuseVolume", 0),
  "prompt": ("PromptVolume", SAFETY_FLOOR_PCT),
  "promptDistracted": ("PromptDistractedVolume", SAFETY_FLOOR_PCT),
  "warningSoft": ("WarningSoftVolume", SAFETY_FLOOR_PCT),
  "warningImmediate": ("WarningImmediateVolume", SAFETY_FLOOR_PCT),
}

# raw AudibleAlert value -> category. sunnypilot's own sounds share the raw value space.
ALERT_CATEGORY: dict[int, str] = {
  AudibleAlert.engage: "engage",
  AudibleAlert.disengage: "disengage",
  AudibleAlert.refuse: "refuse",
  AudibleAlert.prompt: "prompt",
  AudibleAlert.promptRepeat: "prompt",
  AudibleAlert.preAlert: "prompt",
  AudibleAlert.promptDistracted: "promptDistracted",
  AudibleAlert.warningSoft: "warningSoft",
  AudibleAlert.warningImmediate: "warningImmediate",
  AudibleAlertSP.promptSingleLow: "prompt",
  AudibleAlertSP.promptSingleHigh: "prompt",
}

# the sound each category's test button plays
CATEGORY_TEST_ALERT: dict[str, int] = {
  "engage": AudibleAlert.engage,
  "disengage": AudibleAlert.disengage,
  "refuse": AudibleAlert.refuse,
  "prompt": AudibleAlert.prompt,
  "promptDistracted": AudibleAlert.promptDistracted,
  "warningSoft": AudibleAlert.warningSoft,
  "warningImmediate": AudibleAlert.warningImmediate,
}


def clamp_pct(value, floor: int) -> int:
  """A stored value as a usable percent: Auto stays Auto, anything else lands in [floor, 100]."""
  try:
    pct = int(round(float(value)))
  except (TypeError, ValueError):
    return AUTO_PCT
  if pct >= AUTO_PCT:
    return AUTO_PCT
  return max(floor, min(MAX_PCT, pct))


class AlertVolume:
  RELOAD_FRAMES = 50  # 2.5 s at soundd's 20 Hz, the same cadence QuietMode reloads at
  TEST_POLL_FRAMES = 5  # 0.25 s, so a test button feels immediate

  def __init__(self, params):
    self.params = params
    self.enabled = False
    self.levels: dict[str, int] = dict.fromkeys(CATEGORIES, AUTO_PCT)
    self._frame = 0
    self.reload()

  def reload(self) -> None:
    self.enabled = self.params.get_bool(CONTROL_PARAM)
    for cat, (param, floor) in CATEGORIES.items():
      self.levels[cat] = clamp_pct(self.params.get(param, return_default=True), floor)

  def update(self) -> None:
    self._frame += 1
    if self._frame % self.RELOAD_FRAMES == 0:
      self.reload()

  def poll_test_request(self) -> int | None:
    """The raw AudibleAlert a settings test button asked for, consumed on read."""
    if self._frame % self.TEST_POLL_FRAMES != 0:
      return None
    requested = self.params.get(TEST_PARAM)
    if not requested:
      return None
    self.params.remove(TEST_PARAM)
    if isinstance(requested, bytes):
      requested = requested.decode()
    if requested not in CATEGORY_TEST_ALERT:
      return None
    # pick up a level the user just changed without waiting for the next reload
    self.reload()
    return CATEGORY_TEST_ALERT[requested]

  def volume_for(self, alert: int, auto_volume: float) -> float:
    """Output gain for an alert. auto_volume is soundd's ambient-noise volume."""
    if not self.enabled or alert == AudibleAlert.none:
      return auto_volume
    cat = ALERT_CATEGORY.get(int(alert))
    if cat is None:
      return auto_volume
    pct = self.levels[cat]
    if pct == AUTO_PCT:
      return auto_volume
    return pct / 100.0

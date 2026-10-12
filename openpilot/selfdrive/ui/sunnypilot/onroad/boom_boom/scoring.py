"""
Drive scoring for the trip summary: a rank (S to D) and a separate running points score, in two flavours.

This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

Only the driver's own driving counts: stretches where neither openpilot nor the car's cruise control is
setting the speed (cruise not engaged, or the driver on the gas). A hard stop openpilot makes is not the
driver's. The rank is computed from events per 10 km of that distance; the points do not feed the rank.

SAFETY ranks and scores smooth driving and penalises hard brakes, hard launches and tailgating.
CHAOS ranks and scores hard launches and hard stops (with diminishing returns, and never speed).
Tailgating is a penalty in both: it is the one thing here most likely to end in a rear-end collision.
Display only.
"""
import math
from dataclasses import dataclass, field

OFF, SAFETY, CHAOS = 0, 1, 2
FLAVOUR_NAMES = {SAFETY: "SAFETY", CHAOS: "CHAOS"}

MOVING = 0.5               # m/s
HARD_BRAKE = -3.0          # m/s^2, entering an event
HARD_BRAKE_EXIT = -2.0
HARD_LAUNCH = 2.5
HARD_LAUNCH_EXIT = 1.8
SMOOTH_ACCEL = 1.0         # |a| below this is smooth
TAILGATE_GAP = 1.0         # s of time gap
TAILGATE_EXIT_GAP = 1.3
TAILGATE_SPEED = 11.0      # m/s (~25 mph); closer than this in town traffic is normal
TAILGATE_HOLD = 3.0        # s the gap must stay short to count
MIN_RANK_DISTANCE = 1000.0  # m of the driver's own driving before a rank means anything

# points: arcade-sized, so a drive scores in the thousands; the ratios between events are what matter
POINTS_SCALE = 100
CLEAN_STEP_M = 100.0       # safety: points per this much smooth driving
CLEAN_POINTS = 10 * POINTS_SCALE
STREAK_STEP_S = 60.0       # each minute without an incident adds one to the multiplier
STREAK_MAX = 5
TAILGATE_POINTS = -100 * POINTS_SCALE
LAUNCH_POINTS = 100 * POINTS_SCALE  # chaos, per m/s^2 of peak acceleration
STOP_POINTS = 50 * POINTS_SCALE     # chaos, per m/s^2 of peak deceleration
COMBO_WINDOW_S = 10.0      # chaos: events this close together chain
COMBO_MAX = 3
POPUP_T = 1.6              # s a popup stays on screen

RANKS = ((92, "S"), (80, "A"), (65, "B"), (45, "C"), (0, "D"))


def driver_in_control(cruise_engaged: bool, long_active: bool, gas_pressed: bool) -> bool:
  return gas_pressed or not (cruise_engaged or long_active)


def rank_letter(score: float) -> str:
  return next(letter for floor, letter in RANKS if score >= floor)


@dataclass
class Popup:
  text: str
  age: float = 0.0


@dataclass
class DriveScore:
  flavour: int = SAFETY
  driver_distance: float = 0.0
  driver_time: float = 0.0
  smooth_time: float = 0.0
  hard_brakes: int = 0
  hard_launches: int = 0
  tailgates: int = 0
  points: int = 0
  popups: list[Popup] = field(default_factory=list)

  _braking: bool = False
  _launching: bool = False
  _tail_t: float = 0.0
  _tailgating: bool = False
  _peak: float = 0.0
  _streak_t: float = 0.0
  _clean_m: float = 0.0
  _combo: int = 0
  _since_event: float = 1e9

  @property
  def streak(self) -> int:
    return min(STREAK_MAX, 1 + int(self._streak_t // STREAK_STEP_S))

  def _pop(self, text: str) -> None:
    self.popups.append(Popup(text))

  def _incident(self) -> None:
    self._streak_t = 0.0

  def update(self, dt: float, v: float, a: float, driver: bool, lead_present: bool, d_rel: float) -> None:
    for p in self.popups:
      p.age += dt
    self.popups = [p for p in self.popups if p.age < POPUP_T][-3:]
    self._since_event += dt
    if self._since_event > COMBO_WINDOW_S:
      self._combo = 0
    if not driver or v < MOVING:
      self._braking = self._launching = False
      self._tail_t, self._tailgating = 0.0, False
      return

    self.driver_time += dt
    self.driver_distance += v * dt
    self._streak_t += dt
    smooth = abs(a) < SMOOTH_ACCEL
    if smooth:
      self.smooth_time += dt

    # hard brakes and launches: one event per excursion, scored on its peak
    if not self._braking and a < HARD_BRAKE:
      self._braking, self._peak = True, -a
      self.hard_brakes += 1
    elif self._braking:
      self._peak = max(self._peak, -a)
      if a > HARD_BRAKE_EXIT:
        self._braking = False
        self._event("STOP", self._peak, points_per=STOP_POINTS)
    if not self._launching and a > HARD_LAUNCH:
      self._launching, self._peak = True, a
      self.hard_launches += 1
    elif self._launching:
      self._peak = max(self._peak, a)
      if a < HARD_LAUNCH_EXIT:
        self._launching = False
        self._event("LAUNCH", self._peak, points_per=LAUNCH_POINTS)

    # tailgating: a short time gap held at speed, once per episode
    gap = d_rel / v if lead_present and v > 0 else math.inf
    if v > TAILGATE_SPEED and gap < TAILGATE_GAP:
      self._tail_t += dt
      if self._tail_t >= TAILGATE_HOLD and not self._tailgating:
        self._tailgating = True
        self.tailgates += 1
        self.points += TAILGATE_POINTS
        self._incident()
        self._pop(f"{TAILGATE_POINTS:,} TAILGATE")
    elif gap > TAILGATE_EXIT_GAP:
      self._tail_t, self._tailgating = 0.0, False

    # safety: smooth distance earns points, multiplied by the clean streak
    if self.flavour == SAFETY and smooth and not self._tailgating:
      self._clean_m += v * dt
      while self._clean_m >= CLEAN_STEP_M:
        self._clean_m -= CLEAN_STEP_M
        self.points += CLEAN_POINTS * self.streak

  def _event(self, name: str, peak: float, points_per: int) -> None:
    """A finished hard brake or launch with its peak |accel| in m/s^2."""
    if self.flavour == SAFETY:
      self._incident()
      self._pop(f"STREAK LOST: {name}")
      return
    self._combo = min(COMBO_MAX, self._combo + 1) if self._since_event <= COMBO_WINDOW_S else 1
    self._since_event = 0.0
    gained = int(round(points_per * peak)) * self._combo
    self.points += gained
    self._pop(f"+{gained:,} {name}" + (f" x{self._combo}" if self._combo > 1 else ""))

  def rank_score(self) -> float | None:
    """0..100 for the chosen flavour, or None before enough of the driver's own driving."""
    if self.driver_distance < MIN_RANK_DISTANCE:
      return None
    per10 = 10_000.0 / self.driver_distance
    brakes, launches, tails = self.hard_brakes * per10, self.hard_launches * per10, self.tailgates * per10
    smooth = self.smooth_time / self.driver_time if self.driver_time > 0 else 1.0
    if self.flavour == CHAOS:
      score = 100.0 * (1.0 - math.exp(-(brakes + launches) / 4.0)) - 15.0 * tails
    else:
      score = 100.0 - 12.0 * brakes - 8.0 * launches - 15.0 * tails - 30.0 * (1.0 - smooth)
    return max(0.0, min(100.0, score))

  def rank(self) -> str | None:
    s = self.rank_score()
    return None if s is None else rank_letter(s)

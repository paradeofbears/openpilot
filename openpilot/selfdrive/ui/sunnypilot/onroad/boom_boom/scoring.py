"""
Drive scoring for the trip summary: a rank (S to D) built from four sub-scores, and a separate running points
score, in two flavours.

This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

Only the driver's own driving counts: stretches where neither openpilot nor the car's cruise control is
setting the speed (cruise not engaged, or the driver on the gas). A hard stop openpilot makes is not the
driver's. Rates are per 10 km of that distance; the points do not feed the rank.

SAFETY sub-scores: Smoothness (hard brakes and launches, jerk, hard corners, steering, smooth stops),
Following (tailgating, average time gap, closest time to collision), Awareness (distraction, signalling into
an occupied blind spot, speed over a known limit), Engine (economical revs and throttle, no limiter hits).
SPIRITED sub-scores: Control (clean launches and controlled stops, no panic braking or harsh jerks), Cornering
(the share of bends taken on one steady load: no mid-corner correction, hard brake or jerk), Shifting (perfect
shifts in manual mode, limiter hits cost), and Discipline (Following and Awareness, the same penalties as
Safety). Spirited rewards doing it well, not doing it hard: a launch scores the same however hard it is, as long
as it is clean, a clean bend scores the same at any load past BEND_G, and braking hard never scores. Peak
lateral G is kept as a figure to look at, never scored.

A sub-score with no data is left out (None) rather than counted as zero, and the rank is the weighted mean of
the rest, capped at WEAK_LINK above the weakest: one terrible category cannot be averaged away. Speed is never
rewarded; tailgating, distraction and signalling into an occupied blind spot cost points in both flavours.

Thresholds were set from four real drives of a 2022 CX-5 Turbo (routes 00000010-00000015, 2026-10-12, 52 min,
32 of them with the driver setting the speed). Unsignalled lane changes are not scored: while signalling, the
model's lane-line confidence collapses for the whole change, and no drive had an unsignalled one to tune on, so
any detector would risk accusing the driver of something they did not do. Display only.
"""
import math
from dataclasses import dataclass, field

OFF, SAFETY, SPIRITED = 0, 1, 2
FLAVOUR_NAMES = {SAFETY: "SAFETY", SPIRITED: "SPIRITED"}
SUB_NAMES = {SAFETY: ("SMOOTH", "FOLLOWING", "AWARENESS", "ENGINE"),
             SPIRITED: ("CONTROL", "CORNERING", "SHIFTING", "DISCIPLINE")}
WEIGHTS = {SAFETY: (45, 20, 20, 15), SPIRITED: (35, 20, 20, 25)}
WEAK_LINK = 40.0           # the rank is never more than this above the weakest sub-score
SMOOTH_DECAY = 30.0        # weighted incidents per 10 km that take Smoothness to 37

MOVING = 0.5               # m/s
MPH = 0.44704
HARD_BRAKE = -3.0          # m/s^2, entering an event
HARD_BRAKE_EXIT = -2.0
HARD_LAUNCH = 3.0          # safety: ~0.3 g; a turbo on 40% throttle passes 2.5 (route 00000018)
HARD_LAUNCH_EXIT = 2.2
BRISK_LAUNCH = 2.5         # spirited: a launch brisk enough to judge as clean or not
BRISK_LAUNCH_EXIT = 1.8
SMOOTH_ACCEL = 1.0         # |a| below this is smooth
JERK_TAU = 0.15            # s, smoothing of the jerk (the derivative of a 20 Hz acceleration is noisy)
HARSH_JERK = 6.0           # m/s^3, entering a harsh-jerk event (smoothed |jerk| p99 on the reference drives)
HARSH_JERK_EXIT = 3.0
HARSH_JERK_HOLD = 0.09     # s over HARSH_JERK (two UI frames): a one-frame spike is a bump, not the driver
JERK_MIN_SPEED = 2.0       # m/s; below this aEgo jumps by ~2 m/s^2 in a frame as the car creeps off (route 00000017)
MIN_RATE_DISTANCE = 5000.0  # m; rates per 10 km are taken over at least this, so one slip on a short drive is not ten
HARD_CORNER_G = 0.3        # lateral G held HARD_CORNER_HOLD counts as a hard corner (reference p99 0.27 g)
HARD_CORNER_EXIT_G = 0.2
HARD_CORNER_HOLD = 0.5
BEND_G = 0.2               # spirited: lateral G held BEND_HOLD makes a bend worth judging (a brisk on-ramp)
BEND_EXIT_G = 0.12
BEND_HOLD = 1.0
BEND_WOBBLE_G = 0.04       # a mid-corner unload and reload bigger than this and BEND_WOBBLE_SHARE of the peak is
BEND_WOBBLE_SHARE = 0.15   # a correction (clean bends on routes 10-15 wobbled 0.02 g at most, corrections 0.07+)
STEER_FAST = 90.0          # deg/s at speed counts as a jerky steering input
STEER_FAST_SPEED = 15.0    # m/s; below this, fast steering is turning at junctions and parking
STOP_WINDOW_T = 3.0        # s before standstill a stop is judged over
SMOOTH_STOP_DECEL = 2.0    # m/s^2 peak decel into a smooth stop (reference median 1.45)
SMOOTH_STOP_JERK = 4.0     # m/s^3 peak smoothed jerk into a smooth stop
CONTROLLED_STOP_DECEL = 4.0  # spirited: a firm stop is fine, up to this peak decel
CONTROLLED_STOP_JERK = 6.0   # spirited: and no stab at the pedal
PANIC_DECEL = 4.5          # m/s^2 peak of a hard brake that counts as a panic stop
CLEAN_LAUNCH_T = 3.0       # s after a hard launch with no hard brake (and no limiter hit) for it to be clean
TAILGATE_GAP = 1.0         # s of time gap
TAILGATE_EXIT_GAP = 1.3
TAILGATE_SPEED = 11.0      # m/s (~25 mph); closer than this in town traffic is normal
TAILGATE_HOLD = 3.0        # s the gap must stay short to count
GAP_SPEED = 8.0            # m/s; time gaps are averaged above this
GOOD_GAP = 1.8             # s average gap that costs nothing (reference median 2.1)
LOW_TTC = 3.0              # s; a closest time to collision under this costs (reference p1 3.5)
DISTRACTED_EPISODE_T = 2.0  # s of continuous distraction that counts as an episode
OVER_LIMIT = 5 * MPH       # m/s over a known limit that counts as speeding
ECO_RPM = 2500.0
ECO_PEDAL = 600.0          # raw ENGINE_DATA.PEDAL_GAS (reference median 264, p90 952, full ~2000)
LIMITER_MARGIN = 200.0     # rpm under the rev limit that counts as the limiter
LIMITER_HOLD = 0.15        # s
LIMITER_REARM = 800.0      # rpm the revs must fall below the limit before another limiter hit counts
PERFECT_BAND = (900.0, 150.0)  # an upshift with its peak this far below the rev limit (from, to) is perfect
SHIFT_LOOKBACK = 1.0       # s of revs before an upshift its peak is taken over
CLOSE_LEAD_M = 25.0        # a standing start with a car closer than this ahead is not a launch run
MIN_RANK_DISTANCE = 1000.0  # m of the driver's own driving before a rank means anything
MIN_DATA_T = 30.0          # s of a sub-score's data before it counts

# points: arcade-sized, so a drive scores in the thousands; the ratios between events are what matter
POINTS_SCALE = 100
CLEAN_STEP_M = 100.0       # safety: points per this much smooth driving
CLEAN_POINTS = 10 * POINTS_SCALE
STREAK_STEP_S = 60.0       # each minute without an incident adds one to the multiplier
STREAK_MAX = 5
TAILGATE_POINTS = -100 * POINTS_SCALE
BLIND_SPOT_POINTS = -100 * POINTS_SCALE
DISTRACTED_POINTS = -50 * POINTS_SCALE
LIMITER_POINTS = -50 * POINTS_SCALE   # spirited; in safety a limiter hit breaks the streak instead
SMOOTH_STOP_POINTS = 20 * POINTS_SCALE  # safety
CLEAN_LAUNCH_POINTS = 250 * POINTS_SCALE  # spirited, the same however hard the launch
CONTROLLED_STOP_POINTS = 100 * POINTS_SCALE  # spirited
CLEAN_BEND_POINTS = 200 * POINTS_SCALE  # spirited, the same at any load
PERFECT_SHIFT_POINTS = 150 * POINTS_SCALE  # spirited
COMBO_WINDOW_S = 10.0      # spirited: events this close together chain
COMBO_MAX = 3
POPUP_T = 1.6              # s a popup stays on screen

RANKS = ((92, "S"), (80, "A"), (65, "B"), (45, "C"), (0, "D"))


def driver_in_control(cruise_engaged: bool, long_active: bool, gas_pressed: bool) -> bool:
  return gas_pressed or not (cruise_engaged or long_active)


def rank_letter(score: float) -> str:
  return next(letter for floor, letter in RANKS if score >= floor)


def _clip(x: float) -> float:
  return max(0.0, min(100.0, x))


@dataclass
class Popup:
  text: str
  age: float = 0.0


@dataclass
class Extra:
  """What the score reads beyond speed and acceleration; anything unknown stays None or False."""
  lat_g: float | None = None          # |lateral acceleration| in g, from the path curvature
  steer_rate: float | None = None     # deg/s
  v_rel: float = 0.0                  # lead's relative speed, m/s (negative when closing)
  distracted: bool | None = None      # driver monitoring's verdict, None when it is not running
  blinker_left: bool = False
  blinker_right: bool = False
  blind_spot_left: bool = False
  blind_spot_right: bool = False
  speed_limit: float = 0.0            # m/s, 0 when unknown
  rpm: float | None = None
  pedal: float | None = None          # raw ENGINE_DATA.PEDAL_GAS
  gear: int | None = None
  manual: bool = False
  rev_limit: float = 5900.0


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
  # smoothness
  harsh_jerks: int = 0
  hard_corners: int = 0
  peak_lat_g: float = 0.0
  lat_t: float = 0.0
  steer_t: float = 0.0
  steer_fast_t: float = 0.0
  stops: int = 0
  smooth_stops: int = 0
  # following
  gap_t: float = 0.0
  gap_sum: float = 0.0
  min_ttc: float = math.inf
  # awareness
  dm_t: float = 0.0
  distracted_t: float = 0.0
  distractions: int = 0
  blind_spot_signals: int = 0
  limit_t: float = 0.0
  over_limit_t: float = 0.0
  # engine
  rpm_t: float = 0.0
  eco_t: float = 0.0
  limiter_hits: int = 0
  manual_t: float = 0.0
  upshifts: int = 0
  perfect_shifts: int = 0
  # launches: best times from a standstill, s
  best_0_30: float | None = None
  best_0_60: float | None = None

  _braking: bool = False
  _launching: bool = False
  _tail_t: float = 0.0
  _tailgating: bool = False
  _peak: float = 0.0
  _streak_t: float = 0.0
  _clean_m: float = 0.0
  _combo: int = 0
  # spirited control
  launches_judged: int = 0
  clean_launches: int = 0
  controlled_stops: int = 0
  panic_brakes: int = 0
  _launch_check: float | None = None  # s left to watch a finished launch
  _launch_marks: tuple = (0, 0)       # (hard brakes, limiter hits) when the launch began
  _since_event: float = 1e9
  _prev_a: float | None = None
  _jerk: float = 0.0
  _jerking: bool = False
  _jerk_over_t: float = 0.0
  _corner_t: float = 0.0
  _cornering: bool = False
  _corner_peak: float = 0.0
  # spirited bends
  bends: int = 0
  clean_bends: int = 0
  _bend_on: bool = False
  _bend_t: float = 0.0
  _bend_peak: float = 0.0
  _bend_dip: float = 0.0
  _bend_wobbled: bool = False
  _bend_marks: tuple = (0, 0)  # (hard brakes, harsh jerks) at turn-in
  _stop_window: list = field(default_factory=list)  # (age, a, |jerk|) over the last STOP_WINDOW_T
  _distracted_run: float = 0.0
  _distraction_counted: bool = False
  _prev_blink: tuple = (False, False)
  _limiter_t: float = 0.0
  _limiter_armed: bool = True
  _rpm_window: list = field(default_factory=list)  # (age, rpm) over SHIFT_LOOKBACK
  _prev_gear: int | None = None
  _launch_t: float | None = None
  _launch_30: float | None = None

  @property
  def streak(self) -> int:
    return min(STREAK_MAX, 1 + int(self._streak_t // STREAK_STEP_S))

  def _pop(self, text: str) -> None:
    self.popups.append(Popup(text))

  def _incident(self, name: str | None = None) -> None:
    if name is not None and self.flavour == SAFETY and self._streak_t >= STREAK_STEP_S:
      self._pop(f"STREAK LOST: {name}")
    self._streak_t = 0.0

  def _penalty(self, points: int, name: str) -> None:
    self.points += points
    self._incident()
    self._pop(f"{points:,} {name}")

  def update(self, dt: float, v: float, a: float, driver: bool, lead_present: bool, d_rel: float,
             x: Extra | None = None) -> None:
    x = x or Extra()
    for p in self.popups:
      p.age += dt
    self.popups = [p for p in self.popups if p.age < POPUP_T][-3:]
    self._since_event += dt
    if self._since_event > COMBO_WINDOW_S:
      self._combo = 0

    self._jerk_update(dt, v, a)
    self._stops_update(dt, v, a, driver)
    self._launch_update(dt, v, driver, lead_present, d_rel)
    self._judge_launch(dt)
    if not driver or v < MOVING:
      self._braking = self._launching = False
      self._tail_t, self._tailgating = 0.0, False
      self._prev_gear = x.gear
      return

    self.driver_time += dt
    self.driver_distance += v * dt
    self._streak_t += dt
    smooth = abs(a) < SMOOTH_ACCEL
    if smooth:
      self.smooth_time += dt

    self._hard_events(a)
    self._harsh_jerk(dt)
    self._corners(dt, v, x)
    self._steering(dt, v, x)
    self._following(dt, v, lead_present, d_rel, x)
    self._awareness(dt, v, x)
    self._engine(dt, x)

    # safety: smooth distance earns points, multiplied by the clean streak
    if self.flavour == SAFETY and smooth and not self._tailgating:
      self._clean_m += v * dt
      while self._clean_m >= CLEAN_STEP_M:
        self._clean_m -= CLEAN_STEP_M
        self.points += CLEAN_POINTS * self.streak

  # ---- events ---------------------------------------------------------------------------------------------

  def _jerk_update(self, dt: float, v: float, a: float) -> None:
    if v < JERK_MIN_SPEED:
      self._jerk = 0.0
    elif self._prev_a is not None and dt > 0:
      raw = (a - self._prev_a) / dt
      self._jerk += (raw - self._jerk) * min(1.0, dt / JERK_TAU)
    self._prev_a = a

  def _hard_events(self, a: float) -> None:
    # hard brakes and launches: one event per excursion, scored on its peak
    if not self._braking and a < HARD_BRAKE:
      self._braking, self._peak = True, -a
      self.hard_brakes += 1
    elif self._braking:
      self._peak = max(self._peak, -a)
      if a > HARD_BRAKE_EXIT:
        self._braking = False
        self._event("STOP", self._peak)
    launch, launch_exit = (HARD_LAUNCH, HARD_LAUNCH_EXIT) if self.flavour == SAFETY else (BRISK_LAUNCH, BRISK_LAUNCH_EXIT)
    if not self._launching and a > launch:
      self._launching, self._peak = True, a
      self.hard_launches += 1
      self._launch_marks = (self.hard_brakes, self.limiter_hits)
    elif self._launching:
      self._peak = max(self._peak, a)
      if a < launch_exit:
        self._launching = False
        self._event("LAUNCH", self._peak)

  def _harsh_jerk(self, dt: float) -> None:
    j = abs(self._jerk)
    self._jerk_over_t = self._jerk_over_t + dt if j > HARSH_JERK else 0.0
    if not self._jerking and self._jerk_over_t >= HARSH_JERK_HOLD:
      self._jerking = True
      self.harsh_jerks += 1
      if self.flavour == SAFETY:
        self._incident("JERKY")
      elif self.flavour == SPIRITED:
        self._combo_lost()
    elif self._jerking and j < HARSH_JERK_EXIT:
      self._jerking = False

  def _corners(self, dt: float, v: float, x: Extra) -> None:
    if x.lat_g is None:
      return
    self.lat_t += dt
    g = abs(x.lat_g)
    self.peak_lat_g = max(self.peak_lat_g, g)
    if g > HARD_CORNER_G:
      self._corner_t += dt
      self._corner_peak = max(self._corner_peak, g)
      if self._corner_t >= HARD_CORNER_HOLD and not self._cornering:
        self._cornering = True
        self.hard_corners += 1
        if self.flavour == SAFETY:
          self._incident("CORNER")
    elif g < HARD_CORNER_EXIT_G:
      self._corner_t, self._cornering, self._corner_peak = 0.0, False, 0.0
    self._bend(dt, g)

  def _bend(self, dt: float, g: float) -> None:
    """Spirited: a bend is clean when the load builds once and unwinds once, with no correction, hard brake or
    harsh jerk in between."""
    if not self._bend_on:
      if g > BEND_G:
        self._bend_on, self._bend_t, self._bend_wobbled = True, 0.0, False
        self._bend_peak = self._bend_dip = g
        self._bend_marks = (self.hard_brakes, self.harsh_jerks)
      return
    if g > BEND_G:
      self._bend_t += dt
    self._bend_dip = min(self._bend_dip, g)
    wobble = max(BEND_WOBBLE_G, BEND_WOBBLE_SHARE * self._bend_peak)
    if self._bend_peak - self._bend_dip > wobble and g - self._bend_dip > wobble:
      self._bend_wobbled = True  # unloaded and reloaded mid-corner
      self._bend_peak = self._bend_dip = g
    elif g >= self._bend_peak:
      self._bend_peak = self._bend_dip = g
    if g < BEND_EXIT_G:
      self._bend_on = False
      if self._bend_t < BEND_HOLD:
        return  # a kink or a lane change, not a bend
      self.bends += 1
      clean = not self._bend_wobbled and (self.hard_brakes, self.harsh_jerks) == self._bend_marks
      if clean:
        self.clean_bends += 1
      if self.flavour == SPIRITED:
        if clean:
          self._spirited_points("CLEAN CORNER", CLEAN_BEND_POINTS)
        else:
          self._combo_lost()

  def _steering(self, dt: float, v: float, x: Extra) -> None:
    if x.steer_rate is None or v < STEER_FAST_SPEED:
      return
    self.steer_t += dt
    if abs(x.steer_rate) > STEER_FAST:
      self.steer_fast_t += dt

  def _stops_update(self, dt: float, v: float, a: float, driver: bool) -> None:
    self._stop_window = [(age + dt, aa, jj) for age, aa, jj in self._stop_window if age + dt <= STOP_WINDOW_T]
    if v >= MOVING:
      self._stop_window.append((0.0, a, abs(self._jerk)))
    elif self._stop_window and driver:
      # just came to a stop: judge the braking that led into it
      peak_decel = max(0.0, -min(aa for _, aa, _ in self._stop_window))
      peak_jerk = max(jj for _, _, jj in self._stop_window)
      self.stops += 1
      if peak_decel < SMOOTH_STOP_DECEL and peak_jerk < SMOOTH_STOP_JERK:
        self.smooth_stops += 1
        if self.flavour == SAFETY:
          self.points += SMOOTH_STOP_POINTS
          self._pop(f"+{SMOOTH_STOP_POINTS:,} SMOOTH STOP")
      if peak_decel < CONTROLLED_STOP_DECEL and peak_jerk < CONTROLLED_STOP_JERK:
        self.controlled_stops += 1
        if self.flavour == SPIRITED:
          self._spirited_points("CLEAN STOP", CONTROLLED_STOP_POINTS)
      self._stop_window = []
    else:
      self._stop_window = []

  def _launch_update(self, dt: float, v: float, driver: bool, lead_present: bool, d_rel: float) -> None:
    if v < MOVING:
      close = lead_present and d_rel < CLOSE_LEAD_M
      self._launch_t = None if close else 0.0
      self._launch_30 = None
      return
    if self._launch_t is None:
      return
    if not driver:
      self._launch_t = None
      return
    self._launch_t += dt
    if self._launch_30 is None and v >= 30 * MPH:
      self._launch_30 = self._launch_t
      if self.best_0_30 is None or self._launch_30 < self.best_0_30:
        self.best_0_30 = self._launch_30
    if v >= 60 * MPH:
      if self.best_0_60 is None or self._launch_t < self.best_0_60:
        self.best_0_60 = self._launch_t
      self._launch_t = None

  def _following(self, dt: float, v: float, lead_present: bool, d_rel: float, x: Extra) -> None:
    gap = d_rel / v if lead_present and v > 0 else math.inf
    if lead_present and v > GAP_SPEED:
      self.gap_t += dt
      self.gap_sum += gap * dt
      if x.v_rel < -0.5:
        self.min_ttc = min(self.min_ttc, d_rel / -x.v_rel)
    # tailgating: a short time gap held at speed, once per episode
    if v > TAILGATE_SPEED and gap < TAILGATE_GAP:
      self._tail_t += dt
      if self._tail_t >= TAILGATE_HOLD and not self._tailgating:
        self._tailgating = True
        self.tailgates += 1
        self._penalty(TAILGATE_POINTS, "TAILGATE")
    elif gap > TAILGATE_EXIT_GAP:
      self._tail_t, self._tailgating = 0.0, False

  def _awareness(self, dt: float, v: float, x: Extra) -> None:
    if x.distracted is not None:
      self.dm_t += dt
      if x.distracted:
        self.distracted_t += dt
        self._distracted_run += dt
        if self._distracted_run >= DISTRACTED_EPISODE_T and not self._distraction_counted:
          self._distraction_counted = True
          self.distractions += 1
          self._penalty(DISTRACTED_POINTS, "EYES UP")
      else:
        self._distracted_run, self._distraction_counted = 0.0, False
    # a blinker switched on toward a side the blind-spot monitor says is occupied
    on_left = x.blinker_left and not self._prev_blink[0]
    on_right = x.blinker_right and not self._prev_blink[1]
    if (on_left and x.blind_spot_left) or (on_right and x.blind_spot_right):
      self.blind_spot_signals += 1
      self._penalty(BLIND_SPOT_POINTS, "CHECK BLIND SPOT")
    self._prev_blink = (x.blinker_left, x.blinker_right)
    if x.speed_limit > 0:
      self.limit_t += dt
      if v > x.speed_limit + OVER_LIMIT:
        self.over_limit_t += dt

  def _engine(self, dt: float, x: Extra) -> None:
    if x.rpm is None:
      self._prev_gear = x.gear
      return
    self.rpm_t += dt
    if x.rpm < ECO_RPM and (x.pedal is None or x.pedal < ECO_PEDAL):
      self.eco_t += dt
    # the limiter: the revs held within LIMITER_MARGIN of the rev limit
    if x.rpm >= x.rev_limit - LIMITER_MARGIN:
      self._limiter_t += dt
      if self._limiter_t >= LIMITER_HOLD and self._limiter_armed:
        self._limiter_armed = False
        self.limiter_hits += 1
        if self.flavour == SPIRITED:
          self._penalty(LIMITER_POINTS, "LIMITER")
        else:
          self._incident("LIMITER")
    else:
      self._limiter_t = 0.0
      if x.rpm < x.rev_limit - LIMITER_REARM:
        self._limiter_armed = True
    # perfect shifts: a manual upshift taken high but before the limiter
    self._rpm_window = [(age + dt, r) for age, r in self._rpm_window if age + dt <= SHIFT_LOOKBACK]
    self._rpm_window.append((0.0, x.rpm))
    if x.manual:
      self.manual_t += dt
      if x.gear is not None and self._prev_gear is not None and x.gear > self._prev_gear:
        self.upshifts += 1
        peak = max(r for _, r in self._rpm_window)
        lo, hi = x.rev_limit - PERFECT_BAND[0], x.rev_limit - PERFECT_BAND[1]
        if lo <= peak < hi:
          self.perfect_shifts += 1
          if self.flavour == SPIRITED:
            self._spirited_points("PERFECT SHIFT", PERFECT_SHIFT_POINTS)
    self._prev_gear = x.gear

  def _spirited_points(self, name: str, base: int) -> None:
    self._combo = min(COMBO_MAX, self._combo + 1) if self._since_event <= COMBO_WINDOW_S else 1
    self._since_event = 0.0
    gained = base * self._combo
    self.points += gained
    self._pop(f"+{gained:,} {name}" + (f" x{self._combo}" if self._combo > 1 else ""))

  def _event(self, name: str, peak: float) -> None:
    """A finished hard brake or launch with its peak |accel| in m/s^2."""
    if name == "LAUNCH":
      self._launch_check = CLEAN_LAUNCH_T  # judged once it is clear what followed it
    elif peak > PANIC_DECEL:
      self.panic_brakes += 1
      if self.flavour == SPIRITED:
        self._combo_lost()
    if self.flavour == SAFETY:
      self._streak_t = STREAK_STEP_S  # always announce: a hard event is the thing the streak is about
      self._incident(name)

  def _judge_launch(self, dt: float) -> None:
    if self._launch_check is None:
      return
    self._launch_check -= dt
    if self.hard_brakes > self._launch_marks[0] or self.limiter_hits > self._launch_marks[1]:
      self._launch_check = None
      self.launches_judged += 1
      return
    if self._launch_check <= 0:
      self._launch_check = None
      self.launches_judged += 1
      self.clean_launches += 1
      if self.flavour == SPIRITED:
        self._spirited_points("CLEAN LAUNCH", CLEAN_LAUNCH_POINTS)

  def _combo_lost(self) -> None:
    if self._combo > 1:
      self._pop("COMBO LOST")
    self._combo = 0
    self._since_event = 1e9

  # ---- the rank -------------------------------------------------------------------------------------------

  def _per10(self, n: int) -> float:
    return n * 10_000.0 / max(self.driver_distance, MIN_RATE_DISTANCE)

  def following(self) -> float | None:
    if self.gap_t < MIN_DATA_T and self.tailgates == 0:
      return None
    avg_gap = self.gap_sum / self.gap_t if self.gap_t > 0 else GOOD_GAP
    score = 100.0 - 15.0 * self._per10(self.tailgates) - 40.0 * min(1.0, max(0.0, GOOD_GAP - avg_gap))
    if self.min_ttc < LOW_TTC:
      score -= 20.0 * (LOW_TTC - self.min_ttc) / LOW_TTC
    return _clip(score)

  def awareness(self) -> float | None:
    if self.dm_t < MIN_DATA_T and self.limit_t < MIN_DATA_T and self.blind_spot_signals == 0:
      return None
    score = 100.0 - 20.0 * self.blind_spot_signals - 5.0 * self._per10(self.distractions)
    if self.dm_t > 0:
      score -= 2.0 * 100.0 * self.distracted_t / self.dm_t
    if self.limit_t >= MIN_DATA_T:
      score -= 1.5 * 100.0 * self.over_limit_t / self.limit_t
    return _clip(score)

  def sub_scores(self) -> tuple[float | None, ...] | None:
    """The four sub-scores (SUB_NAMES order) for the flavour, None where there is no data; None before
    enough of the driver's own driving."""
    if self.driver_distance < MIN_RANK_DISTANCE:
      return None
    brakes, launches = self._per10(self.hard_brakes), self._per10(self.hard_launches)
    following, awareness = self.following(), self.awareness()
    if self.flavour == SPIRITED:
      control = None
      if self.launches_judged + self.stops:
        clean = (self.clean_launches + self.controlled_stops) / (self.launches_judged + self.stops)
        control = _clip(100.0 * clean - 1.0 * self._per10(self.harsh_jerks) - 10.0 * self._per10(self.panic_brakes))
      cornering = 100.0 * self.clean_bends / self.bends if self.bends else None
      shifting = None
      if self.manual_t >= MIN_DATA_T or self.perfect_shifts:
        shifting = _clip(100.0 * (1.0 - math.exp(-self.perfect_shifts / 3.0)) - 5.0 * self.limiter_hits)
      parts = [p for p in (following, awareness) if p is not None]
      discipline = min(parts) if parts else None
      return control, cornering, shifting, discipline
    # smoothness: incidents per 10 km, weighted, decaying so a short spirited stretch is not a zero
    incidents = brakes + 0.7 * launches + 0.25 * self._per10(self.harsh_jerks) + 0.7 * self._per10(self.hard_corners)
    smooth_share = self.smooth_time / self.driver_time if self.driver_time > 0 else 1.0
    smoothness = 100.0 * math.exp(-incidents / SMOOTH_DECAY) - 15.0 * (1.0 - smooth_share)
    if self.steer_t >= MIN_DATA_T:
      smoothness -= 100.0 * self.steer_fast_t / self.steer_t
    if self.stops:
      smoothness -= 10.0 * (1.0 - self.smooth_stops / self.stops)
    engine = None
    if self.rpm_t >= MIN_DATA_T:
      engine = _clip(60.0 + 40.0 * self.eco_t / self.rpm_t - 10.0 * self._per10(self.limiter_hits))
    return _clip(smoothness), following, awareness, engine

  def rank_score(self) -> float | None:
    """0..100 for the chosen flavour, or None before enough of the driver's own driving."""
    subs = self.sub_scores()
    if subs is None:
      return None
    pairs = [(s, w) for s, w in zip(subs, WEIGHTS[self.flavour], strict=True) if s is not None]
    if not pairs:
      return None  # nothing yet that this style judges
    mean = sum(s * w for s, w in pairs) / sum(w for _, w in pairs)
    return _clip(min(mean, min(s for s, _ in pairs) + WEAK_LINK))

  def rank(self) -> str | None:
    s = self.rank_score()
    return None if s is None else rank_letter(s)

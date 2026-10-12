"""
This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
from types import SimpleNamespace

from opendbc.can.packer import CANPacker
from openpilot.common.test import OpenpilotTestCase
from openpilot.selfdrive.ui.boom_boom.mazda_can import STALE_T, CanTap, Powertrain, decode_frame
from openpilot.selfdrive.ui.boom_boom.shift_lights import (
  AUTO, CAP_MARGIN, DEFAULT_LEAD, DEFAULT_REV_LIMIT, FILL_SPAN, LEAD_OPTIONS, LEDS, REARM_DROP, TOP_GEAR, ShiftLights,
  ShiftLogic,
  flash_point, lit, shift_due,
)
from openpilot.selfdrive.ui.boom_boom import shift_chime

PACKER = CANPacker("mazda_2017")


def frame(name_or_addr, values=None, raw=None):
  if raw is not None:
    return SimpleNamespace(src=0, address=name_or_addr, dat=raw)
  addr, dat, _ = PACKER.make_can_msg(name_or_addr, 0, values)
  return SimpleNamespace(src=0, address=addr, dat=dat)


def manual_frame(on):
  dat = bytearray(8)
  dat[2] = 0x80 if on else 0x00  # byte 2 bit 7, as logged on a 2022 CX-5 Turbo in the M gate
  return frame(0x131, raw=bytes(dat))


class TestDecode(OpenpilotTestCase):
  def test_rpm_gear_manual(self):
    assert decode_frame(*_ad(frame("ENGINE_DATA", {"RPM": 3048.75})))["rpm"] == 3048.75
    assert decode_frame(*_ad(frame("GEAR", {"MORE_GEAR": 3})))["gear"] == 3
    assert decode_frame(*_ad(manual_frame(True))) == {"manual": True}
    assert decode_frame(*_ad(manual_frame(False))) == {"manual": False}
    assert decode_frame(0x123, b"\x00" * 8) == {}

  def test_tap_keeps_latest_and_forgets_stale(self):
    tap = CanTap()
    other_bus = SimpleNamespace(src=2, address=0x202, dat=frame("ENGINE_DATA", {"RPM": 9000}).dat)
    tap.feed([frame("ENGINE_DATA", {"RPM": 2000}), frame("GEAR", {"MORE_GEAR": 2}), manual_frame(True), other_bus], 10.0)
    assert tap.read(10.1) == Powertrain(2000.0, 2, True, 0.0)  # the camera bus copy is ignored
    assert tap.read(10.0 + STALE_T + 0.01) == Powertrain(None, None, None)


def _ad(f):
  return f.address, bytes(f.dat)


RED = DEFAULT_REV_LIMIT  # 5900, where a 2022 CX-5 2.5 Turbo's revs stop in M (its tach turns red at 6300)


def climb(logic, start, end, rate, gear=2, manual=True, fixed=AUTO, dt=0.05, lead=DEFAULT_LEAD):
  """Rev from start to end at `rate` rpm/s; returns the rpms where the chime fired."""
  fired, rpm = [], start
  while rpm <= end:
    if logic.update(rpm, dt, RED, fixed, gear, manual, lead):
      fired.append(rpm)
    rpm += rate * dt
  return fired


class TestShiftPoint(OpenpilotTestCase):
  def test_flash_point_and_cap(self):
    assert flash_point(RED, AUTO) == RED - CAP_MARGIN
    assert flash_point(RED, 4500) == 4500
    assert flash_point(5700, 6000) == 5700 - CAP_MARGIN  # a fixed point never past the limit's margin

  def test_auto_leads_by_the_rev_rate(self):
    assert not shift_due(4500, 1000, RED, AUTO)  # 4500 + 900 short of 5900 at the 0.9 s Normal lead
    assert shift_due(4500, 1600, RED, AUTO)      # 4500 + 1440 reaches it
    assert shift_due(RED - CAP_MARGIN, 0, RED, AUTO)
    assert not shift_due(4900, 5000, RED, 5000)  # a fixed point ignores the rate
    assert not shift_due(2000, 8000, RED, AUTO)  # a launch's rate spike far below the bar is no shift

  def test_fill(self):
    top = flash_point(RED, AUTO)
    assert lit(top - FILL_SPAN - 100, top) == 0
    assert lit(top - FILL_SPAN / 2, top) == LEDS // 2
    assert lit(top, top) == LEDS


class TestShiftLogic(OpenpilotTestCase):
  def test_fast_climb_flashes_early_slow_climb_at_the_cap(self):
    fast = climb(ShiftLogic(), 3000, 6300, 2500)
    assert len(fast) == 1 and RED - 2500 * DEFAULT_LEAD - 300 < fast[0] < RED - 2500 * DEFAULT_LEAD + 300
    slow = climb(ShiftLogic(), 3000, 6300, 300)
    assert len(slow) == 1 and abs(slow[0] - (RED - CAP_MARGIN)) <= 300 * 0.05 + 1

  def test_fixed_point(self):
    fired = climb(ShiftLogic(), 3000, 6000, 2500, fixed=4500)
    assert len(fired) == 1 and 4500 <= fired[0] < 4500 + 2500 * 0.05 + 1

  def test_once_per_climb_rearmed_by_a_shift(self):
    logic = ShiftLogic()
    assert len(climb(logic, 3000, 6100, 2000)) == 1
    assert logic.flashing
    assert not climb(logic, 6100, 6200, 200)       # holding the revs: no second chime
    assert not logic.update(6100 - REARM_DROP + 100, 0.05, RED, AUTO, 2, True)  # small dip: not re-armed
    logic.update(4200, 0.05, RED, AUTO, 3, True)    # the upshift drops the revs
    assert not logic.flashing
    assert len(climb(logic, 4200, 6100, 1500, gear=3)) == 1

  def test_flashes_but_never_chimes_in_top_gear_or_drive(self):
    logic = ShiftLogic()
    assert not climb(logic, 3000, 6200, 2000, gear=TOP_GEAR) and logic.flashing
    assert not climb(ShiftLogic(), 3000, 6200, 2000, manual=False)

  def test_lifting_off_stops_the_flash(self):
    logic = ShiftLogic()
    climb(logic, 3000, 5200, 3000)  # flashing early on a fast climb
    assert logic.flashing
    for _ in range(20):             # lift off: the revs hold, then sag a little, and the rate falls to zero
      logic.update(5150, 0.05, RED, AUTO, 2, True)
    assert not logic.flashing

  def test_warning_time_moves_the_flash(self):
    early, normal, late = (climb(ShiftLogic(), 3000, 6000, 1300, lead=lead)[0] for lead in LEAD_OPTIONS)
    assert early < normal < late
    assert RED - normal >= 1300 * DEFAULT_LEAD - 70  # Normal flashes ~0.9 s ahead of the limit at a 1st-gear climb

  def test_no_rpm(self):
    logic = ShiftLogic()
    assert not logic.update(None, 0.05, RED, AUTO, 2, True) and not logic.flashing


class TestShiftLights(OpenpilotTestCase):
  def test_shows_only_in_manual(self):
    sl = ShiftLights()
    sl.update(Powertrain(4000.0, 3, False), RED, AUTO, 0.05)
    assert not sl.showing
    sl.update(Powertrain(4000.0, 3, True), RED, AUTO, 0.05)
    assert sl.showing
    sl.update(Powertrain(None, 3, True), RED, AUTO, 0.05)
    assert not sl.showing  # no fresh rpm

  def test_unknown_settings_fall_back(self):
    sl = ShiftLights()
    sl.update(Powertrain(), 1234, 777, 0.05, 3.3)
    assert (sl.rev_limit, sl.fixed, sl.lead) == (DEFAULT_REV_LIMIT, AUTO, DEFAULT_LEAD)


class FakeParams:
  def __init__(self, **kw):
    self.store = {"ShiftChime": True, "ShiftChimeVolume": 60, **kw}

  def get_bool(self, k):
    return bool(self.store.get(k))

  def get(self, k, return_default=False):
    return self.store.get(k)

  def remove(self, k):
    self.store.pop(k, None)


class TestSounddChime(OpenpilotTestCase):
  def poll_n(self, chime, n):
    return any(chime.poll() for _ in range(n))

  def test_request_is_consumed_and_plays(self):
    p = FakeParams(ShiftChimeRequest="1")
    c = shift_chime.ShiftChime(p)
    assert self.poll_n(c, 2)
    assert "ShiftChimeRequest" not in p.store
    assert c.volume == 0.6

  def test_switched_off_or_too_soon(self):
    p = FakeParams(ShiftChime=False, ShiftChimeRequest="1")
    c = shift_chime.ShiftChime(p)
    assert not self.poll_n(c, 2) and "ShiftChimeRequest" not in p.store  # consumed, not played
    p = FakeParams(ShiftChimeRequest="1")
    c = shift_chime.ShiftChime(p)
    assert self.poll_n(c, 2)
    p.store["ShiftChimeRequest"] = "1"
    assert not self.poll_n(c, 2)  # inside the minimum gap

  def test_volume_clamped(self):
    assert shift_chime.ShiftChime(FakeParams(ShiftChimeVolume=250)).volume == 1.0
    assert shift_chime.ShiftChime(FakeParams(ShiftChimeVolume="junk")).volume == shift_chime.DEFAULT_VOLUME_PCT / 100

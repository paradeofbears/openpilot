"""
This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
from types import SimpleNamespace

from opendbc.can.packer import CANPacker
from openpilot.common.test import OpenpilotTestCase
from openpilot.selfdrive.ui.sunnypilot.onroad.boom_boom.mazda_can import STALE_T, CanTap, Powertrain, decode_frame
from openpilot.selfdrive.ui.sunnypilot.onroad.boom_boom.shift_lights import (
  DEFAULT_SHIFT_RPM, HYSTERESIS_RPM, LEDS, SPAN_RPM, TOP_GEAR, ChimeTrigger, ShiftLights, lit,
)
from openpilot.sunnypilot.selfdrive.ui import shift_chime

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
    assert tap.read(10.1) == Powertrain(2000.0, 2, True)  # the camera bus copy is ignored
    assert tap.read(10.0 + STALE_T + 0.01) == Powertrain(None, None, None)


def _ad(f):
  return f.address, bytes(f.dat)


class TestLights(OpenpilotTestCase):
  def test_fill(self):
    s = DEFAULT_SHIFT_RPM
    assert lit(s - SPAN_RPM - 100, s) == 0
    assert lit(s - SPAN_RPM / 2, s) == LEDS // 2
    assert lit(s - 1, s) == LEDS - 1
    assert lit(s, s) == LEDS

  def test_shows_only_in_manual(self):
    sl = ShiftLights()
    sl.update(Powertrain(4000.0, 3, False), 5500, 0.05)
    assert not sl.showing
    sl.update(Powertrain(4000.0, 3, True), 5500, 0.05)
    assert sl.showing
    sl.update(Powertrain(None, 3, True), 5500, 0.05)
    assert not sl.showing  # no fresh rpm

  def test_unknown_shift_point_falls_back(self):
    sl = ShiftLights()
    sl.update(Powertrain(), 1234, 0.05)
    assert sl.shift_rpm == DEFAULT_SHIFT_RPM


class TestChimeTrigger(OpenpilotTestCase):
  def test_once_per_climb(self):
    t = ChimeTrigger()
    assert not t.update(5000, 2, True, 5500)
    assert t.update(5600, 2, True, 5500)
    assert not t.update(5700, 2, True, 5500)                       # holding the revs: once only
    assert not t.update(5500 - HYSTERESIS_RPM + 50, 2, True, 5500)  # a small dip does not re-arm
    assert not t.update(5600, 2, True, 5500)
    t.update(4000, 3, True, 5500)                                   # shifted: revs fell, re-armed
    assert t.update(5600, 3, True, 5500)

  def test_not_in_top_gear_or_drive(self):
    assert not ChimeTrigger().update(5600, TOP_GEAR, True, 5500)
    assert not ChimeTrigger().update(5600, 3, False, 5500)
    assert not ChimeTrigger().update(None, 3, True, 5500)


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

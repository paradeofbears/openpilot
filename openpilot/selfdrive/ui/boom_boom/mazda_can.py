"""
Mazda powertrain values the car port never publishes, read by the UI straight off the `can` stream.

This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

Display only: it subscribes to pandad's `can` messages like any logger would and decodes three bus-0
frames. Nothing is sent and no driving process is touched. Mapped on a 2022 CX-5 Turbo
(routes 00000007, 00000008, 2026-10-12):

  ENGINE_DATA 0x202 RPM          100 Hz  engine speed (DBC signal; idle ~610-760, matches the tach)
  ENGINE_DATA 0x202 PEDAL_GAS    100 Hz  accelerator pedal, raw (cruising ~260, full throttle ~2000-2070)
  GEAR 0x228 MORE_GEAR           50 Hz   engaged gear, 1-6 (DBC's GEAR_BOX is the target, ~0.3 s ahead)
  0x131 byte 2 bit 7             50 Hz   manual mode: lever in the M gate (also 0x09E byte 1 bit 2, 10 Hz)

Not in the DBC: the bits live in the opendbc submodule, which this fork does not push to, so they are
read here by byte and bit.
"""
import time
from dataclasses import dataclass

STALE_T = 0.5  # s without a frame and a value is unknown

ENGINE_DATA = 0x202
GEAR = 0x228
MANUAL_MODE_ADDR, MANUAL_MODE_BYTE, MANUAL_MODE_BIT = 0x131, 2, 7

_signals = None


def _dbc_signals():
  global _signals
  if _signals is None:
    from opendbc.can.dbc import DBC
    dbc = DBC("mazda_2017")
    _signals = {
      "rpm": (ENGINE_DATA, dbc.name_to_msg["ENGINE_DATA"].sigs["RPM"]),
      "pedal": (ENGINE_DATA, dbc.name_to_msg["ENGINE_DATA"].sigs["PEDAL_GAS"]),
      "gear": (GEAR, dbc.name_to_msg["GEAR"].sigs["MORE_GEAR"]),
    }
  return _signals


def _value(dat: bytes, sig) -> float:
  from opendbc.can.parser import get_raw_value
  raw = get_raw_value(dat, sig)
  if sig.is_signed:
    raw -= ((raw >> (sig.size - 1)) & 0x1) * (1 << sig.size)
  return raw * sig.factor + sig.offset


def decode_frame(address: int, dat: bytes) -> dict:
  """The values one bus-0 frame carries, by name; empty for frames this does not read."""
  out = {}
  for name, (addr, sig) in _dbc_signals().items():
    if address == addr:
      out[name] = _value(dat, sig)
  if address == MANUAL_MODE_ADDR and len(dat) > MANUAL_MODE_BYTE:
    out["manual"] = bool((dat[MANUAL_MODE_BYTE] >> MANUAL_MODE_BIT) & 1)
  return out


@dataclass
class Powertrain:
  rpm: float | None = None
  gear: int | None = None
  manual: bool | None = None
  pedal: float | None = None


class CanTap:
  """Drains `can` each UI frame and keeps the latest of each value, forgetting stale ones."""

  def __init__(self):
    self._sock = None
    self._values: dict[str, tuple[float, float]] = {}  # name -> (value, monotonic time)

  def close(self) -> None:
    self._sock = None

  def feed(self, frames, now: float) -> None:
    for f in frames:
      if f.src != 0:
        continue
      for name, v in decode_frame(f.address, bytes(f.dat)).items():
        self._values[name] = (v, now)

  def update(self) -> Powertrain:
    from .compat import messaging
    if self._sock is None:
      self._sock = messaging.sub_sock("can", conflate=False)
    now = time.monotonic()
    for evt in messaging.drain_sock(self._sock):
      self.feed(evt.can, now)
    return self.read(now)

  def read(self, now: float) -> Powertrain:
    def fresh(name):
      v = self._values.get(name)
      return v[0] if v is not None and now - v[1] < STALE_T else None
    gear = fresh("gear")
    return Powertrain(fresh("rpm"), int(gear) if gear is not None else None, fresh("manual"), fresh("pedal"))

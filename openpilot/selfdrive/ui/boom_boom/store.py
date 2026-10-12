"""
boom-boom's own settings store, so the package needs no openpilot params (and no params_keys.h edit or rebuild).

This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

It answers the same calls as openpilot's Params that the package uses (get, get_bool, put, put_bool, remove), so
code that took ui_state.params takes this instead. Three kinds of key:
  - settings: one JSON file, settings.json, written whole and atomically on every change;
  - the drive history: its own file, history.json, written when the trip card shows;
  - requests between processes (the shift chime from the UI to soundd): a file each in a run directory that
    does not survive a reboot (/dev/shm on the device), so a stale request never fires at start-up.

Where: $BOOM_BOOM_DIR, else /data/boom_boom on the device, else ~/.comma/boom_boom. Readers in another process
(soundd) see changes within RELOAD_S. On first use, settings saved by an earlier build in openpilot params are
copied across once; that only works while those keys are still registered, as openpilot deletes the files of
unregistered keys at start-up.
"""
import json
import os
import tempfile
import time

SETTINGS_FILE = "settings.json"
HISTORY_FILE = "history.json"
RELOAD_S = 1.0

HISTORY = "BoomDriveHistory"
REQUESTS = ("ShiftChimeRequest",)

DEFAULTS: dict[str, bool | int] = {
  "SlowdownReason": False,
  "SteerLimitArc": False,
  "GForceMeter": False,
  "TripSummary": False,
  "TrafficBox": False,
  "LaneAwareness": False,
  "MiniMap": False,
  "ReverseCameraView": False,
  "TripRankStyle": 0,
  "ShiftLights": False,
  "ShiftChime": False,
  "ShiftRevLimit": 1,
  "ShiftLead": 1,
  "ShiftPoint": 0,
  "ShiftChimeVolume": 60,
}


def default_root() -> str:
  env = os.environ.get("BOOM_BOOM_DIR")
  if env:
    return env
  if os.path.isdir("/data") and os.access("/data", os.W_OK):
    return "/data/boom_boom"
  return os.path.join(os.path.expanduser("~"), ".comma", "boom_boom")


def default_run_dir(root: str) -> str:
  return "/dev/shm/boom_boom" if os.path.isdir("/dev/shm") else os.path.join(root, "run")


def _write_atomic(path: str, data) -> None:
  os.makedirs(os.path.dirname(path), exist_ok=True)
  fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp")
  try:
    with os.fdopen(fd, "w") as f:
      json.dump(data, f)
      f.flush()
      os.fsync(f.fileno())
    os.replace(tmp, path)
  except BaseException:
    if os.path.exists(tmp):
      os.unlink(tmp)
    raise


def _read_json(path: str):
  try:
    with open(path) as f:
      return json.load(f)
  except (OSError, ValueError):
    return None


def _coerce(key: str, value):
  """A stored value as the type its default has, or the default when it cannot be."""
  default = DEFAULTS[key]
  if isinstance(default, bool):
    return value if isinstance(value, bool) else default
  return value if isinstance(value, int) and not isinstance(value, bool) else default


class Store:
  def __init__(self, root: str | None = None, run_dir: str | None = None, legacy_params_dir: str | None = None):
    self.root = root or default_root()
    self.run_dir = run_dir or default_run_dir(self.root)
    self._legacy_dir = legacy_params_dir
    self._settings: dict = {}
    self._mtime: float | None = None
    self._checked = -1e9
    self._load(force=True)

  # ---- files ---------------------------------------------------------------------------------------------

  @property
  def settings_path(self) -> str:
    return os.path.join(self.root, SETTINGS_FILE)

  def _load(self, force: bool = False) -> None:
    now = time.monotonic()
    if not force and now - self._checked < RELOAD_S:
      return
    self._checked = now
    try:
      mtime = os.stat(self.settings_path).st_mtime
    except OSError:
      if self._mtime is None and force:
        self._migrate()
      return
    if force or mtime != self._mtime:
      data = _read_json(self.settings_path)
      if isinstance(data, dict):
        self._settings = {k: _coerce(k, v) for k, v in data.items() if k in DEFAULTS}
      self._mtime = mtime

  def _save(self) -> None:
    _write_atomic(self.settings_path, self._settings)
    try:
      self._mtime = os.stat(self.settings_path).st_mtime
    except OSError:
      pass

  def _migrate(self) -> None:
    """Copy settings an earlier build kept in openpilot params, once; write defaults when there are none."""
    legacy = self._legacy_dir if self._legacy_dir is not None else _legacy_params_dir()
    found = read_legacy(legacy) if legacy else {}
    history = found.pop(HISTORY, None)
    self._settings = found
    if history is not None and not os.path.exists(os.path.join(self.root, HISTORY_FILE)):
      _write_atomic(os.path.join(self.root, HISTORY_FILE), history)
    try:
      self._save()
    except OSError:
      pass  # a read-only place: run on defaults

  # ---- the Params-like interface -------------------------------------------------------------------------

  def get(self, key: str, return_default: bool = False):
    if key == HISTORY:
      return _read_json(os.path.join(self.root, HISTORY_FILE))
    if key in REQUESTS:
      return "1" if os.path.exists(os.path.join(self.run_dir, key)) else None
    self._load()
    if key in self._settings:
      return self._settings[key]
    return DEFAULTS.get(key) if return_default or key in DEFAULTS else None

  def get_bool(self, key: str) -> bool:
    return bool(self.get(key))

  def put(self, key: str, value) -> None:
    if key == HISTORY:
      _write_atomic(os.path.join(self.root, HISTORY_FILE), value)
      return
    if key in REQUESTS:
      os.makedirs(self.run_dir, exist_ok=True)
      with open(os.path.join(self.run_dir, key), "w") as f:
        f.write("1")
      return
    if key not in DEFAULTS:
      raise KeyError(f"boom-boom has no setting {key}")
    self._load(force=True)  # do not overwrite another process's change with a stale copy
    self._settings[key] = _coerce(key, value)
    self._save()

  def put_bool(self, key: str, value: bool) -> None:
    self.put(key, bool(value))

  def remove(self, key: str) -> None:
    if key in REQUESTS:
      try:
        os.unlink(os.path.join(self.run_dir, key))
      except FileNotFoundError:
        pass
    elif key in self._settings:
      del self._settings[key]
      self._save()


def _legacy_params_dir() -> str | None:
  try:
    from openpilot.common.params import Params
    return Params().get_param_path()
  except Exception:
    return None


def read_legacy(params_dir: str) -> dict:
  """Settings and history as an earlier build stored them, one file per key in openpilot's params folder."""
  out: dict = {}
  for key in (*DEFAULTS, HISTORY):
    try:
      with open(os.path.join(params_dir, key), "rb") as f:
        raw = f.read().decode().strip()
    except (OSError, UnicodeDecodeError):
      continue
    if key == HISTORY:
      try:
        value = json.loads(raw)
      except ValueError:
        continue
      if isinstance(value, list):
        out[key] = value
    elif isinstance(DEFAULTS[key], bool):
      out[key] = raw == "1"
    else:
      try:
        out[key] = int(raw)
      except ValueError:
        continue
  return out


_store: Store | None = None


def settings() -> Store:
  """The process's one store."""
  global _store
  if _store is None:
    _store = Store()
  return _store

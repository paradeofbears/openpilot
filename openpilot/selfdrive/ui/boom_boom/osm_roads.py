"""
Nearby roads from mapd's downloaded OpenStreetMap tiles, for the boom-boom mini-map.

This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

mapd (pfeiferj) keeps its offline data under <mapd_root>/offline/<lat2>/<lon2>/<minLat>_<minLon>_<maxLat>_<maxLon>:
one packed Cap'n Proto Offline message (mapd_offline.capnp) per 0.25 degree square, grouped in 2 degree folders,
each road a Way with its own bounding box and full node list. A dense city tile is ~8 MB and ~43k ways.

Converting a whole tile to arrays is the slow part (~1.5 s on a desktop), so nothing does: a tile's way
bounding boxes are read once into an array, and each query converts only the ways that overlap the box
around the car. Queries run on RoadLoader's background thread, never on the drawing loop. Read only.
"""
import math
import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field

import numpy as np

SUPPORTED_MAPD_VERSIONS = {"v1.12.0"}  # the format this reader was written against
AREA_DEG = 0.25
GROUP_DEG = 2
M_PER_DEG = 111_320.0
SIMPLIFY_M = 2.0
TILE_CACHE = 4
YIELD_EVERY = 300  # ways converted between yields, so the drawing thread gets the GIL back

# road kinds, most prominent first
MAJOR, ARTERIAL, MINOR, SERVICE = range(4)
MPH = 0.44704

_schema = None


def schema():
  global _schema
  if _schema is None:
    import capnp
    _schema = capnp.load(os.path.join(os.path.dirname(__file__), "mapd_offline.capnp"))
  return _schema


def tile_path(base: str, lat: float, lon: float) -> str:
  min_lat = math.floor(lat / AREA_DEG) * AREA_DEG
  min_lon = math.floor(lon / AREA_DEG) * AREA_DEG
  group_lat = math.floor(min_lat / GROUP_DEG) * GROUP_DEG
  group_lon = math.floor(min_lon / GROUP_DEG) * GROUP_DEG
  name = f"{min_lat:f}_{min_lon:f}_{min_lat + AREA_DEG:f}_{min_lon + AREA_DEG:f}"  # Go's %f: six decimals
  return os.path.join(base, str(group_lat), str(group_lon), name)


def road_kind(name: str, ref: str, max_speed: float, lanes: int) -> int:
  """mapd keeps no highway class; route numbers, speed and lanes stand in for it."""
  if ref or max_speed >= 55 * MPH:
    return MAJOR
  if lanes >= 3 or max_speed >= 40 * MPH:
    return ARTERIAL
  return MINOR if name else SERVICE


def to_local(lat: np.ndarray, lon: np.ndarray, lat0: float, lon0: float) -> np.ndarray:
  """Metres east and north of (lat0, lon0); flat-earth, fine over a few kilometres."""
  return np.c_[(lon - lon0) * M_PER_DEG * math.cos(math.radians(lat0)), (lat - lat0) * M_PER_DEG].astype(np.float32)


def simplify(p: np.ndarray, tol: float = SIMPLIFY_M) -> np.ndarray:
  """Douglas-Peucker, iterative so long roads cannot hit the recursion limit."""
  if len(p) < 3:
    return p
  keep = np.zeros(len(p), dtype=bool)
  keep[0] = keep[-1] = True
  stack = [(0, len(p) - 1)]
  while stack:
    i0, i1 = stack.pop()
    if i1 - i0 < 2:
      continue
    a, ab = p[i0], p[i1] - p[i0]
    rel = p[i0 + 1:i1] - a
    length = float(np.hypot(*ab))
    d = np.abs(ab[0] * rel[:, 1] - ab[1] * rel[:, 0]) / length if length > 0 else np.hypot(rel[:, 0], rel[:, 1])
    j = int(np.argmax(d))
    if d[j] > tol:
      k = i0 + 1 + j
      keep[k] = True
      stack += [(i0, k), (k, i1)]
  return p[keep]


@dataclass
class Road:
  kind: int
  name: str
  xy: np.ndarray  # (N, 2) float32 metres east/north of the RoadSet origin


@dataclass
class RoadSet:
  lat: float
  lon: float
  roads: list[Road] = field(default_factory=list)
  missing: bool = False  # no downloaded tile covers this spot
  load_ms: float = 0.0


class Tile:
  """One tile file: the parsed message and its ways' bounding boxes as one array."""

  def __init__(self, path: str):
    with open(path, "rb") as f:
      data = f.read()
    self.msg = schema().Offline.from_bytes_packed(data, traversal_limit_in_words=2**62)
    self.ways = self.msg.ways
    self.boxes = np.array([(w.minLat, w.minLon, w.maxLat, w.maxLon) for w in self.ways], dtype=np.float64).reshape(-1, 4)

  def overlapping(self, min_lat: float, min_lon: float, max_lat: float, max_lon: float) -> np.ndarray:
    b = self.boxes
    return np.nonzero((b[:, 0] <= max_lat) & (b[:, 2] >= min_lat) & (b[:, 1] <= max_lon) & (b[:, 3] >= min_lon))[0]


class RoadIndex:
  def __init__(self, base: str):
    self.base = base
    self._tiles: OrderedDict[str, Tile | None] = OrderedDict()

  def _tile(self, path: str) -> Tile | None:
    if path in self._tiles:
      self._tiles.move_to_end(path)
      return self._tiles[path]
    tile = Tile(path) if os.path.isfile(path) else None
    self._tiles[path] = tile
    while len(self._tiles) > TILE_CACHE:
      self._tiles.popitem(last=False)
    return tile

  def query(self, lat: float, lon: float, radius_m: float) -> RoadSet:
    t0 = time.monotonic()
    dlat = radius_m / M_PER_DEG
    dlon = radius_m / (M_PER_DEG * max(math.cos(math.radians(lat)), 0.01))
    box = (lat - dlat, lon - dlon, lat + dlat, lon + dlon)
    paths = dict.fromkeys(tile_path(self.base, la, lo) for la in (box[0], box[2]) for lo in (box[1], box[3]))
    out = RoadSet(lat, lon)
    tiles = [t for t in (self._tile(p) for p in paths) if t is not None]
    out.missing = not tiles
    seen: set[tuple] = set()
    converted = 0
    for tile in tiles:
      for i in tile.overlapping(*box):
        w = tile.ways[int(i)]
        nodes = w.nodes
        if len(nodes) < 2:
          continue
        first = nodes[0]
        key = (w.name, w.ref, len(nodes), round(first.latitude, 7), round(first.longitude, 7))
        if key in seen:  # ways near a tile edge are stored in both tiles
          continue
        seen.add(key)
        ll = np.array([(c.latitude, c.longitude) for c in nodes], dtype=np.float64)
        xy = simplify(to_local(ll[:, 0], ll[:, 1], lat, lon))
        out.roads.append(Road(road_kind(w.name, w.ref, w.maxSpeed, w.lanes), w.name, xy))
        converted += 1
        if converted % YIELD_EVERY == 0:
          time.sleep(0)
    out.roads.sort(key=lambda r: -r.kind)  # minor first, so major roads draw on top
    out.load_ms = (time.monotonic() - t0) * 1000
    return out


class RoadLoader:
  """Runs RoadIndex queries on a background thread; the drawing side only reads `latest`."""

  def __init__(self, base: str, radius_m: float = 1000.0, refresh_m: float = 300.0, retry_s: float = 10.0):
    self.index = RoadIndex(base)
    self.radius_m = radius_m
    self.refresh_m = refresh_m
    self.retry_s = retry_s
    self.latest: RoadSet | None = None
    self.error: str | None = None
    self._pending: tuple[float, float] | None = None
    self._busy = False
    self._failed_at = -1e9
    self._wake = threading.Event()
    self._thread: threading.Thread | None = None

  def needs(self, lat: float, lon: float) -> bool:
    if self.latest is None:
      return True
    dy = (lat - self.latest.lat) * M_PER_DEG
    dx = (lon - self.latest.lon) * M_PER_DEG * math.cos(math.radians(lat))
    return math.hypot(dx, dy) > self.refresh_m

  def request(self, lat: float, lon: float) -> None:
    if self._busy or not self.needs(lat, lon) or time.monotonic() - self._failed_at < self.retry_s:
      return
    self._pending = (lat, lon)
    self._busy = True
    if self._thread is None:
      self._thread = threading.Thread(target=self._run, name="boom-boom-roads", daemon=True)
      self._thread.start()
    self._wake.set()

  def _run(self) -> None:
    while True:
      self._wake.wait()
      self._wake.clear()
      pending, self._pending = self._pending, None
      if pending is not None:
        try:
          self.latest = self.index.query(pending[0], pending[1], self.radius_m)
          self.error = None
        except Exception as e:  # a tile being rewritten by mapd, a format change: try again later
          self.error = f"{type(e).__name__}: {e}"
          self._failed_at = time.monotonic()
      self._busy = False

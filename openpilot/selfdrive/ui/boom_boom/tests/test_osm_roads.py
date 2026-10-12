"""
This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import os
import tempfile
import time

import numpy as np

from openpilot.common.test import OpenpilotTestCase
from openpilot.selfdrive.ui.boom_boom.osm_roads import (
  ARTERIAL, MAJOR, MINOR, MPH, SERVICE, RoadIndex, RoadLoader, road_kind, schema, simplify, tile_path, to_local,
)

LAT0, LON0 = 32.80, -96.80  # inside the 32.75..33.0, -97.0..-96.75 tile


def write_tile(base, lat, lon, ways):
  """ways: list of (name, ref, maxSpeed m/s, lanes, [(lat, lon), ...]) written in mapd's layout."""
  path = tile_path(base, lat, lon)
  os.makedirs(os.path.dirname(path), exist_ok=True)
  msg = schema().Offline.new_message()
  lst = msg.init("ways", len(ways))
  for w, (name, ref, speed, lanes, pts) in zip(lst, ways, strict=True):
    w.name, w.ref, w.maxSpeed, w.lanes = name, ref, speed, lanes
    lats, lons = [p[0] for p in pts], [p[1] for p in pts]
    w.minLat, w.maxLat, w.minLon, w.maxLon = min(lats), max(lats), min(lons), max(lons)
    nodes = w.init("nodes", len(pts))
    for n, (la, lo) in zip(nodes, pts, strict=True):
      n.latitude, n.longitude = la, lo
  with open(path, "wb") as f:
    f.write(msg.to_bytes_packed())
  return path


def east(m):
  return float(m / (111_320.0 * np.cos(np.radians(LAT0))))


class TestTilePath(OpenpilotTestCase):
  def test_matches_mapds_names(self):
    # a real file name from a device's /data/media/0/osm/offline
    assert tile_path("/o", 32.80, -96.80) == os.path.join("/o", "32", "-98", "32.750000_-97.000000_33.000000_-96.750000")
    assert tile_path("/o", 29.6, -95.6).endswith(os.path.join("28", "-96", "29.500000_-95.750000_29.750000_-95.500000"))


class TestHelpers(OpenpilotTestCase):
  def test_road_kinds(self):
    assert road_kind("LBJ Freeway", "I 635", 0.0, 0) == MAJOR
    assert road_kind("Some Road", "", 60 * MPH, 0) == MAJOR
    assert road_kind("Big Avenue", "", 0.0, 4) == ARTERIAL
    assert road_kind("Main Street", "", 40 * MPH, 2) == ARTERIAL
    assert road_kind("Elm Street", "", 30 * MPH, 2) == MINOR
    assert road_kind("", "", 0.0, 0) == SERVICE

  def test_simplify_drops_collinear_points_keeps_corners(self):
    line = np.array([[0, 0], [10, 0.5], [20, 0], [30, 0], [30, 40]], dtype=np.float32)
    s = simplify(line, 2.0)
    assert len(s) == 3 and (s[0] == line[0]).all() and (s[-1] == line[-1]).all() and (s[1] == line[3]).all()

  def test_local_metres(self):
    xy = to_local(np.array([LAT0 + 0.001]), np.array([LON0 + east(100)]), LAT0, LON0)
    assert abs(xy[0, 0] - 100) < 0.5 and abs(xy[0, 1] - 111.3) < 0.5


class TestRoadIndex(OpenpilotTestCase):
  def setUp(self):
    self.dir = tempfile.mkdtemp()

  def test_query_keeps_nearby_roads_only(self):
    near = ("Elm Street", "", 13.4, 2, [(LAT0, LON0 - east(200)), (LAT0, LON0 + east(200))])
    far = ("Far Road", "", 13.4, 2, [(LAT0 + 0.1, LON0), (LAT0 + 0.1, LON0 + 0.01)])
    write_tile(self.dir, LAT0, LON0, [near, far])
    rs = RoadIndex(self.dir).query(LAT0, LON0, 1000.0)
    assert not rs.missing and [r.name for r in rs.roads] == ["Elm Street"]
    xy = rs.roads[0].xy
    assert abs(xy[0, 0] + 200) < 1 and abs(xy[-1, 0] - 200) < 1 and abs(xy[0, 1]) < 1

  def test_a_road_in_two_tiles_is_drawn_once(self):
    # a road crossing the 32.75 tile edge is stored in both tiles, as mapd does with its overlap margin
    edge = 32.75
    road = ("Edge Road", "", 13.4, 2, [(edge - 0.002, LON0), (edge + 0.002, LON0)])
    write_tile(self.dir, edge + 0.01, LON0, [road])
    write_tile(self.dir, edge - 0.01, LON0, [road])
    rs = RoadIndex(self.dir).query(edge, LON0, 500.0)
    assert len(rs.roads) == 1

  def test_majors_draw_last(self):
    ways = [("Highway", "I 35E", 0.0, 0, [(LAT0, LON0), (LAT0 + 0.001, LON0)]),
            ("", "", 0.0, 0, [(LAT0, LON0 + east(50)), (LAT0 + 0.001, LON0 + east(50))])]
    write_tile(self.dir, LAT0, LON0, ways)
    rs = RoadIndex(self.dir).query(LAT0, LON0, 500.0)
    assert [r.kind for r in rs.roads] == [SERVICE, MAJOR]

  def test_no_tile_here(self):
    rs = RoadIndex(self.dir).query(LAT0, LON0, 500.0)
    assert rs.missing and not rs.roads


class TestRoadLoader(OpenpilotTestCase):
  def setUp(self):
    self.dir = tempfile.mkdtemp()

  def wait(self, loader, timeout=5.0):
    t0 = time.monotonic()
    while loader._busy and time.monotonic() - t0 < timeout:
      time.sleep(0.01)
    assert not loader._busy

  def test_loads_in_the_background_and_refreshes_after_moving(self):
    write_tile(self.dir, LAT0, LON0, [("Elm Street", "", 13.4, 2, [(LAT0, LON0), (LAT0 + 0.001, LON0)])])
    loader = RoadLoader(self.dir, radius_m=1000.0, refresh_m=300.0)
    loader.request(LAT0, LON0)
    self.wait(loader)
    assert loader.latest is not None and len(loader.latest.roads) == 1 and loader.error is None
    assert not loader.needs(LAT0 + 0.001, LON0)  # 111 m away: keep the current set
    assert loader.needs(LAT0 + 0.004, LON0)      # 445 m away: refresh

  def test_a_corrupt_tile_is_an_error_not_a_crash(self):
    path = tile_path(self.dir, LAT0, LON0)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
      f.write(b"\x00\xff" * 64)  # half-written while mapd updates it
    loader = RoadLoader(self.dir, retry_s=60.0)
    loader.request(LAT0, LON0)
    self.wait(loader)
    assert loader.latest is None and loader.error
    loader.request(LAT0, LON0)  # inside the retry window: not tried again yet
    assert not loader._busy

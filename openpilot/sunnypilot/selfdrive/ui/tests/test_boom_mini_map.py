"""
This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import math

import numpy as np

from openpilot.cereal import log
from openpilot.common.test import OpenpilotTestCase
from openpilot.selfdrive.ui.sunnypilot.onroad.boom_boom.mini_map import (
  Geometry, MiniMap, Status, clip_segments, location, to_screen,
)
from openpilot.selfdrive.ui.sunnypilot.onroad.boom_boom.osm_roads import MAJOR, MINOR, Road, RoadSet

LAT0, LON0 = 32.80, -96.80


def llk(valid=True, gps=True, heading=0.0, lat=LAT0, lon=LON0):
  return (log.Event.new_message(liveLocationKalman={
    "status": "valid" if valid else "uncalibrated", "gpsOK": gps,
    "positionGeodetic": {"value": [lat, lon, 100.0], "valid": True},
    "calibratedOrientationNED": {"value": [0.0, 0.0, heading], "valid": True},
  }).as_reader()).liveLocationKalman


def road_set(*roads, missing=False):
  return RoadSet(LAT0, LON0, [Road(kind, name, np.array(pts, dtype=np.float32)) for kind, name, pts in roads], missing)


class TestLocation(OpenpilotTestCase):
  def test_valid(self):
    lat, lon, heading = location(llk(heading=1.0))
    assert (round(lat, 6), round(lon, 6), round(heading, 6)) == (LAT0, LON0, 1.0)

  def test_not_trusted(self):
    assert location(None) is None
    assert location(llk(valid=False)) is None
    assert location(llk(gps=False)) is None


class TestScreen(OpenpilotTestCase):
  def test_heading_up(self):
    ahead_north = to_screen(np.array([[0.0, 100.0]]), 0.0, 1.0)[0]
    assert abs(ahead_north[0]) < 1e-4 and ahead_north[1] == -100  # facing north, north is up
    # facing east: east is up, north is to the left
    east, north = to_screen(np.array([[100.0, 0.0], [0.0, 100.0]]), math.pi / 2, 1.0)
    assert east[1] < -99 and abs(east[0]) < 1e-3
    assert north[0] < -99 and abs(north[1]) < 1e-3


class TestClip(OpenpilotTestCase):
  def test_crossing_inside_outside(self):
    a = np.array([[-200.0, 0.0], [-50.0, 0.0], [-200.0, 150.0]], dtype=np.float32)
    b = np.array([[200.0, 0.0], [50.0, 0.0], [200.0, 150.0]], dtype=np.float32)
    keep, t0, t1, d = clip_segments(a, b, 100.0)
    assert keep.tolist() == [True, True, False]
    start, end = a[0] + t0[0] * d[0], a[0] + t1[0] * d[0]
    assert abs(start[0] + 100) < 1e-3 and abs(end[0] - 100) < 1e-3  # clipped at the rim
    assert t0[1] == 0.0 and t1[1] == 1.0                            # wholly inside: untouched


class TestGeometry(OpenpilotTestCase):
  def test_one_run_per_continuous_stretch(self):
    straight = (MAJOR, "Highway", [[-500, 0], [0, 0], [500, 0]])
    # leaves the 100 px circle and comes back: two visible runs
    loop = (MINOR, "Loop", [[-50, 50], [-50, 500], [50, 500], [50, 50]])
    g = Geometry(road_set(straight, loop))
    runs = list(g.runs(np.array([0.0, 0.0], np.float32), 0.0, 1.0, 100.0))
    by_road = {}
    for i, pts in runs:
      by_road.setdefault(i, []).append(pts)
    assert len(by_road[0]) == 1 and len(by_road[0][0]) == 3  # rim, centre point, rim
    assert len(by_road[1]) == 2
    for pts_list in by_road.values():
      for pts in pts_list:
        assert (np.hypot(pts[:, 0], pts[:, 1]) <= 100.0 + 1e-3).all() and pts.dtype == np.float32

  def test_empty(self):
    assert list(Geometry(road_set()).runs(np.zeros(2, np.float32), 0.0, 1.0, 100.0)) == []


class TestStatus(OpenpilotTestCase):
  def update(self, m, loc=None, roads=None, error=None, fmt=True):
    m.update(loc, roads, error, fmt, "Main Street", 10.0)
    return m.status

  def test_states(self):
    roads = road_set((MINOR, "Main Street", [[0, 0], [100, 0]]))
    m = MiniMap()
    assert self.update(m, llk(), roads, fmt=False) == Status.FORMAT
    assert self.update(m, None, roads) == Status.NO_GPS
    assert self.update(MiniMap(), llk(), None) == Status.LOADING
    assert self.update(MiniMap(), llk(), None, error="KjException") == Status.NO_MAP
    assert self.update(MiniMap(), llk(), road_set(missing=True)) == Status.NO_MAP
    assert self.update(MiniMap(), llk(), roads) == Status.OK

  def test_keeps_last_position_when_gps_drops(self):
    roads = road_set((MINOR, "Main Street", [[0, 0], [100, 0]]))
    m = MiniMap()
    self.update(m, llk(), roads)
    self.update(m, None, roads)
    assert m.status == Status.NO_GPS and m.where is not None  # drawn dimmed, not blank

  def test_heading_eases_the_short_way_round(self):
    m = MiniMap()
    m.update(llk(heading=math.radians(350)), None, None, True, "", 10.0)
    m.update(llk(heading=math.radians(10)), None, None, True, "", 10.0)
    h = math.degrees(m.where[2]) % 360
    assert h > 350 or h < 10  # moved across north, not back round through south

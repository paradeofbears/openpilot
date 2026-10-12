"""
Mini-map: a small round heading-up map in the bottom-left corner, after Grand Theft Auto's radar.

This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

Roads come from mapd's downloaded OpenStreetMap tiles through osm_roads.RoadLoader (background thread);
position and heading from sunnypilot's liveLocationKalman (GPS fused with the car's motion, 20 Hz). The
road the car is on (liveMapDataSP.roadName) is highlighted. Zoom widens with speed. Roads are clipped to
the circle in numpy and each continuous run is one raylib polyline call, straight from the array.

It says so instead of guessing: NO GPS (location not valid, the last roads dimmed), LOADING, NO MAP DATA
(no downloaded tile here), MAP FORMAT (a mapd version this reader was not written for). Display only.
"""
import math
from enum import Enum

import numpy as np
import pyray as rl

from openpilot.common.filter_simple import FirstOrderFilter
from .osm_roads import ARTERIAL, MAJOR, MINOR, SERVICE, RoadSet, to_local
from openpilot.system.ui.lib.application import FontWeight, gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.lib.text_measure import measure_text_cached

RADIUS = 150             # px
MIN_RADIUS = 110         # smaller than this and there is no room: not drawn
MARGIN = 50
DM_CLEAR = 290           # px above the bottom kept for the driver monitoring icon
TOP_CLEAR = 450          # px below the top kept for the set speed and speed-limit signs
ZOOM_BP = [0.0, 15.0, 30.0]       # m/s
ZOOM_M = [200.0, 350.0, 600.0]    # metres from the centre to the rim

BG = rl.Color(16, 22, 30, 215)
RIM = rl.Color(255, 255, 255, 70)
ROAD_STYLE = {  # kind: (width px, colour)
  SERVICE: (2.5, rl.Color(95, 100, 108, 255)),
  MINOR: (4.0, rl.Color(145, 150, 158, 255)),
  ARTERIAL: (6.0, rl.Color(195, 198, 204, 255)),
  MAJOR: (9.0, rl.Color(235, 235, 238, 255)),
}
CURRENT = rl.Color(128, 216, 166, 255)
ARROW = rl.Color(255, 255, 255, 255)
ARROW_EDGE = rl.Color(0, 0, 0, 200)
TEXT = rl.Color(255, 255, 255, 170)


class Status(Enum):
  OK = ""
  NO_GPS = "NO GPS"
  LOADING = "LOADING"
  NO_MAP = "NO MAP DATA"
  FORMAT = "MAP FORMAT"


def location(llk) -> tuple[float, float, float] | None:
  """(lat, lon, heading rad clockwise from north) from liveLocationKalman, or None when not trustworthy."""
  if llk is None or str(llk.status) != "valid" or not llk.positionGeodetic.valid or not llk.gpsOK:
    return None
  pos = llk.positionGeodetic.value
  ori = llk.calibratedOrientationNED if llk.calibratedOrientationNED.valid else llk.orientationNED
  if len(pos) < 2 or len(ori.value) < 3 or not ori.valid:
    return None
  return float(pos[0]), float(pos[1]), float(ori.value[2])


def to_screen(xy: np.ndarray, heading: float, scale: float) -> np.ndarray:
  """Local metres (east, north) relative to the car to screen pixels relative to the centre, heading up."""
  s, c = math.sin(heading), math.cos(heading)
  fwd = xy[:, 0] * s + xy[:, 1] * c
  right = xy[:, 0] * c - xy[:, 1] * s
  return np.c_[right * scale, -fwd * scale].astype(np.float32)


def clip_segments(a: np.ndarray, b: np.ndarray, r: float) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
  """Clip segments a->b to a circle of radius r at the origin. Returns (keep mask, t0, t1, d) with the kept part
  running from a + t0*d to a + t1*d."""
  d = b - a
  qa = np.einsum("ij,ij->i", d, d)
  qb = 2 * np.einsum("ij,ij->i", a, d)
  qc = np.einsum("ij,ij->i", a, a) - r * r
  disc = qb * qb - 4 * qa * qc
  ok = (disc > 0) & (qa > 1e-9)
  root = np.sqrt(np.where(ok, disc, 0.0))
  den = np.where(ok, 2 * qa, 1.0)
  t0 = np.clip((-qb - root) / den, 0.0, 1.0)
  t1 = np.clip((-qb + root) / den, 0.0, 1.0)
  return ok & (t1 - t0 > 1e-6), t0, t1, d


class Geometry:
  """A RoadSet flattened into arrays once, so each frame is a handful of numpy operations."""

  def __init__(self, rs: RoadSet):
    self.rs = rs
    pts, seg_a, seg_road = [], [], []
    n = 0
    for i, road in enumerate(rs.roads):
      k = len(road.xy)
      pts.append(road.xy)
      seg_a.append(np.arange(n, n + k - 1))
      seg_road.append(np.full(k - 1, i))
      n += k
    self.points = np.vstack(pts).astype(np.float32) if pts else np.zeros((0, 2), np.float32)
    self.seg_a = np.concatenate(seg_a) if seg_a else np.zeros(0, int)
    self.seg_road = np.concatenate(seg_road) if seg_road else np.zeros(0, int)
    self.kinds = np.array([r.kind for r in rs.roads], dtype=int)
    self.names = [r.name for r in rs.roads]

  def runs(self, car_xy: np.ndarray, heading: float, scale: float, r: float):
    """Yield (road index, Nx2 float32 points relative to the centre) for each continuous visible run."""
    if not len(self.seg_a):
      return
    p = to_screen(self.points - car_xy, heading, scale)
    a, b = p[self.seg_a], p[self.seg_a + 1]
    keep, t0, t1, d = clip_segments(a, b, r)
    idx = np.nonzero(keep)[0]
    if not len(idx):
      return
    t0, t1, d, a = t0[idx], t1[idx], d[idx], a[idx]
    start = a + t0[:, None] * d
    end = a + t1[:, None] * d
    road = self.seg_road[idx]
    # a run continues while the next kept segment is the next one of the same road and neither was clipped there
    cont = (road[1:] == road[:-1]) & (idx[1:] == idx[:-1] + 1) & (t1[:-1] >= 1.0) & (t0[1:] <= 0.0)
    breaks = np.nonzero(~cont)[0] + 1
    for s, e in zip(np.r_[0, breaks], np.r_[breaks, len(idx)], strict=True):
      yield int(road[s]), np.ascontiguousarray(np.vstack([start[s:s + 1], end[s:e]]), dtype=np.float32)


class MiniMap:
  def __init__(self):
    self._geometry: Geometry | None = None
    self._zoom = FirstOrderFilter(ZOOM_M[0], 1.0, 1 / gui_app.target_fps)
    self._heading: float | None = None
    self.where: tuple[float, float, float] | None = None
    self.status = Status.LOADING
    self.road_name = ""

  def reset(self) -> None:
    self._geometry = None
    self._heading = None
    self.where = None
    self.status = Status.LOADING

  def update(self, llk, roads: RoadSet | None, loader_error: str | None, format_ok: bool, road_name: str,
             v_ego: float) -> None:
    self._zoom.update(float(np.interp(v_ego, ZOOM_BP, ZOOM_M)))
    self.road_name = road_name
    if roads is not None and (self._geometry is None or self._geometry.rs is not roads):
      self._geometry = Geometry(roads)
    where = location(llk)
    if where is not None:
      lat, lon, heading = where
      if self._heading is None:
        self._heading = heading
      else:  # ease toward the new heading the short way round
        diff = (heading - self._heading + math.pi) % (2 * math.pi) - math.pi
        self._heading += 0.3 * diff
      self.where = (lat, lon, self._heading)

    if not format_ok:
      self.status = Status.FORMAT
    elif where is None:
      self.status = Status.NO_GPS
    elif roads is not None and roads.missing:
      self.status = Status.NO_MAP
    elif self._geometry is None:
      self.status = Status.LOADING if loader_error is None else Status.NO_MAP
    else:
      self.status = Status.OK

  def render(self, rect: rl.Rectangle, bottom_clear: float) -> None:
    r = RADIUS
    cy = rect.y + rect.height - bottom_clear - r
    top_room = cy - (rect.y + TOP_CLEAR)
    if top_room < r:
      r = top_room
      cy = rect.y + rect.height - bottom_clear - r
    if r < MIN_RADIUS:
      return
    cx = rect.x + MARGIN + r
    centre = rl.Vector2(cx, cy)
    rl.draw_circle_v(centre, r + 6, BG)

    drawn = self._geometry is not None and self.where is not None and self.status in (Status.OK, Status.NO_GPS)
    if drawn:
      dim = 0.35 if self.status == Status.NO_GPS else 1.0
      self._draw_roads(cx, cy, r, dim)
      self._draw_north(cx, cy, r, dim)
    rl.draw_ring(centre, r + 2, r + 6, 0, 360, 96, RIM)
    self._draw_arrow(cx, cy, dim=0.35 if self.status != Status.OK else 1.0)
    if self.status != Status.OK:
      font = gui_app.font(FontWeight.SEMI_BOLD)
      text = tr(self.status.value)
      size = measure_text_cached(font, text, 30)
      rl.draw_text_ex(font, text, rl.Vector2(cx - size.x / 2, cy + 34), 30, 0, TEXT)

  def _draw_roads(self, cx: float, cy: float, r: float, dim: float) -> None:
    g = self._geometry
    lat, lon, heading = self.where
    car = to_local(np.array([lat]), np.array([lon]), g.rs.lat, g.rs.lon)[0]
    scale = r / self._zoom.x
    runs = list(g.runs(car, heading, scale, r))
    offset = np.array([cx, cy], dtype=np.float32)
    current = self.road_name
    for kind in (SERVICE, MINOR, ARTERIAL, MAJOR):  # most prominent last
      width, color = ROAD_STYLE[kind]
      for i, pts in runs:
        if g.kinds[i] != kind:
          continue
        on_it = bool(current) and g.names[i] == current
        _polyline(pts + offset, width + (2 if on_it else 0), _fade(CURRENT if on_it else color, dim))

  def _draw_north(self, cx: float, cy: float, r: float, dim: float) -> None:
    heading = self.where[2]
    nx, ny = -math.sin(heading), -math.cos(heading)  # north's direction on screen, heading up
    font = gui_app.font(FontWeight.BOLD)
    size = measure_text_cached(font, "N", 30)
    px, py = cx + nx * (r - 4), cy + ny * (r - 4)
    rl.draw_circle_v(rl.Vector2(px, py), 19, _fade(BG, 1.0))
    rl.draw_text_ex(font, "N", rl.Vector2(px - size.x / 2, py - size.y / 2), 30, 0, _fade(ARROW, dim))

  @staticmethod
  def _draw_arrow(cx: float, cy: float, dim: float) -> None:
    """Our car: an arrowhead pointing up (the heading), a dark outline under a white fill."""
    for g, color in ((4, ARROW_EDGE), (0, _fade(ARROW, dim))):
      tip = rl.Vector2(cx, cy - 22 - g)
      left = rl.Vector2(cx - 15 - g, cy + 16 + g)
      notch = rl.Vector2(cx, cy + 8 + g)
      right = rl.Vector2(cx + 15 + g, cy + 16 + g)
      rl.draw_triangle(tip, left, notch, color)  # raylib wants counter-clockwise on screen
      rl.draw_triangle(tip, notch, right, color)


def _polyline(pts: np.ndarray, width: float, color: rl.Color) -> None:
  pts = np.ascontiguousarray(pts, dtype=np.float32)
  rl.draw_spline_linear(rl.ffi.cast("Vector2 *", rl.ffi.from_buffer(pts)), len(pts), width, color)


def _fade(c: rl.Color, a: float) -> rl.Color:
  return rl.Color(c.r, c.g, c.b, int(c.a * a))

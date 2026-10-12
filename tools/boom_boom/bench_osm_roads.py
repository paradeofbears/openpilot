#!/usr/bin/env python3
"""
Time the boom-boom mini-map's road loader on real mapd tiles. Read only.

On the comma (from /data/openpilot):
  python tools/boom_boom/bench_osm_roads.py                 # the largest downloaded tile, at its densest spot
  python tools/boom_boom/bench_osm_roads.py --lat 32.78 --lon -96.80
On a PC, point --dir at a folder holding copied tiles in mapd's <lat2>/<lon2>/<file> layout, or pass --tile.

Reports the one-off cost of opening a tile (parse plus the bounding-box array) and the per-refresh cost
of a 1 km query, which is what the mini-map does every few hundred metres on a background thread.
"""
import argparse
import os
import platform
import sys
import time

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from openpilot.selfdrive.ui.sunnypilot.onroad.boom_boom.osm_roads import RoadIndex, Tile

DEFAULT_DIR = "/data/media/0/osm/offline"


def largest_tile(base: str) -> str:
  best, size = None, -1
  for root, _, files in os.walk(base):
    for f in files:
      p = os.path.join(root, f)
      s = os.path.getsize(p)
      if s > size:
        best, size = p, s
  if best is None:
    sys.exit(f"no tiles under {base}")
  return best


def main() -> None:
  ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  ap.add_argument("--dir", default=DEFAULT_DIR)
  ap.add_argument("--tile", help="a single tile file; its folder layout is not needed")
  ap.add_argument("--lat", type=float)
  ap.add_argument("--lon", type=float)
  ap.add_argument("--radius", type=float, default=1000.0)
  args = ap.parse_args()

  path = args.tile or largest_tile(args.dir)
  print(f"{platform.machine()} python {platform.python_version()}")
  print(f"tile {path} ({os.path.getsize(path) / 1e6:.1f} MB)")

  t0 = time.perf_counter()
  tile = Tile(path)
  print(f"open tile: {(time.perf_counter() - t0) * 1000:.0f} ms for {len(tile.boxes)} ways (once per tile)")

  if args.lat is None or args.lon is None:
    centres = np.c_[(tile.boxes[:, 0] + tile.boxes[:, 2]) / 2, (tile.boxes[:, 1] + tile.boxes[:, 3]) / 2]
    h, ey, ex = np.histogram2d(centres[:, 0], centres[:, 1], bins=50)
    iy, ix = np.unravel_index(np.argmax(h), h.shape)
    args.lat, args.lon = (ey[iy] + ey[iy + 1]) / 2, (ex[ix] + ex[ix + 1]) / 2
    print(f"densest spot {args.lat:.4f},{args.lon:.4f}")

  index = RoadIndex(os.path.dirname(os.path.dirname(os.path.dirname(path))))
  index._tiles[path] = tile  # reuse the tile opened above, wherever it lives
  if args.tile:
    import openpilot.selfdrive.ui.sunnypilot.onroad.boom_boom.osm_roads as osm
    osm.tile_path = lambda base, lat, lon: path  # a lone file: every lookup is this tile
  for run in ("first", "repeat"):
    rs = index.query(args.lat, args.lon, args.radius)
    segs = sum(len(r.xy) - 1 for r in rs.roads)
    near = sum(int((np.hypot(r.xy[:, 0], r.xy[:, 1]) < 400).sum()) for r in rs.roads)
    counts = f"{len(rs.roads)} roads, {segs} segments, {near} points within 400 m, missing={rs.missing}"
    print(f"{run} {args.radius:.0f} m query: {rs.load_ms:.0f} ms, {counts}")

  try:
    import resource
    print(f"peak memory {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024:.0f} MB")
  except ImportError:
    pass


if __name__ == "__main__":
  main()

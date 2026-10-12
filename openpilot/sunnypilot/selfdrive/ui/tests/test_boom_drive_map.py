"""
This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import numpy as np
import pyray as rl

from openpilot.common.test import OpenpilotTestCase
from openpilot.selfdrive.ui.sunnypilot.onroad.boom_boom.drive_map import (
  MAX_POINTS, MIN_SPAN_M, STEP_M, DriveTrace, fit, meters,
)
from openpilot.selfdrive.ui.sunnypilot.onroad.boom_boom.scoring import SPIRITED, DriveScore, Extra

DT = 0.05
LAT0, LON0 = 32.78, -96.80
DEG_PER_M = 1 / 111_195.0  # latitude degrees per metre


def drive_north(trace, seconds, v=20.0, start_m=0.0, driver=True, fix=True):
  for i in range(round(seconds / DT)):
    north = start_m + v * DT * (i + 1)
    trace.update(DT, fix, LAT0 + north * DEG_PER_M, LON0, driver)
  return start_m + v * seconds


class TestTrace(OpenpilotTestCase):
  def test_samples_by_distance_and_keeps_who_drove(self):
    t = DriveTrace()
    m = drive_north(t, 10.0)                   # 200 m by the driver
    drive_north(t, 5.0, start_m=m, driver=False)  # 100 m by openpilot
    assert abs(len(t.points) - 300 / STEP_M) <= 2
    assert t.points[0][2] and not t.points[-1][2]
    assert t.drawable and abs(t.span() - 300) < STEP_M + 1

  def test_too_small_or_no_fix_is_not_a_map(self):
    t = DriveTrace()
    drive_north(t, 5.0, v=10.0)  # 50 m
    assert not t.drawable and MIN_SPAN_M > 50
    blind = DriveTrace()
    drive_north(blind, 60.0, fix=False)
    assert blind.points == [] and not blind.drawable

  def test_memory_stays_bounded(self):
    t = DriveTrace()
    drive_north(t, (MAX_POINTS + 50) * STEP_M / 40.0, v=40.0)
    assert len(t.points) <= MAX_POINTS

  def test_marks_land_where_the_car_was(self):
    t = DriveTrace()
    drive_north(t, 10.0)  # at 200 m now
    t.mark("bend", True, ago=5.0)  # 5 s back at 20 m/s: 100 m
    e, n = meters(LAT0, LON0, t.marks[0].lat, t.marks[0].lon)
    assert abs(n - 100.0) < 2.0 and abs(e) < 1e-6
    t.mark("stop", False, ago=60.0)  # older than anything kept: dropped rather than misplaced
    assert len(t.marks) == 1

  def test_fit_keeps_the_aspect_and_stays_in_the_box(self):
    xy = np.array([[0.0, 0.0], [100.0, 400.0]])
    box = rl.Rectangle(10, 20, 400, 600)
    scale, x0, y0 = fit(xy, box, pad=0)
    sx, sy = x0 + xy[:, 0] * scale, y0 - xy[:, 1] * scale
    assert scale == 1.5  # limited by the height: 400 m into 600 px
    assert sx.min() >= 10 and sx.max() <= 410 and sy.min() >= 20 and sy.max() <= 620
    assert sy[1] < sy[0]  # north is up


class TestScoreMarks(OpenpilotTestCase):
  def test_a_clean_bend_is_marked_at_its_peak(self):
    s = DriveScore(flavour=SPIRITED)
    for g in (0.25, 0.3, 0.35, 0.3, 0.25, 0.25, 0.25):
      for _ in range(6):
        s.update(DT, 20.0, 0.0, True, False, 100.0, Extra(lat_g=g))
    for _ in range(4):
      s.update(DT, 20.0, 0.0, True, False, 100.0, Extra(lat_g=0.0))
    kind, clean, ago = s.marks[-1]
    assert (kind, clean) == ("bend", True) and abs(ago - 4 * 6 * DT) < 3 * DT  # four steps back from the exit

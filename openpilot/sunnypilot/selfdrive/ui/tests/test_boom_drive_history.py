"""
This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
from openpilot.common.test import OpenpilotTestCase
from openpilot.selfdrive.ui.sunnypilot.onroad.boom_boom.drive_history import (
  HISTORY, MAX_DRIVES, DriveHistory, line, record, summary,
)
from openpilot.selfdrive.ui.sunnypilot.onroad.boom_boom.scoring import CHAOS, SAFETY, DriveScore


def d(i, rank="A", points=1000, flavour=SAFETY, best_0_30=None):
  return {"id": i, "flavour": flavour, "rank": rank, "score": 85.0, "points": points, "km": 5.0, "best_0_30": best_0_30}


class FakeParams:
  def __init__(self, value=None):
    self.store = {} if value is None else {HISTORY: value}

  def get(self, key):
    return self.store.get(key)

  def put(self, key, value):
    self.store[key] = value


class TestHistory(OpenpilotTestCase):
  def test_record_replaces_the_same_drive_and_trims(self):
    drives = [d(i) for i in range(MAX_DRIVES)]
    drives = record(drives, d(MAX_DRIVES - 1, points=5))
    assert len(drives) == MAX_DRIVES and drives[-1]["points"] == 5
    drives = record(drives, d(100))
    assert len(drives) == MAX_DRIVES and drives[0]["id"] == 1 and drives[-1]["id"] == 100

  def test_bests_and_streak_count_only_the_same_style(self):
    drives = [d(1, "B"), d(2, "A", 3000), d(3, "S", 2000), d(4, "D", 9000, flavour=CHAOS)]
    s = summary(drives, d(5, "A", 4000))
    assert s == {"best_points": 3000, "new_best": True, "new_launch_best": False, "streak": 3}
    assert line(s) == "NEW BEST  |  3 in a row A+"
    s = summary(drives, d(5, "C", 100))
    assert s["streak"] == 0 and line(s) == "best 3,000"
    assert line(summary([], d(1))) == ""  # the first drive has nothing to beat

  def test_launch_personal_best(self):
    drives = [d(1, best_0_30=6.1), d(2, best_0_30=5.8)]
    assert summary(drives, d(3, best_0_30=5.5))["new_launch_best"]
    assert not summary(drives, d(3, best_0_30=5.9))["new_launch_best"]

  def test_save(self):
    params = FakeParams([d(1, "A", 500), "junk"])
    h = DriveHistory()
    h.save(params, DriveScore(flavour=SAFETY))  # nothing driven yet: not remembered
    assert len(params.store[HISTORY]) == 2
    h.save(params, DriveScore(flavour=SAFETY, driver_distance=2000.0, driver_time=100.0, smooth_time=100.0, points=900))
    saved = params.store[HISTORY]
    assert len(saved) == 2 and saved[-1]["points"] == 900 and h.line.startswith("NEW BEST")
    h.save(params, DriveScore(flavour=SAFETY, driver_distance=3000.0, driver_time=150.0, smooth_time=150.0, points=950))
    assert len(params.store[HISTORY]) == 2 and params.store[HISTORY][-1]["points"] == 950  # the same drive, updated

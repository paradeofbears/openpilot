"""
This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import json
import os
import tempfile

from openpilot.common.test import OpenpilotTestCase
from openpilot.selfdrive.ui.boom_boom import store as st
from openpilot.selfdrive.ui.boom_boom.settings_panel import selected_index, store_choice


class StoreCase(OpenpilotTestCase):
  def setUp(self):
    self._tmp = tempfile.TemporaryDirectory()
    self.root = os.path.join(self._tmp.name, "boom_boom")
    self.legacy = os.path.join(self._tmp.name, "params")
    os.makedirs(self.legacy)

  def tearDown(self):
    self._tmp.cleanup()

  def make(self):
    return st.Store(self.root, os.path.join(self._tmp.name, "run"), legacy_params_dir=self.legacy)


class TestStore(StoreCase):
  def test_defaults_then_persists_across_processes(self):
    a = self.make()
    assert a.get_bool("ShiftLights") is False and a.get("ShiftChimeVolume") == 60
    a.put_bool("ShiftLights", True)
    a.put("TripRankStyle", 2)
    b = self.make()  # another process
    assert b.get_bool("ShiftLights") and b.get("TripRankStyle") == 2
    with open(a.settings_path) as f:
      assert json.load(f)["TripRankStyle"] == 2

  def test_a_reader_sees_another_process_change(self):
    reader, writer = self.make(), self.make()
    writer.put_bool("GForceMeter", True)
    reader._checked = -1e9  # as if RELOAD_S had passed
    os.utime(writer.settings_path, (1, 1))  # a different mtime, whatever the filesystem's resolution
    assert reader.get_bool("GForceMeter")

  def test_writing_does_not_undo_another_process(self):
    a, b = self.make(), self.make()
    a.put_bool("MiniMap", True)
    b.put_bool("TrafficBox", True)  # b's copy predates a's write
    c = self.make()
    assert c.get_bool("MiniMap") and c.get_bool("TrafficBox")

  def test_bad_values_fall_back_to_defaults(self):
    os.makedirs(self.root)
    with open(os.path.join(self.root, st.SETTINGS_FILE), "w") as f:
      json.dump({"ShiftLights": "yes", "ShiftChimeVolume": True, "Unknown": 1, "TripRankStyle": 1}, f)
    s = self.make()
    assert s.get_bool("ShiftLights") is False and s.get("ShiftChimeVolume") == 60 and s.get("TripRankStyle") == 1
    try:
      s.put("NotASetting", 1)
      raise AssertionError("unknown keys are refused")
    except KeyError:
      pass

  def test_requests_are_files_that_come_and_go(self):
    s = self.make()
    assert s.get("ShiftChimeRequest") is None
    s.put("ShiftChimeRequest", "1")
    assert self.make().get("ShiftChimeRequest") == "1"  # soundd's side
    s.remove("ShiftChimeRequest")
    assert s.get("ShiftChimeRequest") is None

  def test_history_has_its_own_file(self):
    s = self.make()
    assert s.get(st.HISTORY) is None
    s.put(st.HISTORY, [{"id": "a", "rank": "B"}])
    assert self.make().get(st.HISTORY) == [{"id": "a", "rank": "B"}]


class TestMigration(StoreCase):
  def legacy_param(self, key, raw):
    with open(os.path.join(self.legacy, key), "w") as f:
      f.write(raw)

  def test_earlier_settings_and_history_come_across_once(self):
    self.legacy_param("ShiftLights", "1")
    self.legacy_param("MiniMap", "0")
    self.legacy_param("TripRankStyle", "2")
    self.legacy_param("ShiftChimeVolume", "70")
    self.legacy_param("ShiftPoint", "junk")
    self.legacy_param(st.HISTORY, json.dumps([{"id": "x", "rank": "A"}]))
    s = self.make()
    assert s.get_bool("ShiftLights") and not s.get_bool("MiniMap")
    assert s.get("TripRankStyle") == 2 and s.get("ShiftChimeVolume") == 70 and s.get("ShiftPoint") == 0
    assert s.get(st.HISTORY) == [{"id": "x", "rank": "A"}]
    s.put_bool("ShiftLights", False)
    self.legacy_param("ShiftLights", "1")  # the old key changing later does not override the new store
    assert not self.make().get_bool("ShiftLights")

  def test_no_earlier_settings_writes_defaults(self):
    s = self.make()
    assert os.path.exists(s.settings_path) and s.get("ShiftRevLimit") == 1


class TestPanelChoices(StoreCase):
  def test_volume_buttons_map_to_percent(self):
    s = self.make()
    s.put("ShiftChimeVolume", 70)  # a migrated value between buttons
    assert selected_index(s, "ShiftChimeVolume", 5) in (2, 3)
    store_choice(s, "ShiftChimeVolume", 4)
    assert s.get("ShiftChimeVolume") == 100
    store_choice(s, "TripRankStyle", 2)
    assert s.get("TripRankStyle") == 2 and selected_index(s, "TripRankStyle", 3) == 2

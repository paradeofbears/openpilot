"""
This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import time
from types import SimpleNamespace

import numpy as np

from openpilot.common.params import Params
from openpilot.common.test import OpenpilotTestCase
from openpilot.sunnypilot.selfdrive.ui.alert_volume import (
  AUTO_PCT, CATEGORIES, CONTROL_PARAM, SAFETY_FLOOR_PCT, TEST_PARAM, AlertVolume, AudibleAlert, AudibleAlertSP, clamp_pct,
)
from openpilot.selfdrive.ui import soundd as soundd_module
from openpilot.selfdrive.ui.soundd import Soundd, sound_list

AUTO = 0.3  # a stand-in ambient volume
SOUND_LEN = 1000


class _SM:
  def __init__(self, alert=AudibleAlert.none, updated=False, enabled=False):
    self.updated = {'selfdriveState': updated}
    self.recv_time = {'selfdriveState': time.monotonic()}  # fresh, so no timeout alert
    self._state = SimpleNamespace(alertSound=SimpleNamespace(raw=alert), enabled=enabled)

  def __getitem__(self, key):
    return self._state


def make_soundd(mocker):
  def fake_load(self):
    self.loaded_sounds = {s: np.ones(SOUND_LEN, dtype=np.float32) for s in sound_list}
  mocker.patch.object(Soundd, "load_sounds", fake_load)
  s = Soundd()
  s.auto_volume = AUTO
  return s


def play_frames(s, frames):
  s.get_sound_data(frames)


class TestClampPct(OpenpilotTestCase):
  def test_auto_and_bounds(self):
    assert clamp_pct(101, 0) == AUTO_PCT
    assert clamp_pct(150, 0) == AUTO_PCT
    assert clamp_pct(0, 0) == 0
    assert clamp_pct(-5, 0) == 0
    assert clamp_pct(40, 0) == 40

  def test_safety_floor(self):
    assert clamp_pct(0, SAFETY_FLOOR_PCT) == SAFETY_FLOOR_PCT
    assert clamp_pct(10, SAFETY_FLOOR_PCT) == SAFETY_FLOOR_PCT
    assert clamp_pct(30, SAFETY_FLOOR_PCT) == 30

  def test_garbage_is_auto(self):
    assert clamp_pct(None, 0) == AUTO_PCT
    assert clamp_pct("loud", 0) == AUTO_PCT


class TestAlertVolume(OpenpilotTestCase):
  def setup_method(self):
    self.params = Params()

  def test_defaults_are_auto(self):
    av = AlertVolume(self.params)
    assert not av.enabled
    assert all(v == AUTO_PCT for v in av.levels.values())

  def test_control_off_ignores_levels(self):
    self.params.put("EngageVolume", 20)
    av = AlertVolume(self.params)
    assert av.volume_for(AudibleAlert.engage, AUTO) == AUTO

  def test_control_on_applies_levels(self):
    self.params.put_bool(CONTROL_PARAM, True, block=True)
    self.params.put("EngageVolume", 20, block=True)
    self.params.put("WarningSoftVolume", 0, block=True)  # below the floor
    self.params.put("PromptVolume", 101, block=True)
    av = AlertVolume(self.params)
    assert av.volume_for(AudibleAlert.engage, AUTO) == 0.2
    assert av.volume_for(AudibleAlert.warningSoft, AUTO) == SAFETY_FLOOR_PCT / 100
    assert av.volume_for(AudibleAlert.prompt, AUTO) == AUTO
    assert av.volume_for(AudibleAlert.none, AUTO) == AUTO

  def test_every_safety_alert_has_a_floor(self):
    self.params.put_bool(CONTROL_PARAM, True, block=True)
    for _cat, (param, _floor) in CATEGORIES.items():
      self.params.put(param, 0, block=True)
    av = AlertVolume(self.params)
    for alert in (AudibleAlert.prompt, AudibleAlert.promptRepeat, AudibleAlert.promptDistracted, AudibleAlert.preAlert,
                  AudibleAlert.warningSoft, AudibleAlert.warningImmediate,
                  AudibleAlertSP.promptSingleLow, AudibleAlertSP.promptSingleHigh):
      assert av.volume_for(alert, AUTO) >= SAFETY_FLOOR_PCT / 100, alert
    # the three that may be muted
    for alert in (AudibleAlert.engage, AudibleAlert.disengage, AudibleAlert.refuse):
      assert av.volume_for(alert, AUTO) == 0.0

  def test_reload_cadence(self):
    av = AlertVolume(self.params)
    self.params.put_bool(CONTROL_PARAM, True, block=True)
    for _ in range(AlertVolume.RELOAD_FRAMES - 1):
      av.update()
    assert not av.enabled
    av.update()
    assert av.enabled

  def test_test_request_is_consumed(self):
    av = AlertVolume(self.params)
    self.params.put(TEST_PARAM, "warningSoft", block=True)
    while av._frame % AlertVolume.TEST_POLL_FRAMES:
      av.update()
    assert av.poll_test_request() == AudibleAlert.warningSoft
    assert self.params.get(TEST_PARAM) is None
    assert av.poll_test_request() is None

  def test_unknown_test_request_is_dropped(self):
    av = AlertVolume(self.params)
    self.params.put(TEST_PARAM, "goat", block=True)
    assert av.poll_test_request() is None
    assert self.params.get(TEST_PARAM) is None


class TestSounddAlertVolume(OpenpilotTestCase):
  def setup_method(self):
    self.params = Params()

  def test_stock_ramp_unchanged_with_control_off(self, mocker):
    s = make_soundd(mocker)
    s.update_alert(AudibleAlert.warningImmediate)
    assert s.ramp_start_volume == AUTO

  def test_ramp_starts_from_configured_volume(self, mocker):
    self.params.put_bool(CONTROL_PARAM, True, block=True)
    self.params.put("WarningImmediateVolume", 40, block=True)
    s = make_soundd(mocker)
    s.update_alert(AudibleAlert.warningImmediate)
    assert s.ramp_start_volume == 0.4

  def test_looping_test_sound_plays_once(self, mocker):
    s = make_soundd(mocker)
    s.play_test_alert(AudibleAlert.warningSoft)
    assert sound_list[AudibleAlert.warningSoft][1] is None  # a looping sound

    s.get_audible_alert(_SM())
    assert s.current_alert == AudibleAlert.warningSoft  # still playing, not cut off

    play_frames(s, SOUND_LEN + 10)
    assert s.current_alert == AudibleAlert.none  # stopped at the end of the first loop

    s.get_audible_alert(_SM())
    assert not s.test_alert

  def test_one_shot_test_sound_finishes(self, mocker):
    s = make_soundd(mocker)
    s.play_test_alert(AudibleAlert.engage)
    assert not s.alert_finished()
    play_frames(s, SOUND_LEN)
    assert s.alert_finished()
    s.get_audible_alert(_SM())
    assert not s.test_alert
    assert s.current_alert == AudibleAlert.none

  def test_offroad_none_updates_do_not_cut_a_test(self, mocker):
    s = make_soundd(mocker)
    s.play_test_alert(AudibleAlert.promptDistracted)
    s.get_audible_alert(_SM(AudibleAlert.none, updated=True))
    assert s.current_alert == AudibleAlert.promptDistracted

  def test_real_alert_cuts_a_test(self, mocker):
    s = make_soundd(mocker)
    s.play_test_alert(AudibleAlert.engage)
    s.get_audible_alert(_SM(AudibleAlert.warningImmediate, updated=True))
    assert not s.test_alert
    assert s.current_alert == AudibleAlert.warningImmediate

  def test_test_after_a_finished_alert(self, mocker):
    # offroad, the last onroad chime can sit in current_alert forever; it must not block tests
    s = make_soundd(mocker)
    s.update_alert(AudibleAlert.disengage)
    play_frames(s, SOUND_LEN)
    assert s.alert_finished()
    s.play_test_alert(AudibleAlert.prompt)
    assert s.current_alert == AudibleAlert.prompt
    assert s.current_sound_frame == 0


def test_soundd_imports_alert_volume():
  assert soundd_module.AlertVolume is AlertVolume

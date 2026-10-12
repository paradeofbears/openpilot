"""
This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import pyray as rl

from openpilot.cereal import log
from openpilot.common.test import OpenpilotTestCase
from openpilot.selfdrive.ui.boom_boom.traffic import (
  AMBER, BOX_H, CAR, MIN_BOX_H, RED, TRACK, Car, Mapper, TrafficBox, box_rect, car_color, gather_cars,
)


def svc(name, fields):
  return getattr(log.Event.new_message(**{name: fields}).as_reader(), name)


def rgba(c):
  return (c.r, c.g, c.b, c.a)


def radar_state(*leads):
  fields = {}
  for key, (d, y, v) in zip(("leadOne", "leadTwo"), leads, strict=False):
    fields[key] = {"present": True, "dRel": d, "yRel": y, "vRel": v}
  return svc("radarState", fields)


def tracks(*pts):
  return svc("radarTracks", {"points": [{"trackId": i, "dRel": d, "yRel": y, "vRel": v} for i, (d, y, v) in enumerate(pts)]})


def sm(leads=(), green_light=False, left_bs=False, left_blink=False, lane_y=(-1.8, 1.8)):
  xs = [0.0, 20.0, 40.0]
  return {
    "radarState": radar_state(*leads),
    "carState": svc("carState", {"leftBlindspot": left_bs, "leftBlinker": left_blink}),
    "modelV2": svc("modelV2", {"laneLines": [{"x": xs, "y": [y] * 3} for y in lane_y], "laneLineProbs": [0.9, 0.9]}),
    "longitudinalPlanSP": svc("longitudinalPlanSP", {"e2eAlerts": {"greenLightAlert": green_light}}),
  }


class TestGatherCars(OpenpilotTestCase):
  def test_leads_and_tracks(self):
    cars = gather_cars(radar_state((30.0, 0.0, 0.0)), tracks((30.5, 0.3, 0.0), (45.0, 3.5, 2.0)))
    assert [(c.d, c.lead) for c in cars] == [(30.0, True), (45.0, False)]  # the matching track is the lead

  def test_duplicate_second_lead_dropped(self):
    assert len(gather_cars(radar_state((30.0, 0.0, 0.0), (31.0, 0.5, 0.0)), None)) == 1
    assert len(gather_cars(radar_state((30.0, 0.0, 0.0), (55.0, 0.2, 0.0)), None)) == 2

  def test_nothing_present(self):
    assert gather_cars(radar_state(), None) == []


class TestColors(OpenpilotTestCase):
  def test_by_closing_and_time_to_collision(self):
    assert rgba(car_color(Car(30.0, 0.0, 0.0, True))) == rgba(CAR)
    assert rgba(car_color(Car(30.0, 0.0, 0.0, False))) == rgba(TRACK)
    assert rgba(car_color(Car(30.0, 0.0, -2.0, True))) == rgba(AMBER)   # closing, 15 s away
    assert rgba(car_color(Car(10.0, 0.0, -5.0, True))) == rgba(RED)     # 2 s away


class TestMapping(OpenpilotTestCase):
  def test_directions(self):
    m = Mapper(rl.Rectangle(0, 0, 200, 400))
    cx, ahead = m(20.0, 0.0)
    _, near = m(5.0, 0.0)
    left, _ = m(20.0, 3.0)
    right, _ = m(20.0, -3.0)
    assert cx == 100 and ahead < near  # further ahead is higher on screen
    assert left < cx < right           # left-positive y lands left of centre

  def test_box_stacks_over_the_g_meter_and_gives_up_without_room(self):
    view = rl.Rectangle(30, 30, 2100, 1020)
    alone = box_rect(view, 0, 0)
    stacked = box_rect(view, 0, 350)
    assert alone.height == BOX_H and stacked.y + stacked.height < alone.y + alone.height
    assert stacked.height >= MIN_BOX_H
    assert box_rect(view, 0, 600) is None
    assert box_rect(view, 230, 0).x == alone.x - 230


class TestTrafficBox(OpenpilotTestCase):
  def test_lane_lines_flip_to_left_positive(self):
    box = TrafficBox()
    box.update(sm(), None, True)
    assert [round(float(ys[0]), 3) for _, ys, _ in box.lanes] == [1.8, -1.8]  # model's left line (-1.8 right-positive) is +1.8

  def test_blind_spot_and_blinker(self):
    box = TrafficBox()
    box.update(sm(left_bs=True, left_blink=True), None, True)
    assert box.blind_left and box.blink_left and not box.blind_right

  def test_yields_to_the_green_light_circle(self):
    box = TrafficBox()
    for _ in range(60):
      box.update(sm(leads=[(30.0, 0.0, 0.0)]), None, True)
    assert box._alpha.x > 0.9
    for _ in range(60):
      box.update(sm(leads=[(30.0, 0.0, 0.0)], green_light=True), None, True)
    assert box._alpha.x < 0.05

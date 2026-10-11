#!/usr/bin/env python3
"""
Dump chosen fields from an openpilot drive log, for the boom-boom UI data catalog
(docs/boom-boom/data-catalog.md).

Read-only: it opens log files and prints. It never talks to the car or the device's services.

Inputs, any mix of:
  - an rlog or qlog file (raw, .zst or .bz2)
  - a directory: every rlog under it, in segment order (qlog where a segment has no rlog)
  - a route id or URL, handed to openpilot's LogReader (needs a Linux env: WSL or the device)

Field specs:
  carState.vEgo                      service, then attribute path
  modelV2.laneLineProbs              lists are kept whole
  modelV2.leadsV3[0].prob            [i] indexes a list ([-1] is the last element)
  deviceState.cpuTempC:max           :max :min :mean :len reduce a list to one number
  can0:BRAKE.BRAKE_PRESSURE          a mazda_2017 DBC signal decoded from bus 0 (can2: camera bus)
  derived.ttc                        computed here from other fields, see DERIVED

Modes:
  summary   (default) per-field sample count, measured rate and value distribution
  timeline  one row of latest values every --every seconds, to the screen or --csv FILE
  services  every service in the log with its message count and measured rate
  list      the first message of one service (--service NAME), flattened, to discover fields

Examples:
  python tools/boom_boom/dump_fields.py /data/media/0/realdata/00000123--abcdef1234--5/rlog.zst
  python tools/boom_boom/dump_fields.py ~/rlogs/route_dir --preset lead --preset can
  python tools/boom_boom/dump_fields.py rlog.zst --mode timeline --every 0.5 --csv out.csv
  python tools/boom_boom/dump_fields.py rlog.zst --mode list --service modelV2
  python tools/boom_boom/dump_fields.py rlog.zst --field carState.vEgo --field derived.ttc

Run from the repo root with the repo's venv. On Windows without the full env, PYTHONPATH must
contain the repo root and opendbc_repo, and pycapnp + zstandard must be installed.
"""
from __future__ import annotations

import argparse
import bz2
import csv
import io
import math
import os
import random
import re
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Iterator

# ---------------------------------------------------------------------------------------------
# Field presets: what the data catalog covers. Each one maps to a catalog section.

PRESETS: dict[str, list[str]] = {
  "car": [
    "carState.vEgo", "carState.vEgoRaw", "carState.aEgo", "carState.vEgoCluster", "carState.yawRate",
    "carState.standstill", "carState.gearShifter",
    "carState.steeringAngleDeg", "carState.steeringRateDeg", "carState.steeringTorque", "carState.steeringTorqueEps",
    "carState.steeringPressed", "carState.gasPressed", "carState.brakePressed",
    "carState.leftBlinker", "carState.rightBlinker", "carState.leftBlindspot", "carState.rightBlindspot",
    "carState.genericToggle", "carState.doorOpen", "carState.seatbeltUnlatched",
    "carState.cruiseState.available", "carState.cruiseState.enabled", "carState.cruiseState.speed",
    "carState.cruiseState.speedCluster", "carState.vCruiseCluster",
    "carState.steerFaultTemporary", "carState.steerFaultPermanent", "carState.invalidLkasSetting",
    "carState.lowSpeedAlert", "carState.stockFcw", "carState.accFaulted", "carState.canValid",
    "carStateSP.speedLimit", "carStateSP.zoompilot.lkasArming", "carStateSP.zoompilot.stockEcu",
    "carStateSP.zoompilot.distanceFarther", "carStateSP.zoompilot.cruiseSession.state",
    "carControl.enabled", "carControl.latActive", "carControl.longActive",
    "carControl.actuators.torque", "carControl.actuators.accel", "carControl.hudControl.leadDistanceBars",
    "carOutput.actuatorsOutput.torque", "carOutput.actuatorsOutput.torqueOutputCan", "carOutput.actuatorsOutput.accel",
  ],
  "control": [
    "selfdriveState.state", "selfdriveState.enabled", "selfdriveState.experimentalMode",
    "selfdriveState.personality", "selfdriveState.alertType", "selfdriveState.alertSize",
    "selfdriveStateSP.mads.state", "selfdriveStateSP.mads.lateralHeld",
    "selfdriveStateSP.intelligentCruiseButtonManagement.state",
    "controlsState.curvature", "controlsState.desiredCurvature", "controlsState.longControlState",
    "controlsState.lateralControlState.torqueState.output", "controlsState.lateralControlState.torqueState.saturated",
    "controlsState.lateralControlState.torqueState.actualLateralAccel",
    "controlsState.lateralControlState.torqueState.desiredLateralAccel",
    "longitudinalPlan.aTarget", "longitudinalPlan.hasLead", "longitudinalPlan.fcw",
    "longitudinalPlan.longitudinalPlanSource", "longitudinalPlan.shouldStop", "longitudinalPlan.allowThrottle",
    "longitudinalPlanSP.longitudinalPlanSource", "longitudinalPlanSP.vTarget",
    "longitudinalPlanSP.speedLimit.resolver.speedLimit", "longitudinalPlanSP.speedLimit.resolver.source",
    "longitudinalPlanSP.speedLimit.assist.state",
    "longitudinalPlanSP.smartCruiseControl.vision.state", "longitudinalPlanSP.smartCruiseControl.vision.vAheadMin",
    "longitudinalPlanSP.smartCruiseControl.vision.maxPredictedLateralAccel",
    "longitudinalPlanSP.zoompilot.e2eLeadGap.inhibit", "longitudinalPlanSP.zoompilot.e2eSetSpeed.inhibit",
    "longitudinalPlanSP.zoompilot.leadForecast.leadOne.inhibit",
    "onroadEvents:len",
  ],
  "lead": [
    "radarState.leadOne.present", "radarState.leadOne.dRel", "radarState.leadOne.vRel", "radarState.leadOne.yRel",
    "radarState.leadOne.vLead", "radarState.leadOne.aLeadK", "radarState.leadOne.modelProb",
    "radarState.leadOne.radar", "radarState.leadTwo.present", "radarState.leadTwo.dRel",
    "radarTracks.points:len",
    "derived.ttc", "derived.headway", "derived.closingSpeed",
  ],
  "model": [
    "modelV2.confidence", "modelV2.laneLineProbs", "modelV2.laneLineStds", "modelV2.roadEdgeStds",
    "modelV2.leadsV3[0].prob", "modelV2.leadsV3[0].x[0]", "modelV2.leadsV3[0].v[0]", "modelV2.leadsV3[0].a[0]",
    "modelV2.position.x[-1]", "modelV2.velocity.x[0]", "modelV2.acceleration.x[0]",
    "modelV2.action.desiredCurvature", "modelV2.action.desiredAcceleration", "modelV2.action.shouldStop",
    "modelV2.meta.engagedProb", "modelV2.meta.hardBrakePredicted",
    "modelV2.meta.laneChangeState", "modelV2.meta.laneChangeDirection",
    "modelV2.meta.disengagePredictions.brakeDisengageProbs[0]",
    "modelV2.meta.disengagePredictions.gasDisengageProbs[0]",
    "modelV2.meta.disengagePredictions.steerOverrideProbs[0]",
    "modelV2.meta.disengagePredictions.brake3MetersPerSecondSquaredProbs[0]",
    "modelV2.meta.disengagePredictions.brake5MetersPerSecondSquaredProbs[0]",
    "modelV2.frameDropPerc", "modelV2.modelExecutionTime",
    "drivingModelData.laneLineMeta.leftY", "drivingModelData.laneLineMeta.rightY",
    "drivingModelData.laneLineMeta.leftProb", "drivingModelData.laneLineMeta.rightProb",
    "modelDataV2SP.laneTurnDirection", "modelDataV2SP.leftLaneChangeEdgeBlock", "modelDataV2SP.acceleratorState",
    "derived.laneWidth", "derived.laneCenterOffset",
  ],
  "dm": [
    "driverMonitoringState.alertLevel", "driverMonitoringState.activePolicy", "driverMonitoringState.isRHD",
    "driverMonitoringState.visionPolicyState.awarenessPercent", "driverMonitoringState.visionPolicyState.isDistracted",
    "driverMonitoringState.visionPolicyState.faceDetected",
    "driverMonitoringState.wheeltouchPolicyState.awarenessPercent",
    "driverStateV2.leftDriverData.faceProb", "driverStateV2.leftDriverData.phoneProb",
    "driverStateV2.leftDriverData.sleepProb", "driverStateV2.leftDriverData.sunglassesProb",
    "driverStateV2.wheelOnRightProb",
  ],
  "device": [
    "deviceState.thermalStatus", "deviceState.maxTempC", "deviceState.cpuTempC:max", "deviceState.gpuTempC:max",
    "deviceState.memoryTempC", "deviceState.intakeTempC", "deviceState.exhaustTempC", "deviceState.bottomSocTempC",
    "deviceState.fanSpeedPercentDesired", "deviceState.powerDrawW", "deviceState.somPowerDrawW",
    "deviceState.cpuUsagePercent:mean", "deviceState.gpuUsagePercent", "deviceState.memoryUsagePercent",
    "deviceState.freeSpacePercent", "deviceState.networkType", "deviceState.networkStrength",
    "deviceState.screenBrightnessPercent",
    "peripheralState.voltage", "peripheralState.current", "peripheralState.fanSpeedRpm",
    "pandaStates[0].voltage", "pandaStates[0].current", "pandaStates[0].harnessStatus",
    "pandaStates[0].canState0.totalErrorCnt", "pandaStates[0].canState2.totalErrorCnt",
    "soundPressure.soundPressureWeightedDb",
    "gpsLocationExternal.hasFix", "gpsLocationExternal.satelliteCount", "gpsLocationExternal.horizontalAccuracy",
    "gpsLocationExternal.speed", "gpsLocationExternal.speedAccuracy", "gpsLocationExternal.bearingDeg",
    "gpsLocationExternal.bearingAccuracyDeg", "gpsLocationExternal.altitude",
    "gpsLocation.hasFix", "gpsLocation.horizontalAccuracy",
    "accelerometer.acceleration.v", "gyroscope.gyro.v", "temperatureSensor.temperature",
    "narrowRoadCameraState.exposureValPercent", "narrowRoadCameraState.gain",
    "wideRoadCameraState.exposureValPercent", "cabinCameraState.exposureValPercent",
  ],
  "learned": [
    "lateralTorqueParameters.valid", "lateralTorqueParameters.useParams", "lateralTorqueParameters.calPerc",
    "lateralTorqueParameters.latAccelFactorFiltered", "lateralTorqueParameters.frictionCoefficientFiltered",
    "lateralTorqueParameters.latAccelOffsetFiltered", "lateralTorqueParameters.totalBucketPoints",
    "lateralDelay.lateralDelay", "lateralDelay.lateralDelayEstimate", "lateralDelay.status", "lateralDelay.calPerc",
    "vehicleParameters.valid", "vehicleParameters.steerRatio", "vehicleParameters.stiffnessFactor",
    "vehicleParameters.angleOffsetDeg", "vehicleParameters.angleOffsetAverageDeg", "vehicleParameters.roll",
    "extrinsicsCalibration.calStatus", "extrinsicsCalibration.calPerc", "extrinsicsCalibration.rpyCalib",
    "extrinsicsCalibration.height",
    "deviceMotion.accelerationDevice.x", "deviceMotion.accelerationDevice.y", "deviceMotion.accelerationDevice.z",
    "deviceMotion.angularVelocityDevice.z", "deviceMotion.orientationNED.x", "deviceMotion.orientationNED.y",
    "deviceMotion.velocityDevice.x", "deviceMotion.inputsOK", "deviceMotion.sensorsOK",
    "customReserved19.speedBinLatAccelFactors", "customReserved19.speedBinValid",
    "liveMapDataSP.speedLimitValid", "liveMapDataSP.speedLimit", "liveMapDataSP.speedLimitAhead",
    "liveMapDataSP.roadName",
    "derived.latAccel", "derived.gLong", "derived.gLat",
  ],
  # Mazda DBC signals the port never publishes (and a few it does, for comparison).
  "can": [
    "can0:BRAKE.BRAKE_PRESSURE", "can0:BRAKE.VEHICLE_ACC_X", "can0:BRAKE.VEHICLE_ACC_Y",
    "can0:ENGINE_DATA.RPM", "can0:ENGINE_DATA.PEDAL_GAS", "can0:ENGINE_DATA.SPEED",
    "can0:CHECK_AND_TEMP.COOLANT_TEMP", "can0:CHECK_AND_TEMP.OUTDOOR_TEMP",
    "can0:TEMPERATURE.TEMPERATURE_MAYBE", "can0:NEW_MSG_3.MILAGE_MAYBE",
    "can0:BSM.LEFT_BS_STATUS", "can0:BSM.RIGHT_BS_STATUS", "can0:BSM.LEFT_BS_BEHIND", "can0:BSM.RIGHT_BS_DISTANCE",
    "can0:BSM.LEFT_BS_SIDE", "can0:BSM.REAR_CT_ALERT", "can0:BSM.BSM_OFF",
    "can0:STEER_RATE.LKAS_REQUEST", "can0:STEER_RATE.LKAS_EFFECTIVE", "can0:STEER_RATE.LKAS_BLOCK",
    "can0:STEER_RATE.LKAS_TRACK_STATE", "can0:STEER_RATE.HANDS_OFF_5_SECONDS",
    "can0:STEER_TORQUE.STEER_TORQUE_MOTOR", "can0:STEER_TORQUE.STEER_TORQUE_SENSOR",
    "can0:GEAR.GEAR", "can0:GEAR.GEAR_BOX", "can0:GEAR.MORE_GEAR", "can0:GEAR.BRAKE_HOLD", "can0:EPB.HOLD_STATE",
    "can0:BLINK_INFO.LOW_BEAMS", "can0:BLINK_INFO.HIGH_BEAMS", "can0:BLINK_INFO.WIPER_LO",
    "can0:BLINK_INFO.WIPER_HI", "can0:TURN_SWITCH.HAZARD",
    "can0:DOORS.FL", "can0:DOORS.FR", "can0:DOORS.BL", "can0:DOORS.BR", "can0:DOORS.LEFTGATE",
    "can0:DOORS.DOORS_UNLOCKED", "can0:SEATBELT.PASSENGER_SEATBELT",
    "can0:TRACTION.DSC_OFF", "can0:TRACTION.BRAKE", "can0:TRACTION.TPMS_WARNING_DOUBLE_BLINK",
    "can0:CRZ_EVENTS.CRZ_SPEED", "can0:CRZ_CTRL.DISTANCE_SETTING", "can0:CRZ_CTRL.RADAR_HAS_LEAD",
    "can0:CRZ_CTRL.RADAR_LEAD_RELATIVE_DISTANCE",
    "can0:RADAR_DISTANCE.DIST_OBJ", "can0:RADAR_DISTANCE.ANG_OBJ", "can0:RADAR_DISTANCE.RELV_OBJ",
    "can2:CAM_TRAFFIC_SIGNS.SPEED_SIGN", "can2:CAM_TRAFFIC_SIGNS.SPEED_SIGN_UNIT",
    "can2:CAM_TRAFFIC_SIGNS.STOP_SIGN", "can2:CAM_TRAFFIC_SIGNS.FORWARD_COLLISION",
    "can2:CAM_LANEINFO.LANE_LINES", "can2:CAM_LANEINFO.LINE_VISIBLE", "can2:CAM_LANEINFO.LINE_NOT_VISIBLE",
    "can2:CAM_LANEINFO.LDW_WARN_LL", "can2:CAM_LANEINFO.LDW_WARN_RL", "can2:CAM_LANEINFO.TJA",
    "can2:CAM_LANEINFO.HANDS_WARN_3_BITS",
    "can2:CAM_LANETRACK.LANE_CURVE", "can2:CAM_LANETRACK.LINE1", "can2:CAM_LANETRACK.LINE2",
    "can2:CAM_LKAS.LDW", "can2:CAM_LKAS.LINE_NOT_VISIBLE",
    "can2:CAM_PEDESTRIAN.PED_WARNING", "can2:CAM_SETTINGS.SBS_WARNING_DISTANCE",
    "derived.epsDelivery",
  ],
}


# ---------------------------------------------------------------------------------------------
# Derived values: (inputs, function of those inputs' latest values). Each is evaluated when its
# first input updates, so it runs at that input's rate; None means "not meaningful right now".

def _ttc(present, d_rel, v_rel):
  # Time to collision: gap over closing speed, only while closing.
  if not present or v_rel is None or v_rel > -0.1:
    return None
  return d_rel / -v_rel


def _headway(present, d_rel, v_ego):
  # Time headway: gap over own speed (what the chevron's "TTC" option shows today).
  if not present or not v_ego or v_ego < 1.0:
    return None
  return d_rel / v_ego


def _closing(present, v_rel):
  return -v_rel if present else None


def _lane_width(left, right):
  # drivingModelData's near-field lane-line offsets, m; left is negative of right in device frame.
  if left is None or right is None:
    return None
  return right - left


def _lane_center(left, right):
  if left is None or right is None:
    return None
  return (left + right) / 2


def _lat_accel(curvature, v_ego, roll):
  if curvature is None or v_ego is None:
    return None
  return curvature * v_ego ** 2 - (roll or 0.0) * 9.81


def _g(a):
  return None if a is None else a / 9.81


def _g_lat(a_y, yaw_rate, v_x):
  # deviceMotion's acceleration is d(velocity)/dt in the device frame; the pose filter carries the
  # centripetal term (omega x v) separately, so cornering G needs it added back.
  if a_y is None or yaw_rate is None or v_x is None:
    return None
  return (a_y + yaw_rate * v_x) / 9.81


def _eps_delivery(req, eff):
  # Share of the requested LKAS torque the EPS applied, from its own 0x241 report.
  if req is None or eff is None or abs(req) < 200:
    return None
  return eff / req


DERIVED: dict[str, tuple[list[str], Callable]] = {
  "derived.ttc": (["radarState.leadOne.present", "radarState.leadOne.dRel", "radarState.leadOne.vRel"], _ttc),
  "derived.headway": (["radarState.leadOne.present", "radarState.leadOne.dRel", "carState.vEgo"], _headway),
  "derived.closingSpeed": (["radarState.leadOne.present", "radarState.leadOne.vRel"], _closing),
  "derived.laneWidth": (["drivingModelData.laneLineMeta.leftY", "drivingModelData.laneLineMeta.rightY"], _lane_width),
  "derived.laneCenterOffset": (["drivingModelData.laneLineMeta.leftY", "drivingModelData.laneLineMeta.rightY"], _lane_center),
  "derived.latAccel": (["controlsState.curvature", "carState.vEgo", "vehicleParameters.roll"], _lat_accel),
  "derived.gLong": (["deviceMotion.accelerationDevice.x"], _g),
  "derived.gLat": (["deviceMotion.accelerationDevice.y", "deviceMotion.angularVelocityDevice.z",
                    "deviceMotion.velocityDevice.x"], _g_lat),
  "derived.epsDelivery": (["can0:STEER_RATE.LKAS_REQUEST", "can0:STEER_RATE.LKAS_EFFECTIVE"], _eps_delivery),
}


# ---------------------------------------------------------------------------------------------
# Field specs

_PART = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)((?:\[-?\d+\])*)$")
_IDX = re.compile(r"\[(-?\d+)\]")
REDUCERS = ("max", "min", "mean", "len")


class Spec:
  """One requested field: a log path, a CAN signal or a derived value."""

  def __init__(self, text: str):
    self.text = text
    self.kind = "log"
    self.service = ""
    self.parts: list[tuple[str, list[int]]] = []
    self.reducer: str | None = None
    self.bus = -1
    self.msg = ""
    self.sig = ""

    if text in DERIVED:
      self.kind = "derived"
      self.service = "derived"
      return

    m = re.match(r"^can(\d+):([A-Za-z0-9_]+)\.([A-Za-z0-9_]+)$", text)
    if m:
      self.kind = "can"
      self.bus, self.msg, self.sig = int(m.group(1)), m.group(2), m.group(3)
      self.service = f"can{self.bus}:{self.msg}"
      return

    path, _, reducer = text.partition(":")
    if reducer:
      if reducer not in REDUCERS:
        raise ValueError(f"{text}: reducer must be one of {', '.join(REDUCERS)}")
      self.reducer = reducer
    for p in path.split("."):
      pm = _PART.match(p)
      if not pm:
        raise ValueError(f"{text}: cannot parse {p!r}")
      self.parts.append((pm.group(1), [int(i) for i in _IDX.findall(pm.group(2))]))
    self.service = self.parts[0][0]


def norm(v):
  """A capnp value as plain Python: enums to their name, lists to tuples, structs elided."""
  if v is None or isinstance(v, (bool, int, float, str)):
    return v
  if isinstance(v, bytes):
    return v.hex()
  tname = type(v).__name__
  if "Enum" in tname:
    return str(v)
  if "List" in tname:
    return tuple(norm(x) for x in v)
  if "Struct" in tname:
    return "{struct}"
  return str(v)


def reduce_value(v, reducer: str | None):
  if reducer is None:
    return v
  if not isinstance(v, tuple):
    return v
  if reducer == "len":
    return len(v)
  nums = [x for x in v if isinstance(x, (int, float)) and not isinstance(x, bool)]
  if not nums:
    return None
  if reducer == "max":
    return max(nums)
  if reducer == "min":
    return min(nums)
  return sum(nums) / len(nums)


def resolve(evt, spec: Spec):
  try:
    obj = evt
    for name, idx in spec.parts:
      obj = getattr(obj, name)
      for i in idx:
        obj = obj[i]
    return reduce_value(norm(obj), spec.reducer)
  except Exception:  # inactive union member, short list, missing field in an old log
    return None


# ---------------------------------------------------------------------------------------------
# CAN decoding straight from the DBC: no checksum or counter gating, so every frame on the wire
# is seen. Right for exploring; a UI feature should validate the way carstate's parser does.

class CanDecoder:
  def __init__(self, dbc_name: str = "mazda_2017"):
    from opendbc.can.dbc import DBC
    from opendbc.can.parser import get_raw_value
    self._dbc = DBC(dbc_name)
    self._raw = get_raw_value
    # (bus, address) -> list of (spec text, Signal)
    self.wanted: dict[tuple[int, int], list[tuple[str, object]]] = {}

  def add(self, spec: Spec) -> None:
    msg = self._dbc.name_to_msg.get(spec.msg)
    if msg is None:
      raise ValueError(f"{spec.text}: no message {spec.msg} in the DBC")
    sig = msg.sigs.get(spec.sig)
    if sig is None:
      raise ValueError(f"{spec.text}: no signal {spec.sig} in {spec.msg}")
    self.wanted.setdefault((spec.bus, msg.address), []).append((spec.text, sig))

  def decode(self, frames) -> Iterator[tuple[str, float]]:
    for f in frames:
      key = (f.src, f.address)
      sigs = self.wanted.get(key)
      if not sigs:
        continue
      dat = bytes(f.dat)
      for text, sig in sigs:
        raw = self._raw(dat, sig)
        if sig.is_signed:
          raw -= ((raw >> (sig.size - 1)) & 0x1) * (1 << sig.size)
        yield text, raw * sig.factor + sig.offset


# ---------------------------------------------------------------------------------------------
# Log reading

LOG_NAME = re.compile(r"^(rlog|qlog)(\.zst|\.bz2)?$")


def _segment_key(path: str):
  parent = os.path.basename(os.path.dirname(path))
  m = re.search(r"--(\d+)$", parent)
  return (os.path.dirname(os.path.dirname(path)), parent.rsplit("--", 1)[0], int(m.group(1)) if m else -1, path)


def find_logs(path: str, prefer_qlog: bool) -> list[str]:
  if os.path.isfile(path):
    return [path]
  by_dir: dict[str, dict[str, str]] = {}
  for root, _, files in os.walk(path):
    for fn in files:
      m = LOG_NAME.match(fn)
      if m:
        by_dir.setdefault(root, {})[m.group(1)] = os.path.join(root, fn)
  order = ("qlog", "rlog") if prefer_qlog else ("rlog", "qlog")
  picked = [next(d[k] for k in order if k in d) for d in by_dir.values()]
  return sorted(picked, key=_segment_key)


def _read_file(fn: str) -> Iterator:
  from openpilot.cereal import log
  with open(fn, "rb") as f:
    dat = f.read()
  if fn.endswith(".bz2") or dat.startswith(b"BZh"):
    dat = bz2.decompress(dat)
  elif fn.endswith(".zst") or dat.startswith(b"\x28\xb5\x2f\xfd"):
    import zstandard
    dat = zstandard.ZstdDecompressor().stream_reader(io.BytesIO(dat)).read()
  try:
    yield from log.Event.read_multiple_bytes(dat)
  except Exception as e:  # a segment cut off mid-write ends in a partial event
    print(f"  {fn}: stopped at a corrupt event ({type(e).__name__})", file=sys.stderr)


def iter_events(inputs: list[str], prefer_qlog: bool) -> Iterator:
  for item in inputs:
    if os.path.exists(item):
      files = find_logs(item, prefer_qlog)
      if not files:
        print(f"no rlog or qlog under {item}", file=sys.stderr)
      for fn in files:
        print(f"reading {fn}", file=sys.stderr)
        yield from _read_file(fn)
    else:
      try:
        from openpilot.tools.lib.logreader import LogReader
      except Exception as e:
        hint = "Run in WSL or on the device, or download the rlogs first."
        sys.exit(f"{item} is not a local path, and openpilot's LogReader cannot load here ({e}). {hint}")
      print(f"reading {item} through LogReader", file=sys.stderr)
      yield from LogReader(item)


# ---------------------------------------------------------------------------------------------
# Statistics: bounded memory however long the drive

RESERVOIR = 5000


class FieldStats:
  def __init__(self):
    self.n = 0
    self.none = 0
    self.t_first: float | None = None
    self.t_last: float | None = None
    self.n_true = 0
    self.n_bool = 0
    self.nums: list[float] = []
    self.n_nums = 0
    self.vmin = math.inf
    self.vmax = -math.inf
    self.cats: Counter = Counter()
    self.list_lens: Counter = Counter()
    self.list_elems: list[list[float]] = []
    self.changes = 0
    self._last = object()

  def add(self, t: float, v, rng: random.Random) -> None:
    self.n += 1
    self.t_first = t if self.t_first is None else self.t_first
    self.t_last = t
    if v != self._last:
      self.changes += 1
      self._last = v
    if v is None:
      self.none += 1
    elif isinstance(v, bool):
      self.n_bool += 1
      self.n_true += v
    elif isinstance(v, (int, float)):
      if math.isfinite(v):
        self._num(float(v), rng)
      else:
        self.cats[str(v)] += 1
    elif isinstance(v, tuple):
      self.list_lens[len(v)] += 1
      if 0 < len(v) <= 8 and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v):
        while len(self.list_elems) < len(v):
          self.list_elems.append([])
        if len(self.list_elems[0]) < RESERVOIR:
          for i, x in enumerate(v):
            self.list_elems[i].append(float(x))
    else:
      if len(self.cats) < 50 or v in self.cats:
        self.cats[str(v)] += 1

  def _num(self, x: float, rng: random.Random) -> None:
    self.n_nums += 1
    self.vmin = min(self.vmin, x)
    self.vmax = max(self.vmax, x)
    if len(self.nums) < RESERVOIR:
      self.nums.append(x)
    else:
      j = rng.randrange(self.n_nums)
      if j < RESERVOIR:
        self.nums[j] = x

  def rate(self) -> float | None:
    if self.n < 2 or self.t_last is None or self.t_first is None or self.t_last <= self.t_first:
      return None
    return (self.n - 1) / (self.t_last - self.t_first)

  def describe(self) -> str:
    if self.n == self.none:
      return "always None (inactive union member, empty list, or not meaningful)"
    out = []
    if self.n_nums:
      s = sorted(self.nums)

      def q(p: float) -> float:
        return s[min(len(s) - 1, int(p * len(s)))]
      out.append(f"min {fmt(self.vmin)}  p5 {fmt(q(0.05))}  med {fmt(q(0.5))}  p95 {fmt(q(0.95))}  max {fmt(self.vmax)}")
      if len(set(s)) <= 6:
        out.append("values " + ", ".join(fmt(x) for x in sorted(set(s))))
    if self.n_bool:
      out.append(f"true {100.0 * self.n_true / self.n_bool:.1f}%")
    if self.cats:
      total = sum(self.cats.values())
      out.append(", ".join(f"{k} {100.0 * c / total:.0f}%" for k, c in self.cats.most_common(6)))
    if self.list_lens:
      lens = ",".join(str(k) for k in sorted(self.list_lens))
      out.append(f"list len {lens}")
      if self.list_elems:
        meds = [sorted(e)[len(e) // 2] for e in self.list_elems if e]
        out.append("element medians [" + ", ".join(fmt(m) for m in meds) + "]")
    if self.none:
      out.append(f"None {100.0 * self.none / self.n:.0f}%")
    out.append(f"{self.changes} changes")
    return "  |  ".join(out)


def fmt(x) -> str:
  if x is None:
    return "-"
  if isinstance(x, bool):
    return "1" if x else "0"
  if isinstance(x, float):
    if x == 0 or 0.01 <= abs(x) < 10000:
      return f"{x:.3g}" if abs(x) < 10 else f"{x:.1f}"
    return f"{x:.3e}"
  if isinstance(x, tuple):
    inner = ", ".join(fmt(v) for v in x[:6])
    return f"[{inner}{', ...' if len(x) > 6 else ''}]"
  return str(x)


# ---------------------------------------------------------------------------------------------
# Modes

class Dumper:
  def __init__(self, specs: list[Spec]):
    self.specs = specs
    self.by_service: dict[str, list[Spec]] = {}
    self.derived = [s for s in specs if s.kind == "derived"]
    self.latest: dict[str, object] = {}
    self.can = None
    hidden: list[Spec] = []
    known = {s.text for s in specs}
    for d in self.derived:
      for dep in DERIVED[d.text][0]:
        if dep not in known:
          hidden.append(Spec(dep))
          known.add(dep)
    self.hidden = {s.text for s in hidden}
    for s in specs + hidden:
      if s.kind == "log":
        self.by_service.setdefault(s.service, []).append(s)
      elif s.kind == "can":
        if self.can is None:
          self.can = CanDecoder()
        self.can.add(s)
    # derived fields to re-evaluate when their first input (the trigger) updates
    self.dependents: dict[str, list[str]] = {}
    for d in self.derived:
      self.dependents.setdefault(DERIVED[d.text][0][0], []).append(d.text)

  def updates(self, evt) -> Iterator[tuple[str, object]]:
    """(field, value) pairs this event carries, derived values included."""
    try:
      w = evt.which()
    except Exception:
      return
    changed: list[str] = []
    if w == "can" and self.can is not None:
      for text, v in self.can.decode(evt.can):
        self.latest[text] = v
        changed.append(text)
    for s in self.by_service.get(w, ()):
      v = resolve(evt, s)
      self.latest[s.text] = v
      changed.append(s.text)
    seen: set[str] = set()
    for text in changed:
      if text not in self.hidden:
        yield text, self.latest[text]
      for d in self.dependents.get(text, ()):
        if d not in seen:
          seen.add(d)
          deps = DERIVED[d][0]
          try:
            v = DERIVED[d][1](*[self.latest.get(x) for x in deps])
          except Exception:
            v = None
          self.latest[d] = v
          yield d, v


def mode_summary(events: Iterable, dumper: Dumper) -> None:
  rng = random.Random(0)
  stats: dict[str, FieldStats] = {s.text: FieldStats() for s in dumper.specs}
  svc_count: Counter = Counter()
  t0 = t1 = None
  for evt in events:
    t = evt.logMonoTime * 1e-9
    t0 = t if t0 is None else t0
    t1 = t
    try:
      svc_count[evt.which()] += 1
    except Exception:
      pass
    for text, v in dumper.updates(evt):
      stats[text].add(t, v, rng)

  span = (t1 - t0) if t0 is not None and t1 is not None else 0.0
  print(f"\nlog span {span:.1f} s, {sum(svc_count.values())} events\n")
  missing = []
  group = None
  width = max(len(s.text) for s in dumper.specs) + 2
  for s in dumper.specs:
    st = stats[s.text]
    if st.n == 0:
      missing.append(s.text)
      continue
    if s.service != group:
      group = s.service
      n_msgs = svc_count.get(s.service)
      print(f"== {group}" + (f"  ({n_msgs} msgs)" if n_msgs else ""))
    rate = st.rate()
    rate_txt = f"{rate:7.2f} Hz" if rate is not None else "      - Hz"
    print(f"  {s.text:<{width}} n {st.n:<8} {rate_txt}   {st.describe()}")
  if missing:
    print("\nnever seen in this log (service not logged, not subscribed in a qlog, or wrong name):")
    for m in missing:
      print(f"  {m}")


def mode_timeline(events: Iterable, dumper: Dumper, every: float, csv_path: str | None) -> None:
  cols = [s.text for s in dumper.specs]
  out = open(csv_path, "w", newline="") if csv_path else None
  writer = csv.writer(out) if out else None
  if writer:
    writer.writerow(["t"] + cols)
  else:
    print("\t".join(["t"] + cols))
  current: dict[str, object] = {}
  t0 = None
  next_t = None
  rows = 0
  for evt in events:
    t = evt.logMonoTime * 1e-9
    if t0 is None:
      t0, next_t = t, t
    for text, v in dumper.updates(evt):
      current[text] = v
    if t >= next_t:
      row = [f"{t - t0:.2f}"] + [fmt(current.get(c)) for c in cols]
      if writer:
        writer.writerow(row)
      else:
        print("\t".join(row))
      rows += 1
      next_t += every
      while next_t <= t:
        next_t += every
  if out:
    out.close()
    print(f"wrote {rows} rows to {csv_path}", file=sys.stderr)


def mode_services(events: Iterable) -> None:
  count: Counter = Counter()
  first: dict[str, float] = {}
  last: dict[str, float] = {}
  for evt in events:
    try:
      w = evt.which()
    except Exception:
      continue
    t = evt.logMonoTime * 1e-9
    count[w] += 1
    first.setdefault(w, t)
    last[w] = t
  print(f"{'service':<34} {'msgs':>9} {'rate':>10}")
  for w in sorted(count):
    span = last[w] - first[w]
    rate = (count[w] - 1) / span if span > 0 and count[w] > 1 else 0.0
    print(f"{w:<34} {count[w]:>9} {rate:>8.2f} Hz")


def _flatten(prefix: str, v, out: list[tuple[str, str]], depth: int = 0) -> None:
  if isinstance(v, dict):
    for k, x in v.items():
      _flatten(f"{prefix}.{k}" if prefix else k, x, out, depth + 1)
  elif isinstance(v, list):
    if v and isinstance(v[0], dict) and depth < 8:
      out.append((prefix, f"list of {len(v)}, first:"))
      _flatten(f"{prefix}[0]", v[0], out, depth + 1)
    else:
      head = ", ".join(fmt(x) if not isinstance(x, str) else x for x in v[:6])
      out.append((prefix, f"[{head}{', ...' if len(v) > 6 else ''}] (len {len(v)})"))
  elif isinstance(v, bytes):
    out.append((prefix, f"<{len(v)} bytes>"))
  else:
    out.append((prefix, fmt(v)))


def mode_list(events: Iterable, service: str) -> None:
  for evt in events:
    try:
      if evt.which() != service:
        continue
      d = getattr(evt, service)
      d = d.to_dict() if hasattr(d, "to_dict") else [x.to_dict() for x in d]
    except Exception as e:
      sys.exit(f"cannot read {service}: {e}")
    rows: list[tuple[str, str]] = []
    _flatten(service, d, rows)
    for k, v in rows:
      print(f"  {k:<80} {v}")
    return
  sys.exit(f"no {service} message in the log")


def main(argv: list[str] | None = None) -> None:
  ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  ap.add_argument("inputs", nargs="+", help="rlog/qlog files, directories of segments, or route ids")
  ap.add_argument("--mode", choices=("summary", "timeline", "services", "list"), default="summary")
  ap.add_argument("--preset", action="append", choices=sorted(PRESETS), help="field group (repeatable); default all")
  ap.add_argument("--field", action="append", default=[], help="extra field spec (repeatable)")
  ap.add_argument("--only-fields", action="store_true", help="use only --field, no presets")
  ap.add_argument("--every", type=float, default=1.0, help="timeline row interval, s")
  ap.add_argument("--csv", help="timeline: write CSV here instead of the screen")
  ap.add_argument("--service", help="list: the service to show")
  ap.add_argument("--qlog", action="store_true", help="prefer qlogs in directories (no CAN, decimated services)")
  ap.add_argument("--max-seconds", type=float, help="stop after this much log time")
  args = ap.parse_args(argv)

  events = iter_events(args.inputs, args.qlog)
  if args.max_seconds:
    events = _limit(events, args.max_seconds)

  if args.mode == "services":
    mode_services(events)
    return
  if args.mode == "list":
    if not args.service:
      ap.error("--mode list needs --service")
    mode_list(events, args.service)
    return

  texts: list[str] = []
  if not args.only_fields:
    for p in (args.preset or sorted(PRESETS)):
      texts += PRESETS[p]
  texts += args.field
  if not texts:
    ap.error("no fields: give --preset or --field")
  try:
    specs = [Spec(t) for t in dict.fromkeys(texts)]
    dumper = Dumper(specs)
  except ValueError as e:
    ap.error(str(e))

  if args.mode == "summary":
    mode_summary(events, dumper)
  else:
    mode_timeline(events, dumper, args.every, args.csv)


def _limit(events: Iterable, seconds: float) -> Iterator:
  t0 = None
  for evt in events:
    t = evt.logMonoTime * 1e-9
    t0 = t if t0 is None else t0
    if t - t0 > seconds:
      return
    yield evt


if __name__ == "__main__":
  main()

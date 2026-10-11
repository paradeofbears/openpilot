# boom-boom data catalog

What the onroad UI could draw on a comma 3X in a Mazda, and how far each value can be trusted.
This is Phase 1 of the boom-boom experimental-UI work: inventory first, features after.

Sources read: `openpilot/cereal/{log,services,custom}.capnp|py`, `opendbc_repo/opendbc/car/car.capnp`,
the Mazda port (`opendbc/car/mazda/{carstate,radar_interface,values,interface}.py`,
`opendbc/sunnypilot/car/mazda/carstate_ext.py`), `opendbc/dbc/mazda_2017.dbc`, `docs/zoompilot/*.md`,
the tici UI (`selfdrive/ui/ui_state.py`, `sunnypilot/ui_state.py`, `onroad/`, `sunnypilot/onroad/`).

Status of the numbers: rates are the nominal rates from `cereal/services.py` and the Mazda port's
own constants. **No value here has been checked against a log from this car yet.** Run
`tools/boom_boom/dump_fields.py` (below) on an rlog to fill in real ranges; until then every
"trust" rating is a reading of the code and the zoompilot docs, not a measurement.

## Facts that shape every feature

- **The UI runs at 20 fps on the comma 3X** (device type `tizi`, `system/ui/lib/application.py`).
  A 100 Hz signal is sampled, not seen in full. Anything that needs every sample (peak G, a
  short blind-spot blip) has to be accumulated in the widget's `_update_state` from whatever
  the SubMaster delivers, or computed elsewhere.
- **Leads depend on longitudinal mode.** With alpha long (openpilot longitudinal) the stock radar
  is silenced and `radarUnavailable` is set, so `radarState` leads are vision-only: `radar` is
  false and `dRel`/`vRel` come from the driving model. With stock MRCC the radar's four usable
  tracks (0x361 to 0x364, 10 Hz) feed radard and leads can be radar-matched. The CX-9 2016-20 and
  the G46L radar never have tracks. Which mode this car runs decides how good any lead widget is.
- **Several services were renamed in openpilot 0.11.** The names in older guides map like this:

  | old name | name here | publisher |
  |---|---|---|
  | livePose | deviceMotion | locationd |
  | liveParameters | vehicleParameters | paramsd |
  | liveTorqueParameters | lateralTorqueParameters | torqued |
  | liveCalibration | extrinsicsCalibration | calibrationd |
  | liveDelay | lateralDelay | lagd |
  | roadCameraState / driverCameraState | narrowRoadCameraState / cabinCameraState | camerad |
  | liveTorqueParametersSP | customReserved19 | torqued_ext (zoompilot speed bins) |

- **Most of the Mazda's interesting CAN is not published.** carstate reads about 25 DBC signals and
  turns them into `carState`. Brake pressure, the car's own accelerometer, RPM, the gearbox gear,
  temperatures, the detailed blind-spot and cross-traffic bits, wipers and the camera's stop-sign
  flag are on the bus but nowhere in cereal. Getting them to the UI is a design choice; see
  [Getting unpublished CAN to the UI](#getting-unpublished-can-to-the-ui).
- **The chevron "TTC" option is not time to collision.** `chevron_metrics.py` shows `dRel / vEgo`,
  which is time headway. Real TTC is `dRel / -vRel` while closing. Worth knowing before building
  a lead widget next to it.

Trust scale used below: **High** (direct sensor, decoded and used for control), **Medium** (usable,
with a known caveat), **Low** (derived, noisy or partially decoded), **Unknown** (decoded in the DBC
but never validated on this car; needs a log). "Shown" says whether any tici onroad widget draws
it today, and which.

## 1. Messaging services the tici UI already subscribes to

### carState (100 Hz, card)

| field | units | meaning | Mazda trust | shown |
|---|---|---|---|---|
| vEgo | m/s | speed, Kalman-filtered average of the four wheel speeds | High | speed readout |
| vEgoRaw | m/s | unfiltered wheel-speed average | High | no |
| vEgoCluster | m/s | speed as the dash shows it (hysteresis on vEgo; Mazda sends none) | High | speed readout (TrueVEgoUI off) |
| aEgo | m/s² | derivative from the same Kalman filter | Medium: lags and smooths; fine for a bar, not for peak G | RocketFuel, dev UI "ACC." |
| wheelSpeeds.fl/fr/rl/rr | m/s | per-wheel speed, WHEEL_SPEEDS 0.01 kph | High | no |
| yawRate | rad/s | not set by the Mazda port | none: always 0 | no |
| standstill | bool | ENGINE_DATA.SPEED ≤ 0.1 kph | High | standstill timer |
| gearShifter | enum | GEAR.GEAR: P, R, N, D (0 = shifting maps to unknown) | High | reverse view |
| steeringAngleDeg | deg | STEER.STEER_ANGLE, 0.05° steps | High | dev UI "REAL STEER" |
| steeringRateDeg | deg/s | STEER_RATE.STEER_ANGLE_RATE, 0.25°/s steps | High | no |
| steeringTorque | raw counts, ±127 | driver's hand torque sensor; pressed above 15 | Medium: unitless counts | no |
| steeringTorqueEps | raw, 0.1 scale, units "tbd" in the DBC | EPS motor torque | Medium: real signal, unknown units; the dev UI labels it N·dm without evidence | dev UI "E.T." |
| steeringPressed | bool | driver torque above threshold for 5 frames | High | path colour (override) |
| gasPressed | bool | ENGINE_DATA.PEDAL_GAS > 0; the pedal position itself is discarded | High as a bool | no |
| brakePressed | bool | PEDALS.BRAKE_ON | High | no |
| leftBlinker / rightBlinker | bool | lamp state held 0.4 s so the blink reads steady | High | turn signal icons |
| leftBlindspot / rightBlindspot | bool | BSM.*_BS_STATUS ≠ 0; only when `enableBsm` (0x477 seen at fingerprint) | High when BSM fitted | BlindSpot indicators, turn signal colour |
| genericToggle | bool | high beams on (BLINK_INFO.HIGH_BEAMS) | High | no |
| doorOpen | bool | any of the four doors; liftgate not included | High | no |
| seatbeltUnlatched | bool | driver belt only | High | alert only |
| cruiseState.available / enabled | bool | MRCC main and engaged; under alpha long from PEDALS with a 0.1 s main-off debounce | High | engagement colour |
| cruiseState.speed | m/s | CRZ_EVENTS.CRZ_SPEED, the held set speed | High | set-speed box |
| cruiseState.speedCluster | m/s | dash number; differs only on Oceania clusters | High | set-speed box |
| steerFaultTemporary / Permanent | bool | EPS block that matters / camera ERR_BIT_1 | High | alerts only |
| invalidLkasSetting | bool | car's own lane-keep switched off | High | alert, MADS "held" |
| lowSpeedAlert | bool | legacy EPS below 45 kph | High (legacy EPS only) | alert |
| stockFcw | bool | camera collision or pedestrian warning | Medium: decoded from status bytes | alert |
| accFaulted | bool | radar hand-back failed under alpha long | High | alert |
| canValid / canTimeout | bool | parser health | High | alert |
| fuelGauge, parkingBrake, espDisabled, espActive | | not set by the Mazda port | none | no |

### carStateSP (100 Hz, card)

| field | units | meaning | Mazda trust | shown |
|---|---|---|---|---|
| speedLimit | m/s | CAM_TRAFFIC_SIGNS.SPEED_SIGN, camera sign or the car's map fallback (the port does not tell which) | Medium: depends on the camera; 0 when none | speed-limit sign via the resolver |
| zoompilot.lkasArming | bool | lane keep back on, EPS not yet steering | High | MADS state colour |
| zoompilot.stockEcu | enum | radar takeover progress (alpha long) | High | alerts |
| zoompilot.distanceFarther | bool | the wheel's second distance button | High | no |
| zoompilot.cruiseSession.* | enum, m/s | speed-limit-assist session (state, vCap, lastIntent) | High | SLA widget via longitudinalPlanSP |

### carControl and carOutput (100 Hz, controlsd and card)

| field | units | meaning | Mazda trust | shown |
|---|---|---|---|---|
| carControl.enabled, latActive, longActive | bool | what openpilot is controlling this frame | High | status colour, dev UI |
| carControl.actuators.torque | −1..1 | lateral torque openpilot asked for | High | no |
| carOutput.actuatorsOutput.torque | −1..1 | torque after the port's limits: rate limits, driver-torque limit and the speed-dependent EPS ceiling clamp | High | steering arc (TorqueBar), divided by the speed-dependent rail (`get_steer_rail_schedule`) |
| carOutput.actuatorsOutput.torqueOutputCan | counts, ±1200 | LKAS_REQUEST actually sent | High | no |
| carControl.actuators.accel / carOutput…accel | m/s² | longitudinal command (alpha long) | High | no |
| carControl.hudControl.leadDistanceBars | 1..4 | follow-distance personality as dash bars | High | no |
| carControl.cruiseControl.override | bool | gas override | High | path/HUD colour |

The gap between `actuators.torque` and `actuatorsOutput.torque` is the EPS ceiling clamp at work:
the EPS can deliver at most 1148 counts at 8 m/s and 620 counts above 14.5 m/s
(`CarControllerParams.EPS_CEILING_LOOKUP`). controlsd uses exactly this gap as
`steer_limited_by_safety`. It is the cleanest "how hard is steering working against its limit"
signal there is. The steering arc already shows the delivered half of it: `ui_state` divides
`actuatorsOutput.torque` by the rail for the current speed. What no widget shows is the request
that was cut off, or the torque controller's `saturated` flag.

### controlsState (100 Hz, controlsd)

| field | units | meaning | Mazda trust | shown |
|---|---|---|---|---|
| curvature | 1/m | current path curvature from the vehicle model (steering angle) | High | dev UI lateral accel |
| desiredCurvature | 1/m | what lateral control is aiming for | High | dev UI, steering arc |
| lateralControlState.torqueState.{output, saturated, actualLateralAccel, desiredLateralAccel, p, i, f} | −1..1, bool, m/s² | torque controller internals; `saturated` drives the "Turn Exceeds Steering Limit" alert | High | no (the alert only) |
| longControlState | enum | off, pid, stopping, starting | High | no |
| forceDecel | bool | DM or other forced slowdown | High | no |

### selfdriveState and selfdriveStateSP (100 Hz)

| field | meaning | shown |
|---|---|---|
| state, enabled, active, engageable | openpilot state machine | status colour |
| alertText1/2, alertStatus, alertSize, alertType, alertSound | the current alert; new widgets must yield to `alertSize != none` | alert renderer |
| experimentalMode, personality | driving mode and follow personality | exp button, personality |
| selfdriveStateSP.mads.{state, enabled, active, lateralHeld} | MADS lateral state | path colour |
| selfdriveStateSP.intelligentCruiseButtonManagement.{state, sendButton, vTarget} | ICBM servo | ICBM indicator |

### radarState (20 Hz, radard)

| field | units | meaning | Mazda trust | shown |
|---|---|---|---|---|
| leadOne/leadTwo.present | bool | a lead exists | High | chevron |
| dRel | m | gap from the front bumper | Alpha long: Medium (vision only, noisy past ~60 m). Stock long with tracks: High when `radar` is true | chevron, chevron metrics, dev UI |
| yRel | m, left positive | lateral offset | Medium | chevron position |
| vRel | m/s | closing speed (negative = closing) | Alpha long: Medium-Low, model-estimated; stock: High when radar-matched | dev UI, chevron colour |
| vLead, vLeadK, aLeadK | m/s, m/s² | lead speed and Kalman-filtered lead accel | Medium; aLeadK lags | dev UI "L.S." (vLead via vRel+vEgo) |
| modelProb | 0..1 | vision lead probability | Medium | no |
| radar, radarTrackId | bool, id | lead came from a radar track | High | no |
| radarErrors.* | bool | radar health | High | alerts |

`radarTracks` (20 Hz service, Mazda tracks arrive at 10 Hz) holds up to four raw points with
`dRel/yRel/vRel`. It is logged but **not subscribed by the UI**, and empty under alpha long.

### longitudinalPlan and longitudinalPlanSP (20 Hz)

| field | units | meaning | shown |
|---|---|---|---|
| aTarget | m/s² | the acceleration the planner wants now | no |
| speeds, accels, jerks | lists | plan over ~2.5 s | no |
| hasLead, fcw, shouldStop, allowThrottle, allowBrake | bool | planner flags; allowThrottle colours the path | path colour (allowThrottle) |
| longitudinalPlanSource | enum | cruise, lead0/1/2, e2e: who is limiting speed | no |
| SP.longitudinalPlanSource | enum | cruise, sccVision, sccMap, speedLimitAssist | no |
| SP.smartCruiseControl.vision.{state, vTarget, maxPredictedLateralAccel, vAheadMin} | enum, m/s, m/s² | curve speed control; `vAheadMin` is the lowest planned speed on the horizon | SCC icon |
| SP.speedLimit.resolver.{speedLimit, source, speedLimitOffset, speedLimitFinal…} | m/s, enum | resolved limit and where it came from (car or map) | speed-limit sign |
| SP.speedLimit.assist.{state, vTarget} | enum, m/s | speed-limit assist | SLA sign colour |
| SP.e2eAlerts.{greenLightAlert, leadDepartAlert} | bool | e2e chimes | circular alerts |
| SP.zoompilot.e2eSetSpeed / e2eLeadGap / leadForecast | authority, boost (m/s²), inhibit reason | zoompilot planner assists and why they are idle | no |

### driverMonitoringState and driverStateV2 (20 Hz, dmonitoringd and dmonitoringmodeld)

| field | units | meaning | shown |
|---|---|---|---|
| alertLevel, activePolicy (vision or wheeltouch) | enum | DM escalation and which policy is in charge | DM icon |
| visionPolicyState.{awarenessPercent, isDistracted, distractedTypes.{pose,eye,phone}, faceDetected, pose.{pitch,yaw}} | %, bool, rad | the awareness budget and why it is falling | DM icon colour, face arcs |
| wheeltouchPolicyState.awarenessPercent | % | hands-on budget | no |
| lockout, lockoutMinutesRemaining | bool, min | DM lockout | alerts |
| driverStateV2.leftDriverData.{faceOrientation, faceProb, phoneProb, sleepProb, sunglassesProb, left/rightBlinkProb} | rad, 0..1 | raw cabin model outputs | face arcs |
| wheelOnRightProb | 0..1 | RHD estimate | layout |

Ground rule: DM is read-only here. A widget may show `awarenessPercent`, but nothing may change
how it is computed or alerted.

### deviceState (2 Hz), pandaStates (10 Hz), peripheralState (2 Hz)

See [section 4](#4-device-data).

### GPS: gpsLocation (1 Hz) and gpsLocationExternal (10 Hz)

| field | units | meaning | trust | shown |
|---|---|---|---|---|
| hasFix, satelliteCount | bool, count | fix status | Medium | dev UI (validity only) |
| latitude, longitude, altitude | deg, m | position | Medium; altitude worse | dev UI "ALT." |
| speed, speedAccuracy | m/s | GNSS speed | Medium | no |
| bearingDeg, bearingAccuracyDeg | deg | heading; accuracy 180 means unknown | Medium above walking speed | dev UI "B.D." |
| horizontalAccuracy, verticalAccuracy | m | 1-sigma error | Medium | no |

The comma 3X has no u-blox, so `gpsLocationExternal` is probably absent and `gpsLocation` (the
modem's GNSS, 1 Hz) is the source. To confirm with `--mode services` on a log.

### Camera states (20 Hz each)

`narrowRoadCameraState`, `wideRoadCameraState` (subscribed) and `cabinCameraState` (not
subscribed): `frameId`, `timestampEof`, `exposureValPercent`, `gain`, `measuredGreyFraction`,
`temperaturesC`, `sensor`. Useful for "camera is struggling" hints (low light, glare: exposure
pinned high or low). The video itself comes over VisionIPC, which the reverse view already uses.

### Others already subscribed

| service | rate | what is in it | shown |
|---|---|---|---|
| extrinsicsCalibration | 4 Hz | calibration status and angles, see section 5 | path projection |
| vehicleParameters | 20 Hz | learned steer ratio, roll, see section 5 | dev UI (roll) |
| lateralTorqueParameters | 4 Hz | learned torque model, see section 5 | dev UI "FRIC." "L.A.F." |
| lateralDelay | 4 Hz | learned steering lag | steering arc (time offset) |
| liveMapDataSP | 1 Hz | OSM speed limit, limit ahead with distance, road name | speed-limit sign, road name |
| modelDataV2SP | 20 Hz | lane-turn direction, lane-change edge blocks, accelerator state | lane-change hints |
| onroadEvents | 1 Hz | the active event list | alerts |
| managerState | 2 Hz | running processes | no |
| carParams / carParamsSP | rare | fingerprint, flags, alpha long, maxLateralAccel | gating |
| rawAudioData | 20 Hz, not logged | raw microphone PCM | no tici widget |

## 2. Useful services the UI does not subscribe to yet

| service | rate | what it gives a widget | notes |
|---|---|---|---|
| deviceMotion | 20 Hz | `accelerationDevice.{x,y,z}` (m/s², device frame), `angularVelocityDevice` (rad/s), `orientationNED` (roll, pitch, yaw rad), `velocityDevice` (m/s), each with a std and `valid` | the clean source for live G-forces, pitch (hill grade) and roll; `inputsOK`/`sensorsOK` gate it. `accelerationDevice` is the rate of change of device velocity with gravity removed; the pose filter models the centripetal part separately (`pose_kf.py`), so cornering G is `accelerationDevice.y + angularVelocityDevice.z × velocityDevice.x` |
| accelerometer | 104 Hz | raw IMU acceleration `acceleration.v[3]` | includes gravity and mounting tilt; deviceMotion is the processed version |
| gyroscope | 104 Hz | raw angular rate `gyro.v[3]` | |
| temperatureSensor | 2 Hz | IMU temperature | |
| soundPressure | 10 Hz | `soundPressureWeightedDb`, A-weighted, uncalibrated | cabin noise level from micd; logged |
| radarTracks | 10 Hz on Mazda | up to four raw radar points | empty under alpha long |
| cameraOdometry | 20 Hz | visual odometry trans/rot with std | input to locationd; rarely useful directly |
| drivingModelData | 20 Hz | `laneLineMeta.{leftY, rightY, leftProb, rightProb}` near-field lane offsets, compact path polynomial | the cheapest lane-position source |
| driverAssistance | 20 Hz | `leftLaneDeparture`, `rightLaneDeparture` | openpilot's LDW decision |
| customReserved19 | 4 Hz | zoompilot torque speed bins: per-bin latAccelFactor, friction, valid | the speed-dependent learner |
| procLog | 0.5 Hz | per-process CPU and memory | |
| cabinCameraState | 20 Hz | cabin exposure | |
| can | 100 Hz | every CAN frame; see below | heavy |

Adding a service to the UI means appending it to `sm_services_ext` in
`selfdrive/ui/sunnypilot/ui_state.py`, a one-line hook.

## 3. Mazda car data

### Parsed today

`carstate.py` and `carstate_ext.py` read these and nothing else:

| message (bus) | signals read | ends up in |
|---|---|---|
| WHEEL_SPEEDS (0) | FL FR RL RR | vEgo, wheelSpeeds |
| ENGINE_DATA (0) | SPEED, PEDAL_GAS | standstill, gasPressed (bool only) |
| GEAR (0) | GEAR, BRAKE_HOLD | gearShifter, body hold (internal) |
| EPB (0) | HOLD_STATE | body hold (internal) |
| BLINK_INFO (0) | HIGH_BEAMS, LEFT_BLINK, RIGHT_BLINK | genericToggle, blinkers |
| BSM (0) | LEFT_BS_STATUS, RIGHT_BS_STATUS | left/rightBlindspot (as ≠ 0) |
| STEER (0) | STEER_ANGLE | steeringAngleDeg |
| STEER_TORQUE (0) | STEER_TORQUE_SENSOR, STEER_TORQUE_MOTOR | steeringTorque, steeringTorqueEps |
| STEER_RATE (0) | STEER_ANGLE_RATE, LKAS_BLOCK, LKAS_EFFECTIVE, LKAS_TRACK_STATE, LKAS_FAULT, LKAS_REQUEST | steeringRateDeg; the rest stay inside carstate (fault logic) |
| PEDALS (0) | BRAKE_ON, ACC_OFF, ACC_ACTIVE, STANDSTILL | brakePressed, cruise state |
| SEATBELT (0) | DRIVER_SEATBELT | seatbeltUnlatched |
| DOORS (0) | FL FR BL BR | doorOpen |
| CRZ_CTRL (0) | CRZ_AVAILABLE, CRZ_ACTIVE (stock long only) | cruiseState |
| CRZ_EVENTS (0) | CRZ_SPEED | cruiseState.speed |
| CRZ_BTNS (0) | every button | buttonEvents |
| CRZ_INFO, RADAR_UDS_RESPONSE (0) | liveness and session replies | radar takeover (internal) |
| CAM_LANEINFO (2) | LANE_LINES, ERR_BIT, NO_ERR_BIT, TJA, BIT2 | invalidLkasSetting, stock TJA and high-beam request (internal) |
| CAM_SETTINGS (2) | LKAS_INERVENTION_ON1/2 | lane-keep setting |
| CAM_LKAS (2) | ERR_BIT_1 | steerFaultPermanent |
| CAM_EMPTY, CAM_PEDESTRIAN (2) | STATUS, PED_WARNING, BRAKE_WARNING | stockFcw |
| CAM_TRAFFIC_SIGNS (2) | SPEED_SIGN, SPEED_SIGN_UNIT | carStateSP.speedLimit |
| RADAR_361..364 (0) | DIST_OBJ, ANG_OBJ, RELV_OBJ | radarTracks (stock long only) |

Two things carstate decodes and then throws away are worth a widget: **LKAS_EFFECTIVE**, the
torque the EPS actually applied (vs LKAS_REQUEST, what it was sent), and **LKAS_BLOCK /
LKAS_TRACK_STATE**, the EPS's own "not steering now" state. `mazda-lateral.md` shows a blocked
2022 EPS still delivers a third to a half of the request above 4 m/s. Nothing outside carstate
can see either today.

### In the DBC, never read

Rates are unknown unless stated; the dump script measures them. Trust is **Unknown** for every
row: these are reverse-engineered names, several with "MAYBE" or "tbd" in them, and none has
been validated against a known event on this car.

| signal | DBC scaling | what it probably is | why a driver might care |
|---|---|---|---|
| BRAKE.BRAKE_PRESSURE (0x78) | raw 0..255 | brake line pressure | brake-pedal gauge, "how hard did I brake" |
| BRAKE.VEHICLE_ACC_X / _Y (0x78) | 0.01 / 0.001 m/s², ±40 / ±4.1 | the car's own longitudinal and lateral accelerometer (DSC module) | G-meter from the car, no device-mount error; Y range is only ±0.42 g |
| ENGINE_DATA.RPM (0x202) | 0.25 rpm | engine speed, 100 Hz | tachometer, shift/eco hints |
| ENGINE_DATA.PEDAL_GAS (0x202) | raw, "%" | accelerator position (only > 0 is used) | throttle bar, smooth-driving score |
| GEAR.GEAR_BOX (0x228) | 0 P, 14 R, 1..6 D, 15 shifting | the gear the automatic is in | gear indicator |
| CHECK_AND_TEMP.COOLANT_TEMP / OUTDOOR_TEMP (0x420) | raw / 0.25 °C −63 | engine coolant and ambient temperature | ice warning, warm-up |
| CHECK_AND_TEMP.LOW_ENGINE_OIL_PRESSURE, CHARGING_SYSTEM_MALFUNCTION, CHECK_FUEL_CAP | bool | dash warnings | duplicate the dash; low value |
| TEMPERATURE.TEMPERATURE_MAYBE (0x4d6) | raw | unknown temperature | needs a log |
| NEW_MSG_3.MILAGE_MAYBE (0x4fe) | raw | maybe odometer | trip distance cross-check |
| BSM.LEFT/RIGHT_BS_STATUS value 2 (0x477) | enum | "object in blind spot with blinker on: warning" vs 1 "object present" | a two-level blind-spot widget for free: carstate collapses both to true |
| BSM.REAR_CT_ALERT (0x477) | 5 bits | rear cross-traffic alert | reverse view overlay |
| BSM.LEFT_BS_BEHIND, RIGHT_BS_DISTANCE, LEFT_BS_SIDE, LEFT_BS3, RIGHT_BS4 (0x477) | bits | position of the object in the zone | approaching vs alongside |
| BSM.BSM_OFF (0x477) | bool | BSM switched off | show "BSM off" so no-indicator does not read as clear |
| BLINK_INFO.LOW_BEAMS, WIPER_LO/HI, REAR_WIPER_ON (0x9a) | bits | lights and wipers | "raining" hint, wipers as a confidence cue |
| TURN_SWITCH.HAZARD (0x91) | bool | hazard switch | |
| DOORS.LEFTGATE, DOORS_UNLOCKED, KEYFOB_* (0x43e) | bits | liftgate, lock state | offroad info |
| SEATBELT.PASSENGER_SEATBELT (0x340) | bool | passenger belt | |
| TRACTION.DSC_OFF, BRAKE, ABS_MALFUNCTION, TCS_DCS_MALFUNCTION, TPMS_WARNING_DOUBLE_BLINK (0x415) | bits | stability control off, brake light, faults, TPMS | "DSC off" banner |
| STEER_RATE.HANDS_OFF_5_SECONDS (0x241) | bool | EPS hands-off timer (legacy firmware lockout) | |
| CRZ_CTRL.DISTANCE_SETTING, RADAR_HAS_LEAD, RADAR_LEAD_RELATIVE_DISTANCE, HANDS_ON_STEER_WARN (0x21c) | enums | stock radar's follow setting and lead bars | only meaningful with the stock radar running |
| RADAR_DISTANCE etc. 0x361..0x366 | m, deg, m/s | radar tracks; 0x365/0x366 have an undecoded RELV encoding | stock long only |
| CAM_TRAFFIC_SIGNS.SPEED_SIGN_CAM (0x35f) | bool | 1 camera-recognised, 0 map-based | tell the driver where the limit came from |
| CAM_TRAFFIC_SIGNS.STOP_SIGN (0x35f) | 4 bits, 9 = active | the camera sees a stop sign | stop-sign icon |
| CAM_TRAFFIC_SIGNS.FORWARD_COLLISION (0x35f) | 8 bits | camera FCW state | |
| CAM_LANEINFO.LINE_VISIBLE, LINE_NOT_VISIBLE, LDW_WARN_LL/RL, HANDS_WARN_3_BITS, HANDS_ON_STEER_WARN (0x440, ~2 Hz) | bits | the stock camera's lane view and its warnings | stock-camera lane confidence next to the model's |
| CAM_LANETRACK.LANE_CURVE, LINE1, LINE2 (0x242) | raw | camera's lane curvature and line offsets | comparison with the model |
| CAM_LKAS.LDW, LINE_NOT_VISIBLE (0x243) | bits | camera LDW and line loss | |
| CAM_SETTINGS.SBS_WARNING_DISTANCE, SBS_SCBC, LANEE_DEPARTURE_ALERT, LKAS_SENSETIVITY, WARNING (0x485) | enums | the car's own driver-assist settings menu | show the car's configured warning distance |
| CAM_DISTANCE (0x244) | four byte pairs | possibly an object list; `tools/mazda_long/cam_distance_slots.py` tests this | unknown |

### Getting unpublished CAN to the UI

There are two ways, and the choice is yours because one of them touches a driving process.

1. **Decode in the UI (display-only, no driving code touched).** Subscribe the UI to `can`,
   drain every message each frame, and decode only the handful of addresses a widget needs with
   `opendbc.can.dbc` + `get_raw_value` (what `dump_fields.py` does). Cost: `can` is 100 messages a
   second carrying every frame on three buses, and the UI is single-threaded Python at 20 fps. A
   filter on address before decoding keeps it to a few thousand dictionary lookups a second, but
   it has to be measured on the device. It also skips the parser's checksum and counter checks
   unless the widget re-implements them.
2. **Publish from carstate into CarStateZP (cheap at runtime, touches the car port).** Add fields
   to `CarStateZP` in `custom.capnp` and fill them in carstate, where the parser already runs. It
   does not change any command the car receives, but it edits card's code path and the shared
   schema, so it is outside "display only" as written. I will not do this without your go-ahead.

## 4. Device data

| source | field | units | meaning | trust | shown |
|---|---|---|---|---|---|
| deviceState | thermalStatus | enum ok/overheated/critical | thermald's verdict; drives the offroad throttle | High | sidebar (offroad) |
| deviceState | maxTempC | °C | the max of the temperatures, controls the fan | High | sidebar temp |
| deviceState | cpuTempC[], gpuTempC[], memoryTempC, dspTempC, pmicTempC[], intakeTempC, exhaustTempC, bottomSocTempC, modemTempC[] | °C | individual sensors | High | no |
| deviceState | fanSpeedPercentDesired | % | fan command | High | no |
| deviceState | powerDrawW, somPowerDrawW | W | whole device and SoC power | High | no |
| deviceState | cpuUsagePercent[] (per core), gpuUsagePercent, memoryUsagePercent | % | load | High | no |
| deviceState | freeSpacePercent | % | storage free | High | offroad alert |
| deviceState | networkType, networkStrength, networkStats | enum, bytes | connectivity | High | sidebar |
| deviceState | screenBrightnessPercent | % | backlight | High | no |
| peripheralState | voltage, current, fanSpeedRpm | mV, mA, rpm | car 12 V as seen by the panda, measured fan speed | High | no |
| pandaStates[0] | voltage, current, harnessStatus, ignitionLine/Can, controlsAllowed(Lateral/Longitudinal), safetyTxBlocked, safetyRxInvalid, canState0..2.{totalErrorCnt, busOff, …}, faults | | panda health | High | alerts only |
| soundPressure | soundPressureWeightedDb | dB, uncalibrated | cabin noise | Medium: relative only | no |
| modelV2 / drivingModelData | modelExecutionTime, frameDropPerc | s, % | model health | High | no |
| GPS | hasFix, satelliteCount, horizontalAccuracy | | fix quality | Medium | dev UI |

Note `peripheralState.voltage` is the car battery as the harness sees it: a cheap "12 V battery"
gauge for idling.

## 5. Model outputs (modelV2, 20 Hz)

All positions are in the device frame: x forward, y right, z down, in metres. Times are the
model's 33-point horizon out to 10 s.

| field | units | meaning | trust | shown |
|---|---|---|---|---|
| laneLines[0..3] (x, y, z, t) | m | far-left, left, right, far-right lane lines | Medium | lane lines |
| laneLineProbs[4] | 0..1 | how sure the model is each line exists | Medium: the honest confidence number for lane widgets | line alpha |
| laneLineStds[4] | m | lateral uncertainty of each line | Medium | no |
| roadEdges[2], roadEdgeStds[2] | m | left and right road edges and their uncertainty | Medium | edge alpha |
| position / velocity / acceleration / orientation / orientationRate (x, y, z, t, std) | m, m/s, m/s², rad, rad/s | the predicted ego trajectory | Medium | path; acceleration.x colours the path in experimental mode |
| leadsV3[0..2].{prob, probTime, t, x, y, v, a and stds} | 0..1, m, m/s, m/s² | three lead hypotheses at 0, 2 and 4 s; x is the gap | Medium | via radarState |
| action.{desiredCurvature, desiredAcceleration, shouldStop} | 1/m, m/s², bool | the model's own control output | Medium | no |
| meta.engagedProb | 0..1 | model's belief openpilot is engaged | Low use | no |
| meta.desirePrediction, desireState | 0..1 per desire | lane change and turn desires | Medium | no |
| meta.laneChangeState, laneChangeDirection | enum | lane-change state machine | High | lane-change UI |
| meta.hardBrakePredicted | bool | the 3 and 5 m/s² hard-brake probabilities have stayed above their FCW thresholds for several frames | Medium | no (feeds FCW logic) |
| meta.disengagePredictions.{t, brakeDisengageProbs, gasDisengageProbs, steerOverrideProbs, brake3/4/5MetersPerSecondSquaredProbs, gasPressProbs, brakePressProbs} | 0..1 at several horizons | the model's guess the driver is about to intervene, or that hard braking is coming | Medium, uncalibrated per car | no |
| confidence | red / yellow / green | a 10 s rolling score of any-disengage probability (brake, gas or steer override), thresholded | Medium | no |
| frameDropPerc, modelExecutionTime, big | %, s, bool | model health | High | big model badge |

drivingModelData (20 Hz, not subscribed) repeats the near-field lane geometry as four numbers:
`laneLineMeta.leftY/rightY` (m) and `leftProb/rightProb`. Lane width is `rightY − leftY` and the
offset from lane centre is `(leftY + rightY) / 2`. That is all a lane-position widget needs.

## 6. Learned values

| source | field | units | meaning | trust | shown |
|---|---|---|---|---|---|
| lateralTorqueParameters | latAccelFactorFiltered, frictionCoefficientFiltered, latAccelOffsetFiltered | m/s² per unit torque, unitless, m/s² | torqued's live fit of the steering model | High once `valid`; `calPerc` shows progress | dev UI "L.A.F." "FRIC." |
| lateralTorqueParameters | valid, useParams, calPerc, totalBucketPoints | | learner progress | High | no |
| customReserved19 | speedBinCenters, speedBinLatAccelFactors, speedBinFrictions, speedBinValid | m/s, … | zoompilot's speed-dependent learner | High | no |
| lateralDelay | lateralDelay, lateralDelayEstimate(Std), status, calPerc | s | learned command-to-motion lag (0.338 s total on a CX-5 2022) | High once estimated | steering arc timing |
| vehicleParameters | steerRatio(Std), stiffnessFactor(Std), angleOffsetDeg, angleOffsetAverageDeg, roll, valid | ratio, deg, rad | paramsd: learned steer ratio, tire stiffness, wheel-angle offset, road bank | High once valid | dev UI (roll in lateral accel) |
| extrinsicsCalibration | calStatus, calPerc, rpyCalib, rpyCalibSpread, height, wideFromDeviceEuler | enum, %, rad, m | how the device is mounted | High | path projection; calibration alert |
| deviceMotion | orientationNED (roll, pitch) | rad | road grade and bank as the car experiences them | Medium | no |

What these say about the car and driver: a drifting `angleOffsetAverageDeg` means alignment or a
crowned road; `steerRatio` should sit near 18.1 on the CX-5; `roll` is road bank; a changing
`latAccelFactor` across speed bins is the EPS's speed-dependent assist showing through.

## 7. The dump script

`tools/boom_boom/dump_fields.py` prints chosen fields from an rlog, a folder of segments, or a
route id. It reads only. It has the catalog's fields built in as presets: car, control, lead,
model, dm, device, learned and can. Plain rlogs and folders work anywhere with pycapnp and
zstandard; route ids need openpilot's LogReader, so WSL or the device.

```bash
# everything in the catalog, as a distribution per field with the measured rate
python tools/boom_boom/dump_fields.py /data/media/0/realdata/<route>--5/rlog.zst

# which services are in the log and at what rate (confirms GPS source, deviceMotion, etc.)
python tools/boom_boom/dump_fields.py <segment dir> --mode services

# the unpublished Mazda CAN signals, with derived EPS delivery ratio
python tools/boom_boom/dump_fields.py <segment dir> --preset can

# a 2 Hz timeline of chosen fields to CSV
python tools/boom_boom/dump_fields.py <route dir> --mode timeline --every 0.5 --csv out.csv \
  --only-fields --field carState.vEgo --field derived.ttc --field can0:BRAKE.BRAKE_PRESSURE

# discover every field of one service
python tools/boom_boom/dump_fields.py <rlog> --mode list --service deviceMotion
```

Field specs are `service.path`, with `[i]` to index a list and `:max`, `:min`, `:mean` or `:len`
to reduce one. `can0:MSG.SIGNAL` decodes a mazda_2017 signal from bus 0, `can2:` from the camera
bus. `derived.*` are computed in the script: `ttc`, `headway`, `closingSpeed`, `laneWidth`,
`laneCenterOffset`, `latAccel`, `gLong`, `gLat` and `epsDelivery` (LKAS_EFFECTIVE / LKAS_REQUEST
when the request is over 200 counts). CAN signals need rlogs: qlogs keep only a few `can`
messages per segment.

The script was checked against a synthetic log only; it has not yet read a real drive.

## 8. Feature ideas, ranked by usefulness to a driver

Size: **S** is one widget file and a toggle (a day or less), **M** adds state over time or a new
subscription, **L** needs CAN decoding in the UI or design work with you first.

| # | feature | what the driver gets | data | size |
|---|---|---|---|---|
| 1 | **Real time-to-collision and closing-speed bar** | A bar under the lead chevron that fills and turns amber then red as TTC drops below about 4 s and 2.5 s, plus the closing speed. Only drawn while actually closing, so it stays quiet in steady following. Fixes the misleading "TTC" label next door. | radarState.leadOne.{present, dRel, vRel, radar, modelProb}, carState.vEgo | S |
| 2 | **Steering-limit meter** | The steering arc already shows delivered torque against the speed's rail. This adds what it cannot: the part of the request that was cut off, drawn past the end of the arc, and a red edge while the torque controller reports `saturated`. Explains the "Turn Exceeds Steering Limit" moments, which you now silence, as they build. Could extend the arc rather than add a second widget. | carControl.actuators.torque, carOutput.actuatorsOutput.torque, controlsState…torqueState.saturated, carState.vEgo, the rail from `get_steer_rail_schedule` | S |
| 3 | **Lane-confidence and lane-position strip** | Two small bars for left and right line confidence, plus a marker for where the car sits in the lane, so the driver sees the model losing a line before lateral gets vague. | modelV2.laneLineProbs, laneLineStds, roadEdgeStds, drivingModelData.laneLineMeta (one-line subscription) | S |
| 4 | **Blind-spot history** | Each side's BSM indicator leaves a fading trail for a few seconds after the car clears, and a counter of recent detections. Helps when the BSM lamp blinked while the driver was looking ahead. | carState.left/rightBlindspot, left/rightBlinker | S |
| 5 | **Live G-force dot** | A friction-circle dot with a short trail and the session peak. Smooth-driving feedback. | deviceMotion acceleration, yaw rate and velocity (new subscription); carState.aEgo and curvature·v² as fallback | M |
| 6 | **Model "about to intervene" warning tint** | A subtle border tint when the model's own brake-disengage or hard-brake probability rises, a heads-up that is not an alert and never overlaps one. | modelV2.meta.disengagePredictions, hardBrakePredicted, confidence | S (needs tuning on real logs) |
| 7 | **Trip efficiency and smoothness card** | Distance, average speed, share of distance engaged, hard-brake and hard-accel counts, best/worst jerk. Shown at the end of a drive or on demand. | carState.vEgo, aEgo, selfdriveState.enabled, selfdriveStateSP.mads, carControl.latActive; ideally PEDAL_GAS and RPM | M (L with CAN) |
| 8 | **Why-is-it-slowing indicator** | A small label for what is limiting speed right now: lead, curve, speed limit, model, cruise. Explains a slowdown in one glance. | longitudinalPlan.longitudinalPlanSource, longitudinalPlanSP.longitudinalPlanSource, smartCruiseControl.vision.state, speedLimit.assist.state | S |
| 9 | **Two-level blind spot and cross-traffic in reverse** | Distinguish "car in blind spot" from "car in blind spot and you signalled", and show rear cross-traffic on the reverse view. | BSM.LEFT/RIGHT_BS_STATUS (value 2), BSM.REAR_CT_ALERT; needs the CAN path decision | L |
| 10 | **Device health chip** | A tiny chip that appears only when something is off: thermal throttling, model frame drops, CAN errors, GPS lost. | deviceState.thermalStatus, maxTempC, modelV2.frameDropPerc, pandaStates canState errors, GPS hasFix | S |

Other ideas that did not make the list: a brake-pressure gauge, tachometer and gear indicator
(all need the CAN decision), a cabin-noise meter from soundPressure, road grade from deviceMotion
pitch, a "stock camera vs model" lane comparison, and an awareness-budget bar from DM.

## 9. Open questions for you

1. **Which car is it, and do you run alpha long?** With alpha long every lead number is vision-only,
   which changes how much to promise from ideas 1 and 8.
2. **CAN path:** are you happy for the UI to subscribe to `can` and decode a few addresses itself
   (display-only, some CPU cost), or would you rather publish a few fields from carstate through
   `CarStateZP`? Ideas 9, part of 7 and the gauges depend on this.
3. **A route or rlog from your car**, so this catalog can carry real ranges and rates instead of
   nominal ones. An rlog, not a qlog, for the CAN signals.
4. **Which ideas to build**, in what order. Each will be one commit on boom-boom, off by default
   under Settings > Visuals.



## install boom-boom fork
When your comma device asks for a custom software URL during setup, type:
```
paradeofbears/boom-boom
```

## boom-boom changelog

boom-boom is my experimental branch of zoompilot, mostly new things to look at on the driving screen. Every feature below is **off by default**: the screen features switch on in **Settings > Visuals**, the sound ones in **Settings > Sounds**. They only display information or adjust sounds: none of them changes how the car steers, brakes or accelerates, and real alerts always draw on top of them. Newest first.

- **Lead-time shift lights.** The shift lights flash when the revs, at the rate they are climbing, would reach the redline within 0.6 s: early on a hard pull in 1st and 2nd, close to the redline in higher gears. You can pick a fixed shift point instead. The redline is set to 6,300 rpm, read off the 2022 CX-5 Turbo's tachometer. *Inspiration: the predictive shift lights on race cars, which warn before the limiter, not at it.*
- **Shift lights and shift chime.** With the lever in the M gate, a row of ten dots above the speed fills green, amber and red, then flashes blue when it is time to shift, with the gear shown as "M3". An optional short beep at the shift point plays only when no alert sound is playing. The engine speed, gear and manual-mode signals come straight from the car's CAN bus, mapped from my own drive logs. *Inspiration: LED shift lights on F1 and GT race car steering wheels.*
- **Drive rank and arcade points.** Choose a Safety or Chaos style. The Park summary grades your own driving S to D, and a running score in the thousands, with pops like "+30,000 LAUNCH" and combo multipliers, sits beside the speed. Only stretches where you set the speed count. Tailgating costs points in both styles, and speed is never rewarded. *Inspiration: the S-rank grades and combo scoring of arcade and action games.*
- **Mini-map.** A small round map in the bottom-left corner that turns with the car, drawn from the OpenStreetMap data downloaded for speed limits, with the road you are on highlighted and the zoom widening with speed. *Inspiration: the radar mini-map in Grand Theft Auto.*
- **Failure guard.** If any of these widgets hits an error, that widget switches itself off for the rest of the drive instead of taking the driving screen, and its alerts, down with it. *Inspiration: keeping experiments from ever costing the warnings that matter.*
- **Lane awareness.** An amber glow on the left or right edge of the screen while the blind-spot monitor sees a car there, pulsing if your blinker points into it. Under the lead car, a bar shows your time gap against your follow-distance setting, with a closing or opening arrow and BRAKING when the car ahead slows hard. *Inspiration: a three-lane "can I move over?" readout, drawn where your eyes already are.*
- **Traffic box.** A small top-down map of the cars openpilot knows about: the cars ahead as dots, the lane lines, and the blind-spot zones beside you. *Inspiration: the TRAFFIC box in Sega's Daytona USA.*
- **Trip summary in Park.** Shift into Park after a drive and a card shows distance, time, average and top speed, how much openpilot steered, disengagements, hard brakes and starts, smoothness, and the climb and descent from GPS. *Inspiration: the results screen at the end of a race in a driving game.*
- **G-force meter.** A friction circle in the corner: a dot for how hard the car is accelerating, braking and cornering, a short trail, and a ring at the drive's peak. *Inspiration: the G-meter in motorsport telemetry and track-day apps.*
- **Calmer steering arc.** Replaces the always-on steering arc with one that stays hidden in ordinary steering and fades in only as the steering nears what the motor can deliver at that speed, turning red and showing any request that was cut off. *Inspiration: the stock arc was distracting; this one only appears when it means something.*
- **Why the car is slowing.** Under openpilot longitudinal control, a small label under the speed names what is holding the car below its set speed: a car ahead, a curve, the speed limit, a stop, the model's pace or a lowered set speed. *Inspiration: wondering "why is it slowing down?" mid-drive.*
- **Data catalog and log tool.** A written inventory of every signal, sensor and model output the screen could use on a Mazda ([docs/boom-boom/data-catalog.md](docs/boom-boom/data-catalog.md)), and a script that dumps them from a drive log. *Inspiration: finding out what the car actually knows before deciding what to show.*
- **Cameras in reverse.** In reverse, the wide road camera and the cabin camera show side by side instead of the full-screen Reverse banner. *Inspiration: a quick extra look while backing out.*
- **Silence the steering-limit chime.** A switch that mutes only the sound of "Turn Exceeds Steering Limit"; the banner still shows. *Inspiration: a frequent chime on curvy roads.*
- **Per-alert volumes.** Set the volume of each alert sound separately, with a floor on the warnings that ask you to act. *Inspiration: FrogPilot's alert volume settings, ported over.*

# zoompilot

A Mazda-optimized fork of [sunnypilot](https://github.com/sunnypilot/sunnypilot) for the CX-5 and CX-9. My goal is to enable the best steering possible and support all sunnypilot features on the 2022-2025 CX-5, staying within openpilot's safety guidelines.

This is what I run on my own 2022 CX-5 every day. There's a nicer tour of all of this at [zoompilot.ai](https://zoompilot.ai).

<a href="https://zoompilot.ai/screens/mici-demo.mp4"><img src="https://zoompilot.ai/screens/mici-demo.webp" width="100%" alt="zoompilot on the device: the Mazda defaults already on (the Firehose model, torque control, the v2.0 steering tune, speed-dependent self-tune), then turning on ICBM and Smart Cruise"></a>

## Install

When your comma device asks for a custom software URL during setup, type:

```
zoompilot/main
```

`main` carries the releases, built ahead of time so the device doesn't have to compile on install. `develop` is where the day to day work lands if you want it earlier. Devices installed from my old personal fork move themselves to `main` on their next start.

**This is experimental software.** You drive the car, you follow the law where you live, and you carry the risk. It ships with no warranty and no liability for any damage or injury.

## steering improvements

Using a data driven approach I reverse engineered the steering hardware and developed features to use the EPS to its full potential.

- **Speed-dependent torque.** The EPS caps the steering torque it will deliver, and that cap changes with speed. We encode the whole curve, so openpilot knows the extra torque it has at low speeds and the reduced torque at high speeds. More confident in the neighborhood, fewer wobbles on the highway.
- **Speed-dependent tuning.** Stock openpilot learns ONE lateral acceleration factor and ONE friction value for every speed. We let it learn across seven speed ranges instead, matching the EPS's non-linear speed-dependent behaviour.
- **Rate-matched commands.** The EPS accepts steering commands changing by up to 12 units a frame; stock asked for 10, leaving ~17% of that rate unused. We ask for the full 12, so torque ramps in faster.
- **Factory-matched specs.** Steering ratio, mass, wheelbase, and steering lag, set to Mazda's real figures and refined against thousands of miles of learned data, so commands land where the planner intends.

## fix annoyances

The stock port threw warnings that should have only applied to pre-2022 cars. I pulled the logs from many drivers and cut the false ones. The real ones still fire.

- **Place hands on wheel alert.** The Mazda port was built on pre-2022 cars, where an LKAS_BLOCK signal meant steering control was lost. Across thousands of logged miles from many drivers, we found 2022+ EPS keeps steering through LKAS_BLOCK. It mostly fires near a stop, or when stock LKAS loses the lane lines. Real faults still disengage; we just stopped alerting when the car is still steering.
- **Steering override hysteresis.** The same override filter Hyundai, Ford, Tesla, and Rivian run. It weighs more frames before deciding you've taken the wheel, so a pothole or rough patch no longer trips a phantom takeover.

## wire up sensors

Your CX-5 ships with sensors the stock port never reads. We wire them in.

- **Forward radar.** A radar behind the front badge runs the factory cruise. We read it too: distance, angle, and closing speed for up to four cars ahead, fused with the camera. Braking and throttle stay factory.
- **Blind-spot monitors.** The factory blind-spot sensors already watch the lanes beside you. We feed what they see into openpilot before every lane change.
- **Speed-limit signs.** The camera already reads posted limits for your dash. We route those into speed-limit assist, which can set your cruise to match, so you're not re-dialing at every sign.

## radar cruise enhancements

The CX-5 keeps its factory cruise; zoompilot can set the speed for you by 'pressing' your wheel buttons.

- **Fixed ICBM.** sunnypilot's Intelligent-Cruise-Button-Management and Smart-Cruise are broken for Mazda. I rebuilt how zoompilot works your wheel buttons. The speed you dial is remembered exactly: curves and speed limits can borrow it for a while, but you get your number back, never one or two under it. If the car misses a press, it quietly catches up.
- **Speed-limit assist that sticks.** When the car sees a new limit, the screen asks once. Tap minus to accept a lower one and zoompilot dials the car down for you. It used to forget your answer a moment later; now it holds until the road changes. Press plus while it has you at a limit and it steps aside until the next sign. Your buttons always win.
- **Slow for Curves.** sunnypilot's Smart Cruise: it reduces your set speed before a curve in the road and sets it back after. You can use vision or downloaded maps to determine when to slow down. Enable it in the cruise settings menu.
- **Deceleration overshoot.** The Mazda's cruise control brakes according to how far the set speed sits below the car's speed, so for a curve zoompilot holds the set speed the measured gap below your actual speed that gives the braking the curve needs, then lands it on the curve's speed. Always on for Mazda; no setting.

## additional Mazdas covered

Not just the CX-5.

- **EPS swaps.** Swapped a 2022+ CX-5 steering rack into an older Mazda? We fingerprint the rack by its firmware, not by the car openpilot thinks you're driving, and steer it all the way to a stop.
- **CX-9.** Supported for all features, but speed-dependent torque will take longer to learn since I only supply seeds for the CX-5. The CX-9 specs are also updated to match Mazda's official figures.

## recommended setup

1. Factory-reset the device before you install. A clean device carries no stale settings from a previous fork.
2. Pick a driving model. I run Firehose. DTRv6 is a favourite and MacroStiff is great at high speed.
3. Under steering: turn on torque control, then self-tune, then speed-dependent self-tune.
4. Leave custom tune and manual real-time off. Let the car teach the software. That's the point.

Want to slow down for curves? Under cruise, turn on intelligent cruise button management, then turn on slow for curves: vision, map, or both. Maps need a region downloaded through SunnyLink first.

You can manage almost all of it from the device screen. No laptop, no cloud editor. SunnyLink still works if you like it.

## issues

Something misbehaving on your Mazda? Open an issue on the [tracker](https://github.com/zoompilot/zoompilot/issues). A route ID or dashcam clip helps a lot.

## credits

zoompilot stands on [sunnypilot](https://github.com/sunnypilot/sunnypilot), which stands on [openpilot](https://github.com/commaai/openpilot) by comma.ai. Most of the code here is theirs. Remote access and dashboards come from [sunnylink](https://www.sunnylink.ai/), a free service paid for by the sunnypilot project. To support them: [sponsor sunnypilot](https://github.com/sponsors/sunnyhaibin), or [buy hardware from comma](https://comma.ai/shop).

## license

This project uses software from Haibin Wen and SUNNYPILOT LLC and is licensed under a custom license requiring permission for use. See [LICENSE.md](LICENSE.md) for sunnypilot's terms, [LICENSE](LICENSE) for openpilot's, and [NOTICE.md](NOTICE.md) for how they stack up and what zoompilot's own files are under.

---

These features would work on other vehicles and could be upstreamed into sunnypilot or openpilot. I'm slowly working on that, but it's easier to share my own fork in the meantime.

Mazda, comma.ai, and the sunnypilot project neither endorse this nor have anything to do with it.

zoom-zoom-zoom

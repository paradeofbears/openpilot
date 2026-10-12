# Adding boom-boom to an openpilot build

boom-boom is a set of display-only extras for openpilot's onroad screen: a trip summary with a drive rank and
map, a G-force meter, a calmer steering arc, lane awareness, a traffic box, a mini-map, a reason label for
slowing down, shift lights with a chime, and cameras in reverse. None of it changes what the car does. It
reads messages that are already published and draws on top of the HUD. Real alerts still draw over every
widget.

Everything lives in this one folder. The folder holds its own settings, so a port needs **no params,
no `params_keys.h` edit and no C++ rebuild**. A port is the folder plus a few short hooks.

## Requirements

- The Python raylib UI (`selfdrive/ui`, `system/ui`). It is designed for the comma 3X at 2160×1080.
- Stock openpilot or sunnypilot, recent enough to have `system/ui/widgets/list_view.py` and the raylib
  settings layout.

## 1. Copy the folder

Copy `selfdrive/ui/boom_boom/` into the same place in the target tree. Inside the package, imports are
relative. `compat.py` handles what differs between builds: `openpilot.cereal` versus `cereal`, and
sunnypilot's extra services and widgets.

## 2. Draw the widgets (required)

Hook into the HUD renderer: `selfdrive/ui/onroad/hud_renderer.py` on stock, or
`selfdrive/ui/sunnypilot/onroad/hud_renderer.py` on sunnypilot. Create the overlay once and render it
**last** in `_render`.

```python
from openpilot.selfdrive.ui.boom_boom.overlays import BoomBoomOverlays

# __init__
self.boom_boom = BoomBoomOverlays()

# end of _render(self, rect)
self.boom_boom.render(rect)
```

On sunnypilot, also let the calmer arc replace the stock steering arc:

```python
if ui_state.torque_bar and not self.boom_boom.replaces_torque_bar:
```

Every widget runs inside a failure guard. A widget that raises is switched off for the rest of the drive and
logged, and the rest of the screen keeps working.

## 3. The settings page (required)

Register `BoomBoomLayout` as a settings panel. On stock, edit `selfdrive/ui/layouts/settings/settings.py`.
On sunnypilot, edit `selfdrive/ui/sunnypilot/layouts/settings/settings.py`. Add a member to `PanelType` and
an entry to `_panels`:

```python
from openpilot.selfdrive.ui.boom_boom.settings_panel import BoomBoomLayout

PanelType.BOOM_BOOM: PanelInfo(tr_noop("Boom-boom"), BoomBoomLayout(), icon="icons/fire.png"),
```

The page is built only from stock list widgets. `icons/fire.png` ships with openpilot.

## 4. Optional hooks

| For | Where | Hook |
|---|---|---|
| Shift chime | `selfdrive/ui/soundd.py` | see below |
| Lane awareness gap bar | wherever the model renderer has its lead chevrons for the frame (sunnypilot: `chevron_metrics.draw_lead_status`; stock: after `ModelRenderer` updates `self._lead_vehicles`) | `publish(lead_vehicles)` from `boom_boom.lead_screen` |
| Cameras in reverse | `selfdrive/ui/onroad/augmented_road_view.py` | see below |

**Shift chime.** The chime plays an existing one-shot sound through soundd's test-sound path, and only when
no alert sound is playing.

```python
from openpilot.selfdrive.ui.boom_boom.shift_chime import ShiftChime
from openpilot.selfdrive.ui.boom_boom.store import settings as boom_settings

# __init__
self.shift_chime = ShiftChime(boom_settings())

# in the loop, after the test-sound handling
if self.shift_chime.poll() and self.alert_finished() and sm['selfdriveState'].alertSound.raw == AudibleAlert.none:
  self.play_test_alert(<a one-shot sound: AudibleAlertSP.promptSingleHigh on sunnypilot, AudibleAlert.prompt on stock>)
  self.shift_chime.playing = True

# after the volume is chosen
self.shift_chime.playing = self.shift_chime.playing and self.test_alert
if self.shift_chime.playing:
  self.current_volume = self.shift_chime.volume
```

**Cameras in reverse.** In `AugmentedRoadView.__init__`, create
`ReverseCameraView(boom_settings())`. At the start of `_render`, let it take over the view while
`update(sm, started)` returns True. Draw the alert renderer on top of it unless `hides_alert(...)` says
otherwise.

## What works where

| Feature | Needs |
|---|---|
| Trip summary, G-force meter, drive rank and map | nothing extra. The map needs a GPS fix. |
| Why the car is slowing | openpilot longitudinal. The speed-limit and curve reasons need sunnypilot's planner. |
| Calmer steering arc | sunnypilot's per-speed steering rail schedule (`opendbc.sunnypilot`). Without it, the arc measures against full-scale torque instead. |
| Lane awareness | blind-spot monitoring. The gap bar needs openpilot longitudinal and the chevron hook. |
| Traffic box | blind-spot monitoring for the side zones. Radar tracks need stock cruise. |
| Mini-map | sunnypilot's mapd offline OSM tiles. Without them it says NO MAP DATA. |
| Shift lights, shift chime, engine data in the rank | **a Mazda.** They decode Mazda CAN frames and stay off on other makes. |
| Speed over a known limit in the rank | a speed-limit source (sunnypilot). Without one it is not counted. |

## Settings and data

Settings are kept in `settings.json`, and the drive history in `history.json`. Both live in
`$BOOM_BOOM_DIR` if it is set. Otherwise they go to `/data/boom_boom` on the device, or `~/.comma/boom_boom`
on a PC. Requests between processes (the chime) are files in `/dev/shm/boom_boom`, so none survives a
reboot. Every feature is off by default.

A build that used to keep these settings in openpilot params migrates them once, on first start. This needs
the old keys to still be registered in `params_keys.h`, because manager start-up deletes param files whose
keys are not registered. A fresh port has nothing to migrate and needs no keys.

## Tests

```
pytest selfdrive/ui/boom_boom/tests
```

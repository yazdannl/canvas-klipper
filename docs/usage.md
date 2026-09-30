# Control-layer usage

## Safety and installation

This control layer is software-only validated. The example pin labels are **TO BE MEASURED**, not pin assignments. Before enabling motors, verify the exact CANVAS board revision, motor/Hall wiring, connector power and signal levels, sensor polarity, cutter interface, and the matching MCU firmware on a bench. Do not infer pin values from CC1 toolhead documentation. The printer must have a configured extruder and a toolhead `filament_switch_sensor`; Canvas refuses to load without both.

Run `./canvas-klipper.sh install` to detect the Klipper checkout/config directory, symlink `canvas/canvas.py` and the companion `drv8833.py` through existing `install.sh` logic, copy the config templates under `<config>/canvas/`, select the toolhead switch (or specify one), choose `cutter`/`tip_forming`, set the MCU serial, add `[include canvas/*.cfg]`, and register the Moonraker update manager. Before changing `printer.cfg` or `moonraker.conf`, it creates a unique timestamped `.bak` copy; reruns avoid duplicate entries and preserve edits to generated config. It never guesses physical pin assignments. Since the supplied template lacks the measured `[drv8833]` and lane pin settings required by Klipper, the first run stages configuration but defers restart. Fill those settings and rerun; it restarts Klipper/Moonraker only when the config is complete and Moonraker is idle. Uninstall preserves generated config/symlinks as `.bak` rather than deleting them.

Overrides: `--klipper-dir DIR`, `--config-dir DIR`, `--moonraker-config FILE`, `--serial /dev/serial/by-id/...`, `--toolhead-sensor NAME`, `--toolhead-pin PIN`, `--separation-method cutter|tip_forming`, `--moonraker-url URL`, and `--force` (unknown print state only; printing/paused is always refused). `--non-interactive` requires explicit sensor/method flags and, when no existing sensor is found, both `--toolhead-sensor` and `--toolhead-pin`. `--help` shows the command-specific flags.

The generated template includes the Canvas MCU serial and selected sensor/method, but intentional `TO_BE_MEASURED` driver/lane pins and calibration still require review. Installer does not patch Klipper's MCU source or build/flash the MCU firmware. Apply the documented MCU patch/build where needed. The control uses `drv8833_set_speed()`, asynchronous Hall-bounded `drv8833_move()`, `stop()`, and `get_status()` from the documented host API.

The `[canvas]` section references four driver names (`lane_T0_motor` through `lane_T3_motor`), each lane-present switch and prep switch. Hall odometry comes from the matched `drv8833` host object's `get_status()` (`hall_count`/`hall_distance`), using that driver's required `motor_hall_resolution`; no duplicate Hall input pin is configured by Canvas. `extruder_feed_length`, `extruder_feed_speed`, `extruder_retract_length`, and `extruder_retract_speed` are required; no universal filament-path lengths are assumed, and config loading rejects feed/retract lengths beyond a lane's Hall-distance bound. The optional `hub_tangle_pin` is active-high according to the configured Klipper pin inversion; it blocks loading while active. Optional `cutter_sensor_pin` is considered engaged while active and must clear after cutting.

## Commands

- `CANVAS_TOOL_SELECT TOOL=0..3` unloads the current known lane if needed and loads the requested lane. Re-selecting an already loaded active tool is a no-op.
- `CANVAS_LOAD [TOOL=0..3]` loads the explicit or active lane.
- `CANVAS_UNLOAD [TOOL=0..3] [METHOD=cutter|tip_forming]` separates and unloads. The call-level method overrides the configured default.
- `CANVAS_CUT` invokes the public macro in `config/canvas_macros.cfg`; that macro calls the control extra's `CANVAS_CUT_INTERNAL METHOD=cutter`.
- `CANVAS_STATUS` and the extra's `get_status()` report selected/loaded state, lane switches, Hall counts/distances, optional sensors, motor status and last error.
- `CANVAS_RESET` requests a safe stop/cancel if an operation is in progress. When idle, it clears software lane state only if the toolhead sensor is clear; it does not move filament or erase saved printer state.
- Optional `T0`–`T3` wrappers invoke full tool selection for slicers. Merge them manually to avoid replacing existing macros.

Every lane feed is bounded by both Hall travel and elapsed time. Loading first confirms the lane prep switch, then waits for the required toolhead sensor transition, runs a synchronized extruder assist and checks that Hall odometry advanced by at least `grip_min_distance`. Failed loads stop the motor and retry within `load_attempts`; the lane-present sensor detects an empty spool. Unloading checks hotend readiness, applies the selected separation strategy, retracts through the extruder while reversing the feeder, waits for the toolhead sensor to clear within distance/time bounds, then parks and stops the lane motor. Any error stops all four motors, optionally issues `PAUSE`, and restores extrusion state.

`save_variables` is optional. If configured, the active lane and per-lane loaded bits are persisted and reconciled against the toolhead sensor at Klipper ready. Physical sensor state takes precedence for the active lane.

## Cutter and tip formation

For `separation_method: cutter`, implement `CANVAS_CUTTER_ACTUATE` for the actual printer. Do not use the provided error placeholder as a cutter. An optional cutter confirmation input allows bounded retries controlled by `cutter_retries` and `cutter_timeout`. `park_macro` and `post_cut_macro` are optional hooks; macro names must be plain G-code command identifiers.

For `separation_method: tip_forming`, built-in retraction/ramming uses `tip_forming_moves` as semicolon-separated negative-distance-mm : speed-mm/s pairs (example `-2:25;-4:15;-8:5`) with `tip_forming_cool_ms` pauses. Alternatively configure `tip_form_macro` to run a printer-specific PrusaSlicer/Happy-Hare-style tip routine instead. `post_cut_macro` runs after either strategy. The control code wraps built-in extrusions in save/restore and relative-extrusion state; custom macros remain responsible for their own motion/state safety.

Cutter actuator motion, tip-forming settings, sensor polarity and park movement are printer-specific and must be tuned without a print. `CANVAS_CUT` is a macro hook, not a universal cutter implementation.

## Slicer example

`config/slicer-snippets.cfg` illustrates the minimal OrcaSlicer/PrusaSlicer mapping: assign `T0`, `T1`, `T2`, and `T3` as the tool start commands. Avoid adding a second purge if the slicer's toolchange profile already extrudes a prime amount. Review generated G-code to ensure tool changes do not duplicate unload or extrusion moves.

## Attribution

The control behavior was informed by the GPL-3.0 AFC Canvas reference implementation: [`AFC_canvas.py`](https://github.com/suchmememanyskill/AFC-Klipper-Add-On/blob/DEV/extras/AFC_canvas.py) and [`AFC_canvas_lane.py`](https://github.com/suchmememanyskill/AFC-Klipper-Add-On/blob/DEV/extras/AFC_canvas_lane.py). This project implements its own standalone state machine and does not import AFC or Happy-Hare. Canvas control source retains GPLv3 licensing and this attribution.

## Simulation tests

From the repository root run `pytest tests/control` and `python -m compileall canvas`. Tests model lanes, sensor transitions, Hall pulses, motor speed, extruder moves and cutter behavior. They are not a substitute for hardware calibration or cutter validation.

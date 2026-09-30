# CANVAS wiring: known facts, published pin map, and what you must still verify

## Pin values and where they come from

Every pin value this project ships is in **[canvas-pins.md](canvas-pins.md)**, one table per
function group, with the source URL and a confidence value (`confirmed-in-source`, `inferred`,
`unknown`) for each. Read that document before touching a wire or running a load. Summary:

- Confirmed in the source and filled into `config/canvas.cfg`: the four lane `motor_fwd` /
  `motor_rwd` / `motor_hall` pins and `motor_hall_resolution` (0.26242), the four per-lane
  filament (`prep`) switches, and the toolhead cutter-actuation input.
- Confirmed in the source but living on the **printer's toolhead board**, not the CANVAS mainboard:
  the toolhead/hub switch, the shared tangle input and the cover sensor. See
  `config/canvas_toolhead_example.cfg`.
- No source at all: the four per-lane `lane_T*_present_pin` switches. They are **optional** and
  ship unset, so nothing has to be measured for a stock install; when unset, presence is derived
  from that lane's prep switch.

## Known from published sources

- CANVAS v1 is a four-lane feeder with one motor channel per lane and mechanical lane filament
  switches.
- The CC1 CANVAS mainboard is marked **GD32F303RCT6** with **4× AT8833** (DRV8833 clone)
  H-bridges; COSMOS builds and flashes `stm32f401xc` Klipper firmware onto it and the printer
  talks to it over USB (24V, GND, 5V, D−, D+ on the 5-pin CANVAS port). The silicon and the
  firmware target therefore do not match by name — a successful build is not proof your board
  matches. See [canvas-pins.md](canvas-pins.md) §8.
- The lane pin map itself comes from the CANVAS configuration COSMOS ships in
  `klipper-readonly/canvas.cfg`; OpenCentauri's own AMS documentation calls that file "the only
  worked example available on COSMOS". Values are *confirmed-in-source*, not hardware-verified.
- The toolhead, tangle, cutter and cover sensors are on the CC1 CANVAS **toolhead** board (its
  own Klipper MCU, named `hotend` by COSMOS). No `canvas:`-prefixed equivalents exist.
- No public source publishes a second, spool-end "lane present" switch per lane.

## The user must measure/verify on the exact board

Before connecting anything, record board revision and top-marked MCU, identify each connector
contact with a schematic/continuity measurements, and determine which contacts are USB D+/D−,
ground, VBUS, logic power and motor supply. Measure rails/logic levels and verify
isolation/back-power behavior. Then, for every value marked *confirmed-in-source* above, check
that it is really your board's mapping:

- Confirm each lane's H-bridge pair drives that lane's motor in the feed direction this project
  expects. For lanes `T1` and `T3` the source's own alias table swaps FWD/RWD relative to the
  `[drv8833]` sections ([canvas-pins.md](canvas-pins.md) §8 item 1); swap the two values if a lane
  runs backwards.
- Confirm `motor_hall_resolution: 0.26242` on your unit. It scales every Hall-bounded distance, so
  a wrong value distorts load/unload safety bounds.
- Confirm polarity and pull-up requirement for `canvas:PA8` / `PC7` / `PC11` / `PC0` (per-lane
  filament switches) and for the toolhead switch, and confirm the actual sensor behind
  `hotend:PB0` before enabling `hub_tangle_pin` (the sources disagree on its label).
- Resolve `lane_T*_present_pin` only if you fitted real switches; the key is optional. Left unset,
  presence is derived from the lane prep switch, so the bounded drive to that switch is what
  proves the lane holds filament and a lane that never reaches it fails safely. If you do set the
  key, do **not** point it at that lane's prep pin: a configured switch gates loading before any
  motion, so that combination refuses every load.
- Verify PWM-capable pins, Hall electrical type/edge behavior and actual motor topology, and
  measure the cutter actuation sense, macros, timeouts and retraction distances. Those are
  motion/safety parameters; no published source covers them.

Do not infer pinout or voltage from connector shape, from another board revision, or from the CC2
CANVAS map (a different board, listed separately in [canvas-pins.md](canvas-pins.md) §8 item 5).
Do not connect CAN, RS-485, 24 V, or an unknown power rail to host USB. Do not attach a host or
printer until the pin map and supply arrangement have been independently checked. Use a correctly
keyed/isolated adapter and an isolated bench setup with no filament and no active print. Firmware
compile success and simulation tests do not validate electrical behavior.

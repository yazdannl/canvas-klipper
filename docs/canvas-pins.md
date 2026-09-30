# CANVAS v1 MCU pin map — sources, values and confidence

This document records every CANVAS-related pin value this project knows, where the value came
from, and how much trust it carries. **Nothing here has been verified on real hardware by this
project.** Values marked *confirmed-in-source* are only confirmed to be present in the cited
public file; they are not confirmed to be correct for your board revision, your silicon, your
wiring or your printer's toolhead.

Fill values into `config/canvas.cfg` and `config/canvas_toolhead_example.cfg` from the tables
below. Values that stay `unknown` must stay `TO_BE_MEASURED` in the config — the installer
refuses to activate `[include canvas/*.cfg]` and defers the Klipper restart while any
`TO_BE_MEASURED` remains. The one exception is the optional per-lane `lane_T*_present_pin`
key (§3): it ships **unset**, so a stock CC1 CANVAS install completes without any manual pin
measurement.

## Which board "CANVAS v1" means here

| Item | Value | Source |
|---|---|---|
| Unit | Elegoo CANVAS multimaterial module for the **Centauri Carbon 1 (CC1)** | [S3] |
| CANVAS mainboard MCU (marked on board) | GD32F303RCT6 | [S3], [S4] |
| Klipper firmware target COSMOS builds for it | `stm32f401xc`, 84 MHz, USB-serial on PA11/PA12 | [S10] |
| Host connection to the printer | USB (CANVAS port is 5-pin JST-XHB: 24V, GND, 5V, D−, D+) | [S3] |
| Motor drivers | 4× AT8833 (DRV8833 clone), one per lane | [S3] |
| Per-lane filament detection | one mechanical switch per lane (filament detector board on each channel) | [S4] |
| Lane numbering | `[drv8833 canvas_lane0..3]` = AFC lanes `CANVAS_1..4` = tools `T0..T3` | [S1] |

The CC2 CANVAS mainboard is a **different board** (STM32F103, RS485 to the host, different pin
map) — see the CC2 table below. Never mix the two. This project's firmware target matches the
CC1 board, which is why the CC1 map is the one used in `config/`.

## Sources

| Key | What it is | URL |
|---|---|---|
| S1 | COSMOS shipped CC1 CANVAS Klipper config — the authoritative pin map (lives in the `klipper-readonly/canvas.cfg` that ships on the printer) | https://github.com/OpenCentauri/cosmos/blob/a69c5a2ce6abbb657ab419c6ac315f358c19a063/meta-opencentauri/recipes-data/klipper-afc-addon/files/centauri-carbon-1/canvas.cfg |
| S2 | COSMOS shipped CC1 CANVAS toolhead config (toolhead-board buttons/sensors) | https://github.com/OpenCentauri/cosmos/blob/a69c5a2ce6abbb657ab419c6ac315f358c19a063/meta-opencentauri/recipes-data/klipper-afc-addon/files/centauri-carbon-1/canvas-toolhead.cfg |
| S3 | OpenCentauri hardware docs, CC1 CANVAS — mainboard MCU, toolhead-board connector pin labels | https://github.com/OpenCentauri/OpenCentauri/blob/c921b0fc40fb64bd6d677c75a976a07324112096/docs/hardware/CC1/CANVAS.md |
| S4 | OpenCentauri hardware docs, CANVAS components — one filament switch per lane, RFID board, drivetrain | https://github.com/OpenCentauri/OpenCentauri/blob/c921b0fc40fb64bd6d677c75a976a07324112096/docs/hardware/CANVAS/CANVAS_components.md |
| S5 | COSMOS shipped CC2 CANVAS config (different board; reference only) | https://github.com/OpenCentauri/cosmos/blob/a69c5a2ce6abbb657ab419c6ac315f358c19a063/meta-opencentauri/recipes-data/klipper-afc-addon/files/centauri-carbon-2/canvas.cfg |
| S6 | OpenCentauri hardware docs, CC2 toolhead — filament detector board pin labels (reference only) | https://github.com/OpenCentauri/OpenCentauri/blob/c921b0fc40fb64bd6d677c75a976a07324112096/docs/hardware/CC2/toolhead.md |
| S7 | COSMOS Klipper patch `0003-drv8833-motor-control.patch` — `motor_fwd`/`motor_rwd`/`motor_hall` semantics, MCU protocol | https://github.com/OpenCentauri/cosmos/blob/a69c5a2ce6abbb657ab419c6ac315f358c19a063/meta-opencentauri/recipes-apps/klipper/files/0003-drv8833-motor-control.patch |
| S8 | OpenCentauri AMS docs — "Lanes are defined in `klipper-readonly/canvas.cfg`"; the shipped `canvas.cfg` is "the only worked example available on COSMOS" | https://docs.opencentauri.cc/klipper-conversion/cosmos/ams/ |
| S9 | AFC canvas add-on (option names/semantics only, no pins) | https://github.com/suchmememanyskill/AFC-Klipper-Add-On/blob/484a09b4c16674b586bf33035f1ab1b9dccc67b9/extras/AFC_canvas_lane.py |
| S10 | COSMOS CC1 CANVAS MCU firmware build config | https://github.com/OpenCentauri/cosmos/blob/a69c5a2ce6abbb657ab419c6ac315f358c19a063/meta-opencentauri/recipes-apps/klipper/files/centauri-carbon-1/config.canvas |

**Confidence values used in the tables**

- `confirmed-in-source` — the exact value appears in a cited file for the CC1 CANVAS board. Still
  unverified electrically; board revisions, harness damage or a substituted toolhead board can
  differ.
- `inferred` — derived by reasoning across sources, not stated directly by any one of them.
- `unknown` — no public source. Must be measured on your hardware or left `TO_BE_MEASURED`.

## 1. Lane feed motors and rotation Hall (`[drv8833 T0..T3]`)

All four lanes are on the CANVAS mainboard MCU, named `canvas` in [S1]. `T0` = lane 1 =
AFC `CANVAS_1` = tool `T0`. Pins below are the literal `motor_fwd`/`motor_rwd`/`motor_hall`
values COSMOS ships; the `board_pins` alias table in the same file agrees for lanes 1 and 3
(PA6/PA5, PB8/PB9) but swaps FWD/RWD for lanes 2 and 4 (see §8).

| Pin | Function | Source URL | Confidence |
|---|---|---|---|
| `canvas:PA6` | `motor_fwd` lane 1 / `T0` | [S1] | confirmed-in-source |
| `canvas:PA5` | `motor_rwd` lane 1 / `T0` | [S1] | confirmed-in-source |
| `canvas:PB6` | `motor_hall` lane 1 / `T0` (rotation Hall, mm per count) | [S1] | confirmed-in-source |
| `canvas:PA7` | `motor_fwd` lane 2 / `T1` | [S1] | confirmed-in-source |
| `canvas:PB0` | `motor_rwd` lane 2 / `T1` | [S1] | confirmed-in-source |
| `canvas:PB7` | `motor_hall` lane 2 / `T1` | [S1] | confirmed-in-source |
| `canvas:PB8` | `motor_fwd` lane 3 / `T2` | [S1] | confirmed-in-source |
| `canvas:PB9` | `motor_rwd` lane 3 / `T2` | [S1] | confirmed-in-source |
| `canvas:PB5` | `motor_hall` lane 3 / `T2` | [S1] | confirmed-in-source |
| `canvas:PB1` | `motor_fwd` lane 4 / `T3` | [S1] | confirmed-in-source |
| `canvas:PB10` | `motor_rwd` lane 4 / `T3` | [S1] | confirmed-in-source |
| `canvas:PB4` | `motor_hall` lane 4 / `T3` | [S1] | confirmed-in-source |

Non-pin values from the same `[drv8833]` sections (calibration, still unverified on your unit):

| Value | Function | Source URL | Confidence |
|---|---|---|---|
| `motor_hall_resolution: 0.26242` | mm of filament travel per Hall count, all four lanes | [S1] | confirmed-in-source |
| `motor_cycle_time: 0.0001` | H-bridge PWM cycle time COSMOS uses (100 µs) | [S1], [S7] | confirmed-in-source |
| `PB13` (`pwm_cycle_time _buzzer_canvas`) | CANVAS mainboard buzzer | [S1] | confirmed-in-source |

The three motor/Hall pins of one lane must be on the same MCU ([S7] enforces this), and
`motor_hall_resolution` is mandatory in [S7] and in this project's driver.

## 2. Lane filament switches (`FILAMENT0..3`) — the `lane_T*_prep_pin` values

COSMOS configures exactly one switch per lane and uses it as the lane `prep` switch
(`prep: !canvas:FILAMENTn`). The hardware doc describes these as mechanical filament-presence
switches on the per-channel detector board, actuated by a bullet-shaped pin as filament passes.

| Pin | Function | Source URL | Confidence |
|---|---|---|---|
| `canvas:PA8` | `lane_T0_prep_pin` — lane 1 filament/prep switch (`FILAMENT0`) | [S1], [S4] | confirmed-in-source |
| `canvas:PC7` | `lane_T1_prep_pin` — lane 2 filament/prep switch (`FILAMENT1`) | [S1], [S4] | confirmed-in-source |
| `canvas:PC11` | `lane_T2_prep_pin` — lane 3 filament/prep switch (`FILAMENT2`) | [S1], [S4] | confirmed-in-source |
| `canvas:PC0` | `lane_T3_prep_pin` — lane 4 filament/prep switch (`FILAMENT3`) | [S1], [S4] | confirmed-in-source |

COSMOS uses `!` (pull-up) for these four pins. This project's `config/canvas.cfg` leaves the
Klipper pull-up form to you — confirm whether the switch pulls the line low or high before
choosing `!`.

## 3. Lane-present switches (`lane_T*_present_pin`) — no source, and optional

| Pin | Function | Source URL | Confidence |
|---|---|---|---|
| — | `lane_T0_present_pin` | no source | **unknown** |
| — | `lane_T1_present_pin` | no source | **unknown** |
| — | `lane_T2_present_pin` | no source | **unknown** |
| — | `lane_T3_present_pin` | no source | **unknown** |

No public source documents a second, spool-end "lane present" switch per lane. [S1] configures
one switch per lane, which [S4] describes as the channel's filament detector — the `prep` switch
of §2.

The key is therefore **optional** in this project's control extra:

- **Unset (the shipped default).** The lane's presence is *derived* from its own prep switch.
  `lane.present` is only ever true while that prep switch reads active, so Canvas never reports
  filament present for a lane whose switch reads empty. Because the prep switch is still clear
  while filament sits upstream of the lane, the derived state cannot gate a load before motion
  the way a real presence switch does; the bounded move to the prep switch is what proves the
  lane holds filament, and a lane that reaches it stays guarded by that switch afterwards. A
  lane that never reaches the prep switch within `prep_max_distance`/`prep_timeout` fails the
  load exactly as before, with a message saying no present switch is configured.
- **Configured.** A real switch takes precedence and gates every load before any motion, which
  is the stricter behaviour: it can refuse a load that the derived state would allow.

`CANVAS_STATUS` and `get_status()` report which of the two applies per lane in
`lanes.<T>.present_source` (`prep` or `present_pin`).

Do **not** point `lane_T*_present_pin` at that lane's `FILAMENTn` prep pin even though presence is
now derived from it: with the key configured the guard is evaluated *before* the motor turns, and
the prep switch is still clear then, so that combination refuses every load.

To use real switches, fit and measure them, then uncomment the `lane_T*_present_pin` lines at the
end of `config/canvas.cfg` and replace `TO_BE_MEASURED` with the measured pin. An optional key
left at `TO_BE_MEASURED` still blocks the installer's include and restart, exactly like any
other placeholder.

## 4. Lane LEDs (reference only — not consumed by this project)

`[canvas]` and `[drv8833]` in this project have no LED options, so these are documented for
wiring and for a future status display. Values are the `board_pins canvas` aliases in [S1].

| Pin | Function | Source URL | Confidence |
|---|---|---|---|
| `canvas:PC9` / `canvas:PC8` | lane 1 LED white / red (`LED0_*`) | [S1] | confirmed-in-source |
| `canvas:PC6` / `canvas:PB15` | lane 2 LED white / red (`LED1_*`) | [S1] | confirmed-in-source |
| `canvas:PC10` / `canvas:PA15` | lane 3 LED white / red (`LED2_*`) | [S1] | confirmed-in-source |
| `canvas:PC1` / `canvas:PC12` | lane 4 LED white / red (`LED3_*`) | [S1] | confirmed-in-source |

## 5. Lane odometer/encoder inputs (reference only — not consumed by this project)

This project's Hall odometry comes from the `drv8833` `motor_hall` pins in §1, so the separate
odometer pins below are unused. `AFC_canvas_lane` uses them as `odometer_pin`.

| Pin | Function | Source URL | Confidence |
|---|---|---|---|
| `canvas:PA2` | lane 1 odometer (`ODOMETER0`) | [S1] | confirmed-in-source |
| `canvas:PA3` | lane 2 odometer (`ODOMETER1`) | [S1] | confirmed-in-source |
| `canvas:PA1` | lane 3 odometer (`ODOMETER2`) | [S1] | confirmed-in-source |
| `canvas:PA0` | lane 4 odometer (`ODOMETER3`) | [S1] | confirmed-in-source |
| `3.15786` | odometer mm per pulse, all lanes | [S1] | confirmed-in-source |

## 6. Other CANVAS mainboard pins (reference only)

| Pin | Function | Source URL | Confidence |
|---|---|---|---|
| `canvas:PC2` / `canvas:PC3` | `ENABLE_9V` / `ENABLE_24V` motor-rail enables | [S1] | confirmed-in-source |
| `canvas:PD2` / `canvas:PB3` | RFID reader I²C `SCL` / `SDA` (software I²C) | [S1] | confirmed-in-source |
| `canvas:PC14` | RFID reader IRQ | [S1] | confirmed-in-source |

## 7. Toolhead / cutter board pins — these are **not** on the CANVAS MCU

The CANVAS kit ships a revised toolhead PCB (STM32F402RCT6, separate Klipper MCU). The toolhead
sensor, tangle, cutter-actuation and cover sensors live there, on the MCU COSMOS names `hotend`.
[S3] lists the toolhead's filament detector board connector pads. None of these pins exist on the
CANVAS mainboard; a `canvas:`-prefixed equivalent does not exist.

| Pin | Function | Source URL | Confidence |
|---|---|---|---|
| `hotend:PB2` | Toolhead filament/hub switch — used by COSMOS as both `[AFC_hub toolhead_4way_hub] switch_pin: !hotend:PB2` and `[AFC_extruder extruder] pin_tool_start: !hotend:PB2`; this project's `toolhead_sensor` | [S1], [S2] | confirmed-in-source (label conflict, see §8) |
| `hotend:PB0` | COSMOS `[gcode_button toolhead_tangle_detection] pin: !hotend:PB0` — this project's optional `hub_tangle_pin` | [S2], [S3] | confirmed-in-source (label conflict, see §8) |
| `hotend:PC5` | Cutter actuation Hall — COSMOS `[AFC_canvas CANVAS_1] cutter_pin: !hotend:PC5`; this project's `cutter_sensor_pin` | [S1], [S3] | confirmed-in-source |
| `hotend:PC4` | Toolhead cover-detection Hall (`S1`, magnet in the CANVAS toolhead cover); COSMOS `[gcode_button toolhead_front_cover_detection]` | [S2], [S3] | confirmed-in-source |
| `hotend:PB0` per connector table | Connector pad `S2`, described as "optical filament detect" | [S3] | confirmed-in-source (label conflict, see §8) |
| `hotend:PC6`, `hotend:PC7` | Toolhead stepper UART TX / UART (test points) | [S3] | confirmed-in-source |
| `hotend:PC8`, `hotend:PC9`, `hotend:PA3`, `hotend:PB6`, `hotend:PA1` | Toolhead supplementary board: fan PWM, LED PWM, temp, heat, fan tach | [S3] | confirmed-in-source |

These pins are only meaningful with the CC1 CANVAS toolhead board *and* Klipper firmware on that
board. If your toolhead MCU is not named `hotend`, or you do not have the CANVAS toolhead board,
delete the `hotend:` lines from `config/canvas.cfg` and keep the printer's own sensor.

## 8. Known conflicts and gaps inside the sources

| # | Issue | Detail | What to do |
|---|---|---|---|
| 1 | Motor FWD/RWD swap for lanes 2 and 4 | In [S1] the `[drv8833 canvas_lane1]`/`canvas_lane3]` sections use `motor_fwd: PA7` / `motor_rwd: PB0` and `motor_fwd: PB1` / `motor_rwd: PB10`, while the `[board_pins canvas]` alias table in the same file declares `MOTOR1_FWD=PB0, MOTOR1_RWD=PA7` and `MOTOR3_FWD=PB10, MOTOR3_RWD=PB1`. The pin *pair* is agreed; which pad is "forward" is not. | Use the `[drv8833]` values (they are the ones that run in COSMOS). Verify feed vs. retract direction per lane on the bench before loading filament; swap `motor_fwd`/`motor_rwd` if a lane runs backwards. |
| 2 | `PB0` vs `PB2` function labels on the toolhead board | [S3]'s connector table labels `PB2` = "tangle detection" (`S5`) and `PB0` = "optical filament detect" (`S2`). [S2] instead names `!hotend:PB0` "toolhead_tangle_detection" and uses `!hotend:PB2` as the hub/tool-start switch. On CC2 the two sources agree (`PA1` = tangle, `PB1` = optical). | Treat `PB2` as the toolhead/hub switch (as shipped by COSMOS). For `hub_tangle_pin`, confirm the physical sensor behind `PB0` before enabling it — if it is the optical filament detector, a wrong polarity will block every load. Leave `hub_tangle_pin` unset until verified. |
| 3 | No per-lane presence switch | See §3. | Leave `lane_T*_present_pin` unset so presence is derived from the lane prep switch, or fit and measure real switches and set the keys. |
| 4 | Silicon vs. firmware target | Board is marked GD32F303RCT6 ([S3]); COSMOS builds `stm32f401xc` ([S10]) and this project's pinned firmware does the same. | Confirm your MCU marking and that the flashed firmware actually enumerates on your board. |
| 5 | CC2 board is a different map | CC2 CANVAS: `MOTOR0_FWD=PA1, MOTOR0_RWD=PA0, MOTOR1_FWD=PA2, MOTOR1_RWD=PA3, MOTOR2_FWD=PA7, MOTOR2_RWD=PA6, MOTOR3_FWD=PB1, MOTOR3_RWD=PB0, HALL0=PA10, HALL1=PA8, HALL2=PA11, HALL3=PA9, FILAMENT0=PB14, FILAMENT1=PB15, FILAMENT2=PB12, FILAMENT3=PB13, ODOMETER0=PC8, ODOMETER1=PC6, ODOMETER2=PC9, ODOMETER3=PC7, LED0_WHITE=PC3, LED0_RED=PB3, LED1_WHITE=PB9, LED1_RED=PB5, LED2_WHITE=PC0, LED2_RED=PB8, LED3_WHITE=PD2, LED3_RED=PC12, RFID_SCL=PB10, RFID_SDA=PB11, RFID_IRQ=PC5, buzzer PC15`, host link `/dev/ttyS1` at 250000 baud ([S5]); toolhead: `PA1` tangle, `PA2` cutter, `PB1` optical, `PB0` cover ([S6]). | Listed so nobody mistakes it for the v1 map. Do not use it on a CC1 CANVAS. |
| 6 | COSMOS gaps | [S8] lists that RFID spool-tag reading, the CANVAS buzzer and filament eject are not implemented, and runout is lightly tested. | Do not rely on CANVAS-side RFID or buzzer behaviour. |

## 9. Sources checked that do **not** provide a CANVAS v1 MCU pin map

- **Elegoo official repositories** — `elegooofficial/CentauriCarbon`, `elegooofficial/CentauriCarbon2`,
  `elegooofficial/ElegooSlicer`. The CC2 firmware has an `elegoo/extras/canvas_dev.{h,cpp}` module, but
  it drives CANVAS over **RS485** commands (connect status, filament plugged in, odometer, motor,
  RFID, LED, beeper) rather than exposing MCU GPIO, i.e. it is the CC2 path, not a v1 pin map.
  A code comment in that header (`pb3 s2 pb6 s5 … 耗材检测 风扇脱落 切刀检测 缠料检测`) mentions
  S2/S5 signal names against `PB3/PB4/PB5/PB6` on some host board, which does not match any CC1
  CANVAS value above and is not attributed to the CANVAS MCU — treated as inconclusive, so no
  value here comes from it. https://github.com/elegooofficial/CentauriCarbon2
- **Elegoo wiki / manuals** — user manuals only (mechanical setup, filament loading); no pin
  tables. https://wiki.elegoo.com/en/download-center
- **AFC add-on DEV branch** (`suchmememanyskill/AFC-Klipper-Add-On`, [S9]) — defines the lane/unit
  option names (`prep`, `odometer_pin`, `led_white_pin`, `led_red_pin`, `cutter_pin`,
  `enable_9v_pin`, `enable_24v_pin`) but ships no `canvas.cfg` with pins.
- **Kalico driver patch** — the only `0003-drv8833-motor-control.patch` published is the one COSMOS
  applies to Klipper ([S7]); it is the driver, not a pin map. The `config.canvas` files
  ([S10] and its Katapult twin) are MCU build configs (`stm32f401xc`, features, no pins).
- **Community mirrors** — GitHub code search for the distinctive values (`canvas:PA6`,
  `LED0_WHITE=PC9`, `ODOMETER0=PA2`, `motor_hall_resolution: 0.26242`) finds only
  [S1] and a verbatim copy of it in an unrelated fork (`Natclanwy/THING3`,
  `extras-readonly/canvas.cfg`). No independent measured map exists in public search results.

## 10. What the user must still verify on hardware

1. Board revision, top-marked CANVAS MCU, and which toolhead board you actually have.
2. Each `motor_fwd`/`motor_rwd` pair drives its lane's motor in the direction this project
   expects (feed vs. retract), including the lanes whose alias table conflicts (§8 #1).
3. `motor_hall_resolution: 0.26242` on your unit — a wrong value scales every Hall-bounded
   distance, and it gates load/unload safety.
4. Switch polarity and pull-up requirement for `PA8`/`PC7`/`PC11`/`PC0`, the toolhead switch and
   the optional tangle/cutter inputs. Now that lane presence is derived from the prep switch (§3),
   a lane that will not feed points at these two items far more often than at a missing spool.
5. Cutter actuation sense, macro, timeouts and retraction distances — these are motion/safety
   parameters, not pins, and no source in this document covers them.
6. That the flashed MCU firmware enumerates on your board (silicon vs. target mismatch, §8 #4).

Passing this project's software tests proves none of the above.

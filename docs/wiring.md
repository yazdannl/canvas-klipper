# CANVAS wiring: known facts and measurements required

## Known from published sources

- CANVAS v1 is a four-lane feeder with four motor-driver channels and mechanical lane-present switches.
- CC1 CANVAS documentation identifies a GD32F303RCT6 and four AT8833 (DRV8833-clone) H-bridges.
- COSMOS runs a USB-serial Klipper MCU after firmware conversion, using PA11/PA12 for USB in its F401-target config. This does not establish the stock cable pinout or power arrangement.
- The host driver's three required pins (`motor_fwd`, `motor_rwd`, `motor_hall`) and all lane-switch pins are not mapped in the public source tree consulted here. No generic pin assignments are supplied.

## The user must measure/verify on the exact board

Before connecting anything, record board revision and top-marked MCU, identify each connector contact with a schematic/continuity measurements, and determine which contacts are USB D+/D−, ground, VBUS, logic power and motor supply. Measure rails/logic levels and verify isolation/back-power behavior. Map each lane's two H-bridge inputs, Hall output, lane-present switch, polarity and pull-up requirements. Record toolhead/cutter/tangle sensors separately; they are not automatically on the Canvas MCU. Verify PWM-capable pins, Hall electrical type/edge behavior and actual motor topology before creating Klipper config.

Do not infer pinout or voltage from connector shape, CC1 toolhead-board labels, or another board revision. Do not connect CAN, RS-485, 24 V, or an unknown power rail to host USB. Do not attach a host or printer until the pin map and supply arrangement have been independently checked. Use a correctly keyed/isolated adapter and an isolated bench setup with no filament and no active print. Firmware compile success and simulation tests do not validate electrical behavior.

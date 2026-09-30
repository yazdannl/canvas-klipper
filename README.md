# CANVAS Klipper

Standalone Klipper control and firmware support for an Elegoo CANVAS v1 four-lane feeder. It has no AFC or Happy-Hare runtime dependency.

> **Status: experimental, simulation-tested only, not hardware-verified.** No motor calibration, cutter configuration, or firmware recovery path is certified by this project.

> **Pin map: filled from published sources, never measured by this project.** The CANVAS v1 (CC1) lane motor/Hall pins, lane filament switches and the toolhead/cutter inputs are taken from the CANVAS configuration COSMOS ships plus OpenCentauri's hardware documentation. Every value, its source URL and its confidence are listed in [docs/canvas-pins.md](docs/canvas-pins.md); the `lane_T*_present_pin` switches have no source at all, so that key is optional and ships unset — nothing has to be measured for a stock install.

## Safety warning — read before connecting or flashing

**Flashing or incorrect wiring can permanently brick a CANVAS board or damage the printer/host. Do not connect an unknown CANVAS cable or power rail to a host.** Confirm the exact board revision, MCU, connector pinout, logic levels, motor supply, backup and recovery method before any hardware work. Use an isolated, current-limited bench setup and never flash during a print.

There is an unresolved silicon/configuration discrepancy: hardware notes identify the CANVAS MCU as **GD32F303RCT6**, while COSMOS's checked-in Klipper/Katapult configurations target **STM32F401XC**. This project preserves that experimental firmware target; a successful software build is not proof that it matches your board. No factory application image or verified recovery procedure is included. Firmware flashing is separate from installation and requires explicit user action.

## Requirements

- A CANVAS v1 unit with its matching custom Klipper firmware and four DRV8833-compatible H-bridge/Hall channels.
- Klipper on Linux; upstream Klipper is the target. `firmware/versions.lock` pins the build inputs.
- A configured `[extruder]` **and** a toolhead `[filament_switch_sensor ...]` are mandatory. Canvas config fails if either is absent.
- Lane motor mappings, lane prep switches and motor Hall resolution as published in [docs/canvas-pins.md](docs/canvas-pins.md) — use them, then verify them on your exact board.
- Optional: a per-lane present switch, which **no public source documents**. Without one, lane presence is derived from that lane's prep switch.
- A printer-specific cutter macro or a selected tip-forming strategy, plus measured sensor polarity, feed/retract distances and cutter sense.

## Quick start

Read [CANVAS pin map](docs/canvas-pins.md), [wiring](docs/wiring.md), [firmware](docs/firmware.md), [flashing/recovery](docs/flashing.md), and [control usage](docs/usage.md) before connecting hardware. This project remains experimental and software/simulation-tested only.

1. `./canvas-klipper.sh flash` — checks Moonraker print state, builds missing/stale pinned outputs (offers apt dependency installation when needed), detects the USB device, then stages Katapult and Klipper. The default detection asks you to unplug/replug the unit; `--device PATH` or `--vid-pid VVVV:PPPP` can select it explicitly. Flashing prints the GD32F303 vs STM32F401 warning and requires one exact typed risk phrase. No stock flash-backup tooling/image is available; recovery may require SWD. Optional verified files: `--backup-file PATH --recovery-file PATH`. `--dry-run` does not query Moonraker or open serial; `--yes --i-understand-the-risks` is the non-interactive authorization pair.
2. `./canvas-klipper.sh install` — detects Klipper/config directories (or `--klipper-dir`/`--config-dir`), links host extras, copies config templates to `<config>/canvas/`, auto-fills the Canvas MCU serial, asks which existing filament switch is the toolhead sensor (or asks for a pin and generates the section), asks for the separation method, and registers the Moonraker update manager. Every prompt has a non-interactive flag counterpart (`--serial`, `--toolhead-sensor`, `--toolhead-pin`, `--separation-method`, `--non-interactive`). Before changing `printer.cfg` or `moonraker.conf` it creates a unique timestamped `.bak`; reruns are idempotent and never duplicate includes, sections or symlinks. The distributed template ships the published lane motor/Hall pins, lane prep switches, Hall resolution and toolhead cutter input, with the optional `lane_T*_present_pin` keys unset, so it carries no `TO_BE_MEASURED` and a stock CC1 CANVAS completes in one run: `install` activates `[include canvas/*.cfg]`, restarts Klipper/Moonraker only when Moonraker reports idle, and prints a warning that the pins are source-derived rather than hardware-verified, listing the open risks (T1/T3 motor polarity, the `PB0`/`PB2` toolhead label conflict, uncalibrated Hall resolution and switch polarity). It still leaves the include out and defers the restart while any `TO_BE_MEASURED` remains in a required key — or in an optional key you uncommented but left unresolved — and prints exactly what to fill in. It refuses `printing`/`paused`, and unknown state unless `--force`.

`install` will not guess Canvas pins or patch/build the Klipper MCU firmware. It completes on a stock CC1 CANVAS because the only unsourced key, `lane_T*_present_pin`, is optional; if you set it yourself, any placeholder left in it defers the install exactly like one in a required key (see [docs/canvas-pins.md](docs/canvas-pins.md) §3). Check the hardware/recovery mismatch before use. Uninstall/status are available as `./canvas-klipper.sh uninstall` and `./canvas-klipper.sh status`; see the [flashing](docs/flashing.md) and [usage](docs/usage.md) guides for flags and safety details.

## Commands

- `CANVAS_TOOL_SELECT TOOL=0..3` — unload a known active lane and load the selected lane; repeated selection of the loaded active lane is a no-op.
- `CANVAS_LOAD [TOOL=0..3]`, `CANVAS_UNLOAD [TOOL=0..3] [METHOD=cutter|tip_forming]`.
- `CANVAS_STATUS`, `CANVAS_CUT`, and `CANVAS_RESET` (cancel/recovery without clearing state while filament remains at the toolhead).
- Example `T0`–`T3` slicer aliases. The T aliases perform a full tool selection; merge manually rather than replacing existing macros.

Loading uses lane presence (an optional present switch, otherwise the state derived from that lane's prep switch) and the prep switch, bounded Hall travel/time, the required toolhead sensor, synchronized extruder feed, and Hall odometry grip confirmation. Unloading supports a cutter macro with optional confirmation/retries, or built-in configurable tip-forming ramming/cooling moves and an optional custom tip macro. Per-call `METHOD=` overrides the configured separation mode. `save_variables` is optional.

## Tests

```sh
python3 -m pip install pytest
pytest -q
python3 -m compileall -q canvas klipper/klippy/extras tests
bash -n install.sh firmware/build.sh flash/canvas-flash tests/klipper/run_batch_test.sh
```

The simulator suite includes a test against the real `klipper/klippy/extras/drv8833.py` host module with a fake MCU. `tests/klipper` runs Klipper in file-output mode against the pinned build and Linux-process dictionary when available; it skips if that ignored build is absent. The batch test uses test-only GPIO placeholders and does not access a physical MCU or serial device. Passing software tests is not hardware validation.

## Documentation and provenance

- [CANVAS v1 pin map, sources and confidence](docs/canvas-pins.md)
- [Control-layer setup and usage](docs/usage.md)
- [Wiring and safety](docs/wiring.md)
- [Firmware build](docs/firmware.md)
- [Flashing and recovery](docs/flashing.md)
- [DRV8833 host API](docs/drv8833-api.md)
- [Notices and attribution](NOTICE.md), with detailed pinned firmware provenance in [NOTICE-firmware.md](NOTICE-firmware.md)

Credits and behavioral/source references: OpenCentauri [COSMOS](https://github.com/OpenCentauri/cosmos) (GPL-3.0), the [AFC Canvas fork](https://github.com/suchmememanyskill/AFC-Klipper-Add-On) (GPL-3.0), [Klipper](https://github.com/Klipper3d/klipper) (GPL-3.0), [Katapult](https://github.com/Arksine/katapult) (GPL-3.0), and OpenCentauri's [mcu-flasher](https://github.com/OpenCentauri/OpenCentauri) (MIT). See the notices for component-by-component use and revisions.

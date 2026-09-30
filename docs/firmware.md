# CANVAS firmware build

`firmware/build.sh klipper` builds the Klipper MCU image and Linux-process simulation target from the exact commit in `firmware/versions.lock`, applying `klipper/0001-drv8833-mcu.patch` in an isolated, ignored checkout. `firmware/build.sh katapult` builds Katapult; `firmware/build.sh flasher` builds OpenCentauri's MIT-licensed `mcu-flasher`. Outputs go to ignored `firmware/build-output/`. Dependencies on Debian-like hosts: `git`, `make`, Python 3, `gcc-arm-none-eabi`, `binutils-arm-none-eabi`, and the ARM C library headers (`libnewlib-dev`, `libnewlib-arm-none-eabi`); Katapult uses the same ARM toolchain. Building mcu-flasher additionally needs Rust/Cargo, `pkg-config`, and `libudev-dev`.

## Board target is not confirmed

OpenCentauri CC1/CANVAS notes identify a GD32F303RCT6. The COSMOS Canvas Klipper and Katapult configs, however, both target `stm32f401xc`, 84 MHz, 24-MHz reference, USB PA11/PA12 and application address `0x08010000` (64 KiB). The source does not explain this silicon/target mismatch. Klipper and Katapult upstream provide a buildable STM32F401 target, so this project retains the COSMOS configuration to reproduce the only concrete CANVAS firmware recipe; this is **not evidence** that an F401 image can safely run on GD32F303 hardware. The flash map, clock, USB behavior, pin mux, bootloader offset and exact chip marking must be verified against the user's board revision before any flashing. Do not treat a successful compile as hardware validation.

`firmware/katapult/canvas.config` likewise preserves the upstream COSMOS 64-KiB bootloader/application layout. The Katapult build is only a software build check. No binary stock application image or verified recovery procedure is included.

## Simulation checks

- `pytest -q tests/firmware` exercises host-extra config, command serialization, status, bounded movement and stop behavior with fake Klipper objects.
- `firmware/build.sh klipper` compiles both `canvas-klipper.bin` and `linux-process-klipper.elf`; the former needs the ARM cross-compiler. The Linux process target is a simulation build, not a real Canvas hardware model.
- Firmware does not define CANVAS motor/lane pin assignments; available public sources do not establish those pin numbers.

Never connect an unknown CANVAS cable to a host, inject printer/motor voltage into USB, clear readout protection, or write firmware based only on these configs. Bring up only a user-owned unit on an isolated bench with stable/current-limited power and a separately verified recovery path.

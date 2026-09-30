# Flashing and recovery precautions

`./canvas-klipper.sh flash` is the combined two-stage path. It checks the local Moonraker `print_stats` state, builds missing/stale pinned firmware outputs (offering apt dependencies if needed), selects one serial device, runs the existing image-size/offset/USB-identity preflight, deploys Katapult using `mcu-flasher --canvas`, waits for re-enumeration, then writes Klipper with Katapult's `flashtool.py` and prints the resulting serial path. It refuses `printing`/`paused`; an unavailable/unknown Moonraker state requires `--force` (which never overrides an active print). Print state is rechecked immediately before each write.

Examples:

```sh
./canvas-klipper.sh flash --dry-run
./canvas-klipper.sh flash
./canvas-klipper.sh flash --device /dev/serial/by-id/DEVICE --vid-pid VVVV:PPPP
./canvas-klipper.sh flash --backup-file /safe/path/stock.dump --recovery-file /safe/path/recovery.bin
```

By default, device detection asks you to unplug the Canvas cable, snapshots `/dev/serial/by-id`, `/dev/serial/by-path`, and `/dev/ttyACM*`/`ttyUSB*`, then asks you to plug it back in. It requires exactly one new serial device and reports its sysfs/udev VID:PID and product. COSMOS's `klipper-firmware-canvas-init-d` contains an unverified `ID_VENDOR=ShenZhenCBD` check and a host-specific `/dev/serial/by-path/platform-4200000.usb-usb-0:1.4:1.0` path; the vendor string is used only as the default unplug/replug filter and is **not** verified hardware identity. `--vid-pid` filters candidates; `--device` explicitly selects one node, but its live VID:PID must still be readable. Stage 1 has no published reliable default VID:PID.

Before a write the command prints the full device identity and warns that the build target is STM32F401 while published hardware notes identify GD32F303. The one interactive confirmation must be copied exactly from the prompt; it explicitly names the device, VID:PID, USB product, chip mismatch, bricking risk, and backup/recovery status. Non-interactive operation requires both `--yes --i-understand-the-risks`. Optional `--backup-file` and `--recovery-file` are validated when supplied together.

**No stock firmware backup/recovery utility, verified factory image, or tested recovery route is included.** The one-command flow therefore does not require backup artifacts; the confirmation explicitly says no stock backup exists and recovery may require SWD. This is a deliberate, high-risk exception—not evidence that the board is recoverable. Do not flash unless the exact board revision/MCU, power, boot procedure, and recovery plan have been independently verified. Software build success is not hardware validation.

The existing `flash/canvas-flash` remains available for individual stages. Its default is dry-run. Direct destructive execution still requires `--execute --i-understand-the-risks`, an explicit device/VID:PID and confirmations; missing backup files are allowed only through the explicit `--allow-no-backup --yes --i-understand-the-risks` override. Do not retry an ambiguous/failed transfer automatically. The PTY bootloader tests are simulations only and do not validate real serial or firmware compatibility.

# Flashing and recovery precautions

`flash/canvas-flash --help` describes the two separate stages. Both require an explicitly selected device. The default is a dry run and never opens a serial device; a real write needs `--execute --i-understand-the-risks`, a matching USB VID:PID, existing stock-backup and recovery-image files, and three exact interactive confirmations. Example forms (not recommendations to flash an unverified board):

```sh
flash/canvas-flash --install-katapult --device /dev/serial/by-id/DEVICE \
  --deployer firmware/build-output/katapult-deployer-canvas.bin --vid-pid 1234:5678
flash/canvas-flash --flash-klipper --device /dev/serial/by-id/DEVICE \
  --firmware firmware/build-output/canvas-klipper.bin
```

Add `--stock-backup PATH --recovery-image PATH --execute --i-understand-the-risks` only after the hardware owner has verified those files and recovery route. Stage 1 uses the pinned OpenCentauri `mcu-flasher --canvas` YMODEM dialect to deploy Katapult. Stage 2 uses the pinned Katapult `flashtool.py` over serial. Stage 1's OEM USB identity is undocumented in the source set and must be supplied from observed hardware; stage 2 checks the Katapult identity `1d50:6177`. USB identity is checked from Linux sysfs without opening the serial port before the flasher is launched.

The preflight uses the pinned config's provisional 256-KiB flash size and 64-KiB application offset. It rejects a deployer larger than the flash after accounting for mcu-flasher's 16-KiB metadata prefix, and rejects Klipper images that exceed the region above the app offset. These values are not yet hardware-verified. The wrapper cannot prove that arbitrary firmware bytes were built for that exact MCU/offset; use only outputs of this repository's pinned build and verify their hashes/build metadata independently.

**Phase 0 is still a go/no-go gate.** No Canvas v1 boot-entry procedure, OEM VID:PID, verified stock dump, complete factory application image, Canvas readout-protection state, matching GD32F303 firmware target, or tested recovery method is established. A stock-bootloader artifact referenced in COSMOS is not the full OEM application or proof of a recovery path. Do not flash until the exact board revision and MCU are identified, existing readable flash has been backed up, and restoration/recovery has been tested by the hardware owner. Never explore readout-protection unlock; it may erase the device.

Use stable power. Do not disconnect, reset, or interrupt power during a write. Keep printers idle and disconnected from active work; this project does not contact any printer. On a failed or ambiguous transfer, stop; do not retry automatically. Follow the separately verified board-specific recovery procedure and manually confirm USB enumeration and Klipper MCU identity after success. The mock tests use pseudo-terminals only and do not establish real serial compatibility.

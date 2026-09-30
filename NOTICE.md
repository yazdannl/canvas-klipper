# Notices and attribution

Canvas Klipper is distributed under GNU GPL version 3; see [LICENSE](LICENSE). Copyright and license headers in individual files remain applicable. This notice summarizes the control and firmware provenance. Detailed firmware source revisions, file-level derivation and build information are retained in [NOTICE-firmware.md](NOTICE-firmware.md); that document is part of this project's corresponding-source notices and has not been replaced.

## CANVAS control layer

`canvas/canvas.py` is a standalone implementation with no AFC or Happy-Hare imports. Its load/unload, Hall odometry, retry and cutter behavior is informed by the GPL-3.0 AFC Canvas references:

- https://github.com/suchmememanyskill/AFC-Klipper-Add-On/blob/DEV/extras/AFC_canvas.py
- https://github.com/suchmememanyskill/AFC-Klipper-Add-On/blob/DEV/extras/AFC_canvas_lane.py

No AFC core or Happy-Hare runtime code is included. The source retains GPL-3.0 distribution terms and attribution.

## DRV8833 MCU and host support

`klipper/0001-drv8833-mcu.patch` adapts MCU-side Kconfig, Makefile and C driver work from OpenCentauri COSMOS patch `0003-drv8833-motor-control.patch`; `klipper/klippy/extras/drv8833.py` is a reduced host-side adaptation that preserves COSMOS configuration names and API. Both are GPL-3.0; see their file headers and `NOTICE-firmware.md` for pinned source details.

Klipper and Katapult are GPL-3.0 projects. The flash wrapper invokes the separately built OpenCentauri `mcu-flasher` (MIT) and Katapult's flash utility; their source is not vendored here. No proprietary CANVAS firmware image or stock recovery binary is included.

## Upstream projects

- OpenCentauri COSMOS — https://github.com/OpenCentauri/cosmos — GPL-3.0
- AFC Canvas fork — https://github.com/suchmememanyskill/AFC-Klipper-Add-On — GPL-3.0
- Klipper — https://github.com/Klipper3d/klipper — GPL-3.0
- Katapult — https://github.com/Arksine/katapult — GPL-3.0
- OpenCentauri `mcu-flasher` — https://github.com/OpenCentauri/OpenCentauri — MIT

The comprehensive pinned revision table, patch derivation and flashing-artifact notes are in [NOTICE-firmware.md](NOTICE-firmware.md).

# Firmware source notices and provenance

This project is GPL-3.0 by default, consistent with Klipper/Katapult-derived firmware support. Preserve upstream notices when redistributing source or binaries.

| Component | Source / pinned revision | License | Use here |
|---|---|---|---|
| Klipper | https://github.com/Klipper3d/klipper — `7bc4d09465d31cd30fc0822e8d0abe02cc8c547f` | GPL-3.0 | MCU firmware build target and upstream build system |
| Katapult | https://github.com/Arksine/katapult — `ec59b9bb9ad6c2ec8d4dc6831fbc77f0b308e29e` | GPL-3.0 | Deployable bootloader build and serial flash utility |
| OpenCentauri COSMOS | https://github.com/OpenCentauri/cosmos — `31cf90991d835b7390f52d73753558edb033d1f4` | GPL-3.0 | Reference for Canvas configs and `0003-drv8833-motor-control.patch`; MCU C implementation and host API are derived/adapted, with diagnostic extras omitted |
| OpenCentauri tools | https://github.com/OpenCentauri/OpenCentauri — `c921b0fc40fb64bd6d677c75a976a07324112096` | MIT | `mcu-flasher` Canvas YMODEM utility, built from pinned source |

`klipper/0001-drv8833-mcu.patch` is adapted from the MCU-side Kconfig/Makefile/C portions of COSMOS patch `0003-drv8833-motor-control.patch`; the new host extra `klipper/drv8833.py` preserves the upstream COSMOS API/config field names and is a reduced host-side adaptation. Its header retains the upstream GPL notice. The flasher wrapper is new project code and invokes, rather than vendors, the MIT flasher and GPL Katapult utility.

The source revisions above are recorded in `firmware/versions.lock`. The stock bootloader/application binary is not redistributed. No proprietary firmware or recovery image is included; verify legality and board match before obtaining or using such files.

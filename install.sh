#!/usr/bin/env bash
set -euo pipefail
set +x

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
KLIPPER_DIR=${KLIPPER_DIR:-"${HOME:?HOME must be set}/klipper"}
EXTRAS="$KLIPPER_DIR/klippy/extras"

if [[ ! -d "$EXTRAS" ]]; then
    echo "Klipper extras directory not found: $EXTRAS (set KLIPPER_DIR to the checkout root)" >&2
    exit 2
fi

sources=("$ROOT"/canvas/*.py "$ROOT/klipper/klippy/extras/drv8833.py")
for source in "${sources[@]}"; do
    [[ -f "$source" ]] || { echo "Missing source: $source" >&2; exit 2; }
done

# Preflight every target before creating any link. Existing matching links are
# left untouched; every other existing file, directory, or symlink is a conflict.
for source in "${sources[@]}"; do
    destination="$EXTRAS/$(basename -- "$source")"
    if [[ -e "$destination" || -L "$destination" ]]; then
        if [[ -L "$destination" && "$(readlink -f -- "$destination")" == "$source" ]]; then
            continue
        fi
        echo "Refusing to overwrite existing path: $destination" >&2
        exit 3
    fi
done

for source in "${sources[@]}"; do
    destination="$EXTRAS/$(basename -- "$source")"
    if [[ ! -L "$destination" ]]; then
        ln -s -- "$source" "$destination"
        printf 'Linked %s -> %s\n' "$destination" "$source"
    fi
done

cat <<EOF

Control extras linked. This installer did not edit printer.cfg, apply patches,
restart Klipper, or flash firmware.

For MCU support, use a separate Klipper source checkout. Review then apply:
  git -C "$KLIPPER_DIR" apply --check "$ROOT/klipper/0001-drv8833-mcu.patch"
  git -C "$KLIPPER_DIR" apply "$ROOT/klipper/0001-drv8833-mcu.patch"
Build the pinned project firmware with:
  "$ROOT/firmware/build.sh" klipper

Review README.md and docs before wiring or flashing. Build success does not
resolve the GD32F303RCT6 vs STM32F401XC target uncertainty. Firmware flashing is
a separate, explicit, hardware-gated operation.
EOF

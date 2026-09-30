#!/usr/bin/env bash
set -euo pipefail
set +x

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
KLIPPER_DIR=${KLIPPER_DIR:-"$ROOT/firmware/.build/work/klipper"}
DICT="$ROOT/firmware/build-output/linux-process-klipper.dict"
PYTHON=${KLIPPY_PYTHON:-"$ROOT/firmware/.build/klippy-venv/bin/python"}
[[ -x "$PYTHON" ]] || PYTHON=${PYTHON_FALLBACK:-python3}

if [[ ! -f "$KLIPPER_DIR/klippy/klippy.py" || ! -s "$DICT" ]]; then
    echo "Pinned Klipper build or linux-process dictionary is missing: run firmware/build.sh klipper" >&2
    exit 77
fi

# Klipper imports config sections as extras.<name>; this symlink stays only in
# the ignored build checkout and is never copied into a user's active Klipper.
canvas_extra="$KLIPPER_DIR/klippy/extras/canvas.py"
if [[ -L "$canvas_extra" ]]; then
    [[ "$(readlink -f -- "$canvas_extra")" == "$ROOT/canvas/canvas.py" ]] || {
        echo "Refusing conflicting build-extra path: $canvas_extra" >&2; exit 2;
    }
elif [[ -e "$canvas_extra" ]]; then
    echo "Refusing conflicting build-extra path: $canvas_extra" >&2
    exit 2
else
    ln -s -- "$ROOT/canvas/canvas.py" "$canvas_extra"
fi

TMP=$(mktemp -d "$KLIPPER_DIR/.canvas-batch.XXXXXX")
trap 'rm -rf -- "$TMP"' EXIT
LOG="$TMP/klippy.log"
GCODE="$ROOT/tests/klipper/commands.gcode"
CONFIG="$ROOT/tests/klipper/printer.cfg"

"$PYTHON" "$KLIPPER_DIR/klippy/klippy.py" \
    -o /dev/null -d "$DICT" -i "$GCODE" -l "$LOG" "$CONFIG"

if grep -q "Unknown command" "$LOG"; then
    echo "Batch G-code had an unregistered command" >&2
    exit 1
fi
if ! grep -q "Canvas active=" "$LOG"; then
    echo "CANVAS_STATUS did not execute in Klipper batch mode" >&2
    exit 1
fi
printf '%s\n' "Klipper batch-mode config and T0/T1/CANVAS_STATUS passed."

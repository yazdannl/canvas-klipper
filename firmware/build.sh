#!/usr/bin/env bash
set -euo pipefail

HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
ROOT=$(cd -- "$HERE/.." && pwd)
LOCK="$HERE/versions.lock"
WORK="$HERE/.build/work"
OUT="$HERE/build-output"

lock_value() { awk -v name="$1" '$1 == name { print $3; exit }' "$LOCK"; }
lock_url() { awk -v name="$1" '$1 == name { print $2; exit }' "$LOCK"; }

ensure_checkout() {
    local name="$1" url commit dir
    url=$(lock_url "$name"); commit=$(lock_value "$name"); dir="$WORK/$name"
    if [[ ! -d "$dir/.git" ]]; then
        mkdir -p "$WORK"
        git clone --no-checkout "$url" "$dir"
    fi
    if [[ ! -f "$dir/Makefile" || "$(git -C "$dir" rev-parse HEAD 2>/dev/null || true)" != "$commit" ]]; then
        if [[ -f "$dir/Makefile" && -n "$(git -C "$dir" status --porcelain 2>/dev/null || true)" ]]; then
            echo "Refusing to change dirty build checkout: $dir" >&2; exit 2
        fi
        git -C "$dir" fetch --depth 1 origin "$commit"
        git -C "$dir" checkout --detach "$commit"
    fi
    printf '%s\n' "$dir"
}

prepare_klipper() {
    local dir patch stamp patch_hash
    dir=$(ensure_checkout klipper)
    patch="$ROOT/klipper/0001-drv8833-mcu.patch"
    stamp="$dir/.canvas-drv8833-patch-sha256"
    patch_hash=$(sha256sum "$patch" | awk '{print $1}')
    if [[ -f "$stamp" ]]; then
        [[ "$(<"$stamp")" == "$patch_hash" ]] || {
            echo "Pinned Klipper checkout has a different driver patch; use a fresh ignored build dir" >&2; exit 2;
        }
    elif git -C "$dir" apply --reverse --check "$patch" >/dev/null 2>&1; then
        printf '%s\n' "$patch_hash" > "$stamp"
    else
        git -C "$dir" apply --check "$patch"
        git -C "$dir" apply "$patch"
        printf '%s\n' "$patch_hash" > "$stamp"
    fi
    cp -- "$ROOT/klipper/klippy/extras/drv8833.py" "$dir/klippy/extras/drv8833.py"
    printf '%s\n' "$dir"
}

build_klipper_config() {
    local dir="$1" config="$2" name="$3"
    cp -- "$config" "$dir/.config"
    make -C "$dir" olddefconfig
    make -C "$dir" clean
    make -C "$dir" -j"$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 2)"
    cp -- "$dir/out/klipper.dict" "$OUT/$name.dict"
    if [[ -f "$dir/out/klipper.bin" ]]; then
        cp -- "$dir/out/klipper.bin" "$OUT/$name.bin"
    else
        cp -- "$dir/out/klipper.elf" "$OUT/$name.elf"
    fi
}

build_klipper() {
    mkdir -p "$OUT"
    local dir
    dir=$(prepare_klipper)
    # Klipper's process target exercises compilation of the driver against the
    # host GPIO/PWM implementation without connecting to physical hardware.
    build_klipper_config "$dir" "$HERE/linux-process.config" linux-process-klipper
    command -v arm-none-eabi-gcc >/dev/null || {
        echo "Linux-process build passed, but Canvas firmware needs gcc-arm-none-eabi and binutils-arm-none-eabi" >&2; exit 2;
    }
    build_klipper_config "$dir" "$HERE/klipper/canvas.config" canvas-klipper
}

build_katapult() {
    mkdir -p "$OUT"
    local dir
    dir=$(ensure_checkout katapult)
    cp -- "$HERE/katapult/canvas.config" "$dir/.config"
    make -C "$dir" olddefconfig
    make -C "$dir" clean
    make -C "$dir" -j"$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 2)"
    [[ -s "$dir/out/deployer.bin" ]] || { echo "Katapult deployer output was not produced" >&2; exit 2; }
    cp -- "$dir/out/deployer.bin" "$OUT/katapult-deployer-canvas.bin"
    cp -- "$dir/out/katapult.bin" "$OUT/katapult-canvas.bin"
}

build_flasher() {
    command -v cargo >/dev/null || { echo "Missing Rust toolchain (cargo)" >&2; exit 2; }
    local dir
    dir=$(ensure_checkout mcu-flasher)
    cargo build --locked --release --manifest-path "$dir/mcu-flasher/Cargo.toml"
    mkdir -p "$OUT"
    cp -- "$dir/mcu-flasher/target/release/mcu-flasher" "$OUT/mcu-flasher"
}

case "${1:-all}" in
    klipper) build_klipper ;;
    katapult) build_katapult ;;
    flasher) build_flasher ;;
    all) build_klipper; build_katapult; build_flasher ;;
    *) echo "Usage: $0 [all|klipper|katapult|flasher]" >&2; exit 2 ;;
esac

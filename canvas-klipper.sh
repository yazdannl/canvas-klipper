#!/usr/bin/env bash
set -euo pipefail
set +x
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
exec python3 "$ROOT/installer/manager.py" "$@"

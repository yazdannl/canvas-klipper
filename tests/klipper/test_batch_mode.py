import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
KLIPPER_DIR = ROOT / "firmware" / ".build" / "work" / "klipper"


def test_pinned_klipper_batch_config_and_commands():
    if not (KLIPPER_DIR / "klippy" / "klippy.py").is_file():
        pytest.skip("pinned Klipper build is absent; run firmware/build.sh klipper")
    if not (ROOT / "firmware" / "build-output" /
            "linux-process-klipper.dict").is_file():
        pytest.skip("linux-process Klipper dictionary is absent; run firmware/build.sh klipper")

    python = ROOT / "firmware" / ".build" / "klippy-venv" / "bin" / "python"
    if python.is_file():
        env_python = str(python)
    else:
        env_python = os.environ.get("KLIPPY_PYTHON", "python3")
        probe = subprocess.run(
            [env_python, "-c", "import greenlet, jinja2, cffi, serial"],
            capture_output=True,
            text=True,
            check=False,
        )
        if probe.returncode:
            pytest.skip("Klipper batch dependencies are unavailable")

    env = {"PATH": os.defpath, "KLIPPY_PYTHON": env_python}
    result = subprocess.run(
        ["bash", str(ROOT / "tests" / "klipper" / "run_batch_test.sh")],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "batch-mode config and T0/T1/CANVAS_STATUS passed" in result.stdout

import http.server
import importlib.util
import json
import os
from pathlib import Path
import pty
import subprocess
import threading
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).parents[2]
spec = importlib.util.spec_from_file_location("canvas_manager", ROOT / "installer/manager.py")
manager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manager)

flash_test_path = ROOT / "tests/flash/test_canvas_flash.py"
flash_spec = importlib.util.spec_from_file_location("flash_mock_helpers", flash_test_path)
flash_helpers = importlib.util.module_from_spec(flash_spec)
flash_spec.loader.exec_module(flash_helpers)


class StateHandler(http.server.BaseHTTPRequestHandler):
    state = "standby"

    def do_GET(self):
        data = {"result": {"status": {"print_stats": {"state": self.state}}}}
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


@pytest.fixture

def moonraker():
    StateHandler.state = "standby"
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), StateHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:%d" % server.server_port
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def fake_tree(tmp_path, *, sensor=True):
    home = tmp_path / "home"
    klipper = home / "klipper"
    extras = klipper / "klippy/extras"
    extras.mkdir(parents=True)
    config = home / "printer_data/config"
    config.mkdir(parents=True)
    (config / "printer.cfg").write_text(
        "[extruder]\nstep_pin: PA0\n\n[include parts.cfg]\n", encoding="utf-8")
    sections = "[filament_switch_sensor tool_sensor]\nswitch_pin: PA1\n"
    if sensor:
        (config / "parts.cfg").write_text(sections, encoding="utf-8")
    else:
        (config / "parts.cfg").write_text("[stepper_x]\nstep_pin: PA2\n", encoding="utf-8")
    (config / "moonraker.conf").write_text("[server]\nport: 7125\n", encoding="utf-8")
    serial_root = tmp_path / "serial/by-id"
    serial_root.mkdir(parents=True)
    tty = tmp_path / "dev/ttyACM-fake"
    tty.parent.mkdir()
    tty.write_text("fake serial node")
    link = serial_root / "usb-Canvas_test"
    link.symlink_to(tty)
    return home, klipper, config, link


def fake_commands(tmp_path, monkeypatch):
    bin_dir = tmp_path / "fake-bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"
    script = "#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$FAKE_CALL_LOG\"\nexit 0\n"
    for name in ("sudo", "systemctl", "apt", "apt-get"):
        command = bin_dir / name
        command.write_text(script, encoding="utf-8")
        command.chmod(0o755)
    monkeypatch.setenv("FAKE_CALL_LOG", str(log))
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ["PATH"])
    return log


def cli_install(klipper, config, moonraker, serial, *, sensor="tool_sensor", pin=None,
                method="tip_forming", force=False):
    argv = ["install", "--klipper-dir", str(klipper), "--config-dir", str(config),
            "--moonraker-url", moonraker, "--serial", str(serial), "--non-interactive",
            "--toolhead-sensor", sensor, "--separation-method", method]
    if pin:
        argv += ["--toolhead-pin", pin]
    if force:
        argv += ["--force"]
    return manager.make_parser().parse_args(argv)


def test_install_fresh_and_rerun_are_safe_and_idempotent(tmp_path, monkeypatch, moonraker):
    home, klipper, config, serial = fake_tree(tmp_path)
    log = fake_commands(tmp_path, monkeypatch)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CANVAS_SERIAL_BY_ID_DIR", str(serial.parent))
    args = cli_install(klipper, config, moonraker, serial)

    assert manager.install(args) == 0
    printer = (config / "printer.cfg").read_text()
    moon = (config / "moonraker.conf").read_text()
    generated = (config / "canvas/canvas.cfg").read_text()
    assert printer.count("[include canvas/*.cfg]") == 1
    assert "[update_manager canvas-klipper]" in moon
    assert "serial: %s" % serial in generated
    assert "toolhead_sensor: tool_sensor" in generated
    assert "separation_method: tip_forming" in generated
    assert "[filament_switch_sensor tool_sensor]" not in generated
    assert (klipper / "klippy/extras/canvas.py").is_symlink()
    assert len(list(config.glob("printer.cfg.*.bak"))) == 1
    assert len(list(config.glob("moonraker.conf.*.bak"))) == 1
    assert manager.install(args) == 0
    assert (config / "printer.cfg").read_text() == printer
    assert (config / "moonraker.conf").read_text() == moon
    assert (config / "canvas/canvas.cfg").read_text() == generated
    assert len(list(config.glob("printer.cfg.*.bak"))) == 1
    assert len(list(config.glob("moonraker.conf.*.bak"))) == 1
    assert not log.exists()  # incomplete pin scaffold is never restarted


def test_install_cli_runs_with_fake_home(tmp_path, monkeypatch, moonraker):
    home, klipper, config, serial = fake_tree(tmp_path)
    log = fake_commands(tmp_path, monkeypatch)
    env = {**os.environ, "HOME": str(home), "CANVAS_SERIAL_BY_ID_DIR": str(serial.parent)}
    command = [str(ROOT / "canvas-klipper.sh"), "install", "--klipper-dir", str(klipper),
               "--config-dir", str(config), "--moonraker-url", moonraker, "--serial", str(serial),
               "--non-interactive", "--toolhead-sensor", "tool_sensor", "--separation-method", "cutter"]
    result = subprocess.run(command, env=env, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    assert "[include canvas/*.cfg]" in (config / "printer.cfg").read_text()
    assert "separation_method: cutter" in (config / "canvas/canvas.cfg").read_text()
    assert "restart deferred" in result.stdout
    assert not log.exists()  # the copied template has no measured lane pins yet


def test_install_without_sensor_generates_sensor_config(tmp_path, monkeypatch, moonraker):
    home, klipper, config, serial = fake_tree(tmp_path, sensor=False)
    fake_commands(tmp_path, monkeypatch)
    args = cli_install(klipper, config, moonraker, serial, sensor="canvas_toolhead", pin="PA7")
    assert manager.install(args) == 0
    generated = (config / "canvas/canvas.cfg").read_text()
    assert "[filament_switch_sensor canvas_toolhead]\nswitch_pin: PA7" in generated
    assert "toolhead_sensor: canvas_toolhead" in generated


def add_measured_pins(config_dir):
    path = config_dir / "canvas/canvas.cfg"
    text = path.read_text()
    lane_lines = "".join(
        "lane_T%d_motor: T%d\nlane_T%d_present_pin: canvas:PA%d\nlane_T%d_prep_pin: canvas:PB%d\n" %
        (lane, lane, lane, lane, lane, lane)
        for lane in range(4))
    insertion = text.index("# T0 example.")
    text = text[:insertion] + lane_lines + text[insertion:]
    for lane in range(4):
        text += ("\n[drv8833 T%d]\nmotor_fwd: canvas:PA%d\nmotor_rwd: canvas:PB%d\n"
                 "motor_hall: canvas:PC%d\nmotor_hall_resolution: 0.5\n" %
                 (lane, lane, lane, lane))
    path.write_text(text)


def test_restart_waits_for_measured_config_then_is_idempotent(tmp_path, monkeypatch, moonraker):
    home, klipper, config, serial = fake_tree(tmp_path)
    log = fake_commands(tmp_path, monkeypatch)
    args = cli_install(klipper, config, moonraker, serial)
    manager.install(args)
    assert not log.exists()
    add_measured_pins(config)
    assert manager.install(args) == 0
    calls = log.read_text().splitlines()
    assert calls == ["systemctl restart klipper", "systemctl restart moonraker"]
    assert manager.install(args) == 0
    assert log.read_text().splitlines() == calls


def test_install_refuses_printing_before_any_changes(tmp_path, monkeypatch, moonraker):
    home, klipper, config, serial = fake_tree(tmp_path)
    log = fake_commands(tmp_path, monkeypatch)
    original_printer = (config / "printer.cfg").read_text()
    original_moon = (config / "moonraker.conf").read_text()
    StateHandler.state = "printing"
    with pytest.raises(ValueError, match="printing"):
        manager.install(cli_install(klipper, config, moonraker, serial))
    assert (config / "printer.cfg").read_text() == original_printer
    assert (config / "moonraker.conf").read_text() == original_moon
    assert not (klipper / "klippy/extras/canvas.py").exists()
    assert not log.exists()


def test_install_refuses_unknown_state_without_force(tmp_path, monkeypatch):
    home, klipper, config, serial = fake_tree(tmp_path)
    fake_commands(tmp_path, monkeypatch)
    args = cli_install(klipper, config, "http://127.0.0.1:1", serial)
    with pytest.raises(ValueError, match="unknown"):
        manager.install(args)
    assert not (klipper / "klippy/extras/canvas.py").exists()


def test_uninstall_removes_references_but_preserves_user_data_as_bak(tmp_path, monkeypatch, moonraker):
    home, klipper, config, serial = fake_tree(tmp_path)
    fake_commands(tmp_path, monkeypatch)
    args = cli_install(klipper, config, moonraker, serial)
    manager.install(args)
    printer = config / "printer.cfg"
    moon = config / "moonraker.conf"
    uninstall_args = manager.make_parser().parse_args([
        "uninstall", "--klipper-dir", str(klipper), "--config-dir", str(config),
        "--moonraker-url", moonraker])
    assert manager.uninstall(uninstall_args) == 0
    assert "[include canvas/*.cfg]" not in printer.read_text()
    assert "[update_manager canvas-klipper]" not in moon.read_text()
    assert not (config / "canvas").exists()
    assert list(config.glob("canvas.*.bak"))
    assert list(klipper.glob("klippy/extras/canvas.py.*.bak"))
    assert list(config.glob("printer.cfg.*.bak"))
    assert list(config.glob("moonraker.conf.*.bak"))


def test_flash_device_detection_requires_exactly_one_matching_candidate(tmp_path, monkeypatch):
    candidates = []
    monkeypatch.setattr(manager, "serial_paths", lambda: list(candidates))
    monkeypatch.setattr(manager, "device_info", lambda _p: {
        "vid_pid": "1234:5678", "vendor": "Canvas", "product": "USB serial"})
    with pytest.raises(ValueError, match="found 0"):
        manager.detect_device(None, "1234:5678", prompt=False)
    paths = [tmp_path / "one", tmp_path / "two"]
    for path in paths:
        path.touch()
    candidates[:] = paths[:1]
    assert manager.detect_device(None, "1234:5678", prompt=False) == (str(paths[0]), "1234:5678")
    candidates[:] = paths
    with pytest.raises(ValueError, match="found 2"):
        manager.detect_device(None, "1234:5678", prompt=False)


def test_flash_unplug_replug_filters_cosmos_vendor(tmp_path, monkeypatch):
    new_device = tmp_path / "ttyACM0"
    new_device.touch()
    states = [[], [new_device]]
    monkeypatch.setattr(manager, "serial_paths", lambda: states.pop(0))
    monkeypatch.setattr(manager, "device_info", lambda _p: {
        "vid_pid": "abcd:0001", "vendor": "ShenZhenCBD", "product": "Canvas"})
    messages = []
    path, identity = manager.detect_device(None, None, input_fn=lambda _p: "", output=messages.append)
    assert path == str(new_device)
    assert identity == "abcd:0001"
    assert any("unverified filter from COSMOS" in message for message in messages)


def test_flash_dry_run_is_offline():
    args = manager.make_parser().parse_args(["flash", "--dry-run"])
    assert manager.flash(args) == 0


def test_flash_end_to_end_uses_existing_pty_bootloader_mock(tmp_path, monkeypatch, moonraker, capsys):
    repo = tmp_path / "repo"
    firmware_dir = repo / "firmware"
    output_dir = firmware_dir / "build-output"
    (firmware_dir / "katapult").mkdir(parents=True)
    (firmware_dir / "klipper").mkdir()
    output_dir.mkdir()
    for relative in ("build.sh", "versions.lock", "katapult/canvas.config", "klipper/canvas.config",
                     "linux-process.config"):
        path = firmware_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("build input")
    patch = repo / "klipper/0001-drv8833-mcu.patch"
    patch.parent.mkdir(parents=True)
    patch.write_text("patch")
    driver = repo / "klipper/klippy/extras/drv8833.py"
    driver.parent.mkdir(parents=True)
    driver.write_text("driver")
    deployer = output_dir / "katapult-deployer-canvas.bin"
    firmware = output_dir / "canvas-klipper.bin"
    deployer.write_bytes(b"deployer-image")
    firmware.write_bytes(b"klipper-image")
    time_old = 1000000000
    for item in [*firmware_dir.rglob("*"), patch, driver]:
        if item.is_file():
            os.utime(item, (time_old, time_old))
    os.utime(deployer, (time_old + 20, time_old + 20))
    os.utime(firmware, (time_old + 20, time_old + 20))
    mcu_flasher = tmp_path / "mcu-flasher"
    mcu_flasher.write_text("mock")
    mcu_flasher.chmod(0o755)
    katapult_tool = tmp_path / "flashtool.py"
    katapult_tool.write_text("mock")
    os.utime(mcu_flasher, (time_old, time_old))
    os.utime(katapult_tool, (time_old, time_old))
    monkeypatch.setattr(manager, "ROOT", repo)
    monkeypatch.setattr(manager.flash_tool, "PINNED_MCU_FLASHER", mcu_flasher)
    monkeypatch.setattr(manager.flash_tool, "PINNED_KATAPULT_FLASHTOOL", katapult_tool)

    master, slave = pty.openpty()
    device = os.ttyname(slave)
    monkeypatch.setattr(manager, "detect_device", lambda *_a, **_k: (device, "1234:5678"))
    monkeypatch.setattr(manager, "device_info", lambda _path: {
        "vid_pid": "1234:5678", "vendor": "Canvas", "product": "Canvas USB"})
    identities = iter(("1234:5678", manager.KATAPULT_VID_PID))
    monkeypatch.setattr(manager, "FLASH_IDENTITY_READER", lambda _path: next(identities))
    monkeypatch.setattr(manager, "wait_for_device", lambda expected, _timeout: (device, expected))
    by_id = tmp_path / "by-id"
    by_id.mkdir()
    monkeypatch.setenv("CANVAS_SERIAL_BY_ID_DIR", str(by_id))
    StateHandler.state = "standby"
    calls = []

    def flash_runner(command, **kwargs):
        calls.append(command)
        if "--canvas" in command:
            flash_helpers.canvas_transfer(slave, master, deployer.read_bytes())
        else:
            flash_helpers.katapult_transfer(slave, master, firmware.read_bytes())
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(manager, "FLASH_RUNNER", flash_runner)
    phrase = ("I ACCEPT BRICKING RISK; GD32F303 VS STM32F401; FLASH %s VID:PID 1234:5678 PRODUCT Canvas USB; "
              "WITHOUT STOCK BACKUP; RECOVERY MAY REQUIRE SWD" % device)
    monkeypatch.setattr("builtins.input", lambda _prompt: phrase)
    args = manager.make_parser().parse_args([
        "flash", "--device", device, "--i-understand-the-risks", "--moonraker-url", moonraker,
        "--enumeration-timeout", "0.1"])
    try:
        assert manager.flash(args) == 0
        assert len(calls) == 2
        assert "--canvas" in calls[0]
        assert calls[1][1].endswith("flashtool.py")
        assert "Klipper device enumerated at: %s" % device in capsys.readouterr().out
    finally:
        os.close(master)
        os.close(slave)

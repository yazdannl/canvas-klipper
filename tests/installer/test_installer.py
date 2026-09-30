import http.server
import importlib.util
import json
import os
from pathlib import Path
import pty
import re
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


def test_install_fresh_and_rerun_are_safe_and_idempotent(tmp_path, monkeypatch, moonraker, capsys):
    home, klipper, config, serial = fake_tree(tmp_path)
    log = fake_commands(tmp_path, monkeypatch)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CANVAS_SERIAL_BY_ID_DIR", str(serial.parent))
    args = cli_install(klipper, config, moonraker, serial)
    original_printer = (config / "printer.cfg").read_text()

    assert manager.install(args) == 0
    printer = (config / "printer.cfg").read_text()
    moon = (config / "moonraker.conf").read_text()
    generated = (config / "canvas/canvas.cfg").read_text()
    # The lane-present pins are optional, so nothing blocks the include or the restart.
    assert printer.startswith(original_printer.rstrip())
    assert printer.count("[include canvas/*.cfg]") == 1
    assert "[update_manager canvas-klipper]" in moon
    assert "serial: %s" % serial in generated
    assert "toolhead_sensor: tool_sensor" in generated
    assert "separation_method: tip_forming" in generated
    assert "[filament_switch_sensor tool_sensor]" not in generated
    assert not re.search(r"(?m)^\s*lane_T\d_present_pin:", generated)
    assert [line for line in generated.splitlines()
            if "TO_BE_MEASURED" in line and not line.strip().startswith("#")] == []
    assert manager.canvas_config_complete(config / "printer.cfg", config / "canvas/canvas.cfg")
    assert (klipper / "klippy/extras/canvas.py").is_symlink()
    assert len(list(config.glob("printer.cfg.*.bak"))) == 1
    assert len(list(config.glob("moonraker.conf.*.bak"))) == 1
    out = capsys.readouterr().out
    assert "restart deferred" not in out
    assert "NOT verified on your hardware" in out
    for risk in ("T1/T3", "hotend:PB0", "hotend:PB2", "motor_hall_resolution 0.26242"):
        assert risk in out, risk
    calls = log.read_text().splitlines()
    assert calls == ["systemctl restart klipper", "systemctl restart moonraker"]

    assert manager.install(args) == 0
    assert (config / "printer.cfg").read_text() == printer
    assert (config / "moonraker.conf").read_text() == moon
    assert (config / "canvas/canvas.cfg").read_text() == generated
    assert len(list(config.glob("printer.cfg.*.bak"))) == 1
    assert len(list(config.glob("moonraker.conf.*.bak"))) == 1
    assert log.read_text().splitlines() == calls  # rerun restarts nothing


def test_install_cli_runs_with_fake_home(tmp_path, monkeypatch, moonraker):
    home, klipper, config, serial = fake_tree(tmp_path)
    log = fake_commands(tmp_path, monkeypatch)
    env = {**os.environ, "HOME": str(home), "CANVAS_SERIAL_BY_ID_DIR": str(serial.parent)}
    command = [str(ROOT / "canvas-klipper.sh"), "install", "--klipper-dir", str(klipper),
               "--config-dir", str(config), "--moonraker-url", moonraker, "--serial", str(serial),
               "--non-interactive", "--toolhead-sensor", "tool_sensor", "--separation-method", "cutter"]
    result = subprocess.run(command, env=env, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    assert (config / "printer.cfg").read_text().count("[include canvas/*.cfg]") == 1
    assert "separation_method: cutter" in (config / "canvas/canvas.cfg").read_text()
    assert "restart deferred" not in result.stdout
    assert "NOT verified on your hardware" in result.stdout
    assert log.read_text().splitlines() == ["systemctl restart klipper", "systemctl restart moonraker"]


def test_install_without_sensor_generates_sensor_config(tmp_path, monkeypatch, moonraker):
    home, klipper, config, serial = fake_tree(tmp_path, sensor=False)
    fake_commands(tmp_path, monkeypatch)
    args = cli_install(klipper, config, moonraker, serial, sensor="canvas_toolhead", pin="PA7")
    assert manager.install(args) == 0
    generated = (config / "canvas/canvas.cfg").read_text()
    assert "[filament_switch_sensor canvas_toolhead]\nswitch_pin: PA7" in generated
    assert "toolhead_sensor: canvas_toolhead" in generated


def break_required_pin(config_dir, key):
    """Put the shipped template's remaining placeholder back into a required key."""
    path = config_dir / "canvas/canvas.cfg"
    text = path.read_text()
    setting = re.search(r"(?m)^(%s:\s*).*$" % re.escape(key), text)
    assert setting, key
    return fill_required_pin(config_dir, key, "TO_BE_MEASURED")


def fill_required_pin(config_dir, key, value):
    path = config_dir / "canvas/canvas.cfg"
    text = path.read_text()
    text, count = re.subn(r"(?m)^(%s:\s*).*$" % re.escape(key), lambda m: m.group(1) + value,
                          text, count=1)
    assert count == 1, key
    path.write_text(text)


def add_present_pins(config_dir, pin="canvas:PC4"):
    """Opt in to real per-lane presence switches, as a user who fitted them would."""
    path = config_dir / "canvas/canvas.cfg"
    text = path.read_text()
    for lane in range(4):
        source = "# lane_T%d_present_pin: TO_BE_MEASURED" % lane
        assert source in text
        text = text.replace(source, "lane_T%d_present_pin: %s" % (lane, pin))
    path.write_text(text)


def test_shipped_template_has_no_placeholders_and_optional_lane_present_pins():
    """The distributed template must carry no placeholder and no lane-present key."""
    template = (ROOT / "config/canvas.cfg").read_text()
    settings = manager.canvas_settings([ROOT / "config/canvas.cfg"])
    assert "__duplicate_sections__" not in settings
    canvas = settings["canvas"]
    for lane in range(4):
        driver = settings["drv8833 t%d" % lane]
        for option in ("motor_fwd", "motor_rwd", "motor_hall", "motor_hall_resolution"):
            assert driver[option] and not driver[option].startswith("TO_BE_MEASURED")
        assert canvas["lane_t%d_motor" % lane] == "T%d" % lane
        assert canvas["lane_t%d_prep_pin" % lane].startswith("canvas:")
        # Optional: presence is derived from the prep switch until a real switch is set.
        assert "lane_t%d_present_pin" % lane not in canvas
    # Any other placeholder would be a silent gap in the published pin map.
    leftovers = [line for line in template.splitlines()
                 if "TO_BE_MEASURED" in line and not line.strip().startswith("#")]
    assert leftovers == []
    assert "# lane_T3_present_pin: TO_BE_MEASURED" in template  # documented opt-in block


def test_canvas_config_complete_treats_lane_present_pins_as_optional(tmp_path):
    """Absent optional pins must not block; any surviving placeholder must."""
    config = tmp_path / "printer_data/config"
    (config / "canvas").mkdir(parents=True)
    (config / "printer.cfg").write_text(
        "[extruder]\nstep_pin: PA0\n\n[filament_switch_sensor tool_sensor]\n"
        "switch_pin: PA1\n", encoding="utf-8")
    canvas_cfg = config / "canvas/canvas.cfg"
    shipped = (ROOT / "config/canvas.cfg").read_text(encoding="utf-8").replace(
        "toolhead_sensor: toolhead", "toolhead_sensor: tool_sensor")
    head = "[mcu canvas]\nserial: /dev/serial/by-id/usb-Canvas\n\n"

    canvas_cfg.write_text(head + shipped, encoding="utf-8")
    assert manager.canvas_config_complete(config / "printer.cfg", canvas_cfg) is True

    # An optional key that is set to a placeholder still blocks: it is not a usable pin.
    for lane in range(4):
        broken = shipped.replace("# lane_T%d_present_pin: TO_BE_MEASURED" % lane,
                                 "lane_T%d_present_pin: TO_BE_MEASURED" % lane)
        canvas_cfg.write_text(head + broken, encoding="utf-8")
        assert manager.canvas_config_complete(config / "printer.cfg", canvas_cfg) is False
    # A measured optional value is accepted and does not re-block.
    canvas_cfg.write_text(head + shipped.replace(
        "# lane_T0_present_pin: TO_BE_MEASURED", "lane_T0_present_pin: canvas:PC4"),
        encoding="utf-8")
    assert manager.canvas_config_complete(config / "printer.cfg", canvas_cfg) is True

    complete = head + shipped.replace(
        "# lane_T0_present_pin: TO_BE_MEASURED", "lane_T0_present_pin: canvas:PC4")
    for source, broken in (("motor_hall: canvas:PB6", "motor_hall: TO_BE_MEASURED"),
                           ("motor_hall_resolution: 0.26242",
                            "motor_hall_resolution: TO_BE_MEASURED"),
                           ("lane_T0_motor: T0", "lane_T0_motor: TO_BE_MEASURED"),
                           ("lane_T1_prep_pin: canvas:PC7",
                            "lane_T1_prep_pin: TO_BE_MEASURED"),
                           ("cutter_sensor_pin: !hotend:PC5",
                            "cutter_sensor_pin: TO_BE_MEASURED")):
        assert source in complete
        canvas_cfg.write_text(complete.replace(source, broken, 1), encoding="utf-8")
        assert manager.canvas_config_complete(config / "printer.cfg", canvas_cfg) is False, broken
    canvas_cfg.write_text(complete.replace("serial: /dev/serial/by-id/usb-Canvas",
                                           "serial: TO_BE_MEASURED"), encoding="utf-8")
    assert manager.canvas_config_complete(config / "printer.cfg", canvas_cfg) is False


def test_required_placeholder_defers_then_completes_idempotently(tmp_path, monkeypatch, moonraker,
                                                                capsys):
    home, klipper, config, serial = fake_tree(tmp_path)
    log = fake_commands(tmp_path, monkeypatch)
    args = cli_install(klipper, config, moonraker, serial)
    assert manager.install(args) == 0
    assert (config / "printer.cfg").read_text().count("[include canvas/*.cfg]") == 1
    calls = log.read_text().splitlines()

    break_required_pin(config, "lane_T1_prep_pin")
    assert manager.install(args) == 0
    deferred = capsys.readouterr().out
    assert "restart deferred" in deferred
    assert "lane_T0_motor..lane_T3_motor and each lane's prep_pin" in deferred
    assert "lane_T*_present_pin is optional" in deferred
    assert log.read_text().splitlines() == calls  # nothing restarts on an incomplete config
    assert len(list(config.glob("printer.cfg.*.bak"))) == 1

    fill_required_pin(config, "lane_T1_prep_pin", "canvas:PC13")
    assert manager.install(args) == 0
    assert "restart deferred" not in capsys.readouterr().out
    # Complete again: Klipper restarts for the new config, Moonraker has no reason to.
    completed = calls + ["systemctl restart klipper"]
    assert log.read_text().splitlines() == completed
    printer = (config / "printer.cfg").read_text()
    assert manager.install(args) == 0
    assert (config / "printer.cfg").read_text() == printer
    assert log.read_text().splitlines() == completed
    assert len(list(config.glob("printer.cfg.*.bak"))) == 1


def test_measured_presence_pins_stay_accepted_and_idempotent(tmp_path, monkeypatch, moonraker,
                                                             capsys):
    home, klipper, config, serial = fake_tree(tmp_path)
    log = fake_commands(tmp_path, monkeypatch)
    args = cli_install(klipper, config, moonraker, serial)
    assert manager.install(args) == 0
    calls = log.read_text().splitlines()
    add_present_pins(config)
    assert manager.install(args) == 0
    assert "restart deferred" not in capsys.readouterr().out
    assert "lane_T0_present_pin: canvas:PC4" in (config / "canvas/canvas.cfg").read_text()
    assert log.read_text().splitlines() == calls + ["systemctl restart klipper"]


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


def test_install_detects_single_serial_candidate_without_flag(tmp_path, monkeypatch, moonraker):
    home, klipper, config, serial = fake_tree(tmp_path)
    fake_commands(tmp_path, monkeypatch)
    monkeypatch.setenv("CANVAS_SERIAL_BY_ID_DIR", str(serial.parent))
    args = manager.make_parser().parse_args([
        "install", "--klipper-dir", str(klipper), "--config-dir", str(config),
        "--moonraker-url", moonraker, "--non-interactive", "--toolhead-sensor", "tool_sensor",
        "--separation-method", "cutter"])
    assert manager.install(args) == 0
    assert "serial: %s" % serial in (config / "canvas/canvas.cfg").read_text()


def test_install_requires_explicit_serial_when_candidates_are_ambiguous(tmp_path, monkeypatch, moonraker):
    home, klipper, config, serial = fake_tree(tmp_path)
    fake_commands(tmp_path, monkeypatch)
    monkeypatch.setattr(manager, "serial_paths", lambda: [serial, config / "other"])
    args = cli_install(klipper, config, moonraker, serial)
    args.serial = None
    with pytest.raises(ValueError, match="found 2"):
        manager.install(args)


def test_install_non_interactive_requires_pin_when_no_sensor_exists(tmp_path, monkeypatch, moonraker):
    home, klipper, config, serial = fake_tree(tmp_path, sensor=False)
    fake_commands(tmp_path, monkeypatch)
    args = manager.make_parser().parse_args([
        "install", "--klipper-dir", str(klipper), "--config-dir", str(config),
        "--moonraker-url", moonraker, "--serial", str(serial), "--non-interactive",
        "--toolhead-sensor", "canvas_toolhead", "--separation-method", "cutter"])
    with pytest.raises(ValueError, match="toolhead-pin"):
        manager.install(args)
    assert not (config / "canvas").exists()


def test_install_never_overwrites_user_edited_templates(tmp_path, monkeypatch, moonraker):
    home, klipper, config, serial = fake_tree(tmp_path)
    fake_commands(tmp_path, monkeypatch)
    args = cli_install(klipper, config, moonraker, serial)
    manager.install(args)
    macros = config / "canvas/canvas_macros.cfg"
    macros.write_text(macros.read_text() + "\n[gcode_macro MY_EDIT]\ngcode: M117 edited\n")
    edited = macros.read_text()
    assert manager.install(args) == 0
    assert macros.read_text() == edited


def test_install_refuses_to_overwrite_unmanaged_canvas_cfg(tmp_path, monkeypatch, moonraker):
    home, klipper, config, serial = fake_tree(tmp_path)
    fake_commands(tmp_path, monkeypatch)
    canvas_dir = config / "canvas"
    canvas_dir.mkdir()
    user_file = canvas_dir / "canvas.cfg"
    user_file.write_text("[canvas]\ntoolhead_sensor: mine\n")
    args = cli_install(klipper, config, moonraker, serial)
    with pytest.raises(ValueError, match="unmarked user file"):
        manager.install(args)
    assert user_file.read_text() == "[canvas]\ntoolhead_sensor: mine\n"


def test_uninstall_never_restarts_services_and_keeps_unique_backups(tmp_path, monkeypatch, moonraker):
    home, klipper, config, serial = fake_tree(tmp_path)
    log = fake_commands(tmp_path, monkeypatch)
    args = cli_install(klipper, config, moonraker, serial)
    manager.install(args)
    printer_backup = next(iter(config.glob("printer.cfg.*.bak")))
    saved = printer_backup.read_text()
    uninstall_args = manager.make_parser().parse_args([
        "uninstall", "--klipper-dir", str(klipper), "--config-dir", str(config),
        "--moonraker-url", moonraker])
    assert manager.uninstall(uninstall_args) == 0
    assert manager.uninstall(uninstall_args) == 0  # idempotent, nothing left to change
    backups = list(config.glob("printer.cfg.*.bak"))
    assert len(backups) == len(set(backups))  # never overwrites an existing .bak
    assert any(b.read_text() == saved for b in backups)
    assert log.read_text().splitlines() == ["systemctl restart klipper", "systemctl restart moonraker"]


def test_status_reports_installation_state(tmp_path, monkeypatch, moonraker, capsys):
    home, klipper, config, serial = fake_tree(tmp_path)
    fake_commands(tmp_path, monkeypatch)
    monkeypatch.setenv("CANVAS_SERIAL_BY_ID_DIR", str(serial.parent))
    args = cli_install(klipper, config, moonraker, serial)
    manager.install(args)
    status_args = manager.make_parser().parse_args([
        "status", "--klipper-dir", str(klipper), "--config-dir", str(config),
        "--moonraker-url", moonraker])
    assert manager.status(status_args) == 0
    out = capsys.readouterr().out
    assert "canvas.py: linked" in out
    assert "Moonraker print state: standby" in out


def test_status_tolerates_unreachable_moonraker(tmp_path, monkeypatch, capsys):
    home, klipper, config, serial = fake_tree(tmp_path)
    args = manager.make_parser().parse_args([
        "status", "--klipper-dir", str(klipper), "--config-dir", str(config),
        "--moonraker-url", "http://127.0.0.1:1"])
    assert manager.status(args) == 0
    assert "Moonraker print state: unknown" in capsys.readouterr().out


def test_flash_refuses_while_printing(tmp_path, monkeypatch, moonraker):
    fake_commands(tmp_path, monkeypatch)
    StateHandler.state = "printing"
    args = manager.make_parser().parse_args(["flash", "--device", "/dev/null",
                                            "--moonraker-url", moonraker])
    with pytest.raises(ValueError, match="printing"):
        manager.flash(args)


def test_flash_refuses_unknown_moonraker_state_without_force(tmp_path, monkeypatch):
    fake_commands(tmp_path, monkeypatch)
    args = manager.make_parser().parse_args(["flash", "--device", "/dev/null",
                                            "--moonraker-url", "http://127.0.0.1:1"])
    with pytest.raises(ValueError, match="unknown"):
        manager.flash(args)


def test_flash_non_interactive_requires_explicit_risk_flags(moonraker):
    args = manager.make_parser().parse_args(["flash", "--non-interactive",
                                            "--moonraker-url", moonraker])
    with pytest.raises(ValueError, match="--i-understand-the-risks"):
        manager.flash(args)
    with pytest.raises(ValueError, match="--i-understand-the-risks"):
        manager.flash(manager.make_parser().parse_args(
            ["flash", "--non-interactive", "--yes", "--moonraker-url", moonraker]))


def test_flash_backup_and_recovery_flags_must_be_paired():
    with pytest.raises(ValueError, match="must be supplied together"):
        manager.flash(manager.make_parser().parse_args(
            ["flash", "--dry-run", "--backup-file", "/tmp/does-not-exist.bin"]))


def test_flash_dry_run_is_offline_and_needs_no_device(moonraker, capsys):
    args = manager.make_parser().parse_args(["flash", "--dry-run", "--moonraker-url",
                                             "http://127.0.0.1:1"])
    assert manager.flash(args) == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out
    assert "recovery may require SWD" in out


def test_flash_device_override_rejects_missing_or_mismatched_device(tmp_path, monkeypatch):
    monkeypatch.setattr(manager, "device_info", lambda _p: {
        "vid_pid": "1234:5678", "vendor": "Canvas", "product": "Canvas"})
    with pytest.raises(ValueError, match="does not exist"):
        manager.detect_device(str(tmp_path / "missing"), None, prompt=False)
    node = tmp_path / "ttyACM0"
    node.touch()
    assert manager.detect_device(str(node), "1234:5678", prompt=False) == (str(node), "1234:5678")
    with pytest.raises(ValueError, match="identity mismatch"):
        manager.detect_device(str(node), "dead:beef", prompt=False)


def test_flash_rejects_two_new_devices_from_plug_diff(tmp_path, monkeypatch):
    devices = [tmp_path / "a", tmp_path / "b"]
    states = [[], devices]
    monkeypatch.setattr(manager, "serial_paths", lambda: list(states.pop(0)))
    monkeypatch.setattr(manager, "device_info", lambda _p: {
        "vid_pid": "abcd:0001", "vendor": "ShenZhenCBD", "product": "Canvas"})
    with pytest.raises(ValueError, match="2 new serial devices"):
        manager.detect_device(None, None, input_fn=lambda _p: "", output=lambda _m: None)


def test_flash_rejects_unverified_vendor_from_plug_diff(tmp_path, monkeypatch):
    new_device = tmp_path / "ttyACM0"
    new_device.touch()
    states = [[], [new_device]]
    monkeypatch.setattr(manager, "serial_paths", lambda: states.pop(0))
    monkeypatch.setattr(manager, "device_info", lambda _p: {
        "vid_pid": "abcd:0001", "vendor": "SomeOtherVendor", "product": "USB Serial"})
    with pytest.raises(ValueError, match="ShenZhenCBD"):
        manager.detect_device(None, None, input_fn=lambda _p: "", output=lambda _m: None)


def test_flash_plug_diff_requires_interactive_or_override(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="interactive unplug/replug"):
        manager.detect_device(None, None, prompt=False)


def test_cli_exposes_all_commands_and_flags():
    result = subprocess.run([str(ROOT / "canvas-klipper.sh"), "--help"], text=True,
                            capture_output=True, check=False)
    assert result.returncode == 0
    for command in ("flash", "install", "uninstall", "status"):
        assert command in result.stdout
        help_text = subprocess.run([str(ROOT / "canvas-klipper.sh"), command, "--help"],
                                   text=True, capture_output=True, check=False)
        assert help_text.returncode == 0, help_text.stderr
    flash_help = subprocess.run([str(ROOT / "canvas-klipper.sh"), "flash", "--help"], text=True,
                                capture_output=True, check=False).stdout
    for flag in ("--dry-run", "--yes", "--i-understand-the-risks", "--non-interactive",
                 "--device", "--vid-pid", "--backup-file", "--recovery-file"):
        assert flag in flash_help
    install_help = subprocess.run([str(ROOT / "canvas-klipper.sh"), "install", "--help"], text=True,
                                  capture_output=True, check=False).stdout
    for flag in ("--klipper-dir", "--config-dir", "--serial", "--toolhead-sensor", "--toolhead-pin",
                 "--separation-method", "--non-interactive"):
        assert flag in install_help

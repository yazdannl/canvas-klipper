import importlib.util
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).parents[2] / "klipper" / "klippy" / "extras" / "drv8833.py"
spec = importlib.util.spec_from_file_location("drv8833", MODULE_PATH.resolve())
drv8833 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(drv8833)


class FakeCommand:
    def __init__(self):
        self.calls = []

    def send(self, args):
        self.calls.append(args)


class FakeMCU:
    def __init__(self):
        self.oid = 0
        self.config_callbacks = []
        self.responses = {}
        self.config_commands = []
        self.commands = {}

    def create_oid(self):
        self.oid += 1
        return self.oid

    def register_serial_response(self, callback, msgformat, oid):
        self.responses[(msgformat.split()[0], oid)] = callback

    def register_config_callback(self, callback):
        self.config_callbacks.append(callback)

    def get_constant_float(self, name):
        assert name == "PWM_MAX"
        return 255

    def seconds_to_clock(self, seconds):
        return int(seconds * 1_000_000)

    def add_config_cmd(self, command, **kwargs):
        self.config_commands.append((command, kwargs))

    def lookup_command(self, command):
        return self.commands.setdefault(command, FakeCommand())

    def configure(self):
        for callback in self.config_callbacks:
            callback()


class FakeReactor:
    def __init__(self):
        self.time = 0.0
        self.on_pause = None

    def monotonic(self):
        return self.time

    def pause(self, deadline):
        self.time = deadline
        if self.on_pause:
            self.on_pause()
        return self.time


class FakePins:
    def __init__(self, mcu, mismatch=False):
        self.mcu = mcu
        self.other = FakeMCU() if mismatch else mcu

    def lookup_pin(self, pin, **kwargs):
        use_other = self.other is not self.mcu and pin == "PA1"
        return {"chip": self.other if use_other else self.mcu,
                "pin": pin, "pullup": int(kwargs.get("can_pullup", False))}


class FakePrinter:
    def __init__(self, mcu, mismatch=False):
        self.reactor = FakeReactor()
        self.objects = {"pins": FakePins(mcu, mismatch)}
        self.handlers = {}

    def get_reactor(self):
        return self.reactor

    def lookup_object(self, name, default=None):
        if name in self.objects:
            return self.objects[name]
        if default is not None:
            return default
        raise KeyError(name)

    def register_event_handler(self, event, callback):
        self.handlers[event] = callback

    def command_error(self, message):
        return RuntimeError(message)


class FakeConfig:
    def __init__(self, printer, values=None):
        self.printer = printer
        self.values = {"motor_fwd": "PA0", "motor_rwd": "PA1",
                       "motor_hall": "PA2", "motor_hall_resolution": 0.5,
                       "move_timeout": 10.0}
        self.values.update(values or {})
        self.saved = {}

    def get_printer(self):
        return self.printer

    def get_name(self):
        return "drv8833 lane0"

    def get(self, key):
        return self.values[key]

    def getfloat(self, key, default=None, above=None, minval=None, maxval=None):
        value = self.values.get(key, default)
        if value is None:
            raise ValueError("missing " + key)
        value = float(value)
        if above is not None and value <= above:
            raise ValueError("invalid " + key)
        if minval is not None and value < minval:
            raise ValueError("invalid " + key)
        if maxval is not None and value > maxval:
            raise ValueError("invalid " + key)
        return value

    def error(self, message):
        return RuntimeError(message)


class FakeConfigFile:
    def __init__(self):
        self.saved = {}

    def set(self, section, key, value):
        self.saved[(section, key)] = value


@pytest.fixture
def lane():
    mcu = FakeMCU()
    printer = FakePrinter(mcu)
    config = FakeConfig(printer)
    obj = drv8833.load_config_prefix(config)
    mcu.configure()
    printer.objects["configfile"] = FakeConfigFile()
    return obj, mcu, printer


def test_builds_matching_mcu_protocol_and_pins(lane):
    obj, mcu, _ = lane
    assert len(mcu.config_commands) == 3
    config_cmd = mcu.config_commands[0][0]
    assert "motor_fwd_pin=PA0" in config_cmd
    assert "motor_rwd_pin=PA1" in config_cmd
    assert "hall_pin=PA2" in config_cmd
    assert "hall_resolution=500000" in config_cmd
    assert obj.hall_controller.oid == 1


def test_signed_speed_stop_and_status_hall_count(lane):
    obj, mcu, printer = lane
    obj.drv8833_set_speed(-12.5)
    cmd = mcu.commands["drv8833_set oid=%c enable=%c direction=%c target_speed=%u stop_ticks=%u"]
    assert cmd.calls[-1] == [1, 1, 0, 12500, 0]
    mcu.responses[("drv8833_status", 1)]({
        "active": 1, "manual": 0, "count": 17, "speed": 9350, "duty": 420,
    })
    status = obj.get_status(0)
    assert status["direction"] == "backwards"
    assert status["target_speed"] == 12.5
    assert status["hall_speed"] == 9.35
    assert status["hall_count"] == 17
    assert status["hall_distance"] == 8.5
    obj.stop()
    assert cmd.calls[-1] == [1, 0, 1, 0, 0]
    assert obj.get_status(0)["active"] is False
    assert "klippy:shutdown" in printer.handlers


def test_distance_direction_count_and_async_mode(lane):
    obj, mcu, _ = lane
    obj.drv8833_move(20, -5, wait_for_completion=False)
    command = mcu.commands[
        "drv8833_set oid=%c enable=%c direction=%c target_speed=%u stop_ticks=%u"]
    assert command.calls[-1] == [1, 1, 0, 20000, 10]
    assert obj.get_status(0)["active"] is True


def test_blocking_distance_waits_until_reported_complete(lane):
    obj, _, printer = lane
    printer.reactor.on_pause = lambda: setattr(obj.hall_controller, "active", False)
    obj.drv8833_move(10, 1)
    assert obj.get_status(0)["active"] is False


def test_distance_timeout_stops_motor(lane):
    obj, mcu, _ = lane
    with pytest.raises(RuntimeError, match="timed out"):
        obj.drv8833_move(1, 10)
    command = mcu.commands[
        "drv8833_set oid=%c enable=%c direction=%c target_speed=%u stop_ticks=%u"]
    assert command.calls[-1] == [1, 0, 1, 0, 0]


def test_zero_distance_stops_and_non_finite_is_rejected(lane):
    obj, mcu, _ = lane
    obj.drv8833_move(20, 0)
    command = mcu.commands[
        "drv8833_set oid=%c enable=%c direction=%c target_speed=%u stop_ticks=%u"]
    assert command.calls[-1] == [1, 0, 1, 0, 0]
    with pytest.raises(RuntimeError, match="finite"):
        obj.drv8833_set_speed(float("nan"))


def test_pid_update_and_save_config(lane):
    obj, mcu, printer = lane
    obj.set_pid_gains(2.0, 1.0, 0.1, save_to_config=True)
    command = mcu.commands["drv8833_set_pid oid=%c kp=%u ki=%u kd=%u"]
    assert command.calls[-1] == [1, 20000, 10000, 1000]
    cfg = printer.lookup_object("configfile")
    assert cfg.saved[("drv8833 lane0", "pid_kp")] == "2.000000"


def test_all_pins_must_be_on_same_mcu():
    mcu = FakeMCU()
    printer = FakePrinter(mcu, mismatch=True)
    with pytest.raises(RuntimeError, match="same MCU"):
        drv8833.load_config_prefix(FakeConfig(printer))

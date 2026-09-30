import importlib.util
from pathlib import Path

import pytest

from canvas.canvas import Canvas, CanvasError, LANE_NAMES


class ConfigError(Exception):
    pass


class FakeConfig:
    def __init__(self, printer, values=None):
        self.printer = printer
        self.values = values or {}

    def get_printer(self):
        return self.printer

    def get_name(self):
        return self.values.get("_name", "drv8833 T0")

    def get(self, key, default=...):
        if key in self.values:
            return self.values[key]
        if default is not ...:
            return default
        raise ConfigError("missing config: " + key)

    def getint(self, key, default=..., minval=None):
        value = int(self.get(key, default))
        if minval is not None and value < minval:
            raise ConfigError("invalid integer " + key)
        return value

    def getfloat(self, key, default=..., minval=None, maxval=None, above=None):
        value = float(self.get(key, default))
        if minval is not None and value < minval:
            raise ConfigError("invalid float " + key)
        if maxval is not None and value > maxval:
            raise ConfigError("invalid float " + key)
        if above is not None and value <= above:
            raise ConfigError("invalid float " + key)
        return value

    def getboolean(self, key, default=False):
        return bool(self.get(key, default))

    def error(self, message):
        return ConfigError(message)


class FakeGcmd:
    def __init__(self, params=None):
        self.params = params or {}
        self.info = []

    def get(self, key, default=...):
        if key in self.params:
            return self.params[key]
        if default is not ...:
            return default
        raise ValueError("missing command arg " + key)

    def get_int(self, key, default=...):
        value = self.get(key, default)
        return None if value is None else int(value)

    def respond_info(self, message):
        self.info.append(message)

    def error(self, message):
        return CanvasError(message)


class FakeReactor:
    def __init__(self):
        self.now = 0.0
        self.hardware = None
        self.canvas = None
        self.cancel_at = None
        self.scheduled = []

    def monotonic(self):
        return self.now

    def pause(self, waketime):
        target = max(self.now, waketime)
        if self.hardware:
            self.hardware.advance(target - self.now)
        self.now = target
        if self.cancel_at is not None and self.now >= self.cancel_at:
            self.canvas.cancel_requested = True
        for when, callback in list(self.scheduled):
            if when <= self.now:
                self.scheduled.remove((when, callback))
                callback()
        return self.now

    def schedule(self, delay, callback):
        self.scheduled.append((self.now + delay, callback))


class FakeSensor:
    def __init__(self, hardware):
        self.hardware = hardware
        self.stuck = None

    def get_status(self, eventtime):
        detected = self.hardware.toolhead_present
        if self.stuck is not None:
            detected = self.stuck
        return {"filament_detected": detected}


class FakeMotor:
    def __init__(self, name, hardware):
        self.name = name
        self.hardware = hardware
        self.speed = 0.0
        self.history = []
        self.hall_resolution = 0.5
        self.hall_count = 0
        self.hall_distance = 0.0
        self._hall_travel = 0.0
        self.stop_distance = None
        self._distance_travel = 0.0
        self.hardware.motors[name] = self

    def drv8833_set_speed(self, speed):
        self.speed = float(speed)
        self.stop_distance = None
        if self.speed:
            self.hall_count = 0
            self.hall_distance = 0.0
            self._hall_travel = 0.0
        self.history.append(self.speed)

    def drv8833_move(self, speed, distance, wait_for_completion=True):
        signed_speed = abs(float(speed)) * (1 if distance >= 0 else -1)
        self.drv8833_set_speed(signed_speed)
        self.stop_distance = abs(float(distance))
        self._distance_travel = 0.0
        if wait_for_completion:
            while self.speed:
                self.hardware.reactor.pause(self.hardware.reactor.now + 0.005)

    def stop(self):
        self.speed = 0.0
        self.stop_distance = None
        self.history.append(self.speed)

    def record_hall(self, distance):
        self._hall_travel += abs(distance)
        self.hall_count = int(self._hall_travel / self.hall_resolution)
        self.hall_distance = self.hall_count * self.hall_resolution

    def get_status(self, eventtime=None):
        return {"active": self.speed != 0, "manual": False,
                "direction": "forwards" if self.speed >= 0 else "backwards",
                "target_speed": abs(self.speed), "duty_cycle": 0.0,
                "hall_speed": abs(self.speed), "hall_count": self.hall_count,
                "hall_distance": self.hall_distance,
                "pid_kp": 1.2, "pid_ki": 0.8, "pid_kd": 0.02}


class FakeMCUCommand:
    def __init__(self, mcu, format_string):
        self.mcu = mcu
        self.format_string = format_string

    def send(self, args):
        self.mcu.send(self.format_string, args)


class FakeMCU:
    def __init__(self):
        self.next_oid = 0
        self.responses = {}
        self.config_callbacks = []
        self.drivers = {}
        self.config_commands = []

    def create_oid(self):
        oid = self.next_oid
        self.next_oid += 1
        return oid

    def register_serial_response(self, callback, msgformat, oid):
        self.responses[(msgformat.split()[0], oid)] = callback

    def register_config_callback(self, callback):
        self.config_callbacks.append(callback)

    def get_constant_float(self, name):
        assert name == "PWM_MAX"
        return 255.0

    def seconds_to_clock(self, seconds):
        return int(seconds * 1000000)

    def add_config_cmd(self, command, **kwargs):
        self.config_commands.append(command)

    def lookup_command(self, format_string):
        return FakeMCUCommand(self, format_string)

    def bind_driver(self, driver):
        self.drivers[driver.hall_controller.oid] = driver
        driver._fake_mcu = self
        driver._sim_hall_travel = 0.0
        driver._fake_stop_ticks = 0

    def build_config(self):
        for callback in self.config_callbacks:
            callback()

    def send(self, format_string, args):
        driver = self.drivers[args[0]]
        controller = driver.hall_controller
        if format_string.startswith("drv8833_set "):
            _, enabled, direction, target_speed, stop_ticks = args
            if enabled:
                controller.active = True
                controller.manual = False
                controller.direction = 1 if direction else -1
                controller.target_speed = target_speed / 1000.0
                controller.hall_count = 0
                controller.speed = 0.0
                driver._sim_hall_travel = 0.0
                driver._fake_stop_ticks = int(stop_ticks)
            else:
                controller.active = False
                controller.target_speed = 0.0
                driver._fake_stop_ticks = 0
            self.report_status(driver)
        elif format_string.startswith("drv8833_manual "):
            _, enabled, direction, duty = args
            controller.active = bool(enabled)
            controller.manual = bool(enabled)
            controller.direction = 1 if direction else -1
            driver._sim_hall_travel = 0.0
            self.report_status(driver)
        elif format_string.startswith("drv8833_set_pid "):
            _, kp, ki, kd = args
            scale = 10000.0
            controller.pid_kp = kp / scale
            controller.pid_ki = ki / scale
            controller.pid_kd = kd / scale

    def report_status(self, driver, active=None):
        controller = driver.hall_controller
        if active is not None:
            controller.active = active
        self.responses[("drv8833_status", controller.oid)]({
            "active": controller.active,
            "manual": controller.manual,
            "count": controller.hall_count,
            "speed": int(controller.speed * 1000),
            "duty": int(controller.duty * 10),
        })


class FakePins:
    def __init__(self, mcu):
        self.mcu = mcu

    def lookup_pin(self, pin, can_pullup=False):
        return {"chip": self.mcu, "pin": int(pin[4:]), "pullup": 0}


class FakeButtons:
    def __init__(self, hardware):
        self.hardware = hardware

    def register_buttons(self, pins, callback):
        for pin in pins:
            self.hardware.callbacks.setdefault(pin, []).append(callback)
            callback(self.hardware.reactor.now,
                     self.hardware.pin_values.get(pin, False))


class FakeExtruder:
    def __init__(self, hardware):
        self.hardware = hardware
        self.can_extrude = True

    def get_status(self, eventtime):
        return {"can_extrude": self.can_extrude}


class FakeGcode:
    def __init__(self, printer):
        self.printer = printer
        self.commands = {}
        self.cut_count = 0
        self.tip_moves = []
        self.saved_states = {}
        self.distance_mode = "absolute"
        self.extrusion_mode = "absolute"

    def register_command(self, name, callback, desc=None):
        self.commands[name] = callback

    def run_script_from_command(self, script):
        hardware = self.printer.hardware
        for line in script.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("SAVE_GCODE_STATE"):
                name = line.split("NAME=", 1)[1]
                self.saved_states[name] = (self.distance_mode, self.extrusion_mode)
            elif line == "G90":
                self.distance_mode = "absolute"
            elif line == "G91":
                self.distance_mode = "relative"
            elif line == "M82":
                self.extrusion_mode = "absolute"
            elif line == "M83":
                self.extrusion_mode = "relative"
            elif line.startswith("RESTORE_GCODE_STATE"):
                name = line.split("NAME=", 1)[1]
                self.distance_mode, self.extrusion_mode = self.saved_states[name]
            elif line.startswith("SAVE_VARIABLE"):
                parts = dict(item.split("=", 1) for item in line.split()[1:])
                raw = parts["VALUE"]
                value = raw == "True" if raw in ("True", "False") else int(raw)
                self.printer.save_vars[parts["VARIABLE"]] = value
            elif line.startswith("CANVAS_CUTTER_ACTUATE"):
                self.cut_count += 1
                if hardware.cutter_mode == "stuck":
                    hardware.set_cutter(True)
                elif hardware.cutter_mode == "cycle":
                    hardware.set_cutter(True)
                    hardware.reactor.schedule(0.02, lambda: hardware.set_cutter(False))
            elif line.startswith("G1 E"):
                words = {word[0]: word[1:] for word in line.split()[1:]}
                distance = float(words["E"])
                speed = float(words["F"]) / 60.0
                self.tip_moves.append(distance)
                hardware.extruder_move(distance, speed)
            elif line.startswith("G4 P"):
                duration = float(line.split("P", 1)[1]) / 1000.0
                hardware.reactor.pause(hardware.reactor.now + duration)
            elif line.startswith("PAUSE"):
                self.printer.pause_count += 1


class FakePrinter:
    def __init__(self):
        self.reactor = FakeReactor()
        self.objects = {}
        self.handlers = {}
        self.shutdown = False
        self.pause_count = 0
        self.save_vars = {}
        self.hardware = Hardware(self)
        self.reactor.hardware = self.hardware
        self.gcode = FakeGcode(self)
        self.objects["gcode"] = self.gcode
        self.objects["extruder"] = FakeExtruder(self.hardware)
        self.objects["filament_switch_sensor toolhead"] = FakeSensor(self.hardware)
        self.objects["buttons"] = FakeButtons(self.hardware)
        self.objects["save_variables"] = self
        self.objects["drv8833 T0"] = FakeMotor("T0", self.hardware)
        self.objects["drv8833 T1"] = FakeMotor("T1", self.hardware)
        self.objects["drv8833 T2"] = FakeMotor("T2", self.hardware)
        self.objects["drv8833 T3"] = FakeMotor("T3", self.hardware)

    def get_reactor(self):
        return self.reactor

    def lookup_object(self, name, default=...):
        if name in self.objects:
            return self.objects[name]
        if default is not ...:
            return default
        raise KeyError(name)

    def load_object(self, config, name):
        return self.objects[name]

    def register_event_handler(self, event, callback):
        self.handlers.setdefault(event, []).append(callback)

    def is_shutdown(self):
        return self.shutdown

    def command_error(self, message):
        return CanvasError(message)

    def get_status(self, eventtime):
        return {"variables": self.save_vars}

    def ready(self):
        for callback in self.handlers.get("klippy:ready", []):
            callback()


class Hardware:
    def __init__(self, printer):
        self.printer = printer
        self.reactor = printer.reactor
        self.callbacks = {}
        self.pin_values = {}
        self.motors = {}
        self.positions = {name: 0.0 for name in LANE_NAMES}
        self.present = {name: True for name in LANE_NAMES}
        self.cutter_mode = "cycle"
        self.cutter_engaged = False
        self.grip = True
        self.extruder_active = False
        self.threshold = 5.0
        self.toolhead_stuck = None
        self.prep_stuck = {}

    @property
    def toolhead_present(self):
        if self.toolhead_stuck is not None:
            return self.toolhead_stuck
        return any(position >= self.threshold for position in self.positions.values())

    def set_pin(self, pin, state):
        state = bool(state)
        old = self.pin_values.get(pin, False)
        self.pin_values[pin] = state
        if state != old:
            for callback in self.callbacks.get(pin, []):
                callback(self.reactor.now, state)

    def set_cutter(self, state):
        self.cutter_engaged = bool(state)
        self.set_pin("cutter", state)

    def _update_sensors(self, name):
        self.set_pin("present_" + name, self.present[name])
        prep = self.positions[name] >= 2.0
        if name in self.prep_stuck:
            prep = self.prep_stuck[name]
        self.set_pin("prep_" + name, prep)
        self.set_pin("hub", self.positions[name] > 35.0)
        # Toolhead sensor is provided as a status object, not a button pin.

    @staticmethod
    def _motor_speed(motor):
        controller = getattr(motor, "hall_controller", None)
        if controller is not None:
            if not controller.active:
                return 0.0
            return controller.direction * controller.target_speed
        return motor.speed

    def _move(self, name, distance, hall=True):
        self.positions[name] += distance
        self._update_sensors(name)
        if not hall:
            return
        motor = self.motors[name]
        controller = getattr(motor, "hall_controller", None)
        if controller is None:
            motor.record_hall(distance)
            return
        resolution = controller.hall_resolution
        travel = getattr(motor, "_sim_hall_travel", 0.0) + abs(distance)
        motor._sim_hall_travel = travel
        controller.hall_count = int(travel / resolution)
        controller.speed = abs(controller.target_speed)
        motor._fake_mcu.report_status(motor, active=controller.active)

    def advance(self, duration):
        if duration <= 0:
            return
        for name, motor in self.motors.items():
            speed = self._motor_speed(motor)
            if not speed:
                continue
            distance = speed * duration
            target = getattr(motor, "stop_distance", None)
            if target is not None:
                remaining = max(0.0, target - motor._distance_travel)
                distance = (1 if speed > 0 else -1) * min(abs(distance), remaining)
                motor._distance_travel += abs(distance)
            hall = not (self.extruder_active and not self.grip)
            self._move(name, distance, hall=hall)
            if target is not None and motor._distance_travel >= target:
                motor.stop()
            controller = getattr(motor, "hall_controller", None)
            stop_ticks = getattr(motor, "_fake_stop_ticks", 0)
            if stop_ticks and controller is not None and controller.hall_count >= stop_ticks:
                controller.active = False
                controller.target_speed = 0.0
                motor._fake_stop_ticks = 0
                motor._fake_mcu.report_status(motor, active=False)

    def extruder_move(self, distance, speed):
        lane = self.printer.reactor.canvas.lanes[
            "T%d" % (self.printer.reactor.canvas.active_tool or 0)]
        self.extruder_active = True
        try:
            # Klipper's extruder and Canvas feeder run together; the feeder's
            # measured path movement is the simulated shared filament advance.
            self.reactor.pause(self.reactor.now + abs(distance) / max(speed, 0.01))
            if not any(self._motor_speed(m) for m in self.motors.values()):
                self._move(lane.name, distance, hall=False)
        finally:
            self.extruder_active = False


def make_config(printer, **overrides):
    values = {
        "toolhead_sensor": "toolhead",
        "separation_method": "cutter",
        "cutter_macro": "CANVAS_CUTTER_ACTUATE",
        "hub_tangle_pin": "hub",
        "cutter_sensor_pin": "cutter",
        "load_attempts": 2,
        "cutter_retries": 2,
        "cutter_timeout": 0.05,
        "toolhead_timeout": 0.5,
        "extruder_feed_length": 5.0,
        "extruder_feed_speed": 20.0,
        "extruder_retract_length": 12.0,
        "extruder_retract_speed": 20.0,
        "grip_min_distance": 1.0,
        "load_recovery_distance": 2.0,
        "tip_forming_moves": "-2:25;-4:5",
        "tip_forming_cool_ms": 10,
        "pause_on_error": True,
    }
    values.update(overrides)
    for name in LANE_NAMES:
        values.update({
            "lane_%s_motor" % name: name,
            "lane_%s_present_pin" % name: "present_" + name,
            "lane_%s_prep_pin" % name: "prep_" + name,
            "lane_%s_load_speed" % name: 20.0,
            "lane_%s_load_max_distance" % name: 40.0,
            "lane_%s_load_timeout" % name: 0.5,
            "lane_%s_prep_max_distance" % name: 40.0,
            "lane_%s_prep_timeout" % name: 0.5,
            "lane_%s_unload_speed" % name: 20.0,
            "lane_%s_unload_max_distance" % name: 40.0,
            "lane_%s_unload_timeout" % name: 0.5,
            "lane_%s_park_distance" % name: 0.5,
            "lane_%s_park_speed" % name: 10.0,
        })
    return FakeConfig(printer, values)


def make_canvas(**overrides):
    printer = FakePrinter()
    for name in LANE_NAMES:
        printer.hardware.set_pin("present_" + name, True)
    canvas = Canvas(make_config(printer, **overrides))
    printer.reactor.canvas = canvas
    canvas._handle_connect()
    return printer, canvas


def run_command(printer, command, params=None):
    printer.gcode.commands[command](FakeGcmd(params or {}))


def test_cutter_happy_load_unload_and_idempotent_select():
    printer, canvas = make_canvas()
    run_command(printer, "CANVAS_TOOL_SELECT", {"TOOL": 0})
    assert canvas.active_tool == 0
    assert canvas.loaded["T0"]
    assert canvas.get_status()["toolhead_present"]
    assert printer.gcode.distance_mode == "absolute"
    assert printer.gcode.extrusion_mode == "absolute"
    assert any(speed > 0 for speed in printer.hardware.motors["T0"].history)

    motor_history = list(printer.hardware.motors["T0"].history)
    run_command(printer, "CANVAS_TOOL_SELECT", {"TOOL": 0})
    assert canvas.loaded["T0"]
    assert printer.gcode.cut_count == 0
    assert [speed for speed in printer.hardware.motors["T0"].history if speed]
    assert len([speed for speed in printer.hardware.motors["T0"].history if speed]) == len(
        [speed for speed in motor_history if speed])

    run_command(printer, "CANVAS_UNLOAD", {"TOOL": 0})
    assert not canvas.loaded["T0"]
    assert canvas.active_tool is None
    assert not canvas.get_status()["toolhead_present"]
    assert printer.gcode.cut_count == 1
    assert all(motor.speed == 0 for motor in printer.hardware.motors.values())


def test_tip_forming_unload_and_call_override():
    printer, canvas = make_canvas(separation_method="cutter")
    run_command(printer, "CANVAS_LOAD", {"TOOL": 1})
    run_command(printer, "CANVAS_UNLOAD", {"TOOL": 1, "METHOD": "tip_forming"})
    assert printer.gcode.cut_count == 0
    assert any(move < 0 for move in printer.gcode.tip_moves)
    assert printer.gcode.distance_mode == "absolute"
    assert printer.gcode.extrusion_mode == "absolute"
    assert not canvas.get_status()["toolhead_present"]


def test_toolchange_unloads_old_lane_and_loads_new_lane():
    printer, canvas = make_canvas(cutter_sensor_pin=None)
    run_command(printer, "CANVAS_TOOL_SELECT", {"TOOL": 0})
    run_command(printer, "CANVAS_TOOL_SELECT", {"TOOL": 1})
    assert canvas.active_tool == 1
    assert canvas.loaded["T1"]
    assert canvas.get_status()["toolhead_present"]
    assert printer.gcode.cut_count == 1


def test_config_requires_extruder_and_toolhead_sensor():
    printer = FakePrinter()
    del printer.objects["extruder"]
    canvas = Canvas(make_config(printer))
    with pytest.raises(ConfigError, match="extruder"):
        canvas._handle_connect()

    printer = FakePrinter()
    del printer.objects["filament_switch_sensor toolhead"]
    with pytest.raises(ConfigError, match="toolhead_sensor"):
        Canvas(make_config(printer))


def test_hub_tangle_sensor_blocks_loading_and_prep_switch_is_used():
    printer, canvas = make_canvas()
    printer.hardware.set_pin("hub", True)
    with pytest.raises(CanvasError, match="hub/tangle"):
        run_command(printer, "CANVAS_LOAD", {"TOOL": 0})
    printer.hardware.set_pin("hub", False)
    run_command(printer, "CANVAS_LOAD", {"TOOL": 0})
    assert canvas.lanes["T0"].prep
    assert canvas.lanes["T0"].odometer_distance() > 0


def test_prep_switch_failure_is_bounded_before_toolhead_feed():
    printer, canvas = make_canvas(load_attempts=1, lane_T0_prep_timeout=0.03)
    printer.hardware.prep_stuck["T0"] = False
    with pytest.raises(CanvasError, match="timed out"):
        run_command(printer, "CANVAS_LOAD", {"TOOL": 0})
    assert printer.hardware.motors["T0"].speed == 0


def test_empty_spool_and_stuck_toolhead_sensor_fail_safe():
    printer, canvas = make_canvas(load_attempts=1)
    printer.hardware.present["T0"] = False
    printer.hardware.set_pin("present_T0", False)
    with pytest.raises(CanvasError, match="no filament"):
        run_command(printer, "CANVAS_LOAD", {"TOOL": 0})
    assert all(motor.speed == 0 for motor in printer.hardware.motors.values())

    printer, canvas = make_canvas(load_attempts=1, lane_T0_load_max_distance=4.0)
    printer.hardware.toolhead_stuck = False
    with pytest.raises(CanvasError, match="load failed"):
        run_command(printer, "CANVAS_LOAD", {"TOOL": 0})
    assert all(motor.speed == 0 for motor in printer.hardware.motors.values())


def test_load_timeout_stops_lane():
    printer, canvas = make_canvas(load_attempts=1, lane_T0_load_timeout=0.03)
    printer.hardware.toolhead_stuck = False
    with pytest.raises(CanvasError, match="timed out"):
        run_command(printer, "CANVAS_LOAD", {"TOOL": 0})
    assert printer.hardware.motors["T0"].speed == 0


def test_failed_cutter_retries_are_bounded_and_pauses():
    printer, canvas = make_canvas(load_attempts=1, cutter_retries=3)
    run_command(printer, "CANVAS_LOAD", {"TOOL": 0})
    printer.hardware.cutter_mode = "stuck"
    with pytest.raises(CanvasError, match="cutter sensor did not clear"):
        run_command(printer, "CANVAS_UNLOAD", {"TOOL": 0})
    assert printer.gcode.cut_count == 3
    assert printer.pause_count >= 1
    assert all(motor.speed == 0 for motor in printer.hardware.motors.values())


def test_extruder_grip_failure_retries_and_fails():
    printer, canvas = make_canvas(load_attempts=1)
    printer.hardware.grip = False
    with pytest.raises(CanvasError, match="grip not confirmed"):
        run_command(printer, "CANVAS_LOAD", {"TOOL": 0})
    assert printer.hardware.motors["T0"].speed == 0
    assert not canvas.loaded["T0"]


def test_cancel_requested_during_bounded_motion_stops_every_motor():
    printer, canvas = make_canvas(load_attempts=3)
    printer.reactor.cancel_at = 0.02
    with pytest.raises(CanvasError, match="cancelled"):
        run_command(printer, "CANVAS_LOAD", {"TOOL": 0})
    assert all(motor.speed == 0 for motor in printer.hardware.motors.values())


def test_saved_state_is_restored_and_reconciled_from_sensor():
    printer, canvas = make_canvas()
    run_command(printer, "CANVAS_LOAD", {"TOOL": 2})
    assert printer.save_vars["canvas_active_tool"] == 2
    assert printer.save_vars["canvas_loaded_2"] is True

    # Simulate restart with the same save_variables store and a present toolhead path.
    printer.objects["save_variables"].get_status = lambda eventtime: {
        "variables": printer.save_vars}
    restored = Canvas(make_config(printer))
    printer.reactor.canvas = restored
    restored._handle_connect()
    restored._handle_ready()
    assert restored.active_tool == 2
    assert restored.loaded["T2"]


def test_unload_rejects_wrong_lane_while_toolhead_sensor_is_occupied():
    printer, canvas = make_canvas(load_attempts=1)
    run_command(printer, "CANVAS_LOAD", {"TOOL": 0})
    with pytest.raises(CanvasError, match="not the active lane"):
        run_command(printer, "CANVAS_UNLOAD", {"TOOL": 1})
    assert printer.hardware.motors["T1"].speed == 0
    assert canvas.active_tool == 0


def test_canvas_uses_real_drv8833_host_module_with_simulated_mcu():
    project = Path(__file__).resolve().parents[2]
    driver_path = project / "klipper" / "klippy" / "extras" / "drv8833.py"
    spec = importlib.util.spec_from_file_location("canvas_test_drv8833", driver_path)
    driver_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(driver_module)

    printer = FakePrinter()
    printer.hardware.motors.clear()
    mcu = FakeMCU()
    printer.objects["pins"] = FakePins(mcu)
    for name in LANE_NAMES:
        printer.objects.pop("drv8833 " + name)
        values = {
            "_name": "drv8833 " + name,
            "motor_fwd": "gpio%d" % (int(name[1:]) * 3),
            "motor_rwd": "gpio%d" % (int(name[1:]) * 3 + 1),
            "motor_hall": "gpio%d" % (int(name[1:]) * 3 + 2),
            "motor_hall_resolution": 0.5,
        }
        driver = driver_module.PrinterDrv8833(FakeConfig(printer, values))
        printer.objects["drv8833 " + name] = driver
        printer.hardware.motors[name] = driver
        mcu.bind_driver(driver)
    mcu.build_config()

    canvas = Canvas(make_config(printer))
    printer.reactor.canvas = canvas
    canvas._handle_connect()
    for name in LANE_NAMES:
        printer.hardware.set_pin("present_" + name, True)
    run_command(printer, "CANVAS_TOOL_SELECT", {"TOOL": 0})

    motor = printer.objects["drv8833 T0"]
    status = motor.get_status(printer.reactor.monotonic())
    assert type(motor).__module__ == "canvas_test_drv8833"
    assert status["hall_count"] > 0
    assert status["hall_distance"] >= canvas.grip_min_distance
    lane_status = canvas.get_status()["lanes"]["T0"]
    assert lane_status["odometer_count"] > 0
    assert lane_status["odometer_mm"] >= canvas.grip_min_distance

    run_command(printer, "CANVAS_UNLOAD", {"TOOL": 0, "METHOD": "tip_forming"})
    assert not canvas.get_status()["toolhead_present"]
    assert not motor.get_status(printer.reactor.monotonic())["active"]


def test_reset_refuses_to_forget_filament_at_toolhead():
    printer, canvas = make_canvas()
    run_command(printer, "CANVAS_LOAD", {"TOOL": 0})
    with pytest.raises(CanvasError, match="filament remains"):
        run_command(printer, "CANVAS_RESET")
    assert canvas.active_tool == 0

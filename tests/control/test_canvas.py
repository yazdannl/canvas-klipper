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

    def getfloat(self, key, default=..., minval=None, above=None):
        value = float(self.get(key, default))
        if minval is not None and value < minval:
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
        self.hardware.motors[name] = self

    def drv8833_set_speed(self, speed):
        self.speed = float(speed)
        self.history.append(self.speed)

    def drv8833_move(self, speed, distance, wait_for_completion=True):
        direction = 1 if distance >= 0 else -1
        self.drv8833_set_speed(abs(speed) * direction)

    def get_status(self, eventtime=None):
        return {"active": self.speed != 0, "speed": self.speed}


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

    def _move(self, name, distance, hall=True):
        self.positions[name] += distance
        self._update_sensors(name)
        if hall:
            lane = self.printer.reactor.canvas.lanes[name]
            pulses = int(abs(self.positions[name]) / lane.odometer_mm_per_pulse)
            while lane.odometer_count < pulses:
                lane.odometer_callback(self.reactor.now, True)
                lane.odometer_callback(self.reactor.now, False)

    def advance(self, duration):
        if duration <= 0:
            return
        for name, motor in self.motors.items():
            if motor.speed:
                hall = not (self.extruder_active and not self.grip)
                self._move(name, motor.speed * duration, hall=hall)

    def extruder_move(self, distance, speed):
        lane = self.printer.reactor.canvas.lanes[
            "T%d" % (self.printer.reactor.canvas.active_tool or 0)]
        self.extruder_active = True
        try:
            # Klipper's extruder and Canvas feeder run together; the feeder's
            # measured path movement is the simulated shared filament advance.
            self.reactor.pause(self.reactor.now + abs(distance) / max(speed, 0.01))
            if not any(m.speed for m in self.motors.values()):
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
            "lane_%s_odometer_pin" % name: "hall_" + name,
            "lane_%s_odometer_mm_per_pulse" % name: 0.5,
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
    with pytest.raises(ConfigError, match="extruder"):
        Canvas(make_config(printer))

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


def test_reset_refuses_to_forget_filament_at_toolhead():
    printer, canvas = make_canvas()
    run_command(printer, "CANVAS_LOAD", {"TOOL": 0})
    with pytest.raises(CanvasError, match="filament remains"):
        run_command(printer, "CANVAS_RESET")
    assert canvas.active_tool == 0

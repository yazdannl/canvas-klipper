# Standalone Elegoo CANVAS control for Klipper.
# Behavior informed by AFC Canvas (GPL-3.0); this implementation has no AFC imports.
# Copyright (C) 2026 canvas-klipper contributors
# This file may be distributed under the terms of the GNU GPLv3 license.

import re


LANE_NAMES = ("T0", "T1", "T2", "T3")
DEFAULT_POLL_INTERVAL = 0.005


class CanvasError(Exception):
    pass


class CanvasLane:
    def __init__(self, name, motor, present_pin, prep_pin,
                 load_speed, load_max_distance,
                 load_timeout, prep_max_distance, prep_timeout,
                 unload_speed, unload_max_distance, unload_timeout,
                 park_distance, park_speed):
        self.name = name
        self.motor = motor
        self.present_pin = present_pin
        self.prep_pin = prep_pin
        self.load_speed = load_speed
        self.load_max_distance = load_max_distance
        self.load_timeout = load_timeout
        self.prep_max_distance = prep_max_distance
        self.prep_timeout = prep_timeout
        self.unload_speed = unload_speed
        self.unload_max_distance = unload_max_distance
        self.unload_timeout = unload_timeout
        self.park_distance = park_distance
        self.park_speed = park_speed
        self.present = False
        self.prep = False
        self.odometer_count = 0
        self._odometer_mm = 0.0
        self._last_hall_count = 0
        self._last_hall_distance = 0.0

    def update_odometer(self, eventtime):
        status = self.motor.get_status(eventtime)
        count = int(status["hall_count"])
        distance = float(status["hall_distance"])
        if count < self._last_hall_count or distance < self._last_hall_distance:
            self.odometer_count += count
            self._odometer_mm += max(0.0, distance)
        else:
            self.odometer_count += count - self._last_hall_count
            self._odometer_mm += max(0.0, distance - self._last_hall_distance)
        self._last_hall_count = count
        self._last_hall_distance = distance
        return status

    def reset_odometer(self, eventtime):
        status = self.motor.get_status(eventtime)
        self.odometer_count = 0
        self._odometer_mm = 0.0
        self._last_hall_count = int(status["hall_count"])
        self._last_hall_distance = float(status["hall_distance"])

    def odometer_distance(self):
        return self._odometer_mm


class Canvas:
    cmd_CANVAS_TOOL_SELECT_help = "Select and load CANVAS lane TOOL=0..3"
    cmd_CANVAS_LOAD_help = "Load filament from a CANVAS lane"
    cmd_CANVAS_UNLOAD_help = "Separate and unload the active CANVAS lane"
    cmd_CANVAS_STATUS_help = "Report CANVAS lane and sensor status"
    cmd_CANVAS_RESET_help = "Cancel motion or clear CANVAS state for recovery"
    cmd_CANVAS_CUT_INTERNAL_help = "Run the configured CANVAS cutter separation"

    def __init__(self, config):
        self.printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        self.gcode = self.printer.lookup_object("gcode")
        self.extruder = None
        self.config = config

        self.sensor_name = config.get("toolhead_sensor", "").strip()
        if not self.sensor_name:
            raise config.error("[canvas] toolhead_sensor is required")
        self.toolhead_sensor = self.printer.lookup_object(
            "filament_switch_sensor " + self.sensor_name, None)
        if self.toolhead_sensor is None or not callable(
                getattr(self.toolhead_sensor, "get_status", None)):
            raise config.error(
                "[canvas] requires [filament_switch_sensor %s] as toolhead_sensor"
                % (self.sensor_name,))

        self.load_attempts = config.getint("load_attempts", 3, minval=1)
        self.cutter_retries = config.getint("cutter_retries", 3, minval=1)
        self.cutter_timeout = config.getfloat("cutter_timeout", 3.0, above=0.0)
        self.toolhead_timeout = config.getfloat("toolhead_timeout", 30.0, above=0.0)
        self.extruder_feed_length = config.getfloat(
            "extruder_feed_length", above=0.0)
        self.extruder_feed_speed = config.getfloat(
            "extruder_feed_speed", above=0.0)
        self.extruder_retract_length = config.getfloat(
            "extruder_retract_length", above=0.0)
        self.extruder_retract_speed = config.getfloat(
            "extruder_retract_speed", above=0.0)
        self.grip_min_distance = config.getfloat(
            "grip_min_distance", 1.0, minval=0.0)
        self.load_recovery_distance = config.getfloat(
            "load_recovery_distance", 10.0, minval=0.0)
        self.separation_method = config.get(
            "separation_method", "cutter").strip().lower()
        if self.separation_method not in ("cutter", "tip_forming"):
            raise config.error("separation_method must be cutter or tip_forming")
        self.cutter_macro = self._macro_name(
            config, "cutter_macro", "CANVAS_CUTTER_ACTUATE")
        self.park_macro = self._optional_macro(config, "park_macro")
        self.post_cut_macro = self._optional_macro(config, "post_cut_macro")
        self.tip_form_macro = self._optional_macro(config, "tip_form_macro")
        self.tip_forming_cool_ms = config.getint(
            "tip_forming_cool_ms", 300, minval=0)
        self.tip_forming_moves = self._parse_tip_moves(
            config, config.get("tip_forming_moves", "-2:25;-4:15;-8:5"))
        self.hub_tangle_pin = config.get("hub_tangle_pin", None)
        self.cutter_sensor_pin = config.get("cutter_sensor_pin", None)
        self.pause_on_error = config.getboolean("pause_on_error", True)

        self.lanes = {}
        for index, name in enumerate(LANE_NAMES):
            motor_name = config.get("lane_%s_motor" % (name,)).strip()
            motor = self.printer.lookup_object("drv8833 " + motor_name, None)
            if motor is None or not all(callable(getattr(motor, method, None))
                                         for method in (
                                             "drv8833_set_speed", "drv8833_move",
                                             "stop", "get_status")):
                raise config.error(
                    "lane_%s_motor must name an existing [drv8833 NAME] object "
                    "with the supported host API" % (name,))
            lane = CanvasLane(
                name=name,
                motor=motor,
                present_pin=config.get("lane_%s_present_pin" % name),
                prep_pin=config.get("lane_%s_prep_pin" % name),
                load_speed=config.getfloat("lane_%s_load_speed" % name, 40.0,
                                           above=0.0),
                load_max_distance=config.getfloat(
                    "lane_%s_load_max_distance" % name, 120.0, above=0.0),
                load_timeout=config.getfloat(
                    "lane_%s_load_timeout" % name, self.toolhead_timeout,
                    above=0.0),
                prep_max_distance=config.getfloat(
                    "lane_%s_prep_max_distance" % name, 40.0, above=0.0),
                prep_timeout=config.getfloat(
                    "lane_%s_prep_timeout" % name, 10.0, above=0.0),
                unload_speed=config.getfloat(
                    "lane_%s_unload_speed" % name, 40.0, above=0.0),
                unload_max_distance=config.getfloat(
                    "lane_%s_unload_max_distance" % name, 120.0, above=0.0),
                unload_timeout=config.getfloat(
                    "lane_%s_unload_timeout" % name, self.toolhead_timeout,
                    above=0.0),
                park_distance=config.getfloat(
                    "lane_%s_park_distance" % name, 1.0, minval=0.0),
                park_speed=config.getfloat(
                    "lane_%s_park_speed" % name, 10.0, above=0.0))
            if self.extruder_feed_length > lane.load_max_distance:
                raise config.error(
                    "%s extruder_feed_length exceeds its Hall-distance bound" % name)
            if self.extruder_retract_length > lane.unload_max_distance:
                raise config.error(
                    "%s extruder_retract_length exceeds its Hall-distance bound" % name)
            self.lanes[name] = lane

        self.buttons = self.printer.load_object(config, "buttons")
        for lane in self.lanes.values():
            self.buttons.register_buttons(
                [lane.present_pin],
                lambda eventtime, state, l=lane: setattr(l, "present", bool(state)))
            self.buttons.register_buttons(
                [lane.prep_pin],
                lambda eventtime, state, l=lane: setattr(l, "prep", bool(state)))
        if self.hub_tangle_pin is not None:
            self.hub_tangle = False
            self.buttons.register_buttons(
                [self.hub_tangle_pin],
                lambda eventtime, state: setattr(self, "hub_tangle", bool(state)))
        else:
            self.hub_tangle = False
        if self.cutter_sensor_pin is not None:
            self.cutter_engaged = False
            self.buttons.register_buttons(
                [self.cutter_sensor_pin],
                lambda eventtime, state: setattr(
                    self, "cutter_engaged", bool(state)))
        else:
            self.cutter_engaged = False

        self.active_tool = None
        self.loaded = {name: False for name in LANE_NAMES}
        self.busy = False
        self.cancel_requested = False
        self.last_error = None
        self._load_saved_state()
        self.save_variables = self.printer.lookup_object("save_variables", None)
        self._register_commands()
        self.printer.register_event_handler("klippy:connect", self._handle_connect)
        self.printer.register_event_handler("klippy:ready", self._handle_ready)
        self.printer.register_event_handler("klippy:shutdown", self._handle_shutdown)
        self.printer.register_event_handler(
            "gcode:request_restart", self._handle_restart)

    @staticmethod
    def _macro_name(config, key, default):
        value = config.get(key, default).strip()
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", value):
            raise config.error("%s must be a G-code command name" % (key,))
        return value

    @classmethod
    def _optional_macro(cls, config, key):
        value = config.get(key, None)
        if value is None or not value.strip():
            return None
        return cls._macro_name(config, key, value)

    @staticmethod
    def _parse_tip_moves(config, value):
        moves = []
        try:
            for part in value.split(";"):
                if not part.strip():
                    continue
                distance, speed = (float(v.strip()) for v in part.split(":"))
                if distance >= 0 or speed <= 0:
                    raise ValueError()
                moves.append((distance, speed))
        except (ValueError, TypeError):
            raise config.error(
                "tip_forming_moves must be negative-distance:speed pairs "
                "separated by semicolons")
        if not moves and not config.get("tip_form_macro", None):
            raise config.error("tip_forming_moves must contain at least one move")
        return moves

    def _register_commands(self):
        for name, method, desc in (
                ("CANVAS_TOOL_SELECT", self.cmd_CANVAS_TOOL_SELECT,
                 self.cmd_CANVAS_TOOL_SELECT_help),
                ("CANVAS_LOAD", self.cmd_CANVAS_LOAD, self.cmd_CANVAS_LOAD_help),
                ("CANVAS_UNLOAD", self.cmd_CANVAS_UNLOAD,
                 self.cmd_CANVAS_UNLOAD_help),
                ("CANVAS_STATUS", self.cmd_CANVAS_STATUS,
                 self.cmd_CANVAS_STATUS_help),
                ("CANVAS_RESET", self.cmd_CANVAS_RESET,
                 self.cmd_CANVAS_RESET_help),
                ("CANVAS_CUT_INTERNAL", self.cmd_CANVAS_CUT_INTERNAL,
                 self.cmd_CANVAS_CUT_INTERNAL_help)):
            self.gcode.register_command(name, method, desc=desc)

    def _load_saved_state(self):
        saved = self.printer.lookup_object("save_variables", None)
        if saved is None:
            return
        variables = saved.get_status(self.reactor.monotonic()).get("variables", {})
        tool = variables.get("canvas_active_tool")
        if isinstance(tool, int) and 0 <= tool < len(LANE_NAMES):
            self.active_tool = tool
        for index, name in enumerate(LANE_NAMES):
            self.loaded[name] = bool(variables.get("canvas_loaded_%d" % index, False))

    def _handle_connect(self):
        self.extruder = self.printer.lookup_object("extruder", None)
        if self.extruder is None:
            raise self.config.error("[canvas] requires a configured [extruder]")

    def _handle_ready(self):
        present = self._toolhead_present()
        if self.active_tool is not None:
            self.loaded[LANE_NAMES[self.active_tool]] = present
        if self.save_variables is not None:
            self._persist_state()

    def _handle_shutdown(self):
        self.cancel_requested = True
        self._stop_all()

    def _handle_restart(self, print_time=None):
        self.cancel_requested = True
        self._stop_all()

    def _toolhead_present(self):
        return bool(self.toolhead_sensor.get_status(
            self.reactor.monotonic()).get("filament_detected", False))

    def _hotend_ready(self):
        status = self.extruder.get_status(self.reactor.monotonic())
        if not status.get("can_extrude", False):
            raise CanvasError("hotend is below the extruder's minimum extrusion temperature")

    def _ensure_not_cancelled(self):
        if self.cancel_requested or self.printer.is_shutdown():
            raise CanvasError("CANVAS operation cancelled or printer is shutting down")

    def _stop_all(self):
        for lane in self.lanes.values():
            try:
                lane.motor.stop()
            except Exception:
                pass

    def _persist_state(self):
        if self.save_variables is None:
            return
        value = -1 if self.active_tool is None else self.active_tool
        self.gcode.run_script_from_command(
            "SAVE_VARIABLE VARIABLE=canvas_active_tool VALUE=%d" % value)
        for index, name in enumerate(LANE_NAMES):
            self.gcode.run_script_from_command(
                "SAVE_VARIABLE VARIABLE=canvas_loaded_%d VALUE=%s" %
                (index, "True" if self.loaded[name] else "False"))

    def _gcmd_tool(self, gcmd, required=True):
        value = gcmd.get_int("TOOL", None)
        if value is None:
            if required:
                raise gcmd.error("TOOL=0..3 is required")
            if self.active_tool is None:
                raise gcmd.error("No active CANVAS tool; specify TOOL=0..3")
            return self.active_tool
        if value < 0 or value >= len(LANE_NAMES):
            raise gcmd.error("TOOL must be between 0 and 3")
        return value

    def _run_guarded(self, gcmd, action):
        if self.busy:
            raise gcmd.error("A CANVAS operation is already in progress")
        self.busy = True
        self.cancel_requested = False
        try:
            result = action()
            self.last_error = None
            return result
        except Exception as error:
            self.last_error = str(error)
            self._stop_all()
            if self.pause_on_error and not self.printer.is_shutdown():
                try:
                    self.gcode.run_script_from_command("PAUSE")
                except Exception:
                    pass
            if isinstance(error, CanvasError):
                raise gcmd.error(str(error))
            raise
        finally:
            self._stop_all()
            self.busy = False

    def _drive_until(self, lane, speed, sensor_test, target, max_distance, timeout):
        if sensor_test() == target:
            return 0.0
        lane.reset_odometer(self.reactor.monotonic())
        deadline = self.reactor.monotonic() + timeout
        lane.motor.drv8833_set_speed(speed if target else -speed)
        try:
            while True:
                self._ensure_not_cancelled()
                lane.update_odometer(self.reactor.monotonic())
                if sensor_test() == target:
                    return lane.odometer_distance()
                distance = lane.odometer_distance()
                if distance >= max_distance:
                    raise CanvasError(
                        "%s exceeded %.1f mm without the expected sensor transition" %
                        (lane.name, max_distance))
                now = self.reactor.monotonic()
                if now >= deadline:
                    raise CanvasError(
                        "%s timed out waiting for the expected sensor transition" %
                        lane.name)
                self.reactor.pause(min(deadline, now + DEFAULT_POLL_INTERVAL))
        finally:
            lane.motor.stop()
            lane.update_odometer(self.reactor.monotonic())

    def _drive_distance(self, lane, distance, speed, timeout):
        if distance == 0:
            return
        lane.reset_odometer(self.reactor.monotonic())
        deadline = self.reactor.monotonic() + timeout
        lane.motor.drv8833_move(speed, distance, wait_for_completion=False)
        try:
            while True:
                self._ensure_not_cancelled()
                now = self.reactor.monotonic()
                status = lane.update_odometer(now)
                if lane.odometer_distance() >= abs(distance):
                    return
                if not status["active"]:
                    raise CanvasError(
                        "%s Hall-limited move stopped short (%.2f of %.2f mm)" %
                        (lane.name, lane.odometer_distance(), abs(distance)))
                if now >= deadline:
                    raise CanvasError("%s Hall odometry timed out" % lane.name)
                self.reactor.pause(min(deadline, now + DEFAULT_POLL_INTERVAL))
        finally:
            if lane.motor.get_status(self.reactor.monotonic())["active"]:
                lane.motor.stop()
            lane.update_odometer(self.reactor.monotonic())

    def _extrude(self, distance, speed):
        self._hotend_ready()
        self.gcode.run_script_from_command("SAVE_GCODE_STATE NAME=CANVAS_EXTRUSION")
        try:
            self.gcode.run_script_from_command(
                "G91\nM83\nG1 E%.3f F%.1f\nM400" %
                (distance, speed * 60.0))
        finally:
            self.gcode.run_script_from_command(
                "RESTORE_GCODE_STATE NAME=CANVAS_EXTRUSION")

    def _load_lane(self, lane):
        if not lane.present:
            raise CanvasError("%s has no filament at its lane-present switch" % lane.name)
        if self.hub_tangle:
            raise CanvasError("shared CANVAS hub/tangle sensor is active")
        if self._toolhead_present():
            # A present toolhead sensor is allowed only when adopting the same lane.
            if self.active_tool != int(lane.name[1:]):
                raise CanvasError("toolhead sensor is already occupied by another filament")
            return
        self._hotend_ready()
        lane_index = int(lane.name[1:])
        last_error = None
        for attempt in range(self.load_attempts):
            try:
                self._drive_until(
                    lane, lane.load_speed, lambda: lane.prep, True,
                    lane.prep_max_distance, lane.prep_timeout)
                self._drive_until(
                    lane, lane.load_speed, self._toolhead_present, True,
                    lane.load_max_distance, lane.load_timeout)
                lane.reset_odometer(self.reactor.monotonic())
                coordinated_speed = min(lane.load_speed, self.extruder_feed_speed)
                if self.extruder_feed_length > lane.load_max_distance:
                    raise CanvasError(
                        "configured extruder feed exceeds %s Hall-distance bound" %
                        lane.name)
                lane.motor.drv8833_set_speed(coordinated_speed)
                try:
                    self._extrude(self.extruder_feed_length,
                                  self.extruder_feed_speed)
                finally:
                    lane.motor.stop()
                lane.update_odometer(self.reactor.monotonic())
                gripped = lane.odometer_distance()
                if not self._toolhead_present():
                    raise CanvasError(
                        "%s toolhead sensor cleared during extruder feed" % lane.name)
                if gripped < self.grip_min_distance:
                    raise CanvasError(
                        "%s extruder grip not confirmed by Hall odometry "
                        "(%.2f mm < %.2f mm)" %
                        (lane.name, gripped, self.grip_min_distance))
                self.loaded[lane.name] = True
                self.active_tool = lane_index
                self._persist_state()
                return
            except CanvasError as error:
                last_error = error
                lane.motor.stop()
                if self.cancel_requested or self.printer.is_shutdown():
                    raise
                if attempt + 1 < self.load_attempts and self.load_recovery_distance:
                    try:
                        self._drive_distance(
                            lane, -self.load_recovery_distance,
                            lane.unload_speed,
                            max(1.0, self.load_recovery_distance /
                                max(lane.unload_speed, 1.0) * 5.0))
                    except CanvasError:
                        pass
        raise CanvasError("%s load failed after %d attempts: %s" %
                          (lane.name, self.load_attempts, last_error))

    def _run_macro(self, name):
        if name:
            self.gcode.run_script_from_command(
                "%s EXTRUDER=extruder" % name)

    def _separate(self, method):
        if method not in ("cutter", "tip_forming"):
            raise CanvasError("METHOD must be cutter or tip_forming")
        if method == "tip_forming":
            self._hotend_ready()
            if self.tip_form_macro:
                self._run_macro(self.tip_form_macro)
            else:
                self.gcode.run_script_from_command(
                    "SAVE_GCODE_STATE NAME=CANVAS_TIP_FORM\nG91\nM83")
                try:
                    for distance, speed in self.tip_forming_moves:
                        self._extrude(distance, speed)
                        if self.tip_forming_cool_ms:
                            self.gcode.run_script_from_command(
                                "G4 P%d" % self.tip_forming_cool_ms)
                finally:
                    self.gcode.run_script_from_command(
                        "RESTORE_GCODE_STATE NAME=CANVAS_TIP_FORM")
            self._run_macro(self.post_cut_macro)
            return

        if self.cutter_sensor_pin is not None and self.cutter_engaged:
            raise CanvasError("cutter confirmation sensor is active before cutting")
        for attempt in range(self.cutter_retries):
            self._run_macro(self.cutter_macro)
            if self.cutter_sensor_pin is None:
                break
            deadline = self.reactor.monotonic() + self.cutter_timeout
            while self.cutter_engaged:
                self._ensure_not_cancelled()
                now = self.reactor.monotonic()
                if now >= deadline:
                    break
                self.reactor.pause(min(deadline, now + DEFAULT_POLL_INTERVAL))
            if not self.cutter_engaged:
                break
        else:
            raise CanvasError(
                "cutter sensor did not clear after %d attempts" % self.cutter_retries)
        self._run_macro(self.park_macro)
        self._run_macro(self.post_cut_macro)

    def _unload_lane(self, lane, method=None):
        if self._toolhead_present() and self.active_tool != int(lane.name[1:]):
            raise CanvasError(
                "%s is not the active lane at the toolhead" % lane.name)
        if not self._toolhead_present():
            self.loaded[lane.name] = False
            self._persist_state()
            return
        self._hotend_ready()
        self._separate(method or self.separation_method)
        if self.extruder_retract_length > lane.unload_max_distance:
            raise CanvasError(
                "configured extruder retract exceeds %s Hall-distance bound" %
                lane.name)
        lane.reset_odometer(self.reactor.monotonic())
        lane.motor.drv8833_set_speed(
            -min(lane.unload_speed, self.extruder_retract_speed))
        try:
            self._extrude(-self.extruder_retract_length,
                          self.extruder_retract_speed)
        finally:
            lane.motor.stop()
        lane.update_odometer(self.reactor.monotonic())
        self._drive_until(
            lane, lane.unload_speed, self._toolhead_present, False,
            lane.unload_max_distance, lane.unload_timeout)
        self._drive_distance(
            lane, -lane.park_distance, lane.park_speed,
            max(1.0, lane.park_distance / max(lane.park_speed, 1.0) * 5.0))
        self.loaded[lane.name] = False
        self.active_tool = None
        self._persist_state()

    def _select_tool(self, index):
        name = LANE_NAMES[index]
        lane = self.lanes[name]
        if self.active_tool == index and self._toolhead_present():
            return
        if self._toolhead_present():
            old_index = self.active_tool
            if old_index is None:
                raise CanvasError(
                    "toolhead sensor is occupied but no active lane is known; use CANVAS_RESET")
            self._unload_lane(self.lanes[LANE_NAMES[old_index]])
        self.active_tool = index
        self.loaded[name] = False
        self._load_lane(lane)

    def cmd_CANVAS_TOOL_SELECT(self, gcmd):
        index = self._gcmd_tool(gcmd)
        return self._run_guarded(gcmd, lambda: self._select_tool(index))

    def cmd_CANVAS_LOAD(self, gcmd):
        index = self._gcmd_tool(gcmd, required=False)
        lane = self.lanes[LANE_NAMES[index]]
        return self._run_guarded(gcmd, lambda: self._load_lane(lane))

    def cmd_CANVAS_UNLOAD(self, gcmd):
        index = self._gcmd_tool(gcmd, required=False)
        lane = self.lanes[LANE_NAMES[index]]
        method = gcmd.get("METHOD", self.separation_method).strip().lower()
        return self._run_guarded(gcmd, lambda: self._unload_lane(lane, method))

    def cmd_CANVAS_CUT_INTERNAL(self, gcmd):
        method = gcmd.get("METHOD", "cutter").strip().lower()

        def cut():
            if self.active_tool is None or not self._toolhead_present():
                raise CanvasError("CANVAS_CUT requires a known active toolhead filament")
            self._separate(method)
        return self._run_guarded(gcmd, cut)

    def cmd_CANVAS_STATUS(self, gcmd):
        status = self.get_status(self.reactor.monotonic())
        gcmd.respond_info(
            "Canvas active=%s loaded=%s busy=%s toolhead=%s hub_tangle=%s" %
            (status["active_tool"], status["loaded"], status["busy"],
             status["toolhead_present"], status["hub_tangle"]))

    def cmd_CANVAS_RESET(self, gcmd):
        if self.busy:
            self.cancel_requested = True
            self._stop_all()
            gcmd.respond_info("CANVAS cancellation requested; waiting for safe stop")
            return

        def reset():
            self._stop_all()
            self.last_error = None
            if self._toolhead_present():
                raise CanvasError(
                    "filament remains at toolhead; unload it before resetting lane state")
            self.active_tool = None
            self.loaded = {name: False for name in LANE_NAMES}
            self.cancel_requested = False
            self._persist_state()
        return self._run_guarded(gcmd, reset)

    def get_status(self, eventtime=None):
        lanes = {}
        for name, lane in self.lanes.items():
            motor_status = lane.update_odometer(eventtime)
            lanes[name] = {
                "present": lane.present,
                "prep": lane.prep,
                "loaded": self.loaded[name],
                "odometer_count": lane.odometer_count,
                "odometer_mm": lane.odometer_distance(),
                "motor": motor_status,
            }
        return {
            "active_tool": self.active_tool,
            "loaded": dict(self.loaded),
            "toolhead_present": self._toolhead_present(),
            "hub_tangle": self.hub_tangle,
            "cutter_engaged": self.cutter_engaged,
            "separation_method": self.separation_method,
            "busy": self.busy,
            "cancel_requested": self.cancel_requested,
            "last_error": self.last_error,
            "lanes": lanes,
        }


def load_config(config):
    return Canvas(config)

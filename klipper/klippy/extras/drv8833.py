# DRV8833-compatible H-bridge and Hall driver for Klipper.
#
# API and MCU protocol derived from OpenCentauri COSMOS's driver, with the
# Klipper host implementation simplified for standalone CANVAS use.
# Copyright (C) OpenCentauri contributors
# This file may be distributed under the terms of the GNU GPLv3 license.

import math

HALL_POLL_TIME = 0.001
CONTROL_INTERVAL = 0.010
REPORT_INTERVAL = 0.050
SPEED_SCALE = 1000
DUTY_SCALE = 10
HALL_RESOLUTION_SCALE = 1000000


class MCUDrv8833Controller:
    def __init__(self, config, forward, reverse, hall):
        self.printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        self.mcu = forward["chip"]
        self.oid = self.mcu.create_oid()
        self.forward_pin = forward["pin"]
        self.reverse_pin = reverse["pin"]
        self.hall_pin = hall["pin"]
        self.hall_pullup = hall["pullup"]
        self.cycle_time = config.getfloat("motor_cycle_time", 0.002, above=0.0)
        self.hall_resolution = config.getfloat("motor_hall_resolution", above=0.0)
        self.default_duty = config.getfloat("default_duty", 50.0, minval=0.0, maxval=100.0)
        self.max_duty_step = config.getfloat("max_duty_step", 4.0, above=0.0, maxval=100.0)
        self.pid_kp = config.getfloat("pid_kp", 1.2, minval=0.0)
        self.pid_ki = config.getfloat("pid_ki", 0.8, minval=0.0)
        self.pid_kd = config.getfloat("pid_kd", 0.02, minval=0.0)
        self.active = False
        self.manual = False
        self.hall_count = 0
        self.speed = 0.0
        self.duty = 0.0
        self.status_time = 0.0
        self.direction = 1
        self.target_speed = 0.0
        self._set_cmd = self._manual_cmd = self._pid_cmd = None
        self.mcu.register_response(self._handle_status, "drv8833_status", self.oid)
        self.mcu.register_config_callback(self._build_config)

    def _pid_value(self, value):
        return int(round(value * 10000))

    def _build_config(self):
        pwm_max = int(self.mcu.get_constant_float("PWM_MAX") + 0.5)
        self.mcu.add_config_cmd(
            "config_drv8833 oid=%d motor_fwd_pin=%s motor_rwd_pin=%s "
            "cycle_ticks=%d hall_pin=%s hall_pullup=%d poll_ticks=%d "
            "control_ticks=%d report_ticks=%d hall_resolution=%d pwm_max=%d "
            "default_duty=%d max_duty_step=%d" % (
                self.oid, self.forward_pin, self.reverse_pin,
                self.mcu.seconds_to_clock(self.cycle_time), self.hall_pin,
                self.hall_pullup, self.mcu.seconds_to_clock(HALL_POLL_TIME),
                self.mcu.seconds_to_clock(CONTROL_INTERVAL),
                self.mcu.seconds_to_clock(REPORT_INTERVAL),
                int(round(self.hall_resolution * HALL_RESOLUTION_SCALE)),
                pwm_max, int(round(self.default_duty * DUTY_SCALE)),
                int(round(self.max_duty_step * DUTY_SCALE))))
        self.mcu.add_config_cmd(
            "drv8833_set_pid oid=%d kp=%d ki=%d kd=%d" % (
                self.oid, self._pid_value(self.pid_kp),
                self._pid_value(self.pid_ki), self._pid_value(self.pid_kd)),
            is_init=True)
        self.mcu.add_config_cmd(
            "drv8833_set oid=%d enable=0 direction=1 target_speed=0 stop_ticks=0" % self.oid,
            on_restart=True)
        self._set_cmd = self.mcu.lookup_command(
            "drv8833_set oid=%c enable=%c direction=%c target_speed=%u stop_ticks=%u")
        self._manual_cmd = self.mcu.lookup_command(
            "drv8833_manual oid=%c enable=%c direction=%c duty=%hu")
        self._pid_cmd = self.mcu.lookup_command(
            "drv8833_set_pid oid=%c kp=%u ki=%u kd=%u")

    def _handle_status(self, params):
        self.active = bool(params["active"])
        self.manual = bool(params["manual"])
        self.hall_count = int(params["count"])
        self.speed = params["speed"] / float(SPEED_SCALE)
        self.duty = params["duty"] / float(DUTY_SCALE)
        self.status_time = self.reactor.monotonic()

    def start(self, direction, speed, stop_ticks=0):
        if self._set_cmd is None:
            raise self.printer.command_error("drv8833 MCU is not configured")
        self._set_cmd.send([self.oid, 1, int(direction > 0),
                            int(round(speed * SPEED_SCALE)), stop_ticks])
        self.active, self.manual = True, False
        self.direction, self.target_speed = (1 if direction > 0 else -1), speed

    def manual_start(self, direction, duty):
        if self._manual_cmd is None:
            raise self.printer.command_error("drv8833 MCU is not configured")
        self._manual_cmd.send([self.oid, 1, int(direction > 0),
                               int(round(max(0., min(100., duty)) * DUTY_SCALE))])
        self.active, self.manual = True, True
        self.direction, self.target_speed = (1 if direction > 0 else -1), 0.0

    def set_pid(self, kp, ki, kd):
        if self._pid_cmd is None:
            raise self.printer.command_error("drv8833 MCU is not configured")
        self._pid_cmd.send([self.oid, self._pid_value(kp),
                            self._pid_value(ki), self._pid_value(kd)])
        self.pid_kp, self.pid_ki, self.pid_kd = kp, ki, kd

    def stop(self):
        if self._set_cmd is None:
            raise self.printer.command_error("drv8833 MCU is not configured")
        self._set_cmd.send([self.oid, 0, 1, 0, 0])
        self.active, self.manual = False, False
        self.target_speed = 0.0


class PrinterDrv8833:
    """COSMOS-compatible lane object: drv8833_set_speed/move/status/stop."""

    def __init__(self, config):
        self.printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        self.section_name = config.get_name()
        parts = self.section_name.split(None, 1)
        self.name = parts[1] if len(parts) > 1 else self.section_name
        ppins = self.printer.lookup_object("pins")
        forward = ppins.lookup_pin(config.get("motor_fwd"))
        reverse = ppins.lookup_pin(config.get("motor_rwd"))
        hall = ppins.lookup_pin(config.get("motor_hall"), can_pullup=True)
        mcu = forward["chip"]
        if reverse["chip"] is not mcu or hall["chip"] is not mcu:
            raise config.error("drv8833 motor_fwd, motor_rwd, and motor_hall must use the same MCU")
        self.hall_controller = MCUDrv8833Controller(config, forward, reverse, hall)
        self.controller = self.hall_controller
        self.hall_controller.hall_resolution = config.getfloat("motor_hall_resolution", above=0.0)
        self.move_timeout = config.getfloat("move_timeout", 30.0, above=0.0)
        self._shutdown = lambda *args: self.stop()
        self.printer.register_event_handler("klippy:shutdown", self._shutdown)
        self.printer.register_event_handler("gcode:request_restart", self._shutdown)

    def drv8833_set_speed(self, speed):
        speed = float(speed)
        if not math.isfinite(speed):
            raise self.printer.command_error("drv8833 speed must be finite")
        if speed == 0.0:
            self.stop()
            return
        self.hall_controller.start(1 if speed > 0 else -1, abs(speed))

    def drv8833_move(self, speed, distance, wait_for_completion=True):
        speed, distance = float(speed), float(distance)
        if not math.isfinite(speed) or not math.isfinite(distance):
            raise self.printer.command_error("drv8833 speed and distance must be finite")
        if distance < 0.0:
            speed = -speed
        distance = abs(distance)
        if speed == 0.0 or distance == 0.0:
            self.stop()
            return
        resolution = self.hall_controller.hall_resolution
        if resolution <= 0.0:
            raise self.printer.command_error("motor_hall_resolution must be positive")
        ticks = max(1, int(round(distance / resolution)))
        self.hall_controller.start(1 if speed > 0 else -1, abs(speed), ticks)
        if wait_for_completion:
            start = self.reactor.monotonic()
            deadline = start + min(self.move_timeout, distance / abs(speed) * 4.0 + 2.0)
            eventtime = start
            try:
                while self.hall_controller.active:
                    eventtime = self.reactor.pause(min(deadline, eventtime + REPORT_INTERVAL))
                    if eventtime >= deadline and self.hall_controller.active:
                        raise self.printer.command_error("drv8833 distance move timed out")
            except Exception:
                self.stop()
                raise

    def stop(self):
        self.hall_controller.stop()

    def get_status(self, eventtime):
        c = self.hall_controller
        return {"active": c.active, "manual": c.manual,
                "direction": "forwards" if c.direction > 0 else "backwards",
                "target_speed": c.target_speed, "duty_cycle": c.duty,
                "hall_speed": c.speed, "hall_count": c.hall_count,
                "hall_distance": c.hall_count * c.hall_resolution,
                "pid_kp": c.pid_kp, "pid_ki": c.pid_ki, "pid_kd": c.pid_kd}

    def set_pid_gains(self, kp, ki, kd, save_to_config=False):
        for value in (kp, ki, kd):
            if not math.isfinite(value) or value < 0:
                raise self.printer.command_error("PID gains must be finite and non-negative")
        self.hall_controller.set_pid(kp, ki, kd)
        if save_to_config:
            cfg = self.printer.lookup_object("configfile")
            cfg.set(self.section_name, "pid_kp", "%.6f" % kp)
            cfg.set(self.section_name, "pid_ki", "%.6f" % ki)
            cfg.set(self.section_name, "pid_kd", "%.6f" % kd)


def load_config_prefix(config):
    return PrinterDrv8833(config)

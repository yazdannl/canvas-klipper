# DRV8833 host API

Each configured `[drv8833 <name>]` creates a Klipper object named `drv8833 <name>`. Its pin fields are exactly `motor_fwd`, `motor_rwd`, and `motor_hall`; all three pins must belong to the same MCU. `motor_hall_resolution` is required and is millimetres per detected Hall edge.

The Canvas control layer should retrieve the object with `printer.lookup_object("drv8833 <name>")` and call:

- `drv8833_set_speed(speed)` — continuous movement; positive is forward, negative is reverse, zero stops.
- `drv8833_move(speed, distance, wait_for_completion=True)` — Hall-count-limited move. Negative distance reverses the requested direction. With the default wait it blocks until the MCU reports completion or `move_timeout` expires; timeout stops the motor and raises a Klipper command error. `wait_for_completion=False` starts asynchronously.
- `stop()` — stop the H-bridge outputs immediately.
- `get_status(eventtime)` — returns `active`, `manual`, `direction`, `target_speed`, `duty_cycle`, `hall_speed`, `hall_count`, `hall_distance`, and `pid_kp`, `pid_ki`, `pid_kd`.
- `set_pid_gains(kp, ki, kd, save_to_config=False)` — updates non-negative finite gains; optional save uses Klipper's configfile object.

These names and signed-speed/distance semantics match the COSMOS host API. The implementation intentionally keeps COSMOS's configuration field names and MCU command names while omitting its debug G-code and PID-autotune commands; callers must not depend on those diagnostic commands. MCU-reported Hall count is reset when a move starts. Electrical polarity, Hall resolution, duty limits, and speed calibration require bench validation.

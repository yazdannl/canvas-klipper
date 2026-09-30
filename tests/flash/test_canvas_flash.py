import binascii
import importlib.util
import hashlib
from importlib.machinery import SourceFileLoader
import os
import pty
import select
import struct
import termios
import tty
from pathlib import Path
import subprocess

import pytest


SCRIPT = Path(__file__).parents[2] / "flash" / "canvas-flash"
loader = SourceFileLoader("canvas_flash", str(SCRIPT.resolve()))
spec = importlib.util.spec_from_loader(loader.name, loader)
canvas_flash = importlib.util.module_from_spec(spec)
loader.exec_module(canvas_flash)

ACK, NAK, CRC, SOH, EOT = 0x06, 0x15, 0x43, 0x01, 0x04


def read_exact(fd, size, timeout=1.0):
    data = bytearray()
    while len(data) < size:
        ready, _, _ = select.select([fd], [], [], timeout)
        if not ready:
            raise TimeoutError("pseudo-terminal transfer timed out")
        chunk = os.read(fd, size - len(data))
        if not chunk:
            raise EOFError("pseudo-terminal closed")
        data.extend(chunk)
    return bytes(data)


def send_exact(fd, data):
    view = memoryview(data)
    while view:
        view = view[os.write(fd, view):]


def ymodem_crc(data):
    return binascii.crc_hqx(data, 0)


def ymodem_packet(marker, number, payload):
    packet = bytes([marker, number, 0xFF - number]) + payload
    return packet + struct.pack(">H", ymodem_crc(payload))


def ymodem_frame(fd):
    marker = read_exact(fd, 1)[0]
    body_size = 128 if marker == SOH else 1024 if marker == 0x02 else 0
    if not body_size:
        return bytes([marker])
    return bytes([marker]) + read_exact(fd, body_size + 4)


def canvas_transfer(slave, master, image, *, nak_retry=False, timeout=False):
    tty.setraw(slave, termios.TCSANOW)
    header = bytearray(16)
    header[:4] = bytes([0x14, 0x18, 0x01, 0x1A])
    header[4:8] = bytes([1, 0, 0, 0xFF])
    header[8] = 0x01
    header[12:16] = struct.pack("<I", len(image))
    padded = bytes(header) + hashlib.md5(image).digest() + bytes([0xFF]) * (0x4000 - 0x20) + image
    start_payload = bytearray(128)
    start_meta = b"deployer.bin\0" + (str(len(padded)) + " ").encode()
    start_payload[:len(start_meta)] = start_meta
    start = ymodem_packet(SOH, 0, start_payload)
    send_exact(slave, start)
    assert ymodem_frame(master) == start
    if timeout:
        raise TimeoutError("mock Canvas receiver withheld acknowledgement")
    if nak_retry:
        send_exact(master, bytes([NAK]))
        assert read_exact(slave, 1) == bytes([NAK])
        send_exact(slave, start)
        assert ymodem_frame(master) == start
    send_exact(master, bytes([ACK, CRC]))
    assert read_exact(slave, 2) == bytes([ACK, CRC])

    offset = 0
    block = 1
    while offset < len(padded):
        remaining = len(padded) - offset
        final = block == (len(padded) + 1023) // 1024
        block_size = 128 if final and len(padded) % 1024 <= 128 else 1024
        marker = SOH if block_size == 128 else 0x02
        payload = padded[offset:offset + block_size].ljust(block_size, b"\x1a")
        packet = ymodem_packet(marker, block & 0xFF, payload)
        send_exact(slave, packet)
        assert ymodem_frame(master) == packet
        if nak_retry and block == 1:
            send_exact(master, bytes([NAK]))
            assert read_exact(slave, 1) == bytes([NAK])
            send_exact(slave, packet)
            assert ymodem_frame(master) == packet
        send_exact(master, bytes([ACK]))
        assert read_exact(slave, 1) == bytes([ACK])
        offset += min(block_size, remaining)
        block += 1

    send_exact(slave, bytes([EOT]))
    assert read_exact(master, 1) == bytes([EOT])
    send_exact(master, bytes([NAK]))
    assert read_exact(slave, 1) == bytes([NAK])
    send_exact(slave, bytes([EOT]))
    assert read_exact(master, 1) == bytes([EOT])
    send_exact(master, bytes([ACK]))
    assert read_exact(slave, 1) == bytes([ACK])
    empty = ymodem_packet(SOH, 0, bytes(128))
    send_exact(slave, empty)
    assert ymodem_frame(master) == empty
    send_exact(master, bytes([ACK]))
    assert read_exact(slave, 1) == bytes([ACK])


def katapult_crc(buf):
    crc = 0xFFFF
    for value in buf:
        value ^= crc & 0xFF
        value ^= (value & 0x0F) << 4
        crc = ((value << 8) | (crc >> 8)) ^ (value >> 4) ^ (value << 3)
    return crc & 0xFFFF


def katapult_frame(command, payload=b""):
    assert len(payload) % 4 == 0
    frame = b"\x01\x88" + bytes([command, len(payload) // 4]) + payload
    return frame + struct.pack("<H", katapult_crc(frame[2:])) + b"\x99\x03"


def katapult_response(command, payload=b""):
    body = struct.pack("<I", command) + payload
    assert len(body) % 4 == 0
    frame = b"\x01\x88\xa0" + bytes([len(body) // 4]) + body
    return frame + struct.pack("<H", katapult_crc(frame[2:])) + b"\x99\x03"


def katapult_transfer(slave, master, firmware):
    """Loop the wrapper's Katapult stage through a PTY-backed fake bootloader."""
    tty.setraw(slave, termios.TCSANOW)
    blocks = {}

    def exchange(command, payload=b""):
        request = katapult_frame(command, payload)
        send_exact(slave, request)
        header = read_exact(master, 4)
        assert header[:2] == b"\x01\x88"
        remainder = read_exact(master, header[3] * 4 + 4)
        received = header + remainder
        assert received == request
        command_id = received[2]
        request_payload = received[4:-4]
        assert struct.unpack("<H", received[-4:-2])[0] == katapult_crc(received[2:-4])
        if command_id == 0x11:  # CONNECT
            info = struct.pack("<4sII", b"\x00\x01\x01\x00", 0x10000, 64)
            info += b"stm32f401xc\0mock\0".ljust(20, b"\0")
            response_data = info
        elif command_id == 0x12:  # SEND_BLOCK
            address = struct.unpack("<I", request_payload[:4])[0]
            blocks[address] = request_payload[4:]
            response_data = struct.pack("<I", address)
        elif command_id == 0x13:  # SEND_EOF
            response_data = struct.pack("<I", len(blocks))
        elif command_id == 0x14:  # REQUEST_BLOCK for post-write verify
            address = struct.unpack("<I", request_payload)[0]
            response_data = struct.pack("<I", address) + blocks[address]
        elif command_id == 0x15:  # COMPLETE
            response_data = b""
        else:
            raise AssertionError("unexpected Katapult command %d" % command_id)
        response = katapult_response(command_id, response_data)
        send_exact(master, response)
        response_header = read_exact(slave, 4)
        response_body = read_exact(slave, response_header[3] * 4 + 4)
        return response_header + response_body

    connected = exchange(0x11)
    assert connected[2] == 0xA0
    address = 0x10000
    for offset in range(0, len(firmware), 64):
        block = firmware[offset:offset + 64].ljust(64, b"\xFF")
        response = exchange(0x12, struct.pack("<I", address + offset) + block)
        assert struct.unpack("<I", response[8:12])[0] == address + offset
    exchange(0x13)
    for offset in range(0, len(firmware), 64):
        response = exchange(0x14, struct.pack("<I", address + offset))
        assert response[12:76] == blocks[address + offset]
    exchange(0x15)
    assert blocks and min(blocks) == address
    written = b"".join(blocks[key] for key in sorted(blocks))
    assert written[:len(firmware)] == firmware


def make_files(tmp_path, *, big_firmware=False):
    image = tmp_path / "image.bin"
    image.write_bytes(b"firmware" * 9 if not big_firmware else b"X" * 0x30001)
    backup = tmp_path / "stock.dump"
    backup.write_bytes(b"stock-backup")
    recovery = tmp_path / "recovery.bin"
    recovery.write_bytes(b"recovery-image")
    return image, backup, recovery


def execute_args(stage, device, image, backup, recovery):
    args = ["--device", device, "--execute", "--i-understand-the-risks",
            "--stock-backup", str(backup), "--recovery-image", str(recovery)]
    if stage == "deployer":
        args += ["--install-katapult", "--deployer", str(image), "--vid-pid", "1234:5678"]
    else:
        args += ["--flash-klipper", "--firmware", str(image)]
    return canvas_flash.parse_args().parse_args(args)


def confirmations(device):
    answers = iter([device, "BACKUP-AND-RECOVERY-VERIFIED", "FLASH-CANVAS"])
    return lambda _prompt: next(answers)


def test_default_is_dry_run_and_help_is_available(tmp_path, capsys):
    image, _, _ = make_files(tmp_path)
    args = canvas_flash.parse_args().parse_args([
        "--install-katapult", "--device", "/dev/ttyACM-test",
        "--deployer", str(image), "--vid-pid", "1234:5678"])
    assert not args.execute
    assert canvas_flash.run(args) == 0
    assert "DRY RUN" in capsys.readouterr().out


def test_pseudo_terminal_canvas_ymodem_nak_retry_and_katapult_success(tmp_path):
    image, backup, recovery = make_files(tmp_path)
    firmware = image.read_bytes()
    master, slave = pty.openpty()
    device = os.ttyname(slave)
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        if "--canvas" in command:
            canvas_transfer(slave, master, image.read_bytes(), nak_retry=True)
        else:
            assert command[-2:] == ["--firmware", str(image)]
            katapult_transfer(slave, master, firmware)
        return subprocess.CompletedProcess(command, 0)

    ids = lambda _device: "1234:5678" if len(calls) == 0 else "1d50:6177"
    try:
        first = execute_args("deployer", device, image, backup, recovery)
        assert canvas_flash.run(first, identity_reader=ids, runner=runner,
                                input_fn=confirmations(device), output=lambda _: None) == 0
        # Same pseudo-terminal represents the device after reboot into Katapult.
        second = execute_args("klipper", device, image, backup, recovery)
        assert canvas_flash.run(second, identity_reader=ids, runner=runner,
                                input_fn=confirmations(device), output=lambda _: None) == 0
        assert "--canvas" in calls[0]
        assert calls[1][1].endswith("flashtool.py")
    finally:
        os.close(master)
        os.close(slave)


def test_pseudo_terminal_canvas_timeout_is_not_retried_automatically(tmp_path):
    image, backup, recovery = make_files(tmp_path)
    master, slave = pty.openpty()
    device = os.ttyname(slave)

    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        canvas_transfer(slave, master, image.read_bytes(), timeout=True)
        return subprocess.CompletedProcess(command, 1)

    try:
        args = execute_args("deployer", device, image, backup, recovery)
        with pytest.raises(TimeoutError):
            canvas_flash.run(args, identity_reader=lambda _: "1234:5678", runner=runner,
                             input_fn=confirmations(device), output=lambda _: None)
        assert len(calls) == 1
    finally:
        os.close(master)
        os.close(slave)


def test_wrong_usb_identity_fails_before_open_or_write(tmp_path):
    image, backup, recovery = make_files(tmp_path)
    args = execute_args("klipper", "/dev/ttyACM-test", image, backup, recovery)
    called = []
    with pytest.raises(ValueError, match="wrong or unknown USB"):
        canvas_flash.run(args, identity_reader=lambda _: "0000:0000",
                         runner=lambda *a, **k: called.append(a),
                         input_fn=confirmations(args.device), output=lambda _: None)
    assert not called


def test_wrong_image_size_rejected_before_any_identity_check(tmp_path):
    image, backup, recovery = make_files(tmp_path, big_firmware=True)
    args = execute_args("klipper", "/dev/ttyACM-test", image, backup, recovery)
    with pytest.raises(ValueError, match="does not fit"):
        canvas_flash.run(args, identity_reader=lambda _: pytest.fail("identity read"),
                         runner=lambda *a, **k: pytest.fail("serial utility invoked"),
                         input_fn=confirmations(args.device), output=lambda _: None)

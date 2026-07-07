#!/usr/bin/env python3
"""CV50 USB-TTL bench tool for HAL2026 — loopback, sniff, and active probe.

Run on the machine with the CP2102 adapter (NOT in the cloud session).

    python3 cv50_bench_uart.py --loopback   # adapter self-test: short TXD<->RXD first
    python3 cv50_bench_uart.py --sniff      # passive listen across bauds
    python3 cv50_bench_uart.py --probe      # transmit wake/query candidates, listen after each

Wiring for sniff/probe (crossed!):
    CV50 green  (TX) -> adapter RXD
    CV50 yellow (RX) -> adapter TXD
    CV50 red -> 5V/VBUS, black -> GND
Confirm the laser is visible on a phone camera BEFORE trusting any silent result.

Requires: pip install pyserial
"""

import argparse
import glob
import sys
import time

try:
    import serial
except ImportError:
    sys.exit("pyserial missing: pip install pyserial")

DEFAULT_PORT_GLOB = "/dev/serial/by-id/usb-Silicon_Labs_CP2102*"
BAUDS = [115200, 9600, 57600, 230400, 460800, 921600]
HRLINK_HDR = bytes([0xDF, 0x32])

# Candidate wake/query frames. Placeholders until reference/CV50.pdf command set
# is extracted — add real HR-LINK commands as (label, bytes) tuples.
PROBE_FRAMES = [
    ("CR/LF nudge", b"\r\n"),
    ("HR-LINK header echo", bytes([0xDF, 0x32, 0x00, 0x40])),
    ("Generic TOF query 0x55", bytes([0x55])),
    ("Modbus-ish read (01 03 00 00 00 01 84 0A)",
     bytes([0x01, 0x03, 0x00, 0x00, 0x00, 0x01, 0x84, 0x0A])),
]


def find_port(explicit):
    if explicit:
        return explicit
    hits = glob.glob(DEFAULT_PORT_GLOB)
    if not hits:
        sys.exit(f"No CP2102 found ({DEFAULT_PORT_GLOB}). Is the adapter plugged in?")
    return hits[0]


def report(data):
    if not data:
        return "SILENT"
    tag = "  <-- HR-LINK 0xDF32 FOUND!" if HRLINK_HDR in data else ""
    return f"{len(data)} bytes: {data[:48].hex(' ')}{tag}"


def listen(s, seconds):
    s.reset_input_buffer()
    end = time.time() + seconds
    buf = bytearray()
    while time.time() < end and len(buf) < 4096:
        buf += s.read(256)
    return bytes(buf)


def cmd_loopback(port):
    with serial.Serial(port, 115200, timeout=1) as s:
        s.reset_input_buffer()
        s.write(b"CV50-LOOPBACK-TEST")
        s.flush()
        got = s.read(64)
    if got == b"CV50-LOOPBACK-TEST":
        print("LOOPBACK OK — adapter TX/RX and tooling verified. Remove the short.")
    else:
        print(f"LOOPBACK FAILED (got {got!r}). Short TXD<->RXD on the adapter and retry;")
        print("if it still fails the adapter or port permissions are the problem.")


def cmd_sniff(port, seconds):
    for baud in BAUDS:
        with serial.Serial(port, baud, timeout=0.2) as s:
            data = listen(s, seconds)
        print(f"{baud:>7} baud, {seconds}s: {report(data)}")
        if HRLINK_HDR in data:
            print(f"*** CV50 is streaming at {baud} baud — UART path is ALIVE. ***")
            return
    print("All bauds silent. Verify laser glow + crossed wiring, then run --probe.")


def cmd_probe(port, seconds):
    for baud in (115200, 9600):
        print(f"--- {baud} baud ---")
        with serial.Serial(port, baud, timeout=0.2) as s:
            for label, frame in PROBE_FRAMES:
                s.reset_input_buffer()
                s.write(frame)
                s.flush()
                data = listen(s, seconds)
                print(f"  sent [{label}] {frame.hex(' ')} -> {report(data)}")
                if data:
                    return
    print("No response to any probe. Sensor is not in a UART mode on these pins;")
    print("next steps: tof.corvon.tech with crossed wiring, then Corvon email.")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", help="serial device (default: first CP2102 by-id)")
    ap.add_argument("--seconds", type=float, default=3.0, help="listen window per test")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--loopback", action="store_true")
    mode.add_argument("--sniff", action="store_true")
    mode.add_argument("--probe", action="store_true")
    args = ap.parse_args()

    port = find_port(args.port)
    print(f"Using {port}")
    if args.loopback:
        cmd_loopback(port)
    elif args.sniff:
        cmd_sniff(port, args.seconds)
    else:
        cmd_probe(port, args.seconds)


if __name__ == "__main__":
    main()

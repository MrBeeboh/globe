#!/usr/bin/env python3
"""CV50 USB-TTL bench tool for HAL2026 — loopback, sniff, and boot capture.

Run on the machine with the CP2102 adapter (NOT in the cloud session).

    python3 cv50_bench_uart.py --loopback   # adapter self-test: short TXD<->RXD first
    python3 cv50_bench_uart.py --sniff      # listen across bauds, parse HR-LINK frames
    python3 cv50_bench_uart.py --bootwatch  # open port, then hot-plug the CV50: captures
                                            # anything the sensor emits at power-up

Wiring (crossed!):
    CV50 green  (Tx) -> adapter RXD
    CV50 yellow (Rx) -> adapter TXD
    CV50 red -> 5V/VBUS, black -> GND

Protocol (from reference/CV50.pdf): UART 115200 8N1, streaming only, no commands.
Frame: DF 32 00 40 <seq> 04 <dist_lo> <dist_hi> <str_lo> <str_hi> <cksum=sum&0xFF>
Configuration (protocol/orientation) is done ONLY via https://tof.corvon.tech —
open the COM port there FIRST, then hot-plug the sensor (auto-detect ~100 ms).

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
FRAME_LEN = 11
HDR = bytes([0xDF, 0x32, 0x00, 0x40])


def find_port(explicit):
    if explicit:
        return explicit
    hits = glob.glob(DEFAULT_PORT_GLOB)
    if not hits:
        sys.exit(f"No CP2102 found ({DEFAULT_PORT_GLOB}). Is the adapter plugged in?")
    return hits[0]


def parse_frames(buf):
    """Yield (distance_mm, strength, cksum_ok) for each HR-LINK frame in buf."""
    i = 0
    while True:
        i = buf.find(HDR, i)
        if i < 0 or i + FRAME_LEN > len(buf):
            return
        f = buf[i:i + FRAME_LEN]
        dist = f[6] | (f[7] << 8)
        strength = f[8] | (f[9] << 8)
        ok = (sum(f[:10]) & 0xFF) == f[10]
        yield dist, strength, ok
        i += FRAME_LEN


def summarize(buf):
    if not buf:
        return "SILENT"
    frames = list(parse_frames(buf))
    if not frames:
        return f"{len(buf)} bytes (no HR-LINK frames): {buf[:48].hex(' ')}"
    good = [f for f in frames if f[2]]
    last = (good or frames)[-1]
    return (f"{len(buf)} bytes, {len(frames)} HR-LINK frames "
            f"({len(good)} checksum-OK), last: {last[0]} mm strength {last[1]}")


def listen(s, seconds, limit=8192):
    end = time.time() + seconds
    buf = bytearray()
    while time.time() < end and len(buf) < limit:
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
            s.reset_input_buffer()
            data = listen(s, seconds)
        print(f"{baud:>7} baud, {seconds:.0f}s: {summarize(data)}")
        if HDR in data:
            print(f"*** CV50 is streaming at {baud} baud — UART path ALIVE. ***")
            return
    print("All bauds silent. With crossed wiring + laser glow confirmed, the sensor is")
    print("not in UART streaming mode: run --bootwatch, then use tof.corvon.tech")
    print("(open port first, hot-plug sensor) to set Protocol=APM, Orientation=Down.")


def cmd_bootwatch(port, seconds):
    print("Port open. UNPLUG the CV50's red (5V) wire now, wait 2 s, then re-plug it.")
    print(f"Capturing for {seconds:.0f}s ...")
    with serial.Serial(port, 115200, timeout=0.2) as s:
        s.reset_input_buffer()
        data = listen(s, seconds, limit=32768)
    print(f"Boot capture: {summarize(data)}")
    if data and HDR not in data:
        print("Non-HR-LINK bytes at boot — that's the config/handshake traffic the web")
        print("tool listens for. Good sign: the tool should detect it with this wiring.")
    elif not data:
        print("Nothing at boot either. Double-check green->RXD, then try one TX/RX swap;")
        print("if still dead, escalate to Corvon (see FABLE5_CV50_DIAGNOSIS.md draft).")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", help="serial device (default: first CP2102 by-id)")
    ap.add_argument("--seconds", type=float, default=3.0, help="listen window per test")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--loopback", action="store_true")
    mode.add_argument("--sniff", action="store_true")
    mode.add_argument("--bootwatch", action="store_true")
    args = ap.parse_args()

    port = find_port(args.port)
    print(f"Using {port}")
    if args.loopback:
        cmd_loopback(port)
    elif args.sniff:
        cmd_sniff(port, args.seconds)
    else:
        cmd_bootwatch(port, max(args.seconds, 15.0))


if __name__ == "__main__":
    main()

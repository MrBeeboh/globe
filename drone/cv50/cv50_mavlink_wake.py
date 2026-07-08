#!/usr/bin/env python3
"""Wake an auto-adaptive CV50 by sending MAVLink heartbeats through the CP2102.

Corvon support: the CV50 defaults to an auto-adaptive serial protocol
(ArduPilot/PX4/INAV). Auto-adaptive sensors listen for FC traffic before they
transmit, which is why every passive sniff read 0 bytes. This script plays the
part of the flight controller: it sends MAVLink2 (then MAVLink1) heartbeats at
115200 and reports everything the sensor sends back — decoded MAVLink messages
(expect DISTANCE_SENSOR) or raw non-MAVLink bytes (HR-LINK frames show up as
BAD_DATA starting df 32).

    python3 cv50_mavlink_wake.py [--port /dev/ttyUSB0] [--seconds 20]

Run once per TX/RX arrangement. Wiring that works = CV50 Tx wire on adapter
RXD, CV50 Rx wire on adapter TXD.

Requires: pip install pymavlink
"""

import argparse
import glob
import os
import sys
import time

DEFAULT_PORT_GLOB = "/dev/serial/by-id/usb-Silicon_Labs_CP2102*"


def find_port(explicit):
    if explicit:
        return explicit
    hits = glob.glob(DEFAULT_PORT_GLOB) or glob.glob("/dev/ttyUSB*")
    if not hits:
        sys.exit(f"No USB-TTL adapter found ({DEFAULT_PORT_GLOB} or /dev/ttyUSB*).")
    return hits[0]


def run_phase(mavutil, port, seconds, mavlink2):
    os.environ["MAVLINK20"] = "1" if mavlink2 else ""
    label = "MAVLink2" if mavlink2 else "MAVLink1"
    print(f"--- {label} heartbeats @115200 for {seconds:.0f}s ---")
    m = mavutil.mavlink_connection(port, baud=115200,
                                   source_system=1, source_component=1)
    got_any = False
    end = time.time() + seconds
    next_hb = 0.0
    while time.time() < end:
        now = time.time()
        if now >= next_hb:
            m.mav.heartbeat_send(
                mavutil.mavlink.MAV_TYPE_QUADROTOR,
                mavutil.mavlink.MAV_AUTOPILOT_ARDUPILOTMEGA,
                0, 0, mavutil.mavlink.MAV_STATE_ACTIVE)
            next_hb = now + 0.5  # 2 Hz, generous for detection windows
        msg = m.recv_match(blocking=True, timeout=0.2)
        if msg is None:
            continue
        got_any = True
        if msg.get_type() == "BAD_DATA":
            raw = bytes(msg.data)
            tag = "  <-- HR-LINK header!" if raw[:2] == b"\xdf\x32" else ""
            print(f"  raw bytes: {raw[:32].hex(' ')}{tag}")
        elif msg.get_type() == "DISTANCE_SENSOR":
            print(f"  *** DISTANCE_SENSOR: {msg.current_distance} cm, "
                  f"orient {msg.orientation}, id {msg.id} ***")
        else:
            print(f"  {msg.get_type()}: {msg.to_dict()}")
    m.close()
    return got_any


def main():
    try:
        from pymavlink import mavutil
    except ImportError:
        sys.exit("pymavlink missing: pip install pymavlink")

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port")
    ap.add_argument("--seconds", type=float, default=20.0, help="per phase")
    args = ap.parse_args()

    port = find_port(args.port)
    print(f"Using {port}")
    heard = run_phase(mavutil, port, args.seconds, mavlink2=True)
    if not heard:
        heard = run_phase(mavutil, port, args.seconds, mavlink2=False)

    if heard:
        print("\nVERDICT: sensor responded — wiring is correct and auto-adaptive")
        print("wake works. On the FC use SERIAL7_PROTOCOL=2, RNGFND1_TYPE=10,")
        print("RNGFND1_ORIENT=25 (see FABLE5_CV50_DIAGNOSIS.md rev 3).")
    else:
        print("\nVERDICT: no response to heartbeats in this arrangement.")
        print("Swap yellow<->green at the adapter and run again. Silent both ways =")
        print("reply to Corvon (Angela) with this result and ask for the next step.")


if __name__ == "__main__":
    main()

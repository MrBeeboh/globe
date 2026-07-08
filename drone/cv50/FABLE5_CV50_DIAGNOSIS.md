# CV50 Rangefinder — Fable 5 Diagnosis & Bench Plan (rev 3)

> **REV 3 — READ FIRST (2026-07-08).** Corvon support (Angela) replied:
> the CV50 default is an **auto-adaptive serial protocol** supporting
> ArduPilot/PX4/INAV, and the **I2C interface is a closed protocol — no ACK on a
> bus scan is expected and ArduPilot I2C integration is not supported.**
>
> Implications:
> 1. **Abandon the I2C path permanently.** The empty bus-1 scan was correct behavior.
>    Ignore every I2C step below (kept only for the record).
> 2. **Auto-adaptive almost certainly means the sensor listens before it speaks**:
>    it waits to detect FC traffic (e.g. MAVLink heartbeats) on its RX pin, then picks
>    a protocol and starts transmitting. Every failed test to date was a passive
>    listen — including FC `SERIAL7_PROTOCOL=9`, which never transmits — so total
>    silence is *expected* behavior for an auto-adaptive unit that has heard nothing.
> 3. **Bench proof:** run `cv50_mavlink_wake.py` (this folder) on HAL2026 — it sends
>    MAVLink heartbeats to the CV50 through the CP2102 and reports anything that
>    comes back (MAVLink DISTANCE_SENSOR or raw HR-LINK bytes). Run it once per
>    TX/RX arrangement. If the sensor answers, wiring AND the theory are confirmed.
> 4. **FC settings — from Corvon's official "CV50 Ground Station Configuration
>    Guide" (their example port SERIAL4 translated to our SERIAL7):**
>    - `SERIAL7_PROTOCOL = 1` (**MAVLink1** — the FC then *transmits* heartbeats on
>      SERIAL7, which wakes the auto-adaptive sensor)
>    - `SERIAL7_BAUD = 115`, `SERIAL7_OPTIONS = 0`
>    - `RNGFND1_TYPE = 10` (MAVLink), `RNGFND1_ORIENT = 25` (downward)
>    - Range limits: guide says `RNGFND1_MAX_CM = 5000`, `RNGFND1_MIN_CM = 5`
>      (pre-4.6 names); on ArduCopter 4.7 the params are in meters:
>      `RNGFND1_MAX = 50`, `RNGFND1_MIN = 0.05`.
>    - Write params, refresh, power-cycle, then Mission Planner → Status →
>      `rangefinder1`. (Also clear the old attempt: leave `SCR_ENABLE` as wanted,
>      but scripting is no longer needed for this sensor.)
>    - Guide's success criterion (PX4 section, applies generally): the sensor
>      emits MAVLink `DISTANCE_SENSOR` once it hears the FC.

**Date:** 2026-07-07
**Inputs:** `HANDOFF_CV50_Claude_Fable5.md` (Grok session), `reference/CV50.pdf` (read in
full), corvon.tech ToF tool page screenshot, bench photo (laser glow on adapter power),
CORVON743V1 hwdef from ArduPilot master.
**Scope:** Analysis — the cloud session has no serial access; all tests run on HAL2026.

---

## What changed in rev 2

- **CV50.pdf read end-to-end.** It documents *zero* commands: UART mode is pure
  auto-streaming, I2C is a simple register map at 0x51. There is no serial command to
  switch modes — **the web tool is the only configuration path.**
- **The ToF tool page confirms the output protocol is a persisted setting**:
  UART / I2C / APM (ArduPilot MAVLink) / PX4 / MSP / MODBUS / AUTO. A unit set to a
  UART-family protocol will never ACK on I2C, and a unit set to I2C will never stream
  UART. **One saved setting explains both dead interfaces at once.**
- **The tool's connect procedure requires a specific order**: open the COM port FIRST,
  then hot-plug the sensor — it auto-detects within **~100 ms of sensor boot**. If the
  CV50 was already powered when "Connect" was clicked, **"awaiting device" is the
  expected result**, not a fault.
- **Bench power ruled out:** laser glow (purple, 905 nm) photographed with the CV50 on
  CP2102 power. Spec draw is only 50 mA @ 5 V.
- **The two vendor sources contradict each other on I2C.** The PDF manual says
  pin 1 = SCL, pin 2 = SDA, address **0x51** (and its own descriptions are swapped:
  "SCL — I2C Data Line"). The corvon.tech web spec says pin 1 = TX/**SDA**,
  pin 2 = RX/**SCL**, address **0x31**. Both pin orders and both addresses must be
  treated as possible: the SDA/SCL swap test is mandatory, and any probe must try
  0x51 *and* 0x31 (the existing `cv50_i2c_probe.lua` already does).

## Facts from CV50.pdf (authoritative)

**Pins (terminal diagram):** 1 = SCL/TX, 2 = SDA/RX, 3 = VCC 5V, 4 = GND.
**Cable order at the SH1.0-4P connector:** GND, 5V, Rx(SDA), Tx(SCL).
Verify wire colors by *position in the connector*, not by faith: expected black=GND,
red=5V, yellow=Rx/SDA, green=Tx/SCL.

**Electrical:** 3.5–5.5 V supply, 50 mA @ 5 V, 1–200 Hz rate, 905 nm.

**UART (115200 8N1), streaming only — no commands:**

| Byte | Meaning |
|------|---------|
| 0 | Header `0xDF` |
| 1 | Device ID `0x32` |
| 2 | System ID `0x00` |
| 3 | Message ID `0x40` |
| 4 | Packet sequence `0x00–0xFF` |
| 5 | Payload length `0x04` |
| 6–7 | Distance mm, little-endian |
| 8–9 | Signal strength, little-endian |
| 10 | Checksum = sum of bytes 0–9 (low 8 bits) |

**I2C:** 7-bit address **0x51 per the PDF manual, 0x31 per the corvon.tech web spec** —
probe both. Reg 0x00 = device ID (0x32), 0x01/0x02 = distance mm LE, 0x03/0x04 =
strength LE. Up to 400 kHz. Pin mapping also conflicts: PDF pin 1 = SCL / pin 2 = SDA;
web spec pin 1 = SDA / pin 2 = SCL. In UART mode both agree pin 1 = TX, pin 2 = RX.

---

## Root-cause picture

Two independent faults stack to explain every observation:

1. **Bench (PC) side:** the USB-TTL run was wired straight-through per handoff §4
   (CV50 Rx→adapter RX, CV50 Tx→adapter TX). On a CP2102, TXD is the adapter's
   *output*, so this wiring reads 0 bytes from a healthy sensor **and** blocks the web
   tool's handshake — and the tool was additionally used with the wrong connect order
   (sensor already powered before the port was opened).
2. **Sensor side:** the saved protocol setting is unknown (shipped state). If it is
   I2C, MODBUS, MSP, or PX4, the FC-side UART tests (HR-LINK/`RNGFND1_TYPE` sweep at
   SERIAL7_PROTOCOL=9) would all fail even with perfect wiring; if it is any
   UART-family setting, the FC I2C scan on bus 1 would find nothing even with perfect
   wiring. Either way, one setting kills the *other* interface by design.

Secondary open item: external I2C bus 1 (PB6/PB7) has no internal pull-up flags in the
hwdef and has never ACKed *any* device — if the I2C path is ever needed, prove the bus
first (pull-up voltage test below).

---

## Bench plan for HAL2026 (stop at first success)

**Step 1 — rewire the adapter (crossed):**

| CV50 wire | → CP2102 |
|-----------|----------|
| Black (GND) | GND |
| Red (5V) | 5V / VBUS |
| Green (Tx/SCL) | **RXD** |
| Yellow (Rx/SDA) | **TXD** |

**Step 2 — adapter self-test (once):** disconnect the CV50 data wires, short adapter
TXD↔RXD, run `python3 cv50_bench_uart.py --loopback`. Proves adapter + tooling.

**Step 3 — sniff:** wire per Step 1, run `python3 cv50_bench_uart.py --sniff`.
The script now parses HR-LINK frames and prints live distance in mm. If distance
appears → sensor is in UART streaming mode; skip to Step 5.

**Step 4 — web tool, correct order (the decisive test):**
1. Close every other program using the port (no Python running).
2. Unplug the CV50 from the adapter (at minimum its red 5V wire).
3. Chrome → https://tof.corvon.tech → Connect → pick the CP2102 COM port.
4. **Now** plug the CV50 back in. Auto-detect fires within ~100 ms of boot.
5. When it connects: set **Protocol = APM (ArduPilot)**, **Orientation = Down**,
   Save changes, then re-plug the sensor wires (required after protocol changes).
6. Confirm live distance + CRC errors 0 in the tool's verification panel.

If the tool still never detects it with correct wiring and correct order (try one
TX/RX swap regardless — labels lie): the unit is likely faulty → Step 7.

**Step 5 — back on the FC (after APM protocol is saved):**
APM mode is described as MAVLink on the tool page. Configure:
- `SERIAL7_PROTOCOL = 2` (MAVLink2; try 1 if no joy), `SERIAL7_BAUD = 115`
- `RNGFND1_TYPE = 10` (MAVLink), `RNGFND1_ORIENT = 25`, `RNGFND1_MAX` ≈ 45 m
- If instead you saved plain **UART** protocol: `SERIAL7_PROTOCOL = 28` (Scripting) and
  use `cv50_hrlink_serial.lua`, or keep the web-tool APM route — simpler.
- Power-cycle, check Mission Planner → Status → `rangefinder1`.

**Step 6 — I2C path (only if you *want* I2C instead of UART):**
1. In the web tool set Protocol = I2C first — otherwise the sensor will never ACK.
2. Meter the GPS-plug SDA/SCL pins with FC powered, sensor disconnected: ~3.3 V both
   = pull-ups present; floating = add 4.7 kΩ to 3.3 V or abandon I2C.
3. Wire yellow→BL, green→WH; probe **both 0x51 and 0x31**; if no ACK, swap
   yellow↔green once (the PDF and web spec disagree on which wire is SDA, so the
   swap is a required test, not a guess), power-cycle, re-run `cv50_i2c_probe.lua`.

**Step 7 — escalate to Corvon** (draft below), including the serial number and a note
that the web tool with correct hot-plug order never detects the unit.

---

## Corvon support email draft

> **To:** aeroselfie-support@corvon.tech
> **Subject:** CV50 not detected by tof.corvon.tech (correct hot-plug order) and silent on UART/I2C
>
> Hello,
>
> My CV50 (S/N [label]) powers up (905 nm emitter visible on camera) but:
>
> - tof.corvon.tech never detects it: CP2102 adapter, port opened first, sensor
>   hot-plugged after, TX/RX crossed (and swap also tried), 115200.
> - No HR-LINK `DF 32` frames on a direct PC sniff at 9600–921600 baud.
> - No I2C ACK at 0x51 (or anywhere in a full 7-bit scan) on the flight controller's
>   external bus; the same scanner sees the FC's onboard compass/baro, and SDA/SCL
>   swap was tried.
>
> Questions:
> 1. What protocol setting does the CV50 ship with from the factory?
> 2. Is there any way to reset/force the protocol without the web tool detecting it?
> 3. Your manual (pin 1 = SCL, address 0x51) and your web spec (pin 1 = SDA, address
>    0x31) contradict each other on the I2C pinout and address — which is correct?
> 4. If the unit is faulty, how do I arrange a replacement? Purchased [date/source].
>
> Thanks, Mike

---

## Reference: remotely verified board facts

CORVON743V1 hwdef (ArduPilot master): `I2C_ORDER I2C2 I2C1` → Lua bus 1 = I2C1 =
PB6 (SCL)/PB7 (SDA) external connector, **no PULLUP flags**; `SERIAL_ORDER` confirms
SERIAL7 = UART8 ("User"). Prior agent's bus-1 and SERIAL7 conclusions were correct.
The CV50 is sold as the AERO SELFIE **R50-C**; an English manual is on
aeroselfie.myshopify.com → Manual Books.

# CV50 Rangefinder — Fable 5 Diagnosis & Bench Plan

**Date:** 2026-07-07
**Input:** `HANDOFF_CV50_Claude_Fable5.md` (Grok session) + remote research
**Scope:** Analysis only — this session runs in a cloud container with no access to HAL's
serial ports or the bench hardware. Every test below runs on HAL.

---

## The one-line verdict

Every UART test so far has been **passive listening**, and the handoff's own USB-TTL
wiring table is **straight-through, not crossed** — so the 0-byte results to date do
not yet prove the sensor is dead or mode-locked. Two cheap bench fixes (swap TX/RX at
the adapter, then let the web config tool talk to it) are the most likely path to a
working sensor. The I2C path has a separate unproven dependency: **bus 1 pull-ups**.

---

## Finding 1 — The USB-TTL bench was almost certainly wired straight-through (HIGH confidence)

Handoff §4 table:

| CV50 wire | → CP2102 |
|-----------|----------|
| Yellow (CV50 **Rx**) | **RX** on adapter |
| Green (CV50 **Tx**) | **TX** on adapter |

On essentially every CP2102 breakout, the pin labeled **TXD is the adapter's output**.
Wired as tabulated, CV50 TX drives the adapter's TX (two outputs fighting) and the
adapter's RX listens to CV50 RX (two inputs, silent). **0 bytes is guaranteed with this
wiring even if the sensor is streaming perfectly.** The same error would make
`tof.corvon.tech` show "awaiting device" forever, because the tool's handshake never
reaches the sensor's RX pin.

The handoff's §10.A.3 swap suggestion was never confirmed done. **Do it first.**

Correct bench wiring:

| CV50 wire | → CP2102 |
|-----------|----------|
| Black (GND) | GND |
| Red (5V) | 5V / VBUS (not 3.3V!) |
| Green (CV50 **Tx**) | **RXD** on adapter |
| Yellow (CV50 **Rx**) | **TXD** on adapter |

## Finding 2 — Sensor boot on the bench was never verified (MEDIUM)

Laser-visible-on-phone-camera was only recorded while powered from the FC Optical plug.
Some CP2102 breakouts expose only 3.3 V, or a "5V" pin that sags under the CV50's laser
load. **Before any sniff: point a phone camera at the CV50 on adapter power and confirm
the emitter glows.** No glow → no data, full stop; fix power first.

## Finding 3 — I2C bus 1 has never been proven alive (MEDIUM-HIGH)

Bus 0 finding the IST8310 + DPS310 proves the **Lua I2C API**, not the **external bus
hardware**. The CORVON743V1 hwdef assigns I2C1 to PB6/PB7 with **no internal PULLUP
flags** — the bus only works if the board carries physical pull-up resistors (unknown)
or the attached device provides them (CV50: unknown). A full-address-space scan
returning **zero** devices is exactly what a pull-up-less (floating) bus looks like.

Two-minute multimeter test: FC powered, CV50 **disconnected**, measure GPS-plug SDA and
SCL pins to GND. **~3.3 V on both** = pull-ups exist, bus is viable, keep debugging
wiring/address. **0 V / floating** = the scan can never succeed as-is; add 4.7 kΩ
pull-ups to 3.3 V or abandon the I2C path.

Also worth one try each (already suggested, never verified): SDA↔SCL swap; and if you
own any known-good I2C module (external compass, baro breakout), plug it into the GPS
plug SDA/SCL and re-scan — if a known-good device also fails to ACK, the bus or plug
pin assumption (BL=SDA / WH=SCL) is wrong, not the CV50.

## Finding 4 — The sensor may need configuration before it streams (MEDIUM)

The handoff notes the Corvon tool must "set APM protocol + downward orientation before
ArduPilot UART use." That implies the factory mode is **not** the APM streaming mode
ArduPilot's `RNGFND1_TYPE` sweep was hunting for, and may not stream at all until
configured or queried. This chains with Finding 1: fix the crossing → the web tool can
finally handshake → set APM mode → FC UART path comes alive.

**Action for the remote session:** upload `reference/CV50.pdf` into the chat. I can
read PDFs and will extract the exact HR-LINK command bytes (mode switch, output enable,
I2C address) and turn them into an active-probe script — every script so far only
listened; none ever *sent* anything to the sensor.

---

## Ordered bench plan (stop at first success)

**Phase 0 — 2 minutes, no software**
1. CV50 on CP2102 power only: phone-camera check for laser glow.
2. Continuity-check all 4 wires end-to-end; confirm which color lands on CV50 pin 2
   (SCL/TX) vs pin 3 (SDA/RX) at the sensor connector, not by cable-color faith.

**Phase 1 — UART bench (decisive)**
3. Loopback self-test: disconnect CV50, short adapter TXD↔RXD, run
   `cv50_bench_uart.py --loopback`. Proves adapter + tooling.
4. Wire per Finding 1 (crossed). Run `cv50_bench_uart.py --sniff`.
5. Still silent → `cv50_bench_uart.py --probe` (transmits wake/query candidates).
6. With crossed wiring, retry https://tof.corvon.tech in Chrome. If it connects:
   set **APM protocol + downward**, then move the sensor back to FC SERIAL7
   (`SERIAL7_PROTOCOL=9`, `SERIAL7_BAUD=115`, `RNGFND1_TYPE` per manual — re-check
   the PDF for which type APM mode emulates) and test in Mission Planner.

**Phase 2 — I2C (only if Phase 1 dead)**
7. Pull-up voltage test (Finding 3). Floating → add 4.7 kΩ pull-ups or stop.
8. One SDA↔SCL swap, power-cycle (not reboot), re-run `cv50_i2c_probe.lua`.
9. Optional: known-good I2C device on the GPS plug to validate the bus itself.

**Phase 3 — Corvon escalation** (template below). If they confirm a hardware fault or
an unswitchable mode, invoke handoff §10.D: fly the maiden without the rangefinder.

---

## Corvon support email draft

> **To:** aeroselfie-support@corvon.tech
> **Subject:** CV50 emits no UART data and no I2C ACK — factory mode / mode-switch procedure?
>
> Hello,
>
> I have a CV50 (bought [date/source]) wired to a CORVON743V1 (AERO SELFIE H743,
> ArduCopter 4.7.0-beta7) and it produces no data on either interface:
>
> - **UART:** 0 bytes at 115200 (and 9600/57600/921600) on FC SERIAL7/UART8 *and*
>   directly to a PC via CP2102 USB-TTL with TX/RX crossed both ways. No HR-LINK
>   `DF 32` frames. https://tof.corvon.tech stays at "awaiting device."
> - **I2C:** SDA/SCL on the FC GPS-plug I2C bus; a full 7-bit address scan via
>   ArduPilot Lua finds zero devices (the same scan finds the onboard IST8310 and
>   DPS310 on the internal bus, so the scanner works). Tried both 0x51 and 0x31.
> - The unit powers up and the emitter is visible on a phone camera, so it is not dead.
>
> Questions:
> 1. What is the factory default interface/mode — UART streaming, UART query, or I2C?
> 2. Does the CV50 select UART vs I2C from pin states at power-up, or is it a stored
>    setting? What is the exact procedure to force UART/APM mode?
> 3. What is the correct I2C address — 0x31 or 0x51 — and does the module include
>    internal I2C pull-up resistors?
> 4. Does the CV50 stream HR-LINK frames unprompted, or only after an enable command?
>    If the latter, please send the command bytes.
>
> Serial number: [from label]. I can run any test you suggest on the bench.
>
> Thanks, Mike

---

## What this session verified remotely

- **CORVON743V1 hwdef** (`hwdef.dat`, ArduPilot master): `I2C_ORDER I2C2 I2C1` — bus 1
  = I2C1 = PB6 (SCL) / PB7 (SDA), external connector; **no PULLUP flags** on either
  I2C bus. `SERIAL_ORDER OTG1 USART1 USART2 USART3 UART4 USART6 UART7 UART8` →
  SERIAL7 = UART8 ("User" UART). The prior agent's bus-1 correction and the
  SERIAL7/UART8 assumption are both **confirmed correct**.
- The CV50 is sold as the **AERO SELFIE R50-C** (50 m, ±2 cm, 50 Hz dToF); an English
  manual exists at aeroselfie.myshopify.com → Manual Books (vendor sites are blocked
  from this container; download it on HAL and add to `reference/`).

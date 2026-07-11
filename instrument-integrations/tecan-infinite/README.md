# tecan-infinite

A Tecan Infinite plate reader driven from the same Raspberry Pi as the STAR, through
PyLabRobot. This is the QC endpoint of the epigenome workflow: it reads a plate, it does
not move liquid or heat anything. The STAR builds and cleans a library plate, the reader
tells you whether the plate is what the protocol says it is.

Two instruments are in scope, both in the Infinite 200 family:

- **Infinite 200 PRO**, monochromator optics, absorbance + fluorescence + luminescence.
- **Infinite Nano+** (F Nano+ / M Nano+), the smaller sibling on the same chassis and the
  same USB identity. The F Nano+ is filter-based rather than monochromator-based, so which
  measurement modes and which wavelength commands it accepts is not assumed here. It is a
  thing to confirm on the actual unit, not to take on faith.

PyLabRobot ships a backend for the 200 PRO: `pylabrobot.tecan.infinite.TecanInfinite200Pro`.
That backend is the starting point for both readers. Everything below is derived either
from that backend's source, which is checkable off-instrument and is marked as such, or
from what still has to be settled at the bench, which is marked as not-yet-run. As of
2026-07-11 the reader is identified over USB and the backend loads on the Pi; nothing has
been moved or read yet.

## Status

First contact on 2026-07-11: the reader was plugged into the Pi, identified over USB
read-only, and the backend brought up in an isolated venv. Everything below the USB probe
is still a plan and a script ladder, in the same shape the ODTC work took before its first
live session, kept honest by the same rule: a row stays marked written-or-planned until a
run on the reader moves it. The read-only rungs earned their rows; nothing that moves the
stage has run.

| What | Result |
| --- | --- |
| `tecan_offline_checks.py`, 24 checks (backend shape + 96-well geometry), no device | passed on the Pi, 2026-07-11 |
| USB probe: `0c47:8007` on the Pi's bus, identified, kernel driver state | passed on the instrument (read-only): "TECAN AUSTRIA BIO", bus 3 / addr 3, no kernel driver, endpoints 0x81 / 0x02 |
| Bring-up: `setup()`, `INIT FORCE`, capability queries return | written, not yet run |
| Tray open / close, drawer cycle timed | written, not yet run |
| Absorbance read of a known plate at a fixed wavelength | written, not yet run |
| Rhodamine-B fluorescence ladder read | written, not yet run |
| `counts_per_mm` confirmed against this unit's plate map | not started |
| STAR iSWAP handoff into the open tray | not started |

The read-only first-contact evidence is captured in
[`connection_verified.html`](connection_verified.html): the raw `lsusb` and probe output,
the device identity, and the honest note that no motion has happened.
[`tecan-bench-app.html`](tecan-bench-app.html) is the operator page: the one-time Pi
setup and the whole ladder as copy-to-Pi commands, in the house style, alongside the read
settings and these same status rows.

## The physical link is USB, not the network

This is the split the parent `instrument-integrations/README.md` draws. The ODTC is on the
network with its own state machine; the reader is on the end of a USB cable, like the STAR.

The backend opens the reader as a USB device, vendor `0x0C47` (Tecan), product `0x8007`,
through pyusb / libusb. The Pi needs the USB extra (`pip install pylabrobot[usb]`, which
pulls `pyusb` and `libusb-package`).

On the Pi this lives in its **own** venv, `~/tecan-lab/env`, not the STAR's `star-lab/env`.
Two reasons, both learned on 2026-07-11: the Tecan backend only exists on the fork branch
that carries `pylabrobot/tecan/` (the fork's `main` does not have it, so a plain
`git clone` of the fork misses the module - check out that branch), and installing the
fork into the STAR's venv would swap PyLabRobot under the validated STAR and ODTC
workflows. An isolated venv keeps them untouched. Run the ladder against it with the
`run_on_pi.sh` `VENV` override:

```bash
VENV=/home/lab/tecan-lab/env ./run_on_pi.sh tecan-infinite/tecan_offline_checks.py
```

Two USB facts decide whether the first `setup()` even reaches the firmware, and both are
Linux-host, not PyLabRobot:

- **A kernel driver may hold the interface.** If Linux has bound a driver to the reader,
  libusb cannot claim it until that driver is detached. `01_tecan_probe_usb.py` reports
  whether a driver is attached, read-only, before anything tries to claim the device.
- **Non-root access needs a udev rule.** Without one, `setup()` fails with a permission
  error rather than a missing-device error. A rule for `0c47:8007` granting the run user
  access is a one-time bench step. The specific rule text is a setup note, not committed
  here.

Only one process may hold the USB interface at a time. A second client claiming the same
reader produces the same `Resource busy` failure the STAR shows when two clients race for
its cable. Whatever else is true, do not run two of these scripts at once.

Because the link is USB, there is no address to pass. The parent `run_on_pi.sh` forwards
`ODTC_IP` for the cycler; the reader ignores it and needs nothing in its place.

## The command protocol, read off the backend

The reader speaks framed ASCII commands over the USB bulk endpoints. The backend
(`pylabrobot/tecan/infinite/driver.py`) is the source for all of this:

- **`setup()` moves the instrument.** It sends `QQ`, then `INIT FORCE`, which homes the
  stage. Connecting the reader is not a passive act; the carriage travels. This is why
  bring-up asks for `--confirm i-am-watching`, and why the read-only USB probe is a
  separate, earlier rung that never calls `setup()`.
- **The tray is `ABSOLUTE MTP,OUT` / `ABSOLUTE MTP,IN`, each followed by `BY#T5000`.**
  The `BY#T` is the settle. `reader.loading_tray.open()` and `.close()` wrap them.
- **A read is a per-row raster.** For each row the driver sends `MODE`, `KEYLOCK ON`, the
  `EXCITATION` / `READS` / `TIME` configuration for the mode, positions the stage with
  `ABSOLUTE MTP,X=..,Y=..`, then `SCANX start,end,count`, and decodes the binary
  measurement frames the reader streams back. It closes a run with `TERMINATE`, the
  `CHECK MTP.STEPLOSS` / `CHECK ABS.STEPLOSS` step-loss checks, `KEYLOCK OFF`, and
  `ABSOLUTE MTP,IN`.
- **Absorbance is an OD, computed from a calibration packet the reader sends inside the
  scan.** If that packet is not seen, the read raises rather than returning a wrong
  number. This is the reader's own reference measurement, not something this repo supplies.

The reader is meant to be used at the device level, not by hand-sending commands:

```python
from pylabrobot.tecan.infinite import TecanInfinite200Pro

reader = TecanInfinite200Pro(name="infinite")
await reader.setup()                                  # QQ, INIT FORCE  (homes the stage)
results = await reader.absorbance.read(plate=my_plate, wavelength=600)
await reader.stop()
```

## The scripts, in the order you run them

Each rung does strictly more than the one above it. Do not skip. Only the first two are
safe to run without watching the instrument, and only the first touches nothing at all.

| Script | Touches | What it settles |
| --- | --- | --- |
| `tecan_offline_checks.py` | nothing, no device | Does the backend import in the Pi's venv, and does the geometry math hold |
| `01_tecan_probe_usb.py` | nothing, read-only | Is `0c47:8007` on the bus, is a kernel driver attached, are the endpoints there |
| `02_tecan_bringup.py` | the stage | Does `setup()` home and initialize, do the capability queries answer |
| `03_tecan_tray.py` | the drawer motor | How long a tray cycle takes, and that OUT then IN round-trips |
| `04_tecan_read_absorbance.py` | stage, optics | Will it read a plate and return a full OD matrix |
| `05_tecan_read_rhodamine.py` | stage, optics | Will it read the Rhodamine-B ladder in fluorescence |

`tecan_offline_checks.py` needs no reader and no network. Run it before every live session
and after every PyLabRobot change, exactly as with the ODTC. Its job is to fail loudly, in
the venv, if the fork on the Pi does not carry `pylabrobot.tecan.infinite`, or if the
backend's shape has drifted from what these scripts assume.

`01_tecan_probe_usb.py` imports the standard library first and falls back to `lsusb`. It
works when the venv does not, and it never calls `setup()`, so it cannot move the stage.

```bash
./run_on_pi.sh tecan-infinite/tecan_offline_checks.py
./run_on_pi.sh tecan-infinite/01_tecan_probe_usb.py
```

## What is known before anything is plugged in

These come from the backend source and are asserted in `tecan_offline_checks.py`, so a
PyLabRobot change that alters any of them surfaces as a failing check rather than a
surprise at the bench:

1. **Absorbance wavelength is clamped to 230-1000 nm; fluorescence ex/em to 230-850 nm.**
   A request outside the range raises before any command is sent.
2. **Defaults.** 25 flashes per well. Absorbance bandwidth auto-selects, 9 nm above 315 nm
   and 5 nm at or below it, unless overridden. Fluorescence defaults to `integration_us=20`,
   `gain=100` (of 0-255), `focal_height=20.0` mm.
3. **Absorbance reports no temperature.** `AbsorbanceResult.temperature` is `None` from this
   backend. If a run needs plate temperature it has to come from elsewhere.
4. **The scan is patient, then it gives up.** Each row waits up to `max_row_wait_s` (300 s)
   for its measurements; a stalled USB read raises after that rather than hanging forever.
5. **Geometry is `counts_per_mm`, defaulting to 1000 in x, y, z.** The well-to-stage map
   takes each well's center and the plate's `size_y` and converts to stage counts. The
   offline check runs this map over a real 96-well plate definition and asserts the visit
   order is serpentine and the coordinates are integers in range, all with no device.

## What has to be settled on the instrument

The unknowns, in the order the ladder resolves them:

- **Does libusb on the Pi enumerate and claim `0c47:8007`** past the kernel driver and the
  permissions. (`01`, then `02`.)
- **Does `INIT FORCE` complete cleanly on this unit, and do the capability queries answer.**
  The absorbance path asks the reader for `#BEAM DIAMETER` and falls back to 700 if it does
  not reply; whether the fallback is ever used is a bench observation. (`02`.)
- **Is `counts_per_mm` right for this reader.** The 1000/1000/1000 default is PyLabRobot's,
  not this unit's. If it is wrong the raster lands between wells or off the plate. This is
  the reader's equivalent of the STAR's hand-tuned deck geometry, and it is tuned the same
  way, one small step at a time, against the physical plate. (`04`.)
- **Fluorescence focal height and gain for the Rhodamine ladder.** `focal_height=20.0` mm
  and `gain=100` are defaults, not tuned values. The right focal height depends on the
  plate and the meniscus; the right gain is whatever keeps the brightest ladder rung off
  saturation. Both are `05` arguments, both are flagged in the script. (`05`.)
- **Nano+ versus 200 PRO.** The same backend is the starting point, but the F Nano+ is
  filter-based. Which modes it exposes and whether it accepts the monochromator-style
  `EXCITATION`/`EMISSION` wavelength commands is confirmed on the unit, not assumed.

## Where the QC values come from

The reader's first real job is the Rhodamine-B ladder that `plr-epigenome` already uses as
its readiness check: a known dilution series the STAR dispenses, read back to confirm the
liquid handler is placing the volumes it claims. The ladder's concentrations and its
expected signal shape live with that ladder in `plr-epigenome`, not here; this repo only
drives the reader and reports what it measured. `05_tecan_read_rhodamine.py` prints the
per-well matrix and, if given the ladder layout, checks monotonicity, but the pass/fail
threshold is the ladder's to own.

The excitation and emission wavelengths, the gain, and the focal height are reader settings,
not protocol values, and they are exposed as arguments with defaults marked for tuning. They
are deliberately not stated here as validated numbers, because none has been validated on
this reader yet. Rhodamine B's absorption and emission maxima are the physical starting
points for those arguments; the exact settings are converged at the bench against the actual
ladder and written back here once a run confirms them.

## Safety

Everything `hamilton-star/README.md` says still applies, plus:

- **`setup()` homes the stage.** Connecting the reader moves it. `--confirm i-am-watching`
  is required by everything from bring-up down. The read-only USB probe is the only rung
  that runs without it, because it never calls `setup()`.
- **The reader does not grip plates.** Seat the plate on the tray by hand and confirm it is
  flat before closing. A plate that is not seated can foul the drawer or the stage.
- **This is a lower-energy instrument than the ODTC.** A stock reader has no heaters; if the
  incubation option is fitted, it does, and that is an instrument fact to check, not to
  assume either way. The moving parts are the drawer and the stage.
- **One process, one USB interface.** Two clients on the same reader is the `Resource busy`
  failure. After any failure, let the current process exit before rerunning; do not start a
  second one to "check".

## Next

Run the ladder, bottom rung first, and move each status row as a real run earns it. Tune
`counts_per_mm` and the fluorescence focal height against the physical plate. Then the STAR
iSWAP handoff into the open tray, which is the same unsolved problem as the ODTC handoff:
the tray's position in deck coordinates has to be measured, not guessed, before the arm is
allowed to place a plate into it.

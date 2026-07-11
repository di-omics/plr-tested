"""
05_tecan_read_rhodamine.py - read the Rhodamine-B ladder in fluorescence.

Fifth rung, and the reader's first real job: read back the Rhodamine-B dilution ladder the
STAR dispensed, the readiness check plr-epigenome already uses to confirm the liquid
handler is placing the volumes it claims. Requires setup() (homes the stage) and moves the
drawer, so it is gated on --confirm i-am-watching.

The ladder's concentrations and its pass/fail threshold live with the ladder in
plr-epigenome. This script only drives the reader and reports what it measured. If you tell
it which column holds the ladder, it also checks that the signal is monotonic down that
column, which is a coarse "did the dilution series come out as a series" check, not the
QC verdict.

The excitation and emission wavelengths, the gain, and the focal height are reader
settings, not protocol values. The defaults below are physical starting points for
Rhodamine B, not numbers validated on this reader. Tune them at the bench (gain so the
brightest rung is off saturation, focal height for the plate and meniscus) and write the
converged settings back here once a run confirms them.

    python 05_tecan_read_rhodamine.py --confirm i-am-watching
    python 05_tecan_read_rhodamine.py --confirm i-am-watching --gain 80 --ladder-col 1
    ./run_on_pi.sh tecan-infinite/05_tecan_read_rhodamine.py --confirm i-am-watching
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import tecan_compat


def print_matrix(data) -> None:
    rows = "ABCDEFGH"
    print("     " + "".join(f"{c + 1:>9}" for c in range(len(data[0]))))
    for r, row in enumerate(data):
        label = rows[r] if r < len(rows) else str(r)
        cells = "".join(("      .  " if v is None else f"{v:9.0f}") for v in row)
        print(f"  {label}  {cells}")


def check_monotonic(data, col_1based: int) -> None:
    col = col_1based - 1
    values = [row[col] for row in data if row[col] is not None]
    if len(values) < 2:
        print(f"  ladder check: column {col_1based} has too few readings to judge.")
        return
    down = all(a >= b for a, b in zip(values, values[1:]))
    up = all(a <= b for a, b in zip(values, values[1:]))
    if down or up:
        print(f"  ladder check: column {col_1based} is monotonic ({'decreasing' if down else 'increasing'}).")
    else:
        print(f"  ladder check: column {col_1based} is NOT monotonic -- inspect the dilution series.")


async def run(args) -> int:
    from pylabrobot.tecan.infinite import TecanInfiniteFluorescenceParams

    reader = tecan_compat.build_reader()
    plate = tecan_compat.build_read_plate()
    params = TecanInfiniteFluorescenceParams(gain=args.gain, integration_us=args.integration_us)

    print("connecting (the stage will home)...")
    await reader.setup()
    try:
        print("opening drawer to seat the plate...")
        await reader.loading_tray.open()
        print(f"  seat the Rhodamine ladder plate flat. Closing in {args.seat_seconds:.0f} s, hands clear.")
        await asyncio.sleep(args.seat_seconds)
        await reader.loading_tray.close()

        print(
            f"reading fluorescence ex {args.ex} nm / em {args.em} nm, "
            f"focal {args.focal_height} mm, gain {args.gain}..."
        )
        results = await reader.fluorescence.read(
            plate=plate,
            excitation_wavelength=args.ex,
            emission_wavelength=args.em,
            focal_height=args.focal_height,
            backend_params=params,
        )
        result = results[0]
        print()
        print_matrix(result.data)
        print()
        if args.ladder_col:
            check_monotonic(result.data, args.ladder_col)
        print("fluorescence read ok. The QC verdict is plr-epigenome's; this is the raw signal.")
        return 0
    finally:
        print("disconnecting...")
        await reader.stop()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm", default="")
    # Reader settings, not protocol values. Defaults are Rhodamine-B starting points, not
    # numbers validated on this reader. See the module docstring.
    parser.add_argument("--ex", type=int, default=535, help="excitation nm (start ~535, tune)")
    parser.add_argument("--em", type=int, default=595, help="emission nm (start ~595, tune)")
    parser.add_argument("--gain", type=int, default=100, help="PMT gain 0-255 (tune off saturation)")
    parser.add_argument("--focal-height", type=float, default=20.0, help="mm (tune per plate)")
    parser.add_argument("--integration-us", type=int, default=20)
    parser.add_argument("--seat-seconds", type=float, default=15.0)
    parser.add_argument("--ladder-col", type=int, default=0, help="1-based column of the ladder, for the monotonicity check")
    args = parser.parse_args()
    tecan_compat.require_confirm(args.confirm, "Fluorescence read (setup homes the stage, drawer and stage move)")
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())

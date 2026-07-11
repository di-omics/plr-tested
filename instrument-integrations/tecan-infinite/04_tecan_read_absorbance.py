"""
04_tecan_read_absorbance.py - read a plate in absorbance and print the OD matrix.

Fourth rung: stage plus optics. Requires setup() (homes the stage) and moves the drawer,
so it is gated on --confirm i-am-watching.

This is where counts_per_mm gets judged. If the default 1000/1000/1000 geometry is wrong
for this reader, the raster lands between wells and the matrix comes back wrong or empty,
even though every command "succeeded". Read a plate you know (a blank, or a dye you can
predict) and compare. Geometry is tuned by hand against the physical plate, the same way
the STAR deck is, and any tuned counts_per_mm gets written back into the reader
construction once a run confirms it.

    python 04_tecan_read_absorbance.py --confirm i-am-watching
    python 04_tecan_read_absorbance.py --confirm i-am-watching --wavelength 562 --seat-seconds 20
    ./run_on_pi.sh tecan-infinite/04_tecan_read_absorbance.py --confirm i-am-watching
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import tecan_compat


def print_matrix(data) -> None:
    rows = "ABCDEFGH"
    header = "     " + "".join(f"{c + 1:>8}" for c in range(len(data[0])))
    print(header)
    for r, row in enumerate(data):
        label = rows[r] if r < len(rows) else str(r)
        cells = "".join(("     .  " if v is None else f"{v:8.3f}") for v in row)
        print(f"  {label}  {cells}")


async def run(wavelength: int, seat_seconds: float) -> int:
    reader = tecan_compat.build_reader()
    plate = tecan_compat.build_read_plate()
    print("connecting (the stage will home)...")
    await reader.setup()
    try:
        print("opening drawer to seat the plate...")
        await reader.loading_tray.open()
        print(f"  seat the plate flat on the tray. Closing in {seat_seconds:.0f} s, keep hands clear.")
        await asyncio.sleep(seat_seconds)
        await reader.loading_tray.close()

        print(f"reading absorbance at {wavelength} nm across all 96 wells...")
        results = await reader.absorbance.read(plate=plate, wavelength=wavelength)
        result = results[0]
        print(f"  wavelength {result.wavelength} nm")
        print()
        print_matrix(result.data)
        print()
        print("absorbance read ok. Sanity-check the matrix against what the plate should be.")
        return 0
    finally:
        print("disconnecting...")
        await reader.stop()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm", default="")
    parser.add_argument("--wavelength", type=int, default=600, help="nm, 230-1000")
    parser.add_argument("--seat-seconds", type=float, default=15.0)
    args = parser.parse_args()
    tecan_compat.require_confirm(args.confirm, "Absorbance read (setup homes the stage, drawer and stage move)")
    return asyncio.run(run(args.wavelength, args.seat_seconds))


if __name__ == "__main__":
    sys.exit(main())

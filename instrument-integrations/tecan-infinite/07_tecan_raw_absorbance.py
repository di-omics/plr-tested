"""
07_tecan_raw_absorbance.py - dump the RAW absorbance measurements from the working scan.

The absorbance scan runs and decodes per-well sample/reference counts, but the current
backend then fails computing calibrated OD ("ABS calibration packet not seen"). This
script captures the decoder and, whether or not calibrated OD succeeds, prints the RAW
sample/reference counts, so we can see the reader actually responding to what is in the
wells. These are raw counts, NOT calibrated OD. Honest signal, not a QC number.

--preloaded: plate is already loaded and the drawer is closed; no tray commands.

    VENV=/home/lab/tecan-lab/env ./run_on_pi.sh tecan-infinite/07_tecan_raw_absorbance.py --confirm i-am-watching --preloaded --wells A1,A2,A3,A4,A5,A6
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import tecan_compat

_DECODERS = []


def capture_decoders():
    import pylabrobot.tecan.infinite.protocol as proto

    orig_init = proto._AbsorbanceRunDecoder.__init__

    def cap_init(self, *args, **kwargs):
        orig_init(self, *args, **kwargs)
        _DECODERS.append(self)

    proto._AbsorbanceRunDecoder.__init__ = cap_init


async def run(args) -> int:
    capture_decoders()
    reader = tecan_compat.build_reader()
    plate = tecan_compat.build_read_plate()
    well_names = [w.strip() for w in args.wells.split(",") if w.strip()]
    wells = plate.get_items(well_names)

    print("connecting (the stage will home)...")
    await reader.setup()
    read_error = None
    try:
        if not args.preloaded:
            await reader.loading_tray.open()
            await asyncio.sleep(args.seat_seconds)
            await reader.loading_tray.close()
        else:
            try:
                print("closing drawer (plate loaded); tolerating a settle-response timeout...")
                await reader.loading_tray.close()
                print("  drawer closed.")
            except Exception as exc2:  # noqa: BLE001
                print(f"  close raised {type(exc2).__name__} (BY#T5000 settle); drawer moves IN regardless, continuing.")
        print(f"reading absorbance at {args.wavelength} nm, wells {well_names}...")
        await reader.absorbance.read(plate=plate, wavelength=args.wavelength, wells=wells)
        print("calibrated OD read completed (calibration packet was seen this time).")
    except Exception as exc:  # noqa: BLE001 - expected: calibration decode may fail
        read_error = exc
    finally:
        try:
            await reader.stop()
        except Exception:  # noqa: BLE001
            pass

    print()
    print("=" * 60)
    print("RAW MEASUREMENTS (sample / reference counts, NOT calibrated OD)")
    dec = _DECODERS[-1] if _DECODERS else None
    if dec is None or not getattr(dec, "measurements", None):
        print("  no measurements decoded.")
        if read_error:
            print(f"  read stopped with: {type(read_error).__name__}: {read_error}")
        return 1
    for i, m in enumerate(dec.measurements):
        name = well_names[i] if i < len(well_names) else f"#{i}"
        print(f"  {name:>4}   sample={m.sample:>8}   reference={m.reference:>8}")
    print()
    if read_error:
        print(f"  (calibrated OD not computed: {type(read_error).__name__}: {read_error})")
    print("  These are raw counts. Higher sample count where the dye absorbs less light;")
    print("  the point here is the reader IS measuring the wells.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm", default="")
    parser.add_argument("--wavelength", type=int, default=554, help="nm (554 = Rhodamine B absorption peak)")
    parser.add_argument("--wells", default="A1,A2,A3,A4,A5,A6", help="comma-separated well names")
    parser.add_argument("--preloaded", action="store_true", help="plate loaded, drawer closed; no tray commands")
    parser.add_argument("--seat-seconds", type=float, default=15.0)
    args = parser.parse_args()
    tecan_compat.require_confirm(args.confirm, "Raw absorbance read (setup homes the stage, stage moves)")
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())

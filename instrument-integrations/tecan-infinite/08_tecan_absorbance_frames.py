"""
08_tecan_absorbance_frames.py - log every binary frame during an absorbance scan.

Diagnoses why `read_absorbance` raises "ABS calibration packet not seen". The decoder
identifies a calibration packet by length (payload_len >= 22 and (payload_len-4) % 18 == 0)
and a data packet by (payload_len >= 14 and (payload_len-4) % 10 == 0). This wraps the
decoder's feed_bin to record EVERY binary frame's payload_len (consumed or not), so we can
see whether the reader sends a calibration-length frame at all, or one of an unexpected
length that the predicate misses.

--preloaded: plate loaded, drawer already closed (tolerant close). No dye needed for this.

    VENV=/home/lab/tecan-lab/env ./run_on_pi.sh tecan-infinite/08_tecan_absorbance_frames.py --confirm i-am-watching --preloaded --wells A1
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import tecan_compat

FRAMES = []  # (payload_len, blob_len, hex_preview, is_cal_len, is_data_len)


def instrument_decoder():
    import pylabrobot.tecan.infinite.protocol as proto

    orig_feed_bin = proto._MeasurementDecoder.feed_bin

    def logged_feed_bin(self, payload_len, blob):
        FRAMES.append(
            (
                payload_len,
                len(blob),
                blob[:40].hex(),
                proto._is_abs_calibration_len(payload_len),
                proto._is_abs_data_len(payload_len),
            )
        )
        return orig_feed_bin(self, payload_len, blob)

    proto._MeasurementDecoder.feed_bin = logged_feed_bin


async def run(args) -> int:
    instrument_decoder()
    reader = tecan_compat.build_reader()
    plate = tecan_compat.build_read_plate()
    wells = plate.get_items([w.strip() for w in args.wells.split(",") if w.strip()])

    print("connecting (the stage will home)...")
    await reader.setup()
    err = None
    try:
        if args.preloaded:
            try:
                await reader.loading_tray.close()
            except Exception as e:  # noqa: BLE001
                print(f"  (tolerated close error: {type(e).__name__})")
        else:
            await reader.loading_tray.open()
            await asyncio.sleep(args.seat_seconds)
            await reader.loading_tray.close()
        print(f"reading absorbance at {args.wavelength} nm, wells {args.wells}...")
        await reader.absorbance.read(plate=plate, wavelength=args.wavelength, wells=wells)
        print("read completed (calibration was seen).")
    except Exception as exc:  # noqa: BLE001
        err = exc
    finally:
        try:
            await reader.stop()
        except Exception:  # noqa: BLE001
            pass

    print()
    print("=" * 66)
    print(f"BINARY FRAMES SEEN: {len(FRAMES)}")
    lens = {}
    for pl, bl, hexp, is_cal, is_data in FRAMES:
        lens.setdefault(pl, 0)
        lens[pl] += 1
    print("  payload_len -> count  [cal-len? data-len?]")
    for pl in sorted(lens):
        import pylabrobot.tecan.infinite.protocol as proto
        print(f"    {pl:>4} -> {lens[pl]:>3}   cal={proto._is_abs_calibration_len(pl)}  data={proto._is_abs_data_len(pl)}")
    print()
    cal_frames = [f for f in FRAMES if f[3]]
    unmatched = [f for f in FRAMES if not f[3] and not f[4]]
    print(f"  calibration-length frames (4+18N): {len(cal_frames)}")
    print(f"  frames matching NEITHER cal nor data length: {len(unmatched)}")
    if unmatched:
        print("  unmatched frames (candidates for a miss-sized calibration packet):")
        for pl, bl, hexp, _c, _d in unmatched[:12]:
            print(f"    len={pl:>4}  {hexp}")
    print()
    if cal_frames:
        print("VERDICT: a calibration-length frame WAS present -> parser/decode bug (fix _decode_abs_calibration).")
    elif unmatched:
        print("VERDICT: no cal-length frame, but odd-length frames exist -> the cal packet is a different")
        print("         length on this unit; adjust _is_abs_calibration_len to match one of the lengths above.")
    else:
        print("VERDICT: the reader sent NO calibration packet at all -> likely RATIO LABELS rejected on this")
        print("         unit (like #BEAM DIAMETER). Fix: compute OD from a blank/reference read, or enable it.")
    if err:
        print(f"\n(read raised: {type(err).__name__}: {err})")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm", default="")
    parser.add_argument("--wavelength", type=int, default=554)
    parser.add_argument("--wells", default="A1")
    parser.add_argument("--preloaded", action="store_true")
    parser.add_argument("--seat-seconds", type=float, default=15.0)
    args = parser.parse_args()
    tecan_compat.require_confirm(args.confirm, "Absorbance frame capture (setup homes the stage, stage moves)")
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())

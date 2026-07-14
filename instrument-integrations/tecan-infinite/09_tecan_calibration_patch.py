"""
09_tecan_calibration_patch.py - attempt the calibration-frame fix and read real OD.

The reader sends a 20-byte calibration frame; the stock `_is_abs_calibration_len` requires
payload_len >= 22 (form 4 + 18*N), so it drops it and read_absorbance raises "ABS calibration
packet not seen". This monkeypatches the length check and the decoder to also accept the
20-byte form (hypothesis: 2-byte header + one 18-byte item, i.e. no 2-byte `ex` field), then
runs read_absorbance and prints BOTH the decoded calibration fields and the OD, so we can
judge honestly whether the decode is right (a clear well should read OD ~ 0).

This is a runtime patch, not a committed backend change. If the OD is sensible we port it
into pylabrobot upstream; if it is garbage the byte layout needs proper RE.

    VENV=/home/lab/tecan-lab/env ./run_on_pi.sh tecan-infinite/09_tecan_calibration_patch.py --confirm i-am-watching --preloaded --wells A1
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import tecan_compat


def patch_calibration():
    import pylabrobot.tecan.infinite.protocol as proto

    orig_is_cal = proto._is_abs_calibration_len

    def patched_is_cal(payload_len):
        if orig_is_cal(payload_len):
            return True
        return payload_len >= 20 and (payload_len - 2) % 18 == 0  # 20-byte (2-byte header) form

    def patched_decode(payload_len, blob):
        split = proto._split_payload_and_trailer(payload_len, blob)
        if split is None:
            return None
        payload, _ = split
        if len(payload) >= 22 and (len(payload) - 4) % 18 == 0:
            has_ex = True
        elif len(payload) >= 20 and (len(payload) - 2) % 18 == 0:
            has_ex = False
        else:
            return None
        r = proto.Reader(payload, little_endian=False)
        r.raw_bytes(2)
        ex = r.u16() if has_ex else 0
        items = []
        while r.has_remaining():
            items.append(
                proto._AbsorbanceCalibrationItem(
                    ticker_overflows=r.u32(),
                    ticker_counter=r.u16(),
                    meas_gain=r.u16(),
                    meas_dark=r.u16(),
                    meas_bright=r.u16(),
                    ref_gain=r.u16(),
                    ref_dark=r.u16(),
                    ref_bright=r.u16(),
                )
            )
        for it in items:
            print(
                f"  [patch] cal item: meas_dark={it.meas_dark} meas_bright={it.meas_bright} "
                f"ref_dark={it.ref_dark} ref_bright={it.ref_bright} meas_gain={it.meas_gain} ref_gain={it.ref_gain}"
            )
        return proto._AbsorbanceCalibration(ex=ex, items=items)

    proto._is_abs_calibration_len = patched_is_cal
    proto._decode_abs_calibration = patched_decode
    print("[patch] calibration length check + decoder patched to accept the 20-byte frame")


async def run(args) -> int:
    patch_calibration()
    reader = tecan_compat.build_reader()
    plate = tecan_compat.build_read_plate()
    wells = plate.get_items([w.strip() for w in args.wells.split(",") if w.strip()])

    print("connecting (the stage will home)...")
    await reader.setup()
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
        results = await reader.absorbance.read(plate=plate, wavelength=args.wavelength, wells=wells)
        print()
        print("=" * 60)
        print("OD RESULT (with the patched calibration decode):")
        print(f"  {results[0].data}")
        print()
        print("Sanity: a CLEAR/blank well should be OD ~ 0; strong dye should be positive.")
        print("If these look sane, the decode is right and we port it upstream.")
        return 0
    except Exception:  # noqa: BLE001
        print()
        import traceback
        traceback.print_exc()
        return 1
    finally:
        try:
            await reader.stop()
        except Exception:  # noqa: BLE001
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm", default="")
    parser.add_argument("--wavelength", type=int, default=554)
    parser.add_argument("--wells", default="A1")
    parser.add_argument("--preloaded", action="store_true")
    parser.add_argument("--seat-seconds", type=float, default=15.0)
    args = parser.parse_args()
    tecan_compat.require_confirm(args.confirm, "Patched absorbance read (setup homes the stage, stage moves)")
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())

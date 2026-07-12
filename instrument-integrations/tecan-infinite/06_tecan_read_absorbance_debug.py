"""
06_tecan_read_absorbance_debug.py - instrumented absorbance read to diagnose the
SCANX timeout (PyLabRobot issue #1093).

Same read as 04, but it logs every command and every raw USB read, tags the reads
that happen after SCANX (where #1093 hangs), fails fast with a short per-row timeout
instead of waiting the full 300 s, and prints exactly where it got to. Read a tiny well
set so the run is short.

This does NOT assume the read works. It is a diagnostic: if the reader streams no
measurement bytes after SCANX, it says so, which is the concrete finding to report on
issue #1093.

Motion: setup() homes the stage and the drawer moves, so --confirm i-am-watching.

    VENV=/home/lab/tecan-lab/env ./run_on_pi.sh tecan-infinite/06_tecan_read_absorbance_debug.py --confirm i-am-watching
    python 06_tecan_read_absorbance_debug.py --confirm i-am-watching --wells A1,B1 --row-timeout 25
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
import traceback

import tecan_compat

t0 = time.monotonic()


def _stamp() -> float:
    return time.monotonic() - t0


def instrument(driver, state) -> None:
    """Wrap the driver's command and raw-read paths to print a timed trace."""
    orig_send = driver.send_command
    orig_read = driver.io.read

    async def send_wrap(command, *args, **kwargs):
        state["last_cmd"] = command
        if command.startswith("SCANX"):
            state["scan"] = True
            state["scan_reads"] = 0
            state["scan_bytes"] = 0
            print(f"[{_stamp():7.2f}s] >> {command}   (SCANX sent; now watching for measurement frames)")
        else:
            print(f"[{_stamp():7.2f}s] >> {command}")
        return await orig_send(command, *args, **kwargs)

    async def read_wrap(*args, **kwargs):
        size = kwargs.get("size")
        try:
            data = await orig_read(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - we want to see the failure in-line
            tag = " (post-SCANX)" if state.get("scan") else ""
            print(f"[{_stamp():7.2f}s] io.read size={size} RAISED {type(exc).__name__}: {exc}{tag}")
            raise
        if state.get("scan"):
            state["scan_reads"] += 1
            state["scan_bytes"] += len(data)
        tag = " (post-SCANX)" if state.get("scan") else ""
        preview = data[:24].hex()
        print(f"[{_stamp():7.2f}s] io.read size={size} got={len(data)}B {preview}{tag}")
        return data

    driver.send_command = send_wrap
    driver.io.read = read_wrap


async def run(args) -> int:
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(relativeCreated)8.0fms %(name)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )

    reader = tecan_compat.build_reader()
    plate = tecan_compat.build_read_plate()
    driver = reader.driver
    driver._max_row_wait_s = args.row_timeout  # fail fast instead of the 300 s default
    state = {"scan": False, "last_cmd": None, "scan_reads": 0, "scan_bytes": 0}
    instrument(driver, state)

    print(f"[{_stamp():7.2f}s] connecting (INIT FORCE homes the stage)...")
    await reader.setup()
    read_ok = False
    result = None
    try:
        await reader.loading_tray.open()
        print(f"[{_stamp():7.2f}s] drawer open; seat the plate. Closing in {args.seat_seconds:.0f} s.")
        await asyncio.sleep(args.seat_seconds)
        await reader.loading_tray.close()

        well_names = [w.strip() for w in args.wells.split(",") if w.strip()]
        wells = plate.get_items(well_names)
        print(f"[{_stamp():7.2f}s] reading absorbance at {args.wavelength} nm, wells {well_names}...")
        result = await reader.absorbance.read(plate=plate, wavelength=args.wavelength, wells=wells)
        read_ok = True
    except Exception:  # noqa: BLE001 - diagnostic: capture and characterize the failure
        print()
        print("=" * 68)
        print("READ DID NOT COMPLETE. Traceback:")
        traceback.print_exc()
    finally:
        try:
            await reader.stop()
        except Exception:  # noqa: BLE001
            pass

    print()
    print("=" * 68)
    print("DIAGNOSIS")
    print(f"  last command sent : {state['last_cmd']}")
    print(f"  SCANX reached     : {state['scan']}")
    print(f"  reads after SCANX : {state['scan_reads']}")
    print(f"  bytes after SCANX : {state['scan_bytes']}")
    if read_ok:
        print("  result            : READ OK")
        if result:
            print(f"    wavelength {result[0].wavelength} nm, data {result[0].data}")
    elif state["scan"] and state["scan_bytes"] == 0:
        print("  result            : SCANX was sent but the reader returned NO measurement bytes.")
        print("                      This is the issue #1093 hang: the scan trigger or the")
        print("                      measurement-frame stream, not the connection. Report this,")
        print("                      the last command, and the trace above on the issue.")
    else:
        print("  result            : failed before completing the scan (see traceback).")
    return 0 if read_ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm", default="")
    parser.add_argument("--wavelength", type=int, default=600)
    parser.add_argument("--wells", default="A1,B1", help="comma-separated well names")
    parser.add_argument("--row-timeout", type=float, default=25.0, help="seconds per row before giving up")
    parser.add_argument("--seat-seconds", type=float, default=12.0)
    args = parser.parse_args()
    tecan_compat.require_confirm(args.confirm, "Debug absorbance read (setup homes the stage, drawer and stage move)")
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())

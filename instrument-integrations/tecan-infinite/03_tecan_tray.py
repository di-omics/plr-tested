"""
03_tecan_tray.py - open and close the drawer, and time the cycle.

Third rung. Requires setup() first (homes the stage), so it is gated on
--confirm i-am-watching.

What it settles:
  - That OUT then IN round-trips cleanly on this unit.
  - How long a drawer cycle takes, which is what a future STAR iSWAP handoff has to wait
    on before it can place or take a plate.

By default it opens, holds for a few seconds so you can seat or remove a plate by hand,
then closes. Nothing is read.

    python 03_tecan_tray.py --confirm i-am-watching
    python 03_tecan_tray.py --confirm i-am-watching --hold 15
    ./run_on_pi.sh tecan-infinite/03_tecan_tray.py --confirm i-am-watching
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time

import tecan_compat


async def run(hold_s: float, leave_open: bool) -> int:
    reader = tecan_compat.build_reader()
    print("connecting (the stage will home)...")
    await reader.setup()

    if leave_open:
        t0 = time.monotonic()
        print("opening drawer...")
        await reader.loading_tray.open()
        print(f"  open took {time.monotonic() - t0:.1f} s")
        print()
        print("Drawer is OPEN and will STAY open (no auto-close). Load your plate flat, A1 to the notch.")
        print("Releasing the USB so nothing holds the reader. Run the read when the plate is in.")
        await reader.driver.io.stop()  # release USB WITHOUT the cleanup close, so the tray stays out
        return 0

    try:
        t0 = time.monotonic()
        print("opening drawer...")
        await reader.loading_tray.open()
        t_open = time.monotonic() - t0
        print(f"  open took {t_open:.1f} s")

        print(f"holding open {hold_s:.0f} s (seat or remove the plate now, keep hands clear on close)...")
        await asyncio.sleep(hold_s)

        t1 = time.monotonic()
        print("closing drawer...")
        await reader.loading_tray.close()
        t_close = time.monotonic() - t1
        print(f"  close took {t_close:.1f} s")

        print()
        print(f"tray cycle ok: open {t_open:.1f} s, close {t_close:.1f} s.")
        return 0
    finally:
        print("disconnecting...")
        await reader.stop()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm", default="")
    parser.add_argument("--hold", type=float, default=8.0, help="seconds to hold the drawer open")
    parser.add_argument("--leave-open", action="store_true", help="open the drawer and leave it open (no auto-close), to load a plate")
    args = parser.parse_args()
    tecan_compat.require_confirm(args.confirm, "Tray cycle (setup homes the stage, the drawer moves)")
    return asyncio.run(run(args.hold, args.leave_open))


if __name__ == "__main__":
    sys.exit(main())

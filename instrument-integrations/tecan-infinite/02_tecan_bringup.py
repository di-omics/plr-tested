"""
02_tecan_bringup.py - connect, initialize, read back what the reader tells us.

This is the first rung that moves the instrument. setup() sends QQ then INIT FORCE, which
homes the stage, so it is gated on --confirm i-am-watching.

What it settles:
  - Does libusb claim 0c47:8007 on this host (past the kernel driver and permissions).
  - Does INIT FORCE complete without error on this unit.
  - Do the per-mode capability queries answer. The absorbance path asks the reader for
    #BEAM DIAMETER and falls back to 700 if it does not reply; this prints whatever the
    reader actually returned, so you can see whether the fallback is in play.

It does not open the tray or take a reading. It connects, reports, and disconnects.

    python 02_tecan_bringup.py --confirm i-am-watching
    ./run_on_pi.sh tecan-infinite/02_tecan_bringup.py --confirm i-am-watching
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import tecan_compat


async def run() -> int:
    reader = tecan_compat.build_reader()
    print("connecting (QQ, INIT FORCE -- the stage will home)...")
    await reader.setup()
    try:
        driver = reader.driver
        print("connected.")
        print(f"  driver ready: {driver._ready}")
        caps = driver._mode_capabilities
        if caps:
            print("  mode capabilities the reader answered:")
            for mode, entries in caps.items():
                for cmd, val in entries.items():
                    print(f"    {mode} {cmd} -> {val}")
        else:
            print("  no mode capabilities returned (queries timed out; defaults will be used).")
        print()
        print("bring-up ok. Nothing was opened or read.")
        return 0
    finally:
        print("disconnecting...")
        await reader.stop()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    tecan_compat.require_confirm(args.confirm, "Bring-up (setup homes the stage)")
    return asyncio.run(run())


if __name__ == "__main__":
    sys.exit(main())

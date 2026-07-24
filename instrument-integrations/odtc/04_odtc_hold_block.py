"""
04_odtc_hold_block.py - hold the block and lid at a constant temperature. THIS HEATS.

This is an instrument utility, not a biological method. The operator must supply
the block set point, lid set point, and hold duration explicitly from an approved
local method. No wet-method values are embedded here.

Why this does not call set_block_temperature()
----------------------------------------------
Two reasons, both of which will burn you.

  1. Each of set_block_temperature() and set_lid_temperature() runs its own ODTC
     "pre-method", and a pre-method spends 7 to 10 minutes evenly pre-warming block
     and lid before it reports done. Calling both is a 15 to 20 minute wait for a
     thing that should take one pre-method.

  2. set_block_temperature() uses a backend fallback lid target unless a lid target
     is already stashed on the backend instance:

         lid = self._lid_target_temp if self._lid_target_temp is not None else 105.0

     That fallback is not an operator-approved method value. Calling the setters
     separately can therefore apply the wrong lid target over a loaded plate.

odtc_compat.hold_block_and_lid() sets both targets and runs one pre-method.

--dynamic-time
--------------
The backend's DynamicPreMethodDuration flag. True lets the pre-method finish as soon
as it is evenly warmed (roughly 7 minutes). False holds for a full 10 minutes before
proceeding. Default True.

Usage
-----
    python 04_odtc_hold_block.py --ip $ODTC_IP \
        --block-c <approved> --lid-c <approved> --minutes <approved> \
        --confirm i-am-watching
"""

import argparse
import asyncio
import os
import sys
import time

from odtc_compat import (
    BLOCK_MAX_C,
    BLOCK_MIN_C,
    DOCUMENTED_MAX_LID_C,
    PRE_METHOD_TIMEOUT_S,
    OdtcError,
    block_temperature,
    format_sensors,
    hold_block_and_lid,
    make_odtc,
    read_sensors,
    setup_odtc,
)

CONFIRM_PHRASE = "i-am-watching"
POLL_INTERVAL_S = 15.0


async def watch(odtc, minutes, target_block_c):
    """Poll the sensors while the block holds, so the trace is on the terminal."""
    deadline = time.time() + minutes * 60.0
    print(f"\nholding for {minutes:.1f} min, polling every {POLL_INTERVAL_S:.0f} s")
    while time.time() < deadline:
        sensors = await read_sensors(odtc)
        block = block_temperature(sensors)
        drift = block - target_block_c
        remaining = (deadline - time.time()) / 60.0
        print(f"  t-{remaining:5.1f} min  block {block:6.2f} C "
              f"({drift:+.2f} from target)  {format_sensors(sensors)}")
        await asyncio.sleep(min(POLL_INTERVAL_S, max(deadline - time.time(), 0.1)))


async def main():
    parser = argparse.ArgumentParser(
        description="Hold the ODTC block and lid at a constant temperature. This heats."
    )
    parser.add_argument("--ip", default=os.environ.get("ODTC_IP"))
    parser.add_argument("--client-ip", default=None)
    parser.add_argument("--block-c", type=float, required=True,
                        help=f"block set point, {BLOCK_MIN_C} to {BLOCK_MAX_C} C")
    parser.add_argument("--lid-c", type=float, required=True,
                        help="operator-approved lid set point")
    parser.add_argument("--minutes", type=float, required=True,
                        help="operator-approved hold duration after the pre-method finishes")
    parser.add_argument("--dynamic-time", action="store_true", default=True)
    parser.add_argument("--no-dynamic-time", dest="dynamic_time", action="store_false")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()

    if not args.ip:
        parser.error("no ODTC address. Pass --ip or set ODTC_IP.")
    if not BLOCK_MIN_C <= args.block_c <= BLOCK_MAX_C:
        parser.error(f"--block-c {args.block_c} is outside the ODTC range "
                     f"{BLOCK_MIN_C} to {BLOCK_MAX_C} C")
    if args.lid_c > DOCUMENTED_MAX_LID_C:
        print(f"[warn] lid {args.lid_c} C exceeds the highest documented lid temperature "
              f"({DOCUMENTED_MAX_LID_C} C).")
    if args.confirm != CONFIRM_PHRASE:
        parser.error(f"this heats the block to {args.block_c} C and the lid to "
                     f"{args.lid_c} C. Pass --confirm {CONFIRM_PHRASE}")

    odtc = make_odtc(ip=args.ip, client_ip=args.client_ip)
    await setup_odtc(odtc)

    try:
        sensors = await read_sensors(odtc)
        print(f"before: {format_sensors(sensors)}")

        print(f"\nrunning one pre-method: block {args.block_c} C, lid {args.lid_c} C")
        print("the ODTC pre-warms block and lid evenly before reporting done.")
        print(f"expect 7 to 10 minutes. timeout is {PRE_METHOD_TIMEOUT_S / 60:.0f} min.")
        started = time.time()
        await hold_block_and_lid(odtc, block_c=args.block_c, lid_c=args.lid_c,
                                 dynamic_time=args.dynamic_time)
        print(f"pre-method finished in {(time.time() - started) / 60.0:.1f} min")

        sensors = await read_sensors(odtc)
        print(f"at set point: {format_sensors(sensors)}")
        print(f"block is {block_temperature(sensors):.2f} C, target {args.block_c} C")

        if args.minutes > 0:
            await watch(odtc, args.minutes, args.block_c)

        print("\nstopping the method. The block will drift back toward ambient.")
        await odtc.deactivate_block()
        return 0

    except asyncio.TimeoutError:
        print(f"\nFAILED: pre-method did not finish within "
              f"{PRE_METHOD_TIMEOUT_S / 60:.0f} min.", file=sys.stderr)
        print("The block may still be heating. Check it before rerunning.", file=sys.stderr)
        return 1
    except OdtcError as exc:
        print(f"\nFAILED: {exc}", file=sys.stderr)
        return 1
    finally:
        await odtc.stop()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

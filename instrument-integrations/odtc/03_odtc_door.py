"""
03_odtc_door.py - open and close the ODTC's motorized door. THIS MOVES HARDWARE.

The door is the plate access. It is what the iSWAP will eventually reach through, so
it is the first ODTC motion to characterize: how long it takes, whether it reports
completion, and whether the opening is where the arm expects it.

Safety
------
  - Run 02_odtc_bringup.py first. If the event round trip is broken, OpenDoor is an
    asynchronous command whose completion callback never arrives, and the script will
    sit there while the door does whatever it does.
  - Nothing may be in the door's path. No plate on the block, no iSWAP gripper
    anywhere near the ODTC, no hand.
  - Motion requires --confirm i-am-watching. Default mode is `status`, which reads.

Naming
------
PLR calls these open_lid()/close_lid() because ThermocyclerBackend is written around
machines whose heated lid is the thing that opens. On the ODTC they are OpenDoor and
CloseDoor: the door is a separate motorized plate hatch, and the heated lid is a
static plate the block presses against. Opening the door does not open a heated lid.
Do not read the PLR method name as a statement about the hardware.

Unimplemented on this backend
-----------------------------
get_lid_open() and get_lid_status() both raise NotImplementedError. There is no way to
ask the ODTC whether its door is open through this backend, which is why `status` reads
temperatures and device state instead, and why the operator confirms door position with
their eyes.

Usage
-----
    python 03_odtc_door.py --ip $ODTC_IP                                   # read only
    python 03_odtc_door.py --ip $ODTC_IP --mode open  --confirm i-am-watching
    python 03_odtc_door.py --ip $ODTC_IP --mode close --confirm i-am-watching
    python 03_odtc_door.py --ip $ODTC_IP --mode cycle --confirm i-am-watching
"""

import argparse
import asyncio
import os
import sys
import time

from odtc_compat import (
    OdtcError,
    format_sensors,
    get_status,
    make_odtc,
    read_sensors,
    setup_odtc,
)

# A door movement is an asynchronous SiLA command. It completes when the mechanism
# finishes, so this is a mechanical timeout, not a network one.
DOOR_TIMEOUT_S = 120.0

CONFIRM_PHRASE = "i-am-watching"


async def show_status(odtc, timeout):
    _, state = await get_status(odtc, timeout=timeout)
    sensors = await read_sensors(odtc, timeout=timeout)
    print(f"state: {state!r}")
    print(f"temps: {format_sensors(sensors)}")


async def move_door(odtc, action, timeout):
    verb = "opening" if action == "open" else "closing"
    print(f"{verb} door...")
    started = time.time()
    if action == "open":
        await asyncio.wait_for(odtc.open_lid(), timeout=timeout)
    else:
        await asyncio.wait_for(odtc.close_lid(), timeout=timeout)
    print(f"done in {time.time() - started:.1f} s "
          f"(record this: the iSWAP handoff has to wait it out)")


async def main():
    parser = argparse.ArgumentParser(
        description="Open/close the ODTC door. Motion requires --confirm."
    )
    parser.add_argument("--ip", default=os.environ.get("ODTC_IP"))
    parser.add_argument("--client-ip", default=None)
    parser.add_argument("--mode", choices=["status", "open", "close", "cycle"],
                        default="status",
                        help="status reads and moves nothing (default)")
    parser.add_argument("--timeout", type=float, default=DOOR_TIMEOUT_S)
    parser.add_argument("--confirm", default="",
                        help=f"required for any mode but `status`: {CONFIRM_PHRASE}")
    args = parser.parse_args()

    if not args.ip:
        parser.error("no ODTC address. Pass --ip or set ODTC_IP.")

    moves = args.mode != "status"
    if moves and args.confirm != CONFIRM_PHRASE:
        parser.error(
            f"--mode {args.mode} moves the door. Clear its path, then pass "
            f"--confirm {CONFIRM_PHRASE}"
        )

    odtc = make_odtc(ip=args.ip, client_ip=args.client_ip)
    await setup_odtc(odtc)

    try:
        print("--- before ---")
        await show_status(odtc, args.timeout)

        if args.mode == "open":
            await move_door(odtc, "open", args.timeout)
        elif args.mode == "close":
            await move_door(odtc, "close", args.timeout)
        elif args.mode == "cycle":
            await move_door(odtc, "open", args.timeout)
            await move_door(odtc, "close", args.timeout)

        if moves:
            print("\n--- after ---")
            await show_status(odtc, args.timeout)
            print("\nConfirm the door position with your eyes. This backend cannot report")
            print("it: get_lid_open() and get_lid_status() raise NotImplementedError.")
        return 0

    except asyncio.TimeoutError:
        print(f"\nFAILED: door command did not complete within {args.timeout:.0f} s.",
              file=sys.stderr)
        print("Do not power cycle while the mechanism is mid-travel. Look at it first.",
              file=sys.stderr)
        return 1
    except OdtcError as exc:
        print(f"\nFAILED: {exc}", file=sys.stderr)
        return 1
    finally:
        await odtc.stop()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

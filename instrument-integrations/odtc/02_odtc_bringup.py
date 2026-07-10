"""
02_odtc_bringup.py - connect to the ODTC through PyLabRobot. No motion. No heating.

The ODTC analogue of test_star_no_autoload.py: prove the driver talks to the machine
and that we can read it, before anything moves or gets hot.

What it does
------------
  1. Builds a PLR Thermocycler on ExperimentalODTCBackend.
  2. Calls setup(), which sends Reset (registering this process's HTTP event receiver
     with the device) and then Initialize.
  3. Reads GetStatus and every temperature sensor.
  4. Stops cleanly.

The door does not move. The block is not heated. Initialize is a firmware handshake,
not a mechanical homing cycle, but it is still a command that changes device state,
which is why 01_odtc_probe_raw.py exists to be run first.

Two things this script insists on that PLR does not
---------------------------------------------------
  - setup() calls _reset_and_initialize(), which swallows every exception and prints
    "Warning during ODTC initialization: ...". So setup() can appear to succeed while
    the device never registered our event receiver. Every asynchronous command would
    then hang forever. Here, a failed sensor read is a failed bring-up.
  - get_sensor_data() returns {} on any parse error, and get_block_current_temperature()
    turns that into 0.0 C. We read through odtc_compat.read_sensors(), which raises.

Usage
-----
    python 02_odtc_bringup.py --ip 169.254.1.50
    python 02_odtc_bringup.py --ip 169.254.1.50 --client-ip 169.254.1.1

--client-ip matters on starpi, which has two interfaces: wlan0 on the lab network and
eth0 facing the ODTC. PLR picks the source address by asking the kernel for the route
to the ODTC, which is right as long as the routing table is right. Pass it explicitly
if you want to be sure.
"""

import argparse
import asyncio
import os
import sys

from odtc_compat import (
    DEFAULT_SILA_TIMEOUT_S,
    OdtcError,
    block_temperature,
    format_sensors,
    get_status,
    import_plr,
    local_ip_toward,
    make_odtc,
    read_sensors,
    setup_odtc,
)

IDLE_STATES = ("idle", "standby")


async def main():
    parser = argparse.ArgumentParser(
        description="Connect to an Inheco ODTC through PyLabRobot. No motion, no heating."
    )
    parser.add_argument("--ip", default=os.environ.get("ODTC_IP"),
                        help="ODTC address. Defaults to $ODTC_IP.")
    parser.add_argument("--client-ip", default=None,
                        help="address the ODTC should send events back to. "
                             "Default: whatever the kernel's route to the ODTC picks.")
    parser.add_argument("--timeout", type=float, default=DEFAULT_SILA_TIMEOUT_S)
    args = parser.parse_args()

    if not args.ip:
        parser.error("no ODTC address. Pass --ip or set ODTC_IP.")

    plr = import_plr()
    print(f"PyLabRobot layout: {plr.layout}")

    client_ip = args.client_ip or local_ip_toward(args.ip)
    print(f"ODTC:           {args.ip}:8080")
    print(f"event receiver: {client_ip}:<ephemeral port, chosen at setup>")
    print("the ODTC must be able to open a TCP connection back to that address.\n")

    odtc = make_odtc(ip=args.ip, client_ip=args.client_ip)

    print("setup(): sending Reset (registers our event receiver) then Initialize...")
    print("Initialize homes the door mechanism. Keep the door path clear.")
    await setup_odtc(odtc)
    port = odtc.backend._sila_interface.bound_port
    print(f"event receiver is listening on {client_ip}:{port}")

    try:
        print("\n--- GetStatus ---")
        response, state = await get_status(odtc, timeout=args.timeout)
        print(f"state: {state!r}")
        if state is None:
            print("[warn] no 'state' in the response. _wait_for_idle() cannot work, so")
            print("       set_block_temperature()/set_lid_temperature() will time out.")
            print(f"       raw: {response!r}")
        elif state not in IDLE_STATES:
            print(f"[warn] device is not idle. _run_pre_method() waits for one of "
                  f"{IDLE_STATES}.")

        print("\n--- ReadActualTemperature ---")
        # This is the real proof of life. It is an asynchronous SiLA command, so a
        # successful read means the full round trip works: our POST reached the ODTC,
        # and the ODTC's ResponseEvent reached our HTTP server. If Reset silently
        # failed, this is where we find out, as a timeout rather than as a fake 0.0 C.
        sensors = await read_sensors(odtc, timeout=args.timeout)
        print(format_sensors(sensors))
        print(f"\nblock (Mount): {block_temperature(sensors):.2f} C")

        print("\nbring-up passed. The event round trip works in both directions.")
        return 0

    except OdtcError as exc:
        print(f"\nbring-up FAILED: {exc}", file=sys.stderr)
        print("\nIf that was a timeout, the POST was accepted but the ResponseEvent never",
              file=sys.stderr)
        print("came back. The ODTC cannot reach this host. Check firewall rules and that",
              file=sys.stderr)
        print(f"{client_ip}:{port} is reachable from the ODTC's subnet.", file=sys.stderr)
        return 1
    finally:
        await odtc.stop()
        print("connection closed.")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

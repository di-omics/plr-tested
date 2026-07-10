"""
05_odtc_run_protocol.py - run a thermal program on the ODTC. THIS HEATS.

Programs come from odtc_protocols.py, where every value is transcribed from
the kit user guide. Nothing thermal is defined in this file.

    wga        Table 1, DNA Amplification, lid 70 C    ~2.6 h
    dnaprep    Table 4, DNAPREP,           lid 105 C   ~10 min
    ferat      Table 5, FERAT,             lid 105 C   ~40 min
    ligation   page 16 IV.7, 20 C 15 min,  lid 50 C    ~15 min
    libamp     Table 8, LIB-AMP,           lid 105 C   ~15 min
    timecheck  hardware exercise, one 60 s step        ~1 min
    selftest   hardware exercise, 3 cycles             ~2 min

How a program runs on this firmware
-----------------------------------
Confirmed on the instrument, this ODTC will not run a cycling Method cold. ExecuteMethod
of a full profile is rejected with returnCode 11, "PreMethod or PostHeating is required",
unless a PreMethod has first brought the block to the profile's start conditions. So
this script does not call PyLabRobot's `run_protocol()` (which skips the pre-warm and
gets rejected). It calls `odtc_compat.run_cycling_method()`, which pre-warms, then runs,
then tolerates the NO_SDCARD warning (returnCode 12) this unit raises on every method.

ExecuteMethod's ResponseEvent fires on method *completion*, so the run blocks for the
whole program, pre-warm included. Long runs go detached on the Pi, per this repo's
safety rules, so a dropped SSH session cannot take the process down mid-program.

`timecheck` settled the `PlateauTime` unit: a 60 s step held the block at temperature
for about 56 to 60 seconds, so the durations in `odtc_protocols.py` are in seconds and
scaled correctly. Re-run it after a firmware change before trusting the long holds.

Not run_pcr_profile()
---------------------
`Thermocycler.run_pcr_profile()` is unusable with this backend: it calls
wait_for_lid(), which calls get_lid_status(), which raises NotImplementedError.

Usage
-----
    python 05_odtc_run_protocol.py --program timecheck --print-xml --dry
    python 05_odtc_run_protocol.py --program timecheck --ip $ODTC_IP --confirm i-am-watching
    python 05_odtc_run_protocol.py --program libamp --ip $ODTC_IP --confirm i-am-watching
"""

import argparse
import asyncio
import os
import sys
import time
import xml.dom.minidom

from odtc_compat import (
    OdtcError,
    describe_protocol,
    format_sensors,
    import_plr,
    make_dry_odtc,
    make_odtc,
    read_sensors,
    run_cycling_method,
    setup_odtc,
    validate_protocol,
)
from odtc_protocols import PROGRAMS, START_BLOCK_C_DEFAULT

CONFIRM_PHRASE = "i-am-watching"

START_BLOCK_C = START_BLOCK_C_DEFAULT


def render_method_xml(program, method_name):
    """Ask the real backend to generate the method XML, without a device.

    _generate_method_xml() is pure: it touches no socket. Building a backend against
    an unroutable address is enough to call it, and it means we review exactly the
    bytes the ODTC will be sent, not a reimplementation of them.
    """
    plr = import_plr()
    backend = plr.ExperimentalODTCBackend(ip="192.0.2.1", client_ip="192.0.2.2")
    xml_text, name = backend._generate_method_xml(
        program.protocol,
        program.block_max_volume_ul,
        START_BLOCK_C,
        program.lid_c,
        True,  # post_heating: hold the final temperature after the method ends
        method_name=method_name,
    )
    return xml.dom.minidom.parseString(xml_text).toprettyxml(indent="  ").strip(), name


async def run_dry(program):
    """Rehearse with the device-free chatterbox backend, per this repo's dry-run rule.

    ThermocyclerChatterboxBackend.run_protocol() takes only (protocol, block_max_volume).
    The ODTC keywords (start_lid_temperature, post_heating, ...) are not part of the
    abstract ThermocyclerBackend signature, so they are dropped here. The chatterbox
    therefore proves the stage/step structure, not the lid or the post-heating.
    """
    odtc = make_dry_odtc()
    await odtc.setup()  # chatterbox: no device, so no callback to wait on
    try:
        await odtc.run_protocol(protocol=program.protocol,
                               block_max_volume=program.block_max_volume_ul)
    finally:
        await odtc.stop()
    print("\ndry run complete. Note: the chatterbox ignores lid temperature and")
    print("post_heating. Only the stage and step structure was exercised.")


async def run_live(program, args):
    odtc = make_odtc(ip=args.ip, client_ip=args.client_ip)
    await setup_odtc(odtc)
    try:
        sensors = await read_sensors(odtc)
        print(f"before: {format_sensors(sensors)}\n")

        # run_cycling_method, not PLR's run_protocol. Confirmed on the instrument: this
        # firmware rejects ExecuteMethod of a cycling method with returnCode 11 ("PreMethod
        # or PostHeating is required") unless a PreMethod has first brought the block to
        # the start conditions. run_cycling_method does that pre-warm, then executes,
        # tolerating the NO_SDCARD warning this device raises on every method.
        print(f"pre-warming block to {START_BLOCK_C:.0f} C / lid {program.lid_c:.0f} C, then")
        print("running the method. ExecuteMethod's ResponseEvent fires on completion, so")
        print("this blocks for the whole program. Launch detached on the Pi for long runs.")
        started = time.time()
        name = await run_cycling_method(
            odtc,
            program.protocol,
            block_max_volume_ul=program.block_max_volume_ul,
            lid_c=program.lid_c,
            start_block_c=START_BLOCK_C,
            method_name=args.method_name,
        )
        elapsed = (time.time() - started) / 60.0
        print(f"\nmethod {name!r} completed in {elapsed:.1f} min (wall clock, "
              "including pre-warm and ramps).")

        sensors = await read_sensors(odtc)
        print(f"after: {format_sensors(sensors)}")
        print("\npost_heating is on, so the block is holding the final step temperature.")
        print("stop it with 04_odtc_hold_block.py deactivate, or backend.stop_method().")
        return 0
    finally:
        await odtc.stop()


async def main():
    parser = argparse.ArgumentParser(
        description="Run a the kit user guide thermal program on the ODTC. This heats."
    )
    parser.add_argument("--program", choices=sorted(PROGRAMS), required=True)
    parser.add_argument("--ip", default=os.environ.get("ODTC_IP"))
    parser.add_argument("--client-ip", default=None)
    parser.add_argument("--dry", action="store_true",
                        help="rehearse on the chatterbox backend. No device, no heat.")
    parser.add_argument("--print-xml", action="store_true",
                        help="print the exact ODTC method XML that would be uploaded")
    parser.add_argument("--method-name", default=None,
                        help="name of the method on the device. Default: PLR_Protocol_<timestamp>")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()

    program = PROGRAMS[args.program]

    print(f"program: {program.name}")
    print(f"source:  {program.source}")
    if not program.is_biology:
        print("         NOT a biology protocol. Temperatures and times have no")
        print("         biological meaning; this exists to exercise the hardware.")
    print()
    print(describe_protocol(program.protocol, program.block_max_volume_ul, program.lid_c))

    # Refuse anything the ODTC cannot physically do, before we upload it.
    validate_protocol(program.protocol, program.lid_c)

    if args.print_xml:
        xml_text, name = render_method_xml(program, args.method_name)
        print(f"\n--- method XML ({name}) ---")
        if args.method_name is None:
            print("(the method name is generated from the clock at upload time, so a live")
            print(" run will use a different one. Pass --method-name to pin it.)")
        print(xml_text)

    if args.dry:
        print("\n--- dry run (chatterbox backend) ---")
        await run_dry(program)
        return 0

    if not args.ip:
        parser.error("no ODTC address. Pass --ip, set ODTC_IP, or use --dry.")
    if args.confirm != CONFIRM_PHRASE:
        parser.error(
            f"this heats the block and runs {program.name} to completion. "
            f"Pass --confirm {CONFIRM_PHRASE}"
        )
    if program.name == "wga":
        print("\n[note] wga is a ~2.6 hour program. Launch it detached on the Pi so a")
        print("       dropped SSH session cannot kill it mid-run.")

    try:
        return await run_live(program, args)
    except asyncio.TimeoutError:
        print("\nFAILED: timed out. The method may still be running on the device.",
              file=sys.stderr)
        return 1
    except OdtcError as exc:
        print(f"\nFAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

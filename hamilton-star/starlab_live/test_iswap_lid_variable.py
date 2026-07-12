"""
iSWAP lid move between two slots (parametric).

di-omics / plr-tested
Moves a plate LID from a source slot onto a plate at a dest slot, e.g. to lid
the work plate before it goes to the ODTC thermocycler. Lid move only; no
thermal program.

Uses lh.move_lid, the proven high-level lid API (see move_lid_test.py). move_lid
computes the grip and the placement from the resource geometry, so start with
the offsets at 0 and TRUST it; only nudge in small steps for fine-tuning.

PATCH LOG
  2026-07-12  Created for the ODTC lidding step (generalized from the
              rail27pos1->rail35pos0 file after the source moved to rail35 pos4).
              LESSON: do NOT force pickup-z low. A -14 mm override at rail27 pos1
              drove the grippers into a lid-on-plate and tripped a Z-drive
              HardwareError ('drive locked or incremental sensor fault'). The
              move_lid computed grip (offset 0) is the correct lid-top height.
              Tune only in small steps and prefer going too HIGH (a clean miss)
              over too LOW (a Z crash).
  2026-07-12  CORRECTION + CONFIRMED. The move_lid Z-drive faults were NOT a
              tool problem, they were height: too-low pickup drove the grippers
              into the plate (Z-drive 'drive locked'), too-high missed the lid
              ('Plate not found'). The firmware command code tells which end:
              C0PP = pickup, C0PR = drop. Walked it in on the instrument to a clean run.
              CONFIRMED for the ODTC lidding move rail35 pos4 -> rail35 pos0:
                --src-rail 35 --src-pos 4 --dst-rail 35 --dst-pos 0 \
                --pickup-z-offset-mm 9 --drop-z-offset-mm 18
              Multiple clean SUCCESSes. NOTE the move carries the lid to pos0, so
              the lid must be re-seated on pos4 before each rep (else the next
              pickup is a 'Plate not found' on an empty slot). Offsets left at 0
              default; pass the confirmed values above (they are lid- and
              slot-specific, not a global default).

SAFETY
  - --mode deck assigns the deck and prints coordinates only. No movement.
    setup() re-homes the iSWAP, so a clean deck run also proves the arm is not
    jammed after a fault.
  - Any real move requires --mode move AND --confirm RUN_LID_MOVE.
  - A lid must be on the source slot; a plate must be on the dest slot. A person
    watches with a hand on the E-stop.
"""

import argparse
import asyncio

from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends import STARBackend
from pylabrobot.resources.hamilton import STARDeck
from pylabrobot.resources import PLT_CAR_L5AC_A00, Cor_96_wellplate_360ul_Fb

try:
    from pylabrobot.resources.coordinate import Coordinate
except ImportError:
    from pylabrobot.resources import Coordinate


def shifted(coord, dx=0.0, dy=0.0, dz=0.0):
    return Coordinate(coord.x + dx, coord.y + dy, coord.z + dz)


async def main():
    parser = argparse.ArgumentParser(
        description="iSWAP lid move between two slots (move_lid, tunable offsets)."
    )
    parser.add_argument("--mode", choices=["deck", "move"], default="deck")
    parser.add_argument("--src-rail", type=int, required=True)
    parser.add_argument("--src-pos", type=int, default=4)
    parser.add_argument("--dst-rail", type=int, required=True)
    parser.add_argument("--dst-pos", type=int, default=0)
    parser.add_argument("--pickup-x-offset-mm", type=float, default=0.0)
    parser.add_argument("--pickup-y-offset-mm", type=float, default=0.0)
    parser.add_argument(
        "--pickup-z-offset-mm", type=float, default=0.0,
        help="Trust move_lid (0). Nudge in SMALL steps; prefer too-high over too-low (Z crash).",
    )
    parser.add_argument("--drop-x-offset-mm", type=float, default=0.0)
    parser.add_argument("--drop-y-offset-mm", type=float, default=0.0)
    parser.add_argument("--drop-z-offset-mm", type=float, default=0.0)
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()

    if args.src_rail == args.dst_rail and args.src_pos == args.dst_pos:
        raise ValueError("source and dest are the same slot")
    for p in (args.src_pos, args.dst_pos):
        if p < 0 or p > 4:
            raise ValueError("positions must be 0..4 for PLT_CAR_L5AC_A00")

    print("Initializing STAR with skip_autoload=True...")
    lh = LiquidHandler(backend=STARBackend(), deck=STARDeck())
    await lh.setup(skip_autoload=True)

    try:
        if args.src_rail == args.dst_rail:
            print(f"Assigning one carrier at rail{args.src_rail} (src pos{args.src_pos}, dst pos{args.dst_pos})...")
            carrier = PLT_CAR_L5AC_A00(name=f"lid_carrier_rail{args.src_rail}")
            lh.deck.assign_child_resource(carrier, rails=args.src_rail)
            src_carrier = dst_carrier = carrier
        else:
            print(f"Assigning src carrier rail{args.src_rail} and dst carrier rail{args.dst_rail}...")
            src_carrier = PLT_CAR_L5AC_A00(name=f"lid_src_carrier_rail{args.src_rail}")
            dst_carrier = PLT_CAR_L5AC_A00(name=f"lid_dst_carrier_rail{args.dst_rail}")
            lh.deck.assign_child_resource(src_carrier, rails=args.src_rail)
            lh.deck.assign_child_resource(dst_carrier, rails=args.dst_rail)

        src_site = src_carrier[args.src_pos]
        src_site.location = shifted(
            src_site.location,
            dx=args.pickup_x_offset_mm,
            dy=args.pickup_y_offset_mm,
            dz=args.pickup_z_offset_mm,
        )
        src_plate = Cor_96_wellplate_360ul_Fb(name="lid_source_plate", with_lid=True)
        src_carrier[args.src_pos] = src_plate

        dst_site = dst_carrier[args.dst_pos]
        dst_site.location = shifted(
            dst_site.location,
            dx=args.drop_x_offset_mm,
            dy=args.drop_y_offset_mm,
            dz=args.drop_z_offset_mm,
        )
        dst_plate = Cor_96_wellplate_360ul_Fb(name="lid_dest_plate", with_lid=False)
        dst_carrier[args.dst_pos] = dst_plate

        lid_loc = src_plate.lid.get_absolute_location()
        dst_loc = dst_plate.get_absolute_location()

        print("")
        print(f"iSWAP LID move: rail{args.src_rail} pos{args.src_pos} -> rail{args.dst_rail} pos{args.dst_pos}")
        print(f"  source lid pickup:  abs {lid_loc}")
        print(f"  dest plate (drop):  abs {dst_loc}")
        print(f"  pickup offsets: x{args.pickup_x_offset_mm} y{args.pickup_y_offset_mm} z{args.pickup_z_offset_mm}")
        print(f"  drop offsets:   x{args.drop_x_offset_mm} y{args.drop_y_offset_mm} z{args.drop_z_offset_mm}")
        print("")

        if args.mode == "deck":
            print("Mode deck: assignment/coordinate print only. No movement.")
            return

        if args.confirm != "RUN_LID_MOVE":
            raise RuntimeError("Refusing to move. Add: --mode move --confirm RUN_LID_MOVE")

        print(f"MOVING LID with iSWAP: rail{args.src_rail} pos{args.src_pos} -> rail{args.dst_rail} pos{args.dst_pos}...")
        print("A lid must be on the source slot; a plate on the dest slot. Hand near E-stop.")
        async with lh.backend.slow_iswap():
            await lh.move_lid(src_plate.lid, dst_plate)
        print("SUCCESS: iSWAP lid move completed.")

    finally:
        print("Parking iSWAP / stopping...")
        try:
            await lh.backend.park_iswap()
        except Exception as e:
            print(f"park_iswap warning: {e!r}")
        await lh.stop()
        print("Done.")


if __name__ == "__main__":
    asyncio.run(main())

"""
test_iswap_plate_deck_to_landing_variable.py

iSWAP isolated plate move: a source carrier position -> a LANDING carrier position, with
variable rails and tunable pickup/drop geometry. This is the decoupled transfer test for
the Tecan on-deck integration: prove the arm can pick a plate and place it at the reader's
landing coordinate (and, with the return twin, take it back) BEFORE the reader is committed
to the deck. Use a plate-carrier at the rail nearest the reader as the stand-in landing;
tune its rail/x/y/z to the reader's drawer position once that is fixed.

Mirrors the validated rail35 pos0 -> rail35 pos2 leg. --mode deck prints geometry and moves
nothing; --mode move requires the confirm token. Use an EMPTY sacrificial plate, landing
physically clear, a person at the E-stop, and only ONE process on the STAR USB.

    # geometry only, no motion:
    ./run_on_pi.sh starlab_live/test_iswap_plate_deck_to_landing_variable.py --mode deck \
        --source-rail 35 --landing-rail 20
    # move (empty plate, watched):
    ./run_on_pi.sh starlab_live/test_iswap_plate_deck_to_landing_variable.py --mode move \
        --source-rail 35 --landing-rail 20 --pickup-z-offset-mm 5.0 --drop-z-offset-mm 12.0 \
        --confirm RUN_ISWAP_LANDING_TEST
"""

import argparse
import asyncio

from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends import STARBackend
from pylabrobot.resources import PLT_CAR_L5AC_A00, Cor_96_wellplate_360ul_Fb
from pylabrobot.resources.hamilton import STARDeck

try:
    from pylabrobot.resources.coordinate import Coordinate
except ImportError:
    from pylabrobot.resources import Coordinate

CONFIRM_PHRASE = "RUN_ISWAP_LANDING_TEST"


def shifted(coord, dx=0.0, dy=0.0, dz=0.0):
    return Coordinate(coord.x + dx, coord.y + dy, coord.z + dz)


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["deck", "move"], default="deck")
    parser.add_argument("--source-rail", type=int, default=35)
    parser.add_argument("--source-pos", type=int, default=0)
    parser.add_argument("--landing-rail", type=int, default=20)
    parser.add_argument("--landing-pos", type=int, default=0)
    parser.add_argument("--pickup-z-offset-mm", type=float, default=5.0)
    parser.add_argument("--drop-x-offset-mm", type=float, default=0.0)
    parser.add_argument("--drop-y-offset-mm", type=float, default=0.0)
    parser.add_argument("--drop-z-offset-mm", type=float, default=12.0)
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()

    print("Initializing STAR with skip_autoload=True...")
    lh = LiquidHandler(backend=STARBackend(), deck=STARDeck())
    await lh.setup(skip_autoload=True)

    try:
        if args.source_rail == args.landing_rail:
            raise RuntimeError("source-rail and landing-rail must differ (two carriers).")

        print(f"Assigning source carrier at rail {args.source_rail}, landing carrier at rail {args.landing_rail}...")
        src_carrier = PLT_CAR_L5AC_A00(name="iswap_src_carrier")
        lh.deck.assign_child_resource(src_carrier, rails=args.source_rail)
        land_carrier = PLT_CAR_L5AC_A00(name="iswap_landing_carrier")
        lh.deck.assign_child_resource(land_carrier, rails=args.landing_rail)

        pickup_plate = Cor_96_wellplate_360ul_Fb(name="iswap_pickup_plate", with_lid=False)
        src_carrier[args.source_pos] = pickup_plate
        drop_site = land_carrier[args.landing_pos]

        pickup_base = pickup_plate.location
        drop_base = drop_site.location

        pickup_plate.location = shifted(pickup_base, dz=args.pickup_z_offset_mm)
        drop_site.location = shifted(
            drop_base, dx=args.drop_x_offset_mm, dy=args.drop_y_offset_mm, dz=args.drop_z_offset_mm
        )

        print("")
        print("Deck map:")
        print(f"  pickup: rail{args.source_rail} pos{args.source_pos}   pickup Z offset +{args.pickup_z_offset_mm} mm")
        print(f"  landing: rail{args.landing_rail} pos{args.landing_pos}   drop offset x{args.drop_x_offset_mm} y{args.drop_y_offset_mm} z{args.drop_z_offset_mm} mm")
        print(f"  pickup base -> shifted: {pickup_base} -> {pickup_plate.location}")
        print(f"  drop   base -> shifted: {drop_base} -> {drop_site.location}")
        print("")

        if args.mode == "deck":
            print("Mode deck: assignment/coordinate print only. No movement.")
            print("Confirm the landing Z is within the iSWAP reach (<= ~145 mm above deck) before moving.")
            return

        if args.confirm != CONFIRM_PHRASE:
            raise RuntimeError(f"Refusing to move. Add: --confirm {CONFIRM_PHRASE}")

        print(f"MOVING PLATE with iSWAP: rail{args.source_rail} pos{args.source_pos} -> rail{args.landing_rail} pos{args.landing_pos}")
        print("EMPTY sacrificial plate. Landing must be physically clear. Hand near the E-stop.")

        async with lh.backend.slow_iswap():
            await lh.move_resource(pickup_plate, drop_site)

        print(f"SUCCESS: iSWAP moved plate to rail{args.landing_rail} pos{args.landing_pos}.")

    finally:
        print("Parking / stopping...")
        await lh.stop()
        print("Done.")


asyncio.run(main())

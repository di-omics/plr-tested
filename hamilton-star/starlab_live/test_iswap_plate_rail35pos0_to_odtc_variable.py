"""
iSWAP forward leg: rail35 pos0 -> ODTC plate nest.

di-omics / plr-tested
Part of the ampseq / PTA-WGA workflow ODTC integration. This is the plate-move
leg ONLY. It does not trigger any thermal program (that lives separately in
instrument-integrations/odtc via the PLR ExperimentalODTCBackend).

PATCH LOG
  2026-07-10  Created from test_iswap_plate_rail35pos0_to_rail27_variable.py, the
              proven HHS forward mover. Run --mode deck first (no motion).
  2026-07-10  Geometry corrected against the KNOWN-WORKING full-plate HHS mover
              00_pta_wga_96wp_all12_DSPH15_DRY_ISWAP_HHS_pickupZ5.py:
                - pickup-z default 8.5 -> 5.0. The 8.5 gripped the plate ~3.5 mm
                  too high and failed to pick it up. 5.0 is the validated rail35
                  pos0 grip and is identical regardless of destination.
                - drop offsets seeded from the validated HHS nest values
                  x12.0 / y54.5 / z17.0. These are proven for the rail27 HHS nest,
                  not the rail20 ODTC nest, so treat them as a STARTING point:
                  they place the plate at a real instrument-nest height (far safer
                  than a raw 0.0 carrier coordinate) and get fine-tuned in small
                  steps for the ODTC with a sacrificial plate and eyes on the deck.
                - added park_iswap() before stop, matching the proven movers.
  2026-07-12  HARDWARE-CONFIRMED forward drop for the rail20 pos1 ODTC nest.
              Tuned live on the instrument with a sacrificial plate, operator watching:
              from the HHS-derived start (x12/y54.5/z17) the drop was walked
                - 10 mm left  (x 12.0 -> 2.0)
                - 18 mm down  (y 54.5 -> 36.5)
                -  5 mm lower (z 17.0 -> 12.0, it was releasing from the air)
              landing the plate cleanly seated in the nest at carrier (6, 141, 98.15).
              These are now the defaults. pickup-z stays 5.0. Confirmed with
              --odtc-rail 20 --odtc-position 1; three clean forward reps.
              (Return leg is not yet hardware-confirmed; see the return script.)

SAFETY
  - --mode deck assigns the deck and prints coordinates only. No movement.
  - Any real move requires --mode move AND --confirm RUN_ODTC_ISWAP_FWD.
  - Use an EMPTY sacrificial plate for tuning. A person watches with a hand on the
    E-stop. The ODTC nest must be physically empty and its lid open and clear of
    the iSWAP swing.
  - --odtc-rail is required so the arm is never sent to a guessed rail.
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


PICKUP_RAIL = 35
PICKUP_POSITION = 0


def shifted(coord, dx=0.0, dy=0.0, dz=0.0):
    return Coordinate(coord.x + dx, coord.y + dy, coord.z + dz)


async def main():
    parser = argparse.ArgumentParser(
        description="iSWAP forward leg: rail35 pos0 -> ODTC nest (untuned, tunable offsets)."
    )
    parser.add_argument("--mode", choices=["deck", "move"], default="deck")
    parser.add_argument(
        "--odtc-rail", type=int, required=True,
        help="Rail the ODTC plate-nest carrier is assigned to. Required; no default.",
    )
    parser.add_argument(
        "--odtc-position", type=int, default=0,
        help="Carrier position 0..4 for the ODTC nest.",
    )
    parser.add_argument(
        "--pickup-z-offset-mm", type=float, default=5.0,
        help="Grip height offset at rail35 pos0. Validated value is 5.0 (pickupZ5 mover).",
    )
    parser.add_argument(
        "--drop-x-offset-mm", type=float, default=2.0,
        help="Hardware-confirmed for the rail20 pos1 ODTC nest (2026-07-12).",
    )
    parser.add_argument(
        "--drop-y-offset-mm", type=float, default=36.5,
        help="Hardware-confirmed for the rail20 pos1 ODTC nest (2026-07-12).",
    )
    parser.add_argument(
        "--drop-z-offset-mm", type=float, default=12.0,
        help="Hardware-confirmed for the rail20 pos1 ODTC nest (2026-07-12).",
    )
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()

    if args.odtc_position < 0 or args.odtc_position > 4:
        raise ValueError("--odtc-position must be 0..4 for PLT_CAR_L5AC_A00")

    print("Initializing STAR with skip_autoload=True...")
    lh = LiquidHandler(backend=STARBackend(), deck=STARDeck())
    await lh.setup(skip_autoload=True)

    try:
        print(f"Assigning pickup carrier rail{PICKUP_RAIL} and ODTC carrier rail{args.odtc_rail}...")
        pickup_carrier = PLT_CAR_L5AC_A00(name=f"pickup_carrier_rail{PICKUP_RAIL}")
        odtc_carrier = PLT_CAR_L5AC_A00(name=f"odtc_carrier_rail{args.odtc_rail}")

        lh.deck.assign_child_resource(pickup_carrier, rails=PICKUP_RAIL)
        lh.deck.assign_child_resource(odtc_carrier, rails=args.odtc_rail)

        pickup_plate = Cor_96_wellplate_360ul_Fb(
            name="iswap_pickup_plate_rail35_pos0",
            with_lid=False,
        )
        pickup_carrier[PICKUP_POSITION] = pickup_plate

        drop_site = odtc_carrier[args.odtc_position]

        pickup_base = pickup_plate.location
        drop_base = drop_site.location

        pickup_plate.location = shifted(pickup_base, dz=args.pickup_z_offset_mm)
        drop_site.location = shifted(
            drop_base,
            dx=args.drop_x_offset_mm,
            dy=args.drop_y_offset_mm,
            dz=args.drop_z_offset_mm,
        )

        print("")
        print("Deck map:")
        print(f"  pickup plate: rail{PICKUP_RAIL} pos{PICKUP_POSITION}")
        print(f"  ODTC nest:    rail{args.odtc_rail} pos{args.odtc_position}")
        print(f"  pickup Z offset: +{args.pickup_z_offset_mm} mm")
        print(f"  drop X offset:   +{args.drop_x_offset_mm} mm  (confirmed rail20 pos1)")
        print(f"  drop Y offset:   +{args.drop_y_offset_mm} mm  (confirmed rail20 pos1)")
        print(f"  drop Z offset:   +{args.drop_z_offset_mm} mm  (confirmed rail20 pos1)")
        print("")
        print(f"  pickup base location:    {pickup_base}")
        print(f"  pickup shifted location: {pickup_plate.location}")
        print(f"  drop base location:      {drop_base}")
        print(f"  drop shifted location:   {drop_site.location}")
        print("")

        if args.mode == "deck":
            print("Mode deck: assignment/coordinate print only. No movement.")
            return

        if args.confirm != "RUN_ODTC_ISWAP_FWD":
            raise RuntimeError(
                "Refusing to move. Add: --mode move --confirm RUN_ODTC_ISWAP_FWD"
            )

        print("MOVING PLATE with iSWAP: rail35 pos0 -> ODTC nest...")
        print("Use EMPTY sacrificial plate. ODTC nest must be empty and clear. Hand near E-stop.")

        async with lh.backend.slow_iswap():
            await lh.move_resource(pickup_plate, drop_site)

        print("SUCCESS: iSWAP forward move rail35 pos0 -> ODTC nest completed.")

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

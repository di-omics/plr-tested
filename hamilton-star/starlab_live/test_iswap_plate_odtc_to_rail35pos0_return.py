"""
iSWAP return leg: ODTC plate nest -> rail35 pos0.

di-omics / plr-tested
Return half of the PCR enrichment / WGS preparation ODTC plate move. Plate-move only; triggers
no thermal program.

PATCH LOG
  2026-07-10  Created from test_iswap_plate_rail27pos2_hhs_to_rail35pos0_return.py.
              Added --mode deck (no motion) and a --confirm gate the original HHS
              return script lacked, because this leg is not yet tuned.
  2026-07-10  Added park_iswap() before stop, matching the proven movers.
  2026-07-10  FRAME FIX. First real return attempt failed with firmware
              NoElementError('Plate not found'): the grippers closed ~3 mm below
              the plate. Cause: this script shifted plate.location (plate-in-slot
              frame, base z -3.03) while the forward mover shifts drop_site.location
              (slot-in-carrier frame, base z ~86). Reusing the forward drop offsets
              here therefore landed 3.03 mm low (exactly the plate anchor). Fix:
              shift the ODTC SLOT here too, so the pickup offsets mean the same as
              the forward drop offsets.
  2026-07-12  Re-based on the now hardware-confirmed forward drop (x2 / y36.5 / z12
              at rail20 pos1). The offset catalog over the proven HHS and mag
              round trips found the return rule: the pickup grips the SAME x/y as
              the drop, and BELOW it in z (HHS grips ~11 mm below its z17 drop; the
              mag rack ~1 mm below). x/y here are set to mirror the confirmed drop
              (x2 / y36.5). z is dropped to 9.0 as a STARTING estimate below the
              z12 drop; the ODTC nest is shallow (the drop z was lowered to 12 so
              the plate stops flying in), so the grip-below-drop is expected small.
              THE RETURN Z IS NOT YET HARDWARE-CONFIRMED: bracket ~8-11 in 1-2 mm
              steps with a sacrificial plate. Do NOT grip at drop height (z12/z17);
              that sits above the plate rim and trips NoElementError('Plate not
              found'). return-drop onto rail35 pos0 keeps the proven 8.5.

SAFETY
  - --mode deck assigns the deck and prints coordinates only. No movement.
  - Any real move requires --mode move AND --confirm RUN_ODTC_ISWAP_RET.
  - The plate must physically be on the ODTC nest; rail35 pos0 must be empty.
    A person watches with a hand on the E-stop.
  - --odtc-rail is required so the arm is never sent to a guessed rail.
"""

import argparse
import asyncio

from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends import STARBackend
from pylabrobot.resources import Coordinate
from pylabrobot.resources.hamilton import STARDeck
from pylabrobot.resources import PLT_CAR_L5AC_A00
from pylabrobot.resources import Cor_96_wellplate_360ul_Fb


RETURN_RAIL = 35
RETURN_POSITION = 0


def shifted(coord, dx=0.0, dy=0.0, dz=0.0):
    return Coordinate(coord.x + dx, coord.y + dy, coord.z + dz)


async def main():
    parser = argparse.ArgumentParser(
        description="iSWAP return leg: ODTC nest -> rail35 pos0 (untuned, tunable offsets)."
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
        "--odtc-pickup-x-offset-mm", type=float, default=2.0,
        help="Slot-frame; mirrors the confirmed forward drop x (proven rule: pick up at the drop x/y).",
    )
    parser.add_argument(
        "--odtc-pickup-y-offset-mm", type=float, default=36.5,
        help="Slot-frame; mirrors the confirmed forward drop y (proven rule: pick up at the drop x/y).",
    )
    parser.add_argument(
        "--odtc-pickup-z-offset-mm", type=float, default=0.0,
        help="Slot-frame. HARDWARE-CONFIRMED 2026-07-12: z0 grips. The plate settles ~9 mm deep in the ODTC nest (z11 and z9 whiffed high, clean no-dive), so grab low at z0. Operator later asked for z1.5; NOT yet grip-tested.",
    )
    parser.add_argument(
        "--return-drop-z-offset-mm", type=float, default=8.5,
        help="Drop height offset onto rail35 pos0. Proven return value is 8.5.",
    )
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()

    if args.odtc_position < 0 or args.odtc_position > 4:
        raise ValueError("--odtc-position must be 0..4 for PLT_CAR_L5AC_A00")

    lh = LiquidHandler(backend=STARBackend(), deck=STARDeck())
    try:
        print("Initializing STAR with skip_autoload=True...")
        await lh.setup(skip_autoload=True)

        print(f"Assigning ODTC pickup carrier rail{args.odtc_rail} and return carrier rail{RETURN_RAIL}...")
        odtc_carrier = PLT_CAR_L5AC_A00(name=f"odtc_pickup_carrier_rail{args.odtc_rail}")
        return_carrier = PLT_CAR_L5AC_A00(name=f"return_carrier_rail{RETURN_RAIL}")

        lh.deck.assign_child_resource(odtc_carrier, rails=args.odtc_rail)
        lh.deck.assign_child_resource(return_carrier, rails=RETURN_RAIL)

        odtc_site = odtc_carrier[args.odtc_position]
        odtc_base = odtc_site.location
        odtc_site.location = shifted(
            odtc_base,
            dx=args.odtc_pickup_x_offset_mm,
            dy=args.odtc_pickup_y_offset_mm,
            dz=args.odtc_pickup_z_offset_mm,
        )

        plate = Cor_96_wellplate_360ul_Fb(name="iswap_plate_on_odtc_nest")
        odtc_carrier[args.odtc_position] = plate

        drop_site = return_carrier[RETURN_POSITION]
        drop_base = drop_site.location
        drop_site.location = shifted(drop_base, dz=args.return_drop_z_offset_mm)

        print("")
        print("iSWAP RETURN LEG: ODTC nest -> rail35 pos0")
        print("Physical requirements:")
        print(f"  plate is currently on the ODTC nest (rail{args.odtc_rail} pos{args.odtc_position})")
        print(f"  rail{RETURN_RAIL} pos{RETURN_POSITION} is empty")
        print("  hand near E-stop")
        print("")
        print(f"  ODTC pickup base:     {odtc_base}")
        print(f"  ODTC pickup shifted:  {odtc_site.location}   (slot frame, same as forward drop)")
        print(f"  return drop base:     {drop_base}")
        print(f"  return drop shifted:  {drop_site.location}")
        print("")

        if args.mode == "deck":
            print("Mode deck: assignment/coordinate print only. No movement.")
            return

        if args.confirm != "RUN_ODTC_ISWAP_RET":
            raise RuntimeError(
                "Refusing to move. Add: --mode move --confirm RUN_ODTC_ISWAP_RET"
            )

        print("MOVING PLATE: ODTC nest -> rail35 pos0...")
        async with lh.backend.slow_iswap():
            await lh.move_resource(plate, drop_site)
        print("SUCCESS: iSWAP returned plate from ODTC nest to rail35 pos0.")

    finally:
        print("Parking iSWAP / stopping STAR backend...")
        try:
            await lh.backend.park_iswap()
        except Exception as e:
            print(f"park_iswap warning: {e!r}")
        await lh.stop()
        print("Done.")


if __name__ == "__main__":
    asyncio.run(main())

"""Settle the sign of STARBackend mix_position_from_liquid_surface on real hardware, safely.

PATCH 2026-07-16: created after a pre-flight audit blocked the targeted PCR firmware-mix build.

WHY THIS EXISTS
  PyLabRobot 0.2.1 ships two contradictory docstrings for the SAME parameter:
    STARBackend.dispense      "The height to move above the liquid surface for mix"
    STARBackend.dispense_pip  "Mix position in Z- direction from liquid surface ... Default 250"
  A firmware default of 250 (= 25 mm) is only coherent as a DEPTH BELOW a surface, and the
  parameter is unsigned (range 0..900), but the higher-level wording says the opposite.
  Nothing in PLR pins it: every golden firmware string in STAR_tests.py has mixing
  disabled (mc00 / mp000), so the source cannot settle this. Only the machine can.

WHY IT MATTERS
  01_targeted_pcr_round1_mastermix_col1.py, 03_targeted_pcr_round2_mastermix_col1.py and the V2
  single-home runner all pass:
      liquid_height = 1.5, mix_position_from_liquid_surface = 2.0
  lld_mode is never passed and defaults to LLDMode.OFF, so PLR models the surface as
  well_bottom + liquid_height = well_bottom + 1.5 mm. Then:
      DEPTH reading -> mix Z = 1.5 - 2.0 = well_bottom - 0.5 mm
          eight tips driven 0.5 mm INTO the plastic, three cycles, per plate.
      RAISE reading -> mix Z = 1.5 + 2.0 = well_bottom + 3.5 mm
          tip parked in air above a 25 uL meniscus that is only 0.657 mm deep:
          it would aspirate 18 uL of air and blow it into the reaction.
  Both readings condemn the current 2.0 value. This test tells us WHICH way to fix it.
  Nothing asserts today: 2.0 -> 20 is inside 0..900, and the guard in dispense_pip is
  written `assert any(0 <= x <= 900 ...)` instead of `all`, so one good channel would
  mask seven bad ones anyway.

SAFE BY CONSTRUCTION
  The declared surface is placed far above the well bottom so that BOTH possible
  readings land in free space. No value of the sign can crush a tip.

      DECLARED_SURFACE_MM = 10.0   -> modelled surface = well_bottom + 10.0 mm
      MIX_POSITION_MM     =  5.0   -> the parameter under test

      DEPTH reading: mix Z = 10.0 - 5.0 =  5.0 mm above the well bottom
                     ten times the known-bad 0.5 mm crush line, still inside the well.
      RAISE reading: mix Z = 10.0 + 5.0 = 15.0 mm above the well bottom
                     above the CellTreat 350 uL Fb rim (well depth ~10.9 mm): open air.

  The two outcomes differ by 10 mm and are trivially distinguishable by eye or camera.

  DRY. No reagent. The target column MUST be empty. Tips are returned by default: this
  is a dry rehearsal, not a single-cell reagent run, so carryover does not apply.

HOW TO READ THE RESULT
  Watch the tips during the three mix cycles:
    tips sit DOWN INSIDE the well, roughly half its depth (~5 mm off the bottom)
        -> DEPTH. Measured DOWNWARD from the surface. The targeted PCR mix Z is
           well_bottom - 0.5 mm and WOULD HAVE CRUSHED all eight tips.
    tips sit UP ABOVE the plate rim (~15 mm off the bottom, clearly in open air)
        -> RAISE. Measured UPWARD from the surface. The targeted PCR mix would have
           cycled air above the meniscus and mixed nothing.

  Either way, report the observation and STOP. Do not re-run the targeted PCR mastermix
  build until MIX_POSITION_FROM_SURFACE is corrected in all three call sites:
    01_targeted_pcr_round1_mastermix_col1.py, 03_targeted_pcr_round2_mastermix_col1.py,
    run_targeted_pcr_odtc_LIDDED_1col_full_v2_singlehome_dry.py

NOTE ON --mode deck
  lh.setup() runs BEFORE the mode check, so --mode deck DOES home the channels and the
  iSWAP on this file, exactly as it does on 01_/03_. It is not a motion-free gate.
  Treat it as a supervised homing run: human present, hand near the E-stop.

USAGE
  ./run_on_pi.sh starlab_live/test_mix_position_sign_SAFE.py --mode deck
  ./run_on_pi.sh starlab_live/test_mix_position_sign_SAFE.py --mode sign
"""

import argparse
import asyncio
from typing import Dict, List

from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends import STARBackend
from pylabrobot.liquid_handling.standard import Mix
from pylabrobot.resources import (
    PLT_CAR_L5AC_A00,
    CellTreat_96_wellplate_350ul_Fb,
    Coordinate,
)
from pylabrobot.resources.hamilton import STARDeck, TIP_CAR_480_A00
import pylabrobot.resources as plr_resources

# Deck geometry, identical to the validated targeted PCR mastermix scripts.
TIP_RAIL = 48
LABWARE_RAIL = 35
P50_TIP_POS = 1
WORK_POS = 0
SOURCE_96WP_POS = 1

# The parameter under test, and the declared surface that makes it safe either way.
# See the SAFE BY CONSTRUCTION block above before touching either number.
DECLARED_SURFACE_MM = 10.0
MIX_POSITION_MM = 5.0

MIX_CYCLES = 3
MIX_VOLUME_UL = 5.0
MIX_FLOW_RATE = 100.0

# Air only. The target column must be empty; this volume is moved to make the firmware
# execute a real dispense-with-mix, not to transfer anything.
AIR_VOLUME_UL = 20.0

# Column 12: deliberately far from column 1, which carries template in a real run.
TARGET_COL = 12

# Reused verbatim from the validated mastermix geometry.
P50_WORK_DSP_OFFSETS = [Coordinate(-0.68, 3.22, 0.0)] * 8

# Reused verbatim from 01_targeted_pcr_round1_mastermix_col1.py:85. Factory names vary by PLR
# build, so probe rather than hardcode.
P50_TIP_FACTORY_CANDIDATES = ["hamilton_96_tiprack_50uL_filter", "hamilton_96_tiprack_50ul_filter"]


def make_resource(label: str, name: str, candidates: List[str], terms: List[str]):
    for factory_name in candidates:
        factory = getattr(plr_resources, factory_name, None)
        if factory is not None:
            print(f"Using {label} resource factory: {factory_name}")
            return factory(name=name)
    terms_lower = [term.lower() for term in terms]
    available = sorted(n for n in dir(plr_resources) if any(t in n.lower() for t in terms_lower))
    raise RuntimeError(f"Could not find factory for {label}. Tried {candidates}. Nearby: {available[:80]}")


def make_p50_tips(name: str):
    return make_resource("p50 filter tips", name, P50_TIP_FACTORY_CANDIDATES, ["tip", "50"])


def wells_for_column(plate, col: int):
    return plate[f"A{col}:H{col}"]


async def assign_deck(lh: LiquidHandler) -> Dict[str, object]:
    print("Assigning deck: mix_position_from_liquid_surface sign test...")

    tip_carrier = TIP_CAR_480_A00(name="tip_car_rail48")
    labware_carrier = PLT_CAR_L5AC_A00(name="labware_car_rail35")
    lh.deck.assign_child_resource(tip_carrier, rails=TIP_RAIL)
    lh.deck.assign_child_resource(labware_carrier, rails=LABWARE_RAIL)

    p50_tips = make_p50_tips("r48_pos1_p50_filter_tips")
    # Work plate model is load-bearing: CellTreat and Cor differ ~1.25 mm at the WELL
    # BOTTOM while differing only ~0.10 mm in overall height, so substituting the model
    # silently reindexes every height in this file. Keep CellTreat.
    work_plate = CellTreat_96_wellplate_350ul_Fb(name="rail35_pos0_work_96wp")

    tip_carrier[P50_TIP_POS] = p50_tips
    labware_carrier[WORK_POS] = work_plate

    depth_z = DECLARED_SURFACE_MM - MIX_POSITION_MM
    raise_z = DECLARED_SURFACE_MM + MIX_POSITION_MM

    print("\nDeck:")
    print(f"  rail48 pos{P50_TIP_POS} = p50 filter tips")
    print(f"  rail35 pos{WORK_POS} = work 96WP (CellTreat 350 uL Fb), target column {TARGET_COL}")
    print("\nSign test geometry:")
    print(f"  DECLARED_SURFACE_MM (liquid_height)          = {DECLARED_SURFACE_MM}")
    print(f"  MIX_POSITION_MM (parameter under test)       = {MIX_POSITION_MM}")
    print(f"  mix {MIX_CYCLES}x {MIX_VOLUME_UL} uL @ {MIX_FLOW_RATE} uL/s")
    print("\nPredicted outcomes (both safe, 10 mm apart):")
    print(f"  if DEPTH (Z- below surface): tips mix at {depth_z} mm above the well bottom (inside the well)")
    print(f"  if RAISE (above surface):    tips mix at {raise_z} mm above the well bottom (above the rim, in air)")
    print("\nThe known-bad crush line is 0.5 mm. Neither outcome approaches it.")

    return {"p50_tips": p50_tips, "work_plate": work_plate}


async def run_sign_test(lh: LiquidHandler, r: Dict[str, object]) -> None:
    p50_tips = r["p50_tips"]
    work_plate = r["work_plate"]

    tip_col = wells_for_column(p50_tips, 1)
    targets = wells_for_column(work_plate, TARGET_COL)

    print(f"\nPicking up p50 tips, rack column 1...")
    await lh.pick_up_tips(tip_col)

    try:
        # Aspirate air from the empty target column. lld_mode stays OFF, so the tip simply
        # travels to well_bottom + DECLARED_SURFACE_MM and takes air. Nothing is transferred.
        print(f"Aspirating {AIR_VOLUME_UL} uL of AIR from EMPTY col {TARGET_COL} "
              f"at {DECLARED_SURFACE_MM} mm above the well bottom...")
        await lh.aspirate(
            targets,
            vols=[AIR_VOLUME_UL] * 8,
            liquid_height=[DECLARED_SURFACE_MM] * 8,
            offsets=P50_WORK_DSP_OFFSETS,
            blow_out_air_volume=[0.0] * 8,
        )

        print("\n>>> WATCH THE TIPS NOW <<<")
        print(f"    inside the well  (~{DECLARED_SURFACE_MM - MIX_POSITION_MM} mm off the bottom) -> DEPTH")
        print(f"    above the rim    (~{DECLARED_SURFACE_MM + MIX_POSITION_MM} mm off the bottom) -> RAISE")
        await lh.dispense(
            targets,
            vols=[AIR_VOLUME_UL] * 8,
            liquid_height=[DECLARED_SURFACE_MM] * 8,
            offsets=P50_WORK_DSP_OFFSETS,
            blow_out_air_volume=[0.0] * 8,
            mix=[Mix(volume=MIX_VOLUME_UL, repetitions=MIX_CYCLES, flow_rate=MIX_FLOW_RATE)] * 8,
            mix_position_from_liquid_surface=[MIX_POSITION_MM] * 8,
        )
        print("\nMix cycles complete. Record where the tips sat, then stop.")
    finally:
        print("Returning tips to the rack (dry rehearsal, no reagent, no carryover).")
        await lh.return_tips()


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Determine the sign of STARBackend mix_position_from_liquid_surface. "
                    "Safe by construction: both readings land in free space."
    )
    parser.add_argument("--mode", choices=["deck", "sign"], default="deck")
    args = parser.parse_args()

    lh = LiquidHandler(backend=STARBackend(), deck=STARDeck())
    # NOTE: this homes channels and the iSWAP, including under --mode deck.
    await lh.setup(skip_autoload=True)
    try:
        r = await assign_deck(lh)

        if args.mode == "deck":
            print("\nMode deck: assignment only. No liquid handling executed.")
            return

        if args.mode == "sign":
            await run_sign_test(lh, r)
            return

        raise RuntimeError(f"Unhandled mode: {args.mode}")
    finally:
        await lh.backend.park_iswap()
        await lh.stop()


if __name__ == "__main__":
    asyncio.run(main())

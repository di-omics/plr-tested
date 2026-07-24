import argparse
import asyncio
from dataclasses import dataclass
from typing import Dict, List

from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends import STARBackend
from pylabrobot.resources.hamilton import STARDeck, TIP_CAR_480_A00
from pylabrobot.resources import PLT_CAR_L5AC_A00, CellTreat_96_wellplate_350ul_Fb, Coordinate
import pylabrobot.resources as plr_resources
from pylabrobot.liquid_handling.standard import Mix

from pathlib import Path as _MethodPath
import sys as _method_sys

_method_root = next(parent for parent in _MethodPath(__file__).resolve().parents if parent.name == "hamilton-star")
if str(_method_root) not in _method_sys.path:
    _method_sys.path.insert(0, str(_method_root))
from operator_parameters import required_positive

# PCR-enrichment stage-1 addition, four-column dry motion proof
#
# Purpose:
# - Keep the existing WGS/sequencing validation deck unchanged.
# - Transfer an operator-defined stage-1 solution to an operator-prepared destination.
# - The wet-method composition and volume come from the required local profile.
# - Dry observation: run with --return-tips.
# - Production behavior: discards tips by default if --return-tips is omitted.
#
# Deck:
#   rail48 pos0 = p10 tips
#   rail48 pos1 = p50 tips
#   rail35 pos0 = destination/work 96WP or compatible strip/plate, column 1
#   rail35 pos1 = source 96WP/strip/reagent plate, column 1 only
#
# Wet-method composition, input volume, transfer volume, and thermal handoff are
# operator-supplied and intentionally absent from this public file.

TIP_RAIL = 48
P10_TIP_POS = 0
P50_TIP_POS = 1

LABWARE_RAIL = 35
WORK_POS = 0
SOURCE_96WP_POS = 1

SOURCE_COL = 1

# 4-COLUMN DRY MOTION PROOF (2026-07-16). Uses the tuned geometry from
# 01_pcr_enrichment_round1_mastermix_col1.py as recorded by the hardware validation
# (13/13 clean, twice); the dispense+mix loops over four
# destination columns instead of one. Every tuned coordinate, the firmware in-well Mix, and
# the blowout are unchanged. Source stays column 1: each A-H source well feeds its own row
# across all four destination columns.
#
# The column-loop idiom is taken from 04_pcr_enrichment_96wp_pcr1_pcr2_mastermix_DSPH15_DRY.py:210,
# but NOT its geometry: 04 uses P50_SOURCE_ASP_HEIGHT 0.9 (vs 0.0 here), dispense offset
# x -0.38 (vs the -0.68 locked by the Y/X-SAFE DISPENSE PATCH V5), blowout 6.0 (vs 10.0),
# and carries NO mix at all. Do not "sync" this file to 04.
#
# ##########################################################################################
# DRY ONLY. THIS FILE MUST NOT BE RUN WET AS WRITTEN.
# It picks up ONE p50 tip column and holds it across all four destination columns, then
# returns it. That is safe with no reagent on the deck. It is FATAL with reagent: the tip is
# planted INSIDE each destination reaction to mix (mix Z = +0.5 mm), then returns to the
# SHARED source well at col 1 to aspirate for the next column, which would carry template
# from column 1 into the master mix and thence into every later column. The samples are
# low-input DNA, and CLAUDE.md is explicit that carryover is fatal to low-input
# work. A wet 4-column version needs FRESH TIPS PER DESTINATION COLUMN (see the
# MultiRackTipCursor in whole_genome_seq_v2_p50only_2rack_4col_discardtips_h7_bo6.py:134) and a
# second p50 rack, because 4 cols x 2 adds + cleanup exceeds one 12-column rack.
# ##########################################################################################
DEST_COLS = [1, 2, 3, 4]

VOL_PCR1_MASTER_MIX = required_positive("pcr_enrichment.round_1_transfer_ul")
REACTION_VOLUME_UL = required_positive("pcr_enrichment.round_1_reaction_volume_ul")

# Reuse the validated sequencing validation column-1 P50 geometry.
P50_WORK_DSP_HEIGHT = [1.5] * 8   # raised 0.5 -> 1.5 (2026-07-12): at 0.5 the tips crushed into the well at dispense
P50_WORK_DSP_OFFSETS = [Coordinate(-0.68, 3.22, 0.0)] * 8
P50_SOURCE_ASP_HEIGHT = [0.0] * 8
P50_SOURCE_ASP_OFFSETS = [Coordinate(-0.65, 3.35, 0.0)] * 8
P50_BLOWOUT_AIR_VOLUME = 6.0

# IN-WELL MIX (firmware Mix): the tip stays planted IN the well and the plunger cycles in
# place. This is real mixing. A Python aspirate/dispense loop is NOT: it retracts the whole
# head between cycles (aspirate low, lift, dispense high, repeat), which is squirt-and-
# repeat, not agitation. Observed on the instrument 2026-07-16 and rejected for that reason.
#
# THE SIGN IS PROVEN, DO NOT GUESS IT AGAIN. test_mix_position_sign_SAFE.py ran on the
# instrument 2026-07-16 (declared surface 10 mm, param 5 mm -> the tips went DOWN to 5 mm,
# inside the well). mix_position_from_liquid_surface is a DEPTH measured DOWNWARD:
#
#     mix Z = well_bottom + liquid_height - mix_position_from_liquid_surface
#
# lld_mode is never passed and defaults to LLDMode.OFF, so the modelled surface is
# well_bottom + liquid_height (NOT the real meniscus). With liquid_height = 1.5:
#     param 2.0 -> mix Z = -0.5 mm   eight tips INTO the plastic  (the 87b6e52 bug)
#     param 1.0 -> mix Z = +0.5 mm   the aspirate height the on-camera build already used
# PLR 0.2.1's STARBackend.dispense docstring says this value moves the tip ABOVE the
# surface. It is WRONG. dispense_pip ("Z- direction", firmware default 250 = 25 mm) is
# right. Nothing guards this: 2.0 -> 20 is inside the legal 0..900 range, dispense_pip
# checks with `assert any(...)` rather than `all(...)` so one good channel masks seven bad
# ones, and chatterbox has no well-geometry model. The number below is load-bearing.
#
# Reaction volume is required from the operator profile. The motion values below are
# hardware calibration; verify the locally approved reaction volume keeps the mix
# position safe for the selected well before any wet run.
# Sample is low-input DNA: blowout stays at 10 uL so nothing precious
#   is left in the tip; 12 uL was rejected as splash risk in a shallow well.
MIX_CYCLES = 3
MIX_VOLUME_UL = 10.0
MIX_FLOW_RATE = 10.0                     # uL/s, plunger speed for the in-well mix. 50 -> 10
                                         # (2026-07-16): at 50 the whole 3x 10 uL mix took 1.2 s,
                                         # too fast to see or hear. At 10 it takes ~6 s.
MIX_POSITION_FROM_SURFACE = [1.0] * 8    # -> mix Z = 1.5 - 1.0 = 0.5 mm above the well bottom
P50_MIX_BLOWOUT_AIR_VOLUME = 10.0

# Define p10 resources too so deck layout stays identical, although PCR1-MM uses p50.
P10_WORK_DSP_HEIGHT = [0.5] * 8
P10_WORK_DSP_OFFSETS = [Coordinate(-0.68, 3.22, 0.0)] * 8
P10_SOURCE_ASP_HEIGHT = [0.0] * 8
P10_SOURCE_ASP_OFFSETS = [Coordinate(-0.65, 3.35, 0.0)] * 8
P10_BLOWOUT_AIR_VOLUME = 7.0

POST_DISPENSE_SETTLE_SECONDS = 1.0

P10_TIP_FACTORY_CANDIDATES = ["hamilton_96_tiprack_10uL_filter", "hamilton_96_tiprack_10ul_filter"]
P50_TIP_FACTORY_CANDIDATES = ["hamilton_96_tiprack_50uL_filter", "hamilton_96_tiprack_50ul_filter"]


@dataclass
class Step:
    mode: str
    label: str
    volume_ul: float
    tip_type: str
    manual_prep: str
    manual_stop: str


PCR1_MM_STEP = Step(
    mode="pcr1-mm",
    label="PCR-enrichment operator-defined stage 1",
    volume_ul=VOL_PCR1_MASTER_MIX,
    tip_type="p50",
    manual_prep=(
        "Prepare destination and source wells according to the approved local method. "
        "The transfer volume is read from PLR_METHOD_PARAMETERS_FILE."
    ),
    manual_stop=(
        "Follow the operator-approved thermal handoff; no biological profile is public."
    ),
)


def make_resource(label: str, name: str, candidates: List[str], terms: List[str]):
    for factory_name in candidates:
        factory = getattr(plr_resources, factory_name, None)
        if factory is not None:
            print(f"Using {label} resource factory: {factory_name}")
            return factory(name=name)
    terms_lower = [term.lower() for term in terms]
    available = sorted(n for n in dir(plr_resources) if any(term in n.lower() for term in terms_lower))
    raise RuntimeError(f"Could not find factory for {label}. Tried {candidates}. Nearby: {available[:80]}")


def make_p10_tips(name: str):
    return make_resource("p10 filter tips", name, P10_TIP_FACTORY_CANDIDATES, ["tip", "10"])


def make_p50_tips(name: str):
    return make_resource("p50 filter tips", name, P50_TIP_FACTORY_CANDIDATES, ["tip", "50"])


def wells_for_column(plate, col: int):
    return plate[f"A{col}:H{col}"]


async def assign_deck(lh: LiquidHandler) -> Dict[str, object]:
    print("Assigning PCR enrichment round 1 deck: WGS/sequencing validation compatible column-1 layout...")

    tip_carrier = TIP_CAR_480_A00(name="tip_car_rail48")
    labware_carrier = PLT_CAR_L5AC_A00(name="labware_car_rail35")
    lh.deck.assign_child_resource(tip_carrier, rails=TIP_RAIL)
    lh.deck.assign_child_resource(labware_carrier, rails=LABWARE_RAIL)

    p10_tips = make_p10_tips("r48_pos0_p10_filter_tips")
    p50_tips = make_p50_tips("r48_pos1_p50_filter_tips")
    work_plate = CellTreat_96_wellplate_350ul_Fb(name="rail35_pos0_pcr_enrichment_round1_dest_96wp")
    source_96wp = CellTreat_96_wellplate_350ul_Fb(name="rail35_pos1_pcr_enrichment_round1_mm_source_96wp")

    tip_carrier[P10_TIP_POS] = p10_tips
    tip_carrier[P50_TIP_POS] = p50_tips
    labware_carrier[WORK_POS] = work_plate
    labware_carrier[SOURCE_96WP_POS] = source_96wp

    print("\nDeck:")
    print("  rail48 pos0 = p10 tips, present for deck compatibility")
    print("  rail48 pos1 = p50 tips, used for PCR1 master mix")
    print(f"  rail35 pos0 = destination/work 96WP, destination columns {DEST_COLS}")
    print("  rail35 pos1 = source 96WP/strip, SOURCE COLUMN 1 ONLY")
    print("\nPCR1 master-mix mode:")
    print(f"  destination cols {DEST_COLS} A-H are prepared by the operator")
    print("  source col 1 A-H contains complete PCR1 master mix")
    print(f"  transfer = {VOL_PCR1_MASTER_MIX} uL x8 by p50, per column, {len(DEST_COLS)} columns "
          f"({VOL_PCR1_MASTER_MIX * len(DEST_COLS)} uL drawn per source well)")
    print(f"  final reaction volume = {REACTION_VOLUME_UL} uL (operator profile)")
    print("\nP50 geometry:")
    print(f"  P50_SOURCE_ASP_HEIGHT = {P50_SOURCE_ASP_HEIGHT}")
    print(f"  P50_SOURCE_ASP_OFFSETS = {P50_SOURCE_ASP_OFFSETS}")
    print(f"  P50_WORK_DSP_HEIGHT = {P50_WORK_DSP_HEIGHT}")
    print(f"  P50_WORK_DSP_OFFSETS = {P50_WORK_DSP_OFFSETS}")
    print(f"  P50_BLOWOUT_AIR_VOLUME = {P50_BLOWOUT_AIR_VOLUME}")

    return {
        "p10_tips": p10_tips,
        "p50_tips": p50_tips,
        "work_plate": work_plate,
        "source_96wp": source_96wp,
    }


async def finish_tips(lh: LiquidHandler, discard_tips: bool):
    if discard_tips:
        print("Discarding tips...")
        await lh.discard_tips()
    else:
        print("Returning tips to rack...")
        await lh.return_tips()


async def transfer_pcr1_master_mix(lh: LiquidHandler, r: Dict[str, object], discard_tips: bool, tip_col: int):
    step = PCR1_MM_STEP
    vols = [step.volume_ul] * 8

    tips = r["p50_tips"][f"A{tip_col}:H{tip_col}"]

    print(f"\n=== {step.mode.upper()}: {step.label} ===")
    print(f"PREP: {step.manual_prep}")
    print(f"Source rail35 pos1 col {SOURCE_COL} -> destination rail35 pos0 cols {DEST_COLS}")
    print(f"Volume: {step.volume_ul} uL x8 per column, {len(DEST_COLS)} columns "
          f"= {step.volume_ul * len(DEST_COLS)} uL drawn per source well")
    print(f"Tip type: p50; tip column {tip_col}; discard_tips={discard_tips}")

    # ONE tip column is picked up here and held across all four destination columns, then
    # returned. Safe DRY ONLY. See the DRY ONLY banner at the top of this file before ever
    # putting reagent on this deck.
    await lh.pick_up_tips(tips)
    try:
        # Dispense the master mix AND mix IN PLACE: the firmware Mix cycles the plunger while
        # the tip stays IN the well (the head does NOT retract between cycles), then a heavy
        # blowout so no sample is left in the tip. mix Z = liquid_height - MIX_POSITION_FROM_
        # SURFACE = 1.5 - 1.0 = 0.5 mm above the well bottom. See the PATCH note above: that
        # parameter is a DOWNWARD depth and the sign is proven on hardware, not assumed.
        for dest_col in DEST_COLS:
            print(f"\n--- destination column {dest_col} of {DEST_COLS} ---")
            print(f"Aspirating {step.volume_ul} uL x8 from source col {SOURCE_COL}...")
            await lh.aspirate(
                wells_for_column(r["source_96wp"], SOURCE_COL),
                vols=vols,
                liquid_height=P50_SOURCE_ASP_HEIGHT,
                offsets=P50_SOURCE_ASP_OFFSETS,
                blow_out_air_volume=[0.0] * 8,
            )
            print(f"Dispensing {step.volume_ul} uL x8 to dest col {dest_col}; in-well mix "
                  f"{MIX_CYCLES}x {MIX_VOLUME_UL} uL @ {MIX_FLOW_RATE} uL/s at mix Z "
                  f"{P50_WORK_DSP_HEIGHT[0] - MIX_POSITION_FROM_SURFACE[0]} mm above the well bottom; "
                  f"blowout {P50_MIX_BLOWOUT_AIR_VOLUME} uL...")
            await lh.dispense(
                wells_for_column(r["work_plate"], dest_col),
                vols=vols,
                liquid_height=P50_WORK_DSP_HEIGHT,
                offsets=P50_WORK_DSP_OFFSETS,
                blow_out_air_volume=[P50_MIX_BLOWOUT_AIR_VOLUME] * 8,
                mix=[Mix(volume=MIX_VOLUME_UL, repetitions=MIX_CYCLES, flow_rate=MIX_FLOW_RATE)] * 8,
                mix_position_from_liquid_surface=MIX_POSITION_FROM_SURFACE,
            )
            print(f"Post-dispense settle: {POST_DISPENSE_SETTLE_SECONDS} sec")
            await asyncio.sleep(POST_DISPENSE_SETTLE_SECONDS)
    finally:
        await finish_tips(lh, discard_tips)

    print(f"\nSUCCESS: {step.label} addition completed.")
    print(step.manual_stop)


async def main():
    parser = argparse.ArgumentParser(
        description="PCR enrichment round 1 master-mix addition, column 1, WGS/sequencing validation compatible deck."
    )
    parser.add_argument("--mode", choices=["deck", "pcr1-mm"], default="deck")
    parser.add_argument(
        "--return-tips",
        action="store_true",
        help="Return tips instead of discarding. Use this for dry observation. Default is production-style discard.",
    )
    parser.add_argument(
        "--tip-col",
        type=int,
        default=1,
        help="P50 tip column to use for pcr1-mm. Default: 1.",
    )
    args = parser.parse_args()

    if args.tip_col < 1 or args.tip_col > 12:
        raise ValueError("--tip-col must be 1..12")

    discard_tips = not args.return_tips

    print("Initializing STAR with skip_autoload=True...")
    lh = LiquidHandler(backend=STARBackend(), deck=STARDeck())
    await lh.setup(skip_autoload=True)

    try:
        r = await assign_deck(lh)

        if args.mode == "deck":
            print("\nMode deck: assignment only. No liquid handling executed.")
            return

        if args.mode == "pcr1-mm":
            print(f"Production tip behavior: discard_tips={discard_tips}; selected p50 tip column={args.tip_col}")
            await transfer_pcr1_master_mix(lh, r, discard_tips, tip_col=args.tip_col)
            return

        raise RuntimeError(f"Unhandled mode: {args.mode}")

    finally:
        print("Stopping STAR backend...")
        try:
            await lh.backend.park_iswap()
        except Exception as e:
            print(f"park_iswap warning: {e!r}")
        await lh.stop()
        print("Done.")


if __name__ == "__main__":
    asyncio.run(main())

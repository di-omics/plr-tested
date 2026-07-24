import argparse
import asyncio
import math
from dataclasses import dataclass
from typing import Dict, List, Optional

from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends import STARBackend
from pylabrobot.liquid_handling.backends.hamilton.STAR_chatterbox import STARChatterboxBackend
from pylabrobot.resources.hamilton import STARDeck, TIP_CAR_480_A00
from pylabrobot.resources import PLT_CAR_L5AC_A00, CellTreat_96_wellplate_350ul_Fb, Coordinate
import pylabrobot.resources as plr_resources

from pathlib import Path as _MethodPath
import sys as _method_sys

_method_root = next(parent for parent in _MethodPath(__file__).resolve().parents if parent.name == "hamilton-star")
if str(_method_root) not in _method_sys.path:
    _method_sys.path.insert(0, str(_method_root))
from operator_parameters import required_positive

# Generic scRNA-seq reagent-add motion scaffold. Biological reagent identities,
# compositions, volumes, and thermal methods are supplied only through an
# operator-approved local profile. Public modes are deliberately numbered stages.
#
# The calibrated p10/p50 heights, offsets, liquid-capacity limits, and Y=3.20
# exclusion below are hardware safety values and remain unchanged.

TIP_RAIL = 48
P10_TIP_POS = 0
P50_TIP_POS = 1

LABWARE_RAIL = 35
WORK_POS = 0
SOURCE_96WP_POS = 1

SOURCE_COL = 1
DEST_COL = 1

# Largest liquid volume per single-tip transfer, leaving blowout headroom. The p10 tip is
# 10 uL nominal and the p10 blowout air is 7 uL, so the liquid cap is held below the nominal
# (all current p10 adds are <= 4 uL anyway); never let a p10 add approach 10 uL of liquid.
P10_MAX_TRANSFER_UL = 8.0
P50_MAX_TRANSFER_UL = 40.0

# Reused verbatim from the confirmed PCR enrichment/WGS preparation col-1 adds (via methylation_seq scripts).
P50_SOURCE_ASP_HEIGHT = [0.0] * 8
P50_SOURCE_ASP_OFFSETS = [Coordinate(-0.65, 3.35, 0.0)] * 8
P50_WORK_DSP_HEIGHT = [0.5] * 8
P50_WORK_DSP_OFFSETS = [Coordinate(-0.68, 3.22, 0.0)] * 8
P50_BLOWOUT_AIR_VOLUME = 6.0

P10_SOURCE_ASP_HEIGHT = [0.0] * 8
P10_SOURCE_ASP_OFFSETS = [Coordinate(-0.65, 3.35, 0.0)] * 8
P10_WORK_DSP_HEIGHT = [0.5] * 8
P10_WORK_DSP_OFFSETS = [Coordinate(-0.68, 3.22, 0.0)] * 8
P10_BLOWOUT_AIR_VOLUME = 7.0

POST_DISPENSE_SETTLE_SECONDS = 1.0

P10_TIP_FACTORY_CANDIDATES = ["hamilton_96_tiprack_10uL_filter", "hamilton_96_tiprack_10ul_filter"]
P50_TIP_FACTORY_CANDIDATES = ["hamilton_96_tiprack_50uL_filter", "hamilton_96_tiprack_50ul_filter"]


@dataclass
class Step:
    mode: str
    label: str
    volume_ul: float
    tip_type: str          # "p10" or "p50"
    next_odtc: Optional[str]
    manual_prep: str
    manual_stop: str


STEPS: Dict[str, Step] = {
    "stage-1": Step("stage-1", "operator stage 1", required_positive("scrnaseq.stage_1_volume_ul"), "p10", "scrnaseq-stage-1", "Load the operator-approved stage-1 solution.", "Run the operator-approved stage-1 handoff."),
    "stage-2": Step("stage-2", "operator stage 2", required_positive("scrnaseq.stage_2_volume_ul"), "p50", "scrnaseq-stage-2", "Load the operator-approved stage-2 solution.", "Run the operator-approved stage-2 handoff."),
    "stage-3": Step("stage-3", "operator stage 3", required_positive("scrnaseq.stage_3_volume_ul"), "p50", "scrnaseq-stage-3", "Load the operator-approved stage-3 solution.", "Run the operator-approved stage-3 handoff."),
    "stage-4": Step("stage-4", "operator stage 4", required_positive("scrnaseq.stage_4_volume_ul"), "p50", "scrnaseq-stage-4", "Load the operator-approved stage-4 solution.", "Run the operator-approved stage-4 handoff."),
    "stage-5": Step("stage-5", "operator stage 5", required_positive("scrnaseq.stage_5_volume_ul"), "p10", None, "Load the operator-approved stage-5 solution.", "Continue according to the operator method."),
    "stage-6": Step("stage-6", "operator stage 6", required_positive("scrnaseq.stage_6_volume_ul"), "p50", "scrnaseq-stage-5", "Load the operator-approved stage-6 solution.", "Run the operator-approved stage-5 handoff."),
    "stage-7": Step("stage-7", "operator stage 7", required_positive("scrnaseq.stage_7_volume_ul"), "p10", "scrnaseq-stage-6", "Load the operator-approved stage-7 solution.", "Run the operator-approved stage-6 handoff."),
    "stage-8": Step("stage-8", "operator stage 8", required_positive("scrnaseq.stage_8_volume_ul"), "p50", None, "Load the operator-approved stage-8 solution.", "Continue according to the operator method."),
    "stage-9": Step("stage-9", "operator stage 9", required_positive("scrnaseq.stage_9_volume_ul"), "p50", "scrnaseq-stage-7", "Load the operator-approved stage-9 solution.", "Run the operator-approved stage-7 handoff."),
}


def split_volume(total_ul: float, tip_type: str) -> List[float]:
    """Split a total volume into equal per-tip transfers within the tip's liquid capacity."""
    cap = P10_MAX_TRANSFER_UL if tip_type == "p10" else P50_MAX_TRANSFER_UL
    n = max(1, math.ceil(total_ul / cap))
    return [total_ul / n] * n


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
    print("Assigning scRNA-seq reagent-add deck: current 35/48 swap-source column-1 layout...")

    tip_carrier = TIP_CAR_480_A00(name="tip_car_rail48")
    labware_carrier = PLT_CAR_L5AC_A00(name="labware_car_rail35")
    lh.deck.assign_child_resource(tip_carrier, rails=TIP_RAIL)
    lh.deck.assign_child_resource(labware_carrier, rails=LABWARE_RAIL)

    p10_tips = make_p10_tips("r48_pos0_p10_filter_tips")
    p50_tips = make_p50_tips("r48_pos1_p50_filter_tips")
    work_plate = CellTreat_96_wellplate_350ul_Fb(name="rail35_pos0_scrnaseq_work_96wp")
    source_96wp = CellTreat_96_wellplate_350ul_Fb(name="rail35_pos1_scrnaseq_reagent_source_96wp")

    tip_carrier[P10_TIP_POS] = p10_tips
    tip_carrier[P50_TIP_POS] = p50_tips
    labware_carrier[WORK_POS] = work_plate
    labware_carrier[SOURCE_96WP_POS] = source_96wp

    print("\nDeck:")
    print("  rail48 pos0 = p10 tips")
    print("  rail48 pos1 = p50 tips")
    print("  rail35 pos0 = destination/work 96WP, column 1")
    print("  rail35 pos1 = source 96WP/strip, SOURCE COLUMN 1 ONLY (swap reagent between modes)")

    print("\nGeometry (reused verbatim from confirmed PCR enrichment/WGS preparation col-1 adds; see header):")
    print(f"  P50 source asp height {P50_SOURCE_ASP_HEIGHT[0]}, work dsp height {P50_WORK_DSP_HEIGHT[0]}, "
          f"blowout {P50_BLOWOUT_AIR_VOLUME} uL, max {P50_MAX_TRANSFER_UL} uL/transfer")
    print(f"  P10 source asp height {P10_SOURCE_ASP_HEIGHT[0]}, work dsp height {P10_WORK_DSP_HEIGHT[0]}, "
          f"blowout {P10_BLOWOUT_AIR_VOLUME} uL")

    return {"p10_tips": p10_tips, "p50_tips": p50_tips, "work_plate": work_plate, "source_96wp": source_96wp}


async def finish_tips(lh: LiquidHandler, discard_tips: bool):
    if discard_tips:
        print("Discarding tips...")
        await lh.discard_tips()
    else:
        print("Returning tips to rack...")
        await lh.return_tips()


async def transfer_reagent(lh: LiquidHandler, r: Dict[str, object], step: Step, discard_tips: bool, tip_col: int):
    if step.tip_type == "p50":
        tips = r["p50_tips"][f"A{tip_col}:H{tip_col}"]
        src_h, src_off = P50_SOURCE_ASP_HEIGHT, P50_SOURCE_ASP_OFFSETS
        dsp_h, dsp_off = P50_WORK_DSP_HEIGHT, P50_WORK_DSP_OFFSETS
        blowout = P50_BLOWOUT_AIR_VOLUME
    elif step.tip_type == "p10":
        tips = r["p10_tips"][f"A{tip_col}:H{tip_col}"]
        src_h, src_off = P10_SOURCE_ASP_HEIGHT, P10_SOURCE_ASP_OFFSETS
        dsp_h, dsp_off = P10_WORK_DSP_HEIGHT, P10_WORK_DSP_OFFSETS
        blowout = P10_BLOWOUT_AIR_VOLUME
    else:
        raise RuntimeError(f"Unknown tip_type {step.tip_type!r} for mode {step.mode!r}")

    per_transfer = split_volume(step.volume_ul, step.tip_type)

    print(f"\n=== {step.mode.upper()}: {step.label} ===")
    print(f"PREP: {step.manual_prep}")
    print(f"Source rail35 pos1 col {SOURCE_COL} -> destination rail35 pos0 col {DEST_COL}")
    print(f"Volume: {step.volume_ul} uL x8 as {len(per_transfer)} x {per_transfer[0]:.1f} uL "
          f"{step.tip_type} transfer(s); tip column {tip_col}; discard_tips={discard_tips}")

    await lh.pick_up_tips(tips)
    try:
        for k, vol in enumerate(per_transfer):
            vols = [vol] * 8
            if len(per_transfer) > 1:
                print(f"  transfer {k + 1}/{len(per_transfer)}: {vol:.1f} uL x8")
            print(f"Aspirating {vol:.1f} uL x8 from source col {SOURCE_COL}...")
            await lh.aspirate(
                wells_for_column(r["source_96wp"], SOURCE_COL),
                vols=vols, liquid_height=src_h, offsets=src_off, blow_out_air_volume=[0.0] * 8,
            )
            print(f"Dispensing {vol:.1f} uL x8 to work col {DEST_COL} with blowout {blowout} uL...")
            await lh.dispense(
                wells_for_column(r["work_plate"], DEST_COL),
                vols=vols, liquid_height=dsp_h, offsets=dsp_off, blow_out_air_volume=[blowout] * 8,
            )
        await asyncio.sleep(POST_DISPENSE_SETTLE_SECONDS)
    finally:
        await finish_tips(lh, discard_tips)

    print(f"\nSUCCESS: {step.label} addition completed.")
    print(f"NEXT: {step.manual_stop}")


def make_backend(dry: bool):
    if dry:
        print("Backend: STARChatterboxBackend (DRY - simulated, no hardware movement).")
        return STARChatterboxBackend()
    print("Backend: STARBackend (REAL hardware - human-gated).")
    return STARBackend()


async def main():
    parser = argparse.ArgumentParser(
        description="scRNA-seq staged reagent additions, column 1, swap-source deck."
    )
    parser.add_argument("--mode", choices=["deck"] + list(STEPS.keys()), default="deck")
    parser.add_argument(
        "--dry", action="store_true",
        help="Use STARChatterboxBackend (simulated, no movement). Default is real STARBackend (human-gated).",
    )
    parser.add_argument(
        "--return-tips", action="store_true",
        help="Return tips instead of discarding. Dry rehearsal only; RNA runs MUST discard (the default).",
    )
    parser.add_argument("--tip-col", type=int, default=1, help="Tip column to use. Default: 1.")
    args = parser.parse_args()

    if args.tip_col < 1 or args.tip_col > 12:
        raise ValueError("--tip-col must be 1..12")

    discard_tips = not args.return_tips

    print("Initializing STAR with skip_autoload=True...")
    lh = LiquidHandler(backend=make_backend(args.dry), deck=STARDeck())
    await lh.setup(skip_autoload=True)

    try:
        r = await assign_deck(lh)

        if args.mode == "deck":
            print("\nMode deck: assignment only. No liquid handling executed.")
            return

        step = STEPS[args.mode]
        print(f"Tip behavior: discard_tips={discard_tips} (RNA runs discard; --return-tips is dry-observe only); "
              f"tip column={args.tip_col}")
        await transfer_reagent(lh, r, step, discard_tips, tip_col=args.tip_col)
        return

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

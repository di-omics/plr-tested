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

# NEBNext Single Cell / Low Input RNA library prep (scRNA-seq) - staged reagent additions,
# column 1 only, swap-source.
#
# STATUS: written, simulation-first. NOT yet run on hardware. See scrnaseq/README.md.
#
# What this is
# ------------
# One reagent addition per --mode, into destination/work rail35 pos0 column 1, from a single
# source column at rail35 pos1 column 1 - the same swap-source, single-column, one-add-per-run
# pattern as the verified whole-genome sequencing and targeted PCR master-mix scripts and the emseq scripts. The
# operator loads the reagent named in each mode's PREP line into the source column, runs the
# mode, then swaps in the next reagent. Thermocycling and the SPRI cleanups happen between the
# adds; each mode's STOP line says which ODTC program (if any) runs next. The end-to-end order
# is in run_scrnaseq_odtc_1col_full_dry.py and scrnaseq/README.md.
#
# This implements Section 1 of E6420 ("Protocol for Cells"). Section 2 ("Low Input RNA") is
# the same back half; the only differences are the front-end sample handling and one extra
# 0.5 uL Cell Lysis Buffer in the cDNA amplification mix (E6420 Section 2.4.1). Cells are
# sorted into 5 uL cold 1X Cell Lysis Buffer OFF-DECK (Section 1.2); the work column starts
# holding those 5 uL of lysed cells.
#
# RNA safety: single-cell RNA work is contamination- and RNase-sensitive. Tips are DISCARDED,
# never returned, for real reagent runs (like single-cell whole-genome amplification). --return-tips is for dry
# rehearsal only. Keep reagents cold; Murine RNase Inhibitor is in the lysis buffer.
#
# Reagent map (single column, 8 wells A-H). Volumes per NEB #E6420 manual (v6.0), Section 1.
#
#   mode           add uL  tip  reagent (loaded into source pos1 col1)             -> next ODTC
#   primer-mix      4.0    p10  1 Single Cell RT Primer Mix + 3 water (premix)       sc-anneal
#   rt-mix         11.0    p50  5 RT Buffer + 1 TSO + 2 RT Enzyme + 3 water          sc-rt
#                              (vortex buffer first; add enzyme last)
#   cdna-pcr-mix   80.0    p50  50 cDNA PCR MM + 2 cDNA PCR Primer + 28 water        sc-cdna-pcr
#                              (added as 2 x 40 uL p50 transfers, see split_volume)
#   fs-mix          9.0    p50  7 Ultra II FS Reaction Buffer + 2 FS Enzyme Mix      sc-fs
#                              (vortex enzyme mix first)
#   adaptor         2.5    p10  NEBNext Adaptor for Illumina, diluted 1:25 (0.6 uM)  (none)
#                              (add BEFORE the ligation mix)
#   ligation-mm    31.0    p50  30 Ultra II Ligation MM + 1 Ligation Enhancer        sc-ligation
#   user-enzyme     3.0    p10  USER enzyme (cleaves the NEBNext adaptor)            sc-user
#   pcr-primer     10.0    p50  index primer mix (i7 + i5 combined; one index/well)  (none)
#   pcr-mm         25.0    p50  Ultra II Q5 Master Mix                               sc-lib-pcr
#
# Deck (current 35/48 deck):
#   rail48 pos0 = p10 tips        rail48 pos1 = p50 tips
#   rail35 pos0 = destination/work 96WP, column 1
#   rail35 pos1 = source 96WP/strip, column 1 only (swap the reagent here between modes)
#
# Geometry provenance and its limits (read before a hardware run)
# --------------------------------------------------------------
# The p50 and p10 source->work offsets and heights are reused VERBATIM from the hardware-
# confirmed ampseq/whole-genome amplification-WGA column-1 adds (confirmed 2026-06-15 / 2026-05-12), via the emseq
# scripts. No new coordinate is invented here. As with emseq, those values were tuned for
# adding into a SMALL starting volume; several scRNA adds go into a fuller well (cdna-pcr-mix
# into 20 uL; ligation-mm into 37.5 uL; pcr-mm into 25 uL). The near-bottom dispense height
# (0.5 mm) needs tuning for high-volume adds on the deck before a wet run. This script adds
# and blows out; it does NOT mix on deck (the manual asks for 10x pipette mixing), which stays
# an operator step until tuned. Every mode is sim-only until tuned on hardware.
#
# Tip capacity: p50 transfers are capped at 40 uL of liquid (40 + 6 uL blowout air = 46 < 50),
# so cdna-pcr-mix (80 uL) is delivered as two 40 uL p50 transfers with one tip. p10 adds stay
# at 4 uL or less. Y = 3.20 is blacklisted repo-wide; the dispense Y here is 3.22.

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

# Reused verbatim from the confirmed ampseq/whole-genome amplification-WGA col-1 adds (via emseq scripts).
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
    "primer-mix": Step(
        "primer-mix", "Primer anneal mix", 4.0, "p10", "sc-anneal",
        "Work col 1 A-H should already hold 5 uL of cells lysed in cold 1X NEBNext Cell Lysis "
        "Buffer (sorted off-deck, E6420 Section 1.2; carryover < 1 uL path). Load source col 1 "
        "with the primer anneal premix: 1 uL Single Cell RT Primer Mix + 3 uL nuclease-free "
        "water per reaction.",
        "Seal/spin, then run ODTC sc-anneal (70 C 5 min, 4 C hold, lid 105 C).",
    ),
    "rt-mix": Step(
        "rt-mix", "Reverse transcription + template switching mix", 11.0, "p50", "sc-rt",
        "Work col 1 holds 9 uL annealed sample. Load source col 1 with the RT mix: 5 uL Single "
        "Cell RT Buffer (vortex it first) + 1 uL Template Switching Oligo + 2 uL Single Cell RT "
        "Enzyme Mix (add enzyme LAST) + 3 uL water (E6420 Section 1.4.1).",
        "Seal/spin, then run ODTC sc-rt (42 C 90 min, 70 C 10 min, 4 C hold, lid 105 C).",
    ),
    "cdna-pcr-mix": Step(
        "cdna-pcr-mix", "cDNA amplification mix", 80.0, "p50", "sc-cdna-pcr",
        "Work col 1 holds 20 uL RT product. Load source col 1 with the cDNA amplification mix: "
        "50 uL Single Cell cDNA PCR Master Mix + 2 uL Single Cell cDNA PCR Primer + 28 uL water "
        "(E6420 Section 1.5.1). Load 85-90 uL per source well for margin. Delivered as two 40 "
        "uL p50 transfers.",
        "Seal/spin, then run ODTC sc-cdna-pcr (98 C 45 s; N x [98 C 10 s / 62 C 15 s / 72 C 3 "
        "min]; 72 C 5 min; 4 C hold; lid 105 C). N is input-dependent (default 18 = HEK single "
        "cell; see E6420 table). Then SPRI double-cleanup: scrnaseq_cleanup.py --cleanup post-cdna.",
    ),
    "fs-mix": Step(
        "fs-mix", "Fragmentation / end prep mix", 9.0, "p50", "sc-fs",
        "The post-cdna cleanup keeps 30 uL. Quantify the cleaned cDNA off-deck (Bioanalyzer HS, "
        "E6420 Section 1.7; typical yield 1-20 ng) and normalize to 26 uL before this step, so the "
        "FS reaction is 35 uL (26 + 7 + 2). Load source col 1 with the FS mix: 7 uL Ultra II FS "
        "Reaction Buffer + 2 uL Ultra II FS Enzyme Mix (vortex the enzyme mix 5-8 s first; "
        "E6420 Section 1.8.3).",
        "Seal/spin, then run ODTC sc-fs (37 C 25 min, 65 C 30 min, 4 C hold, lid 75 C).",
    ),
    "adaptor": Step(
        "adaptor", "Adaptor (added before ligation mix)", 2.5, "p10", None,
        "Work col 1 holds 35 uL FS reaction. Load source col 1 with NEBNext Adaptor for Illumina "
        "diluted 1:25 (0.6 uM) in Adaptor Dilution Buffer. Add the adaptor FIRST; do NOT premix "
        "adaptor with the Ligation Master Mix / Enhancer (E6420 Section 1.9.3).",
        "No thermocycling yet. Proceed to mode ligation-mm.",
    ),
    "ligation-mm": Step(
        "ligation-mm", "Ligation enhancer + master mix", 31.0, "p50", "sc-ligation",
        "Work col 1 holds 37.5 uL (FS reaction + adaptor). Load source col 1 with the ligation "
        "mix: 30 uL Ultra II Ligation Master Mix + 1 uL Ligation Enhancer (may be premixed; "
        "stable ~8 h at 4 C). Caution: the Ligation Master Mix is very viscous.",
        "Seal/spin, then run ODTC sc-ligation (20 C 15 min, 4 C hold; manual specifies lid OFF, "
        "run at lid 50 C, see odtc_protocols.py note). Then add USER: mode user-enzyme.",
    ),
    "user-enzyme": Step(
        "user-enzyme", "USER enzyme", 3.0, "p10", "sc-user",
        "Work col 1 holds 68.5 uL ligation reaction. Load source col 1 with USER Enzyme (cleaves "
        "the NEBNext adaptor; required for NEBNext adaptors, E6420 Section 1.9.6).",
        "Seal/spin, then run ODTC sc-user (37 C 15 min, 4 C hold, lid 47 C). Then SPRI cleanup "
        "at 0.8X: scrnaseq_cleanup.py --cleanup post-ligation.",
    ),
    "pcr-primer": Step(
        "pcr-primer", "Index primers", 10.0, "p50", None,
        "Work col 1 holds 15 uL adaptor-ligated DNA. Load source col 1 with the index primer mix, "
        "one index per well A-H (Option B, i7 + i5 combined at 10 uM combined; purchased "
        "separately, E6420 Section 1.11.1B). For Option A (separate i7/i5, 5 uL each) run this "
        "mode twice at 5 uL from two source loads.",
        "No thermocycling yet. Proceed to mode pcr-mm.",
    ),
    "pcr-mm": Step(
        "pcr-mm", "Q5 library PCR master mix", 25.0, "p50", "sc-lib-pcr",
        "Work col 1 holds 25 uL (adaptor-ligated DNA + index primers). Load source col 1 with "
        "NEBNext Ultra II Q5 Master Mix (E6420 Section 1.11.1).",
        "Seal/spin, then run ODTC sc-lib-pcr (98 C 30 s; N x [98 C 10 s / 65 C 75 s]; 65 C 5 min; "
        "4 C hold; lid 105 C). N default 8 for 1-20 ng cDNA (see E6420 table). Then SPRI cleanup "
        "at 0.9X: scrnaseq_cleanup.py --cleanup post-pcr.",
    ),
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

    print("\nGeometry (reused verbatim from confirmed ampseq/PTA-WGA col-1 adds; see header):")
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
        description="scRNA-seq (E6420) staged reagent additions, column 1, swap-source deck."
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

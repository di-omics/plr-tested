import argparse
import asyncio
from dataclasses import dataclass
from typing import Dict, List, Optional

from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends import STARBackend
from pylabrobot.liquid_handling.backends.hamilton.STAR_chatterbox import STARChatterboxBackend
from pylabrobot.resources.hamilton import STARDeck, TIP_CAR_480_A00
from pylabrobot.resources import PLT_CAR_L5AC_A00, CellTreat_96_wellplate_350ul_Fb, Coordinate
import pylabrobot.resources as plr_resources

# EM-seq v2 (UltraShear-coupled) - staged reagent additions, column 1 only, swap-source.
#
# STATUS: written, simulation-first. NOT yet run on hardware. See emseq/README.md.
#
# What this is
# ------------
# One reagent addition per --mode, into destination/work rail35 pos0 column 1, from a
# single source column at rail35 pos1 column 1. This is the same swap-source, single-
# column, one-add-per-run pattern as the verified PTA/WGA and ampseq master-mix scripts
# (00_pta_wga_col1_swap_source_staged..., 01_ampseq_pcr1_mastermix_col1.py). The operator
# loads the reagent named in each mode's PREP line into the source column, runs the mode,
# then swaps in the next reagent. The thermocycling and the SPRI cleanups happen between
# these adds; the STOP line of each mode says which ODTC program (if any) runs next, and
# the end-to-end order is in run_emseq_odtc_1col_full_dry.py and emseq/README.md.
#
# Reagent map (single column, 8 wells A-H). Volumes are per NEB #M7634 Section 3 (the
# UltraShear + EM-seq v2 coupled protocol) and NEB #E8015 (EM-seq v2). The default path
# is the > 10 ng input path (undiluted T4-BGT, elution option A). Control-DNA spike-in,
# the Fe(II) 1:1250 dilution, and (for <= 10 ng) the T4-BGT 1:10 dilution are off-deck
# operator prep, called out in the PREP lines.
#
#   mode          add uL  tip  reagent (loaded into source pos1 col1)         -> next ODTC
#   shear-mm       18.0   p50  UltraShear MM: 14 Rxn Buffer + 4 UltraShear       emseq-shear
#   endprep-mm      5.0   p10  End Prep MM: 2 (500mM DTT, M7634) + 3 EndPrep enz emseq-endprep
#   adaptor         2.5   p10  EM-seq Adaptor (add BEFORE ligation MM)           (none)
#   ligation-mm    31.0   p50  1 Ligation Enhancer + 30 Ultra II Ligation MM     emseq-ligation
#   tet2-mm        17.0   p50  10 TET2 Buffer + 1 UDP-Glucose + 1 DTT +          (none)
#                              1 T4-BGT + 4 TET2                                 (Fe(II) initiates)
#   feii            5.0   p10  Diluted Fe(II) (1:1250 in water, fresh)           emseq-tet2
#   stop            1.0   p10  Stop Reagent                                      emseq-tet2-stop
#   formamide       4.0   p10  Formamide (denaturant)                           emseq-denature
#   deaminate-mm   20.0   p50  14 water + 4 Deamination Buffer + 1 Albumin +     emseq-deaminate
#                              1 APOBEC
#   pcr-primer      5.0   p10  NEBNext LV UDI primer pair (per-well index)       (none)
#   pcr-mm         45.0   p50  NEBNext Q5U Master Mix                            emseq-pcr
#
# Deck (current 35/48 deck):
#   rail48 pos0 = p10 tips
#   rail48 pos1 = p50 tips
#   rail35 pos0 = destination/work 96WP, column 1
#   rail35 pos1 = source 96WP/strip, column 1 only (swap the reagent here between modes)
#
# Geometry provenance and its limit (read before a hardware run)
# -------------------------------------------------------------
# The p50 and p10 source->work offsets and heights below are reused VERBATIM from the
# hardware-confirmed ampseq/PTA-WGA column-1 adds (01_ampseq_pcr1_mastermix_col1.py, p50,
# confirmed 2026-06-15; the PTA/WGA p10 lock 2026-05-12). No new coordinate is invented
# here. BUT those values were tuned for adding a mix INTO a small starting volume (2.5-3
# uL). Several EM-seq adds go into a much fuller well (e.g. pcr-mm 45 uL into 40 uL;
# ligation-mm 31 uL into 51.5 uL). Dispensing at work height 0.5 mm into a half-full well
# may submerge the tip and drag liquid on withdrawal. This is a real tuning item and is
# why every EM-seq mode is sim-only until a person tunes the high-volume dispense on the
# deck, one step at a time, the way every other coordinate in this repo was tuned.
#
# This script adds and blows out; it does NOT mix on deck. The manual asks for 10x pipette
# mixing at most steps. On-deck mixing is deliberately out of scope here (it is new,
# unverified motion) and remains an operator step until tuned.
#
# Y = 3.20 is blacklisted repo-wide (adjacent-channel spacing safety error). The dispense
# Y here is 3.22; do not drop it toward 3.20.

TIP_RAIL = 48
P10_TIP_POS = 0
P50_TIP_POS = 1

LABWARE_RAIL = 35
WORK_POS = 0
SOURCE_96WP_POS = 1

SOURCE_COL = 1
DEST_COL = 1

# Reused verbatim from 01_ampseq_pcr1_mastermix_col1.py (p50, confirmed 2026-06-15).
P50_SOURCE_ASP_HEIGHT = [0.0] * 8
P50_SOURCE_ASP_OFFSETS = [Coordinate(-0.65, 3.35, 0.0)] * 8
P50_WORK_DSP_HEIGHT = [0.5] * 8
P50_WORK_DSP_OFFSETS = [Coordinate(-0.68, 3.22, 0.0)] * 8
P50_BLOWOUT_AIR_VOLUME = 6.0

# Reused verbatim from the PTA/WGA p10 column-1 lock (2026-05-12).
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
    "shear-mm": Step(
        "shear-mm", "UltraShear fragmentation master mix", 18.0, "p50", "emseq-shear",
        "Work col 1 A-H should already hold 26 uL of combined gDNA + control DNA (0.1-200 ng "
        "sample + lambda + pUC19, made up to 26 uL with 1X TE; off-deck, M7634 Section 3.1.1). "
        "Load source col 1 with UltraShear master mix (14 uL Reaction Buffer + 4 uL UltraShear "
        "per reaction). Recommended source load: 24-28 uL per well for margin.",
        "Seal/spin, then run ODTC emseq-shear (37 C default 30 min, 65 C 15 min, 4 C hold, "
        "lid 75 C) via instrument-integrations/odtc.",
    ),
    "endprep-mm": Step(
        "endprep-mm", "Coupled End Prep master mix", 5.0, "p10", "emseq-endprep",
        "Work col 1 holds 44 uL fragmented DNA. Load source col 1 with End Prep master mix: "
        "2 uL 500 mM DTT (the green DTT from M7634, NOT the yellow EM-seq DTT) + 3 uL Ultra II "
        "End Prep Enzyme Mix. The EM-seq End Prep Reaction Buffer is NOT used in the coupled "
        "protocol (M7634 Section 3.2.1).",
        "Seal/spin, then run ODTC emseq-endprep (20 C 15 min, 65 C 15 min, 4 C hold, lid 75 C).",
    ),
    "adaptor": Step(
        "adaptor", "EM-seq adaptor (added before ligation mix)", 2.5, "p10", None,
        "Work col 1 holds 49 uL End Prep reaction. Load source col 1 with NEBNext EM-seq "
        "Adaptor. Add the adaptor to the sample FIRST; do NOT premix adaptor with the Ligation "
        "Enhancer/Master Mix (M7634 Section 3.3.1).",
        "No thermocycling yet. Proceed to mode ligation-mm.",
    ),
    "ligation-mm": Step(
        "ligation-mm", "Ligation enhancer + master mix", 31.0, "p50", "emseq-ligation",
        "Work col 1 holds 51.5 uL (End Prep + adaptor). Load source col 1 with the ligation mix: "
        "1 uL Ligation Enhancer + 30 uL Ultra II Ligation Master Mix per reaction (may be premixed; "
        "stable ~8 h at 4 C). Caution: the Ligation Master Mix is viscous.",
        "Seal/spin, then run ODTC emseq-ligation (20 C 15 min, 4 C hold; manual specifies lid OFF, "
        "run at lid 50 C, see odtc_protocols.py note). Then SPRI cleanup at 1.1X: emseq_cleanup.py "
        "--cleanup post-ligation.",
    ),
    "tet2-mm": Step(
        "tet2-mm", "TET2 protection master mix", 17.0, "p50", None,
        "Work col 1 holds 28 uL adaptor-ligated, cleaned DNA (elution option A, > 10 ng input). "
        "Load source col 1 with TET2 master mix: 10 uL TET2 Reaction Buffer (Supplement already "
        "reconstituted) + 1 uL UDP-Glucose + 1 uL DTT (yellow) + 1 uL T4-BGT (undiluted for > 10 ng; "
        "1:10 diluted for <= 10 ng) + 4 uL TET2 (E8015 Section 1.5.3).",
        "No thermocycling yet; oxidation is initiated by Fe(II) in the next mode. Proceed to mode feii.",
    ),
    "feii": Step(
        "feii", "Diluted Fe(II) solution", 5.0, "p10", "emseq-tet2",
        "Work col 1 holds 45 uL TET2 reaction. Prepare diluted Fe(II) FRESH off-deck (1 uL of "
        "500 mM Fe(II) into 1249 uL water) and load source col 1. Use immediately; do not store "
        "(E8015 Section 1.5.4).",
        "Seal/spin, then run ODTC emseq-tet2 (37 C 1 h, 4 C hold, lid 45 C).",
    ),
    "stop": Step(
        "stop", "Stop reagent", 1.0, "p10", "emseq-tet2-stop",
        "Work col 1 holds 50 uL. Load source col 1 with Stop Reagent (yellow) (E8015 Section 1.5.6).",
        "Seal/spin, then run ODTC emseq-tet2-stop (37 C 30 min, 4 C hold, lid 45 C). Then SPRI "
        "cleanup at 1X: emseq_cleanup.py --cleanup post-tet2.",
    ),
    "formamide": Step(
        "formamide", "Formamide denaturant", 4.0, "p10", "emseq-denature",
        "Work col 1 holds 16 uL protected, cleaned DNA. Load source col 1 with Formamide "
        "(recommended denaturant; 0.05 N NaOH is the alternative, E8015 Section 1.7). Pre-heat "
        "the ODTC to 85 C / lid 105 C before this step.",
        "Seal/spin, then run ODTC emseq-denature (85 C 10 min, 4 C hold, lid 105 C). The manual "
        "cools on ice off-instrument; here the block holds 4 C (see odtc_protocols.py note).",
    ),
    "deaminate-mm": Step(
        "deaminate-mm", "APOBEC deamination master mix", 20.0, "p50", "emseq-deaminate",
        "Work col 1 holds 20 uL denatured DNA. Load source col 1 with deamination master mix: "
        "14 uL nuclease-free water + 4 uL Deamination Reaction Buffer + 1 uL Recombinant Albumin "
        "+ 1 uL APOBEC (E8015 Section 1.8.1).",
        "Seal/spin, then run ODTC emseq-deaminate (37 C 3 h, 4 C hold, lid 45 C). Samples go "
        "directly to PCR with no cleanup.",
    ),
    "pcr-primer": Step(
        "pcr-primer", "UDI index primer pair", 5.0, "p10", None,
        "Work col 1 holds 40 uL deaminated DNA. Load source col 1 with the NEBNext LV Unique Dual "
        "Index primer pairs, one index per well A-H (purchased separately; E8015 Section 1.9.1). "
        "Each well gets its own index.",
        "No thermocycling yet. Proceed to mode pcr-mm.",
    ),
    "pcr-mm": Step(
        "pcr-mm", "Q5U PCR master mix", 45.0, "p50", "emseq-pcr",
        "Work col 1 holds 45 uL (deaminated DNA + index primer). Load source col 1 with NEBNext "
        "Q5U Master Mix (E8015 Section 1.9.1).",
        "Seal/spin, then run ODTC emseq-pcr (98 C 30 s; N x [98 C 10 s / 62 C 30 s / 65 C 60 s]; "
        "65 C 5 min; 4 C hold; lid 105 C). N is input-dependent (default 8 = 10 ng; see the E8015 "
        "table). Then SPRI cleanup at 0.8X: emseq_cleanup.py --cleanup post-pcr.",
    ),
}


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
    print("Assigning EM-seq reagent-add deck: current 35/48 swap-source column-1 layout...")

    tip_carrier = TIP_CAR_480_A00(name="tip_car_rail48")
    labware_carrier = PLT_CAR_L5AC_A00(name="labware_car_rail35")
    lh.deck.assign_child_resource(tip_carrier, rails=TIP_RAIL)
    lh.deck.assign_child_resource(labware_carrier, rails=LABWARE_RAIL)

    p10_tips = make_p10_tips("r48_pos0_p10_filter_tips")
    p50_tips = make_p50_tips("r48_pos1_p50_filter_tips")
    work_plate = CellTreat_96_wellplate_350ul_Fb(name="rail35_pos0_emseq_work_96wp")
    source_96wp = CellTreat_96_wellplate_350ul_Fb(name="rail35_pos1_emseq_reagent_source_96wp")

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
          f"blowout {P50_BLOWOUT_AIR_VOLUME} uL")
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
    vols = [step.volume_ul] * 8

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

    print(f"\n=== {step.mode.upper()}: {step.label} ===")
    print(f"PREP: {step.manual_prep}")
    print(f"Source rail35 pos1 col {SOURCE_COL} -> destination rail35 pos0 col {DEST_COL}")
    print(f"Volume: {step.volume_ul} uL x8; tip {step.tip_type} column {tip_col}; discard_tips={discard_tips}")

    await lh.pick_up_tips(tips)
    try:
        print(f"Aspirating {step.volume_ul} uL x8 from source col {SOURCE_COL}...")
        await lh.aspirate(
            wells_for_column(r["source_96wp"], SOURCE_COL),
            vols=vols,
            liquid_height=src_h,
            offsets=src_off,
            blow_out_air_volume=[0.0] * 8,
        )
        print(f"Dispensing {step.volume_ul} uL x8 to work col {DEST_COL} with blowout {blowout} uL...")
        await lh.dispense(
            wells_for_column(r["work_plate"], DEST_COL),
            vols=vols,
            liquid_height=dsp_h,
            offsets=dsp_off,
            blow_out_air_volume=[blowout] * 8,
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
        description="EM-seq v2 (UltraShear-coupled) staged reagent additions, column 1, swap-source deck."
    )
    parser.add_argument("--mode", choices=["deck"] + list(STEPS.keys()), default="deck")
    parser.add_argument(
        "--dry",
        action="store_true",
        help="Use STARChatterboxBackend (simulated, no movement). Default is real STARBackend (human-gated).",
    )
    parser.add_argument(
        "--return-tips",
        action="store_true",
        help="Return tips instead of discarding. Use for dry observation. Default is production-style discard.",
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
        print(f"Production tip behavior: discard_tips={discard_tips}; tip column={args.tip_col}")
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

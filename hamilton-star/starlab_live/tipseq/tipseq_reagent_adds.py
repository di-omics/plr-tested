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

# TIP-seq (targeted insertion of promoters sequencing) - staged reagent additions, column 1
# only, swap-source. Covers the automatable T7 linear-amplification + library back half.
#
# STATUS: written, simulation-first. NOT yet run on hardware. See tipseq/README.md.
#
# What this is
# ------------
# One reagent addition per --mode, into destination/work rail35 pos0 column 1, from a single
# source column at rail35 pos1 column 1 - the same swap-source, single-column, one-add-per-run
# pattern as the verified PTA/WGA and targeted PCR master-mix scripts and the emseq/scrnaseq scripts.
#
# TIP-seq combines CUT&Tag pA-Tn5 tagmentation with T7 linear amplification. The CUT&Tag front
# end (conA beads, primary/secondary antibody, pA-Tn5 binding, tagmentation, and - for single
# cell / sciTIP - FACS sorting) is OFF-DECK / operator work; it is not a liquid-handler-standard
# flow. Automation begins after the tagmented gDNA is SPRI-purified and the DNA + SPRI beads are
# resuspended in 8 uL water (the paper's "single-tube" back half). The SPRI beads are RETAINED in
# the well through IVT, RT, and second-strand synthesis, and are re-bound with SPRI binding buffer
# at each cleanup (see tipseq_cleanup.py); they are only left behind at the final DNA purification.
#
# Source: Bartlett et al., "High-throughput single-cell epigenomic profiling by targeted
# insertion of promoters (TIP-seq)", J. Cell Biol. 2021, 220(12):e202103078. Materials and
# methods, "Bulk TIP-seq". Volumes transcribed from that section.
#
# RNA safety: TIP-seq carries RNA intermediates (post-IVT RNA, first-strand RT). Tips are
# DISCARDED, never returned, for real reagent runs. --return-tips is for dry rehearsal only.
#
# Reagent map (single column, 8 wells A-H). GuHCl (Tn5 stop before the final DNA cleanup) is an
# operator/off-deck add (its volume is stock-dependent to reach 4 M final), not a robot mode.
#
#   mode          add uL  tip  reagent (loaded into source pos1 col1)                -> next ODTC
#   gapfill-mix   2.0    p10  Taq 5X Master Mix (M0285)                               tip-gapfill
#   ivt-mix       6.3    p50  2 NTP (100 mM) + 2 10X T7 buffer + 2 T7 pol mix +       tip-ivt
#                             0.3 RNase inhibitor (HiScribe T7, E2040S)
#   hexamer       2.5    p10  random hexamer (20 uM)                                  tip-rt-anneal
#   rt-mix        8.5    p50  4 5X first-strand buffer + 2 dNTP (10 mM) + 2 DTT       tip-rt
#                             (100 mM) + 0.5 SMART MMLV RT (Takara 639524)
#   rnaseh        1.0    p10  RNase H, 1:10 dilution of 5 U/uL                        tip-rnaseh
#   sss-oligo     2.5    p10  second-strand oligo (sss_scnXTv2 / sss_scinXTv2)        tip-ss-anneal
#   ss-taq        5.9    p50  Taq 5X Master Mix (M0285)                               tip-ss
#   tn5-mix       4.0    p10  2 TAPS buffer + 2 Tn5 (ME-B only, 0.7 uM)               tip-tag
#   pcr-mix      24.0    p50  20 NEBNext High-Fidelity 2X PCR MM (M0541L) +           tip-pcr
#                             2 index primers (10 uM) + 2 i7 indexes (10 uM)
#
# Deck (current 35/48 deck):
#   rail48 pos0 = p10 tips        rail48 pos1 = p50 tips
#   rail35 pos0 = destination/work 96WP, column 1
#   rail35 pos1 = source 96WP/strip, column 1 only (swap the reagent here between modes)
#
# Geometry provenance and its limits
# ----------------------------------
# The p50 and p10 source->work offsets and heights are reused VERBATIM from the hardware-confirmed
# targeted PCR/PTA-WGA column-1 adds (via the emseq/scrnaseq scripts). No new coordinate is invented.
# Those values were tuned for adding into a SMALL starting volume and for wells WITHOUT beads; the
# TIP-seq well holds SPRI beads from the start, so the dispense height and mixing need tuning on the
# deck before a wet run. This script adds and blows out; it does NOT mix on deck (the paper mixes
# by pipetting/vortex), which stays an operator step until tuned. Every mode is sim-only until tuned.
# p10 adds stay within the hardware-confirmed whole-genome amplification envelope: up to 6 uL of liquid plus the 7 uL
# blowout air (the whole-genome sequencing reaction add, 6 uL p10, is confirmed on hardware; liquid+blowout of
# ~13 uL sits above the 10 uL tip nominal but is what the confirmed bo7 add uses). The cap is 6 uL
# and the largest p10 add here is tn5-mix at 4 uL. Controls (IgG negative, positive antibody) are
# OFF-DECK / manual in this single-column version; this script runs one reaction column.
# Y = 3.20 is blacklisted repo-wide; the dispense Y here is 3.22.

TIP_RAIL = 48
P10_TIP_POS = 0
P50_TIP_POS = 1

LABWARE_RAIL = 35
WORK_POS = 0
SOURCE_96WP_POS = 1

SOURCE_COL = 1
DEST_COL = 1

# Confirmed p10 ceiling: the whole-genome sequencing reaction add of 6 uL p10 (blowout 7) is hardware-confirmed.
P10_MAX_TRANSFER_UL = 6.0
P50_MAX_TRANSFER_UL = 40.0
# Highest confirmed p10 plunger demand (liquid + blowout air), used as a --dry sanity guard.
P10_CONFIRMED_ENVELOPE_UL = 13.0

# Reused verbatim from the confirmed targeted PCR/PTA-WGA col-1 adds (via emseq/scrnaseq scripts).
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
    tip_type: str
    next_odtc: Optional[str]
    manual_prep: str
    manual_stop: str


STEPS: Dict[str, Step] = {
    "gapfill-mix": Step(
        "gapfill-mix", "Taq gap-fill mix", 2.0, "p10", "tip-gapfill",
        "Work col 1 A-H should already hold 8 uL of SPRI-purified tagmented gDNA + retained SPRI "
        "beads in water (CUT&Tag + pA-Tn5 tagmentation + first SPRI done off-deck; Bulk TIP-seq). "
        "Load source col 1 with Taq 5X Master Mix (M0285).",
        "Seal/spin, then run ODTC tip-gapfill (72 C 3 min, 4 C hold, lid 105 C).",
    ),
    "ivt-mix": Step(
        "ivt-mix", "T7 IVT mix", 6.3, "p50", "tip-ivt",
        "Work col 1 holds 10 uL gap-filled reaction (beads retained). Load source col 1 with the "
        "T7 IVT mix (HiScribe T7, E2040S): 2 uL NTP (100 mM) + 2 uL 10X T7 reaction buffer + 2 uL "
        "T7 polymerase mix + 0.3 uL RNase inhibitor per reaction.",
        "Seal/spin, then run ODTC tip-ivt (37 C for 16-19 h, default 17 h; 4 C hold; lid 47 C). "
        "This is an overnight hold; launch it detached on the Pi. Then SPRI cleanup: "
        "tipseq_cleanup.py --cleanup post-ivt (RNA, elute 9 uL RNase-free water).",
    ),
    "hexamer": Step(
        "hexamer", "Random hexamer", 2.5, "p10", "tip-rt-anneal",
        "Work col 1 holds 9 uL purified RNA (beads retained). Load source col 1 with random "
        "hexamer (20 uM).",
        "Seal/spin, then run ODTC tip-rt-anneal (70 C 3 min, 4 C hold, lid 105 C).",
    ),
    "rt-mix": Step(
        "rt-mix", "First-strand RT mix", 8.5, "p50", "tip-rt",
        "Work col 1 holds 11.5 uL annealed sample. Load source col 1 with the first-strand mix "
        "(SMART MMLV, Takara 639524): 4 uL 5X first-strand buffer + 2 uL dNTP (10 mM) + 2 uL DTT "
        "(100 mM) + 0.5 uL SMART MMLV RT per reaction.",
        "Seal/spin, then run ODTC tip-rt (22 C 10 min, 42 C 60 min, 70 C 10 min, 4 C hold, lid 105 C).",
    ),
    "rnaseh": Step(
        "rnaseh", "RNase H", 1.0, "p10", "tip-rnaseh",
        "Work col 1 holds 20 uL first-strand reaction. Load source col 1 with RNase H, a 1:10 "
        "dilution of 5 U/uL, to degrade RNA in cDNA-RNA hybrids.",
        "Seal/spin, then run ODTC tip-rnaseh (37 C 20 min, 4 C hold, lid 47 C).",
    ),
    "sss-oligo": Step(
        "sss-oligo", "Second-strand oligo", 2.5, "p10", "tip-ss-anneal",
        "Work col 1 holds 21 uL. Load source col 1 with the second-strand synthesis oligo (20 uM; "
        "sss_scnXTv2 for bulk, sss_scinXTv2 for sciTIP; anneals downstream of the T7 promoter TSS).",
        "Seal/spin, then run ODTC tip-ss-anneal (65 C 2 min, 4 C hold, lid 105 C).",
    ),
    "ss-taq": Step(
        "ss-taq", "Second-strand Taq mix", 5.9, "p50", "tip-ss",
        "Work col 1 holds 23.5 uL. Load source col 1 with Taq 5X Master Mix (M0285) for "
        "second-strand synthesis.",
        "Seal/spin, then run ODTC tip-ss (72 C 8 min, 4 C hold, lid 105 C). Then SPRI cleanup: "
        "tipseq_cleanup.py --cleanup post-ss (cDNA, elute 7 uL water).",
    ),
    "tn5-mix": Step(
        "tn5-mix", "Tn5 fragmentation mix", 4.0, "p10", "tip-tag",
        "Work col 1 holds 7 uL purified cDNA (beads retained). Load source col 1 with the Tn5 mix: "
        "2 uL TAPS buffer + 2 uL Tn5 (ME-B adapters only, 0.7 uM) per reaction.",
        "Seal/spin, then run ODTC tip-tag (55 C 6 min, 4 C hold, lid 105 C). Then (operator) add "
        "GuHCl to 4 M final and vortex to degrade Tn5 (volume is stock-dependent). Then SPRI "
        "cleanup: tipseq_cleanup.py --cleanup post-tag (DNA, elute 16 uL, transfer off the beads).",
    ),
    "pcr-mix": Step(
        "pcr-mix", "Indexing PCR mix", 24.0, "p50", "tip-pcr",
        "Work col 1 holds 16 uL purified DNA (moved off the beads into a fresh column). Load source "
        "col 1 with the PCR mix: 20 uL NEBNext High-Fidelity 2X PCR MM (M0541L) + 2 uL index primers "
        "(10 uM) + 2 uL i7 indexes (10 uM), one index combination per well.",
        "Seal/spin, then run ODTC tip-pcr (72 C 5 min gap fill; 98 C 30 s; N x [98 C 10 s / 63 C "
        "30 s]; 72 C 1 min; 8 C hold; lid 105 C). N is optimized per sample (bulk ~7-9, sciTIP "
        "7-12; default 8). Then SPRI cleanup: tipseq_cleanup.py --cleanup post-pcr (0.85X left-side "
        "size select, > 200 bp).",
    ),
}


def split_volume(total_ul: float, tip_type: str) -> List[float]:
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
    print("Assigning TIP-seq reagent-add deck: current 35/48 swap-source column-1 layout...")

    tip_carrier = TIP_CAR_480_A00(name="tip_car_rail48")
    labware_carrier = PLT_CAR_L5AC_A00(name="labware_car_rail35")
    lh.deck.assign_child_resource(tip_carrier, rails=TIP_RAIL)
    lh.deck.assign_child_resource(labware_carrier, rails=LABWARE_RAIL)

    p10_tips = make_p10_tips("r48_pos0_p10_filter_tips")
    p50_tips = make_p50_tips("r48_pos1_p50_filter_tips")
    work_plate = CellTreat_96_wellplate_350ul_Fb(name="rail35_pos0_tipseq_work_96wp")
    source_96wp = CellTreat_96_wellplate_350ul_Fb(name="rail35_pos1_tipseq_reagent_source_96wp")

    tip_carrier[P10_TIP_POS] = p10_tips
    tip_carrier[P50_TIP_POS] = p50_tips
    labware_carrier[WORK_POS] = work_plate
    labware_carrier[SOURCE_96WP_POS] = source_96wp

    print("\nDeck:")
    print("  rail48 pos0 = p10 tips")
    print("  rail48 pos1 = p50 tips")
    print("  rail35 pos0 = destination/work 96WP, column 1 (holds DNA + retained SPRI beads)")
    print("  rail35 pos1 = source 96WP/strip, SOURCE COLUMN 1 ONLY (swap reagent between modes)")

    print("\nGeometry (reused verbatim from confirmed targeted PCR/PTA-WGA col-1 adds; see header):")
    print(f"  P50 source asp height {P50_SOURCE_ASP_HEIGHT[0]}, work dsp height {P50_WORK_DSP_HEIGHT[0]}, "
          f"blowout {P50_BLOWOUT_AIR_VOLUME} uL, max {P50_MAX_TRANSFER_UL} uL/transfer")
    print(f"  P10 source asp height {P10_SOURCE_ASP_HEIGHT[0]}, work dsp height {P10_WORK_DSP_HEIGHT[0]}, "
          f"blowout {P10_BLOWOUT_AIR_VOLUME} uL, max {P10_MAX_TRANSFER_UL} uL/transfer")

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

    # Sanity guard: PLR's --dry VolumeTracker checks liquid volume but not blowout air, so a future
    # mistune could overfill a p10 tip only on hardware. Fail loudly here instead.
    if step.tip_type == "p10":
        for vol in per_transfer:
            if vol + blowout > P10_CONFIRMED_ENVELOPE_UL:
                raise ValueError(
                    f"{step.mode}: p10 transfer {vol:.1f} uL + {blowout} uL blowout exceeds the "
                    f"confirmed {P10_CONFIRMED_ENVELOPE_UL} uL envelope; split further or use p50")

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
        description="TIP-seq staged reagent additions (T7 linear-amp + library), column 1, swap-source deck."
    )
    parser.add_argument("--mode", choices=["deck"] + list(STEPS.keys()), default="deck")
    parser.add_argument(
        "--dry", action="store_true",
        help="Use STARChatterboxBackend (simulated, no movement). Default is real STARBackend (human-gated).",
    )
    parser.add_argument(
        "--return-tips", action="store_true",
        help="Return tips instead of discarding. Dry rehearsal only; real runs MUST discard (the default).",
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
        print(f"Tip behavior: discard_tips={discard_tips} (real runs discard; --return-tips is dry-observe only); "
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

import argparse
import asyncio
from dataclasses import dataclass
from typing import Dict, List

from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends import STARBackend
from pylabrobot.liquid_handling.backends.hamilton.STAR_chatterbox import STARChatterboxBackend
from pylabrobot.resources.hamilton import STARDeck, TIP_CAR_480_A00
from pylabrobot.resources import (
    PLT_CAR_L5AC_A00,
    CellTreat_12_troughplate_15000ul_Vb,
    CellTreat_96_wellplate_350ul_Fb,
    Coordinate,
)
import pylabrobot.resources as plr_resources

# TIP-seq - SPRI bead cleanup, column 1, on the magnet.
#
# STATUS: written, simulation-first. NOT yet run on hardware. See tipseq/README.md.
#
# What this is
# ------------
# TIP-seq keeps the SAME SPRI beads in the well from tagmentation onward. Each intermediate
# cleanup RE-BINDS nucleic acid to those retained beads by adding 2.0X SPRI binding buffer
# (20% PEG 8000, 2.5 M NaCl, 10 mM Tris, 1 mM EDTA), rather than adding fresh beads. Only the
# final library cleanup uses fresh beads for a 0.85X left-side size selection. (Source: Bartlett
# et al., TIP-seq, JCB 2021, e202103078, Materials and methods, Bulk TIP-seq.)
#
#   --cleanup      kind                 bind                elute              source
#   post-ivt       reactivation         2.0X binding buffer 9 uL RNase-free H2O  Bulk TIP-seq (RNA)
#   post-ss        reactivation         2.0X binding buffer 7 uL H2O             Bulk TIP-seq (cDNA)
#   post-tag       reactivation-final   2.0X binding buffer 16 uL H2O, off beads Bulk TIP-seq (DNA)
#   post-pcr       sizeselect           0.85X fresh beads    ~21 uL, > 200 bp     Bulk TIP-seq (library)
#
# This is the emseq/scrnaseq cleanup script generalized: same mag+trough geometry (reused VERBATIM
# from the hardware-confirmed ampseq cleanup), same standard leg set. The "bind-add" leg adds SPRI
# binding buffer to the retained beads for reactivation cleanups, or fresh beads for the size
# selection. Any single leg is a valid --mode for step-by-step tuning. RNA/library runs DISCARD
# tips (the default); --return-tips is for dry rehearsal only.
#
# Deck (current 35/48 deck):
#   rail48 pos1 = p50 tips (elution add, residual ethanol removal)
#   rail48 pos2 = p300 tips (bind add, supernatant/ethanol removal)
#   rail35 pos2 = magnet, holding the work plate (moved here by iSWAP), column 1
#   rail35 pos3 = 12-well reservoir/trough
#
# Reservoir map (rail35 pos3):
#   A1 = fresh SPRI beads (post-pcr 0.85X)     A2/A3 = 80% ethanol
#   A4 = RNase-free water (post-ivt elution)   A5 = SPRI binding buffer (2.0X reactivation)
#   A6 = nuclease-free water (post-ss / post-tag elution)
#   A7 = 10 mM Tris pH 8.0 (post-pcr final library elution)      A12 = waste
#
# Scope and honesty
# -----------------
# Incubation, bead pelleting, and air-dry timings are operator/timed and not modeled. The retained
# beads are already in the well for the reactivation cleanups; the geometry (tuned for beadless
# wells) needs tuning on the deck. The post-tag reaction volume includes operator-added GuHCl to
# 4 M final (stock-dependent), so its bind/supernatant volumes are estimates and flagged. post-pcr
# elution volume and the left-side size-selection are user-chosen; the value here is a placeholder
# for the plate flow. All geometry is inherited, not re-tuned for TIP-seq; every mode is sim-only.
# Controls (IgG negative, positive antibody) are OFF-DECK / manual in this single-column version;
# this script cleans one column.

TIP_RAIL = 48
P50_TIP_POS = 1
P300_TIP_POS = 2

LABWARE_RAIL = 35
MAG_POS = 2
TROUGH_POS = 3

DEST_COL = 1

TROUGH_BEADS = "A1"
TROUGH_ETOH1 = "A2"
TROUGH_ETOH2 = "A3"
TROUGH_RNA_ELUTION = "A4"     # RNase-free water
TROUGH_BINDING = "A5"         # SPRI binding buffer (20% PEG), reactivation
TROUGH_WATER = "A6"           # nuclease-free water (cDNA/DNA elution)
TROUGH_TRIS = "A7"            # 10 mM Tris pH 8.0 (final library elution)
TROUGH_WASTE = "A12"

VOL_ETHANOL_ADD = 200.0
VOL_ETHANOL_REMOVE = 200.0
VOL_RESIDUAL_ETHANOL_REMOVE = 20.0

P50_ELUTION_MAX_UL = 40.0


@dataclass
class Cleanup:
    name: str
    ratio_label: str
    kind: str                 # "reactivation", "reactivation-final", "sizeselect"
    bind_ul: float            # binding buffer (reactivation) or fresh beads (sizeselect)
    bind_source: str
    supernatant_remove_ul: float
    elution_ul: float
    elution_source: str
    keep_ul: float
    source: str


CLEANUPS: Dict[str, Cleanup] = {
    # 16.3 uL IVT + 33 uL binding buffer (2.0X) = ~49 bound; remove 55. Elute 9 uL RNase-free water.
    "post-ivt": Cleanup("post-ivt", "2.0X", "reactivation", 33.0, TROUGH_BINDING, 55.0,
                        9.0, TROUGH_RNA_ELUTION, 9.0, "TIP-seq Bulk (RNA purify)"),
    # 29.4 uL second-strand + 59 uL binding buffer (2.0X) = ~88 bound; remove 92. Elute 7 uL water.
    "post-ss": Cleanup("post-ss", "2.0X", "reactivation", 59.0, TROUGH_BINDING, 92.0,
                       7.0, TROUGH_WATER, 7.0, "TIP-seq Bulk (cDNA purify)"),
    # ~33 uL (11 tag + GuHCl to 4M, stock-dependent) + 66 uL binding buffer (2.0X) = ~99; remove 105.
    # Elute 16 uL water and transfer OFF the beads to a fresh column.
    "post-tag": Cleanup("post-tag", "2.0X", "reactivation-final", 66.0, TROUGH_BINDING, 105.0,
                        16.0, TROUGH_WATER, 16.0, "TIP-seq Bulk (DNA purify)"),
    # 40 uL PCR + 34 uL fresh beads (0.85X, left-side size select > 200 bp) = 74; remove 78. Elute ~21.
    "post-pcr": Cleanup("post-pcr", "0.85X", "sizeselect", 34.0, TROUGH_BEADS, 78.0,
                        21.0, TROUGH_TRIS, 21.0, "TIP-seq Bulk (library, left-side size select)"),
}

# Geometry reused verbatim from the confirmed ampseq cleanup (via emseq/scrnaseq). No TIP-seq tuning.
P300_TROUGH_ASP_HEIGHT = [0.3] * 8
P300_TROUGH_ASP_OFFSETS = [Coordinate(0.0, 1.5, 0.0)] * 8
P300_MAG_DSP_HEIGHT = [4.0] * 8
P300_MAG_DSP_OFFSETS = [Coordinate(0.28, 3.00, 14.5)] * 8
P300_MAG_REMOVE_ASP_HEIGHT = [16.0] * 8
P300_MAG_REMOVE_ASP_OFFSETS = [Coordinate(0.28, 3.35, 0.0)] * 8
P300_WASTE_DSP_HEIGHT = [12.0] * 8
P300_WASTE_DSP_OFFSETS = [Coordinate(0.0, 1.5, 0.0)] * 8
P300_ADD_BLOWOUT_AIR_VOLUME = 3.0
P300_REMOVE_BLOWOUT_AIR_VOLUME = 2.0

P50_MAG_RESIDUAL_ASP_HEIGHT = [8.0] * 8
P50_MAG_RESIDUAL_ASP_OFFSETS = [Coordinate(0.28, 3.35, 0.0)] * 8
P50_WASTE_DSP_HEIGHT = [8.0] * 8
P50_WASTE_DSP_OFFSETS = [Coordinate(0.0, 1.5, 0.0)] * 8
P50_RESIDUAL_BLOWOUT_AIR_VOLUME = 2.0

P50_LOW_TROUGH_ASP_HEIGHT = [2.0] * 8
P50_LOW_TROUGH_ASP_OFFSETS = [Coordinate(0.0, 1.5, 0.0)] * 8
P50_LOW_MAG_DSP_HEIGHT = [3.0] * 8
P50_LOW_MAG_DSP_OFFSETS = [Coordinate(0.28, 2.20, 16.0)] * 8
P50_LOW_ADD_BLOWOUT_AIR_VOLUME = 4.0

P50_TIP_FACTORY_CANDIDATES = ["hamilton_96_tiprack_50uL_filter", "hamilton_96_tiprack_50ul_filter"]
P300_TIP_FACTORY_CANDIDATES = [
    "hamilton_96_tiprack_300uL_filter",
    "hamilton_96_tiprack_300ul_filter",
    "hamilton_96_tiprack_300uL_filter_slim",
    "hamilton_96_tiprack_300ul_filter_slim",
]


def make_resource(label: str, name: str, candidates: List[str], terms: List[str]):
    for factory_name in candidates:
        factory = getattr(plr_resources, factory_name, None)
        if factory is not None:
            print(f"Using {label} resource factory: {factory_name}")
            return factory(name=name)
    terms_lower = [term.lower() for term in terms]
    available = sorted(n for n in dir(plr_resources) if any(term in n.lower() for term in terms_lower))
    raise RuntimeError(f"Could not find factory for {label}. Tried {candidates}. Nearby: {available[:100]}")


def make_p50_tips(name: str):
    return make_resource("p50 filter tips", name, P50_TIP_FACTORY_CANDIDATES, ["tip", "50"])


def make_p300_tips(name: str):
    return make_resource("p300 filter tips", name, P300_TIP_FACTORY_CANDIDATES, ["tip", "300"])


def wells_for_column(plate, col: int):
    return plate[f"A{col}:H{col}"]


async def assign_deck(lh: LiquidHandler, cleanup: Cleanup) -> Dict[str, object]:
    print(f"Assigning TIP-seq {cleanup.name} cleanup deck ({cleanup.ratio_label}, {cleanup.kind}): "
          "mag pos2 + trough pos3...")

    tip_carrier = TIP_CAR_480_A00(name="tip_car_rail48")
    labware_carrier = PLT_CAR_L5AC_A00(name="labware_car_rail35")
    lh.deck.assign_child_resource(tip_carrier, rails=TIP_RAIL)
    lh.deck.assign_child_resource(labware_carrier, rails=LABWARE_RAIL)

    p50_tips = make_p50_tips("r48_pos1_p50_filter_tips")
    p300_tips = make_p300_tips("r48_pos2_p300_filter_tips")
    mag_plate = CellTreat_96_wellplate_350ul_Fb(name="rail35_pos2_tipseq_cleanup_mag_96wp")
    trough = CellTreat_12_troughplate_15000ul_Vb(name="rail35_pos3_tipseq_cleanup_12w_reservoir")

    tip_carrier[P50_TIP_POS] = p50_tips
    tip_carrier[P300_TIP_POS] = p300_tips
    labware_carrier[MAG_POS] = mag_plate
    labware_carrier[TROUGH_POS] = trough

    bind_kind = "fresh SPRI beads" if cleanup.kind == "sizeselect" else "SPRI binding buffer (reactivate retained beads)"
    print("\nDeck:")
    print("  rail48 pos1 = p50 tips (elution, residual ethanol)")
    print("  rail48 pos2 = p300 tips (bind add, supernatant/ethanol removal)")
    print("  rail35 pos2 = magnet + work plate, column 1 (retained beads present)")
    print("  rail35 pos3 = 12-well reservoir/trough")

    print(f"\n{cleanup.name} volumes ({cleanup.source}):")
    print(f"  bind add = {cleanup.bind_ul} uL x8 ({cleanup.ratio_label}) from {cleanup.bind_source}: {bind_kind}")
    print(f"  supernatant remove = {cleanup.supernatant_remove_ul} uL x8, p300")
    print(f"  ethanol add/remove = {VOL_ETHANOL_ADD}/{VOL_ETHANOL_REMOVE} uL x8, p300 (x2 washes)")
    print(f"  residual ethanol remove = {VOL_RESIDUAL_ETHANOL_REMOVE} uL x8, p50")
    print(f"  elution add = {cleanup.elution_ul} uL from {cleanup.elution_source}; keep {cleanup.keep_ul} uL")
    if cleanup.kind == "reactivation-final":
        print("  then transfer the eluate OFF the beads to a fresh column (off-deck)")
    if cleanup.kind == "sizeselect":
        print("  left-side size selection (> 200 bp); elution volume is user-chosen (placeholder here)")

    return {"p50_tips": p50_tips, "p300_tips": p300_tips, "mag_plate": mag_plate, "trough": trough}


async def finish_tips(lh: LiquidHandler, discard_tips: bool, tip_kind: str):
    if discard_tips:
        print(f"Discarding {tip_kind} tips...")
        await lh.discard_tips()
    else:
        print(f"Returning {tip_kind} tips...")
        await lh.return_tips()


async def p300_add_from_trough(lh, r, source_well_name, volume_ul, discard_tips, tip_col, what):
    vols = [volume_ul] * 8
    trough, plate = r["trough"], r["mag_plate"]
    print(f"\nP300 ADD: {what}: reservoir {source_well_name} -> mag col {DEST_COL}; {volume_ul} uL x8 (tip col {tip_col})")
    await lh.pick_up_tips(r["p300_tips"][f"A{tip_col}:H{tip_col}"])
    try:
        await lh.aspirate([trough[source_well_name][0]] * 8, vols=vols,
                          liquid_height=P300_TROUGH_ASP_HEIGHT, offsets=P300_TROUGH_ASP_OFFSETS,
                          blow_out_air_volume=[0.0] * 8)
        await lh.dispense(wells_for_column(plate, DEST_COL), vols=vols,
                         liquid_height=P300_MAG_DSP_HEIGHT, offsets=P300_MAG_DSP_OFFSETS,
                         blow_out_air_volume=[P300_ADD_BLOWOUT_AIR_VOLUME] * 8)
    finally:
        await finish_tips(lh, discard_tips, "p300")


async def p50_add_from_trough_low(lh, r, source_well_name, volume_ul, discard_tips, tip_col, what):
    vols = [volume_ul] * 8
    trough, plate = r["trough"], r["mag_plate"]
    print(f"\nP50 LOW ADD: {what}: reservoir {source_well_name} -> mag col {DEST_COL}; {volume_ul} uL x8 (tip col {tip_col})")
    await lh.pick_up_tips(r["p50_tips"][f"A{tip_col}:H{tip_col}"])
    try:
        await lh.aspirate([trough[source_well_name][0]] * 8, vols=vols,
                          liquid_height=P50_LOW_TROUGH_ASP_HEIGHT, offsets=P50_LOW_TROUGH_ASP_OFFSETS,
                          blow_out_air_volume=[0.0] * 8)
        await lh.dispense(wells_for_column(plate, DEST_COL), vols=vols,
                         liquid_height=P50_LOW_MAG_DSP_HEIGHT, offsets=P50_LOW_MAG_DSP_OFFSETS,
                         blow_out_air_volume=[P50_LOW_ADD_BLOWOUT_AIR_VOLUME] * 8)
    finally:
        await finish_tips(lh, discard_tips, "p50")


async def elution_add(lh, r, source_well_name, volume_ul, discard_tips, tip_col, what):
    if volume_ul > P50_ELUTION_MAX_UL:
        await p300_add_from_trough(lh, r, source_well_name, volume_ul, discard_tips, tip_col, what)
    else:
        await p50_add_from_trough_low(lh, r, source_well_name, volume_ul, discard_tips, tip_col, what)


async def p300_remove_to_waste(lh, r, volume_ul, discard_tips, tip_col, what):
    vols = [volume_ul] * 8
    trough, plate = r["trough"], r["mag_plate"]
    print(f"\nP300 REMOVE: {what}: mag col {DEST_COL} -> waste {TROUGH_WASTE}; {volume_ul} uL x8 (tip col {tip_col})")
    await lh.pick_up_tips(r["p300_tips"][f"A{tip_col}:H{tip_col}"])
    try:
        await lh.aspirate(wells_for_column(plate, DEST_COL), vols=vols,
                          liquid_height=P300_MAG_REMOVE_ASP_HEIGHT, offsets=P300_MAG_REMOVE_ASP_OFFSETS,
                          blow_out_air_volume=[0.0] * 8)
        await lh.dispense([trough[TROUGH_WASTE][0]] * 8, vols=vols,
                         liquid_height=P300_WASTE_DSP_HEIGHT, offsets=P300_WASTE_DSP_OFFSETS,
                         blow_out_air_volume=[P300_REMOVE_BLOWOUT_AIR_VOLUME] * 8)
    finally:
        await finish_tips(lh, discard_tips, "p300")


async def p50_remove_residual_to_waste(lh, r, volume_ul, discard_tips, tip_col):
    vols = [volume_ul] * 8
    trough, plate = r["trough"], r["mag_plate"]
    print(f"\nP50 RESIDUAL REMOVE: mag col {DEST_COL} -> waste {TROUGH_WASTE}; {volume_ul} uL x8 (tip col {tip_col})")
    await lh.pick_up_tips(r["p50_tips"][f"A{tip_col}:H{tip_col}"])
    try:
        await lh.aspirate(wells_for_column(plate, DEST_COL), vols=vols,
                          liquid_height=P50_MAG_RESIDUAL_ASP_HEIGHT, offsets=P50_MAG_RESIDUAL_ASP_OFFSETS,
                          blow_out_air_volume=[0.0] * 8)
        await lh.dispense([trough[TROUGH_WASTE][0]] * 8, vols=vols,
                         liquid_height=P50_WASTE_DSP_HEIGHT, offsets=P50_WASTE_DSP_OFFSETS,
                         blow_out_air_volume=[P50_RESIDUAL_BLOWOUT_AIR_VOLUME] * 8)
    finally:
        await finish_tips(lh, discard_tips, "p50")


LEG_ORDER = [
    "bind-add", "supernatant-remove",
    "ethanol-add1", "ethanol-remove1", "ethanol-add2", "ethanol-remove2",
    "residual-remove", "elution-add",
]


def build_legs(cleanup: Cleanup):
    bind_what = "fresh beads add (0.85X)" if cleanup.kind == "sizeselect" else "binding buffer (reactivate beads)"
    return {
        "bind-add": lambda lh, r, dt, tc: p300_add_from_trough(lh, r, cleanup.bind_source, cleanup.bind_ul, dt, tc, bind_what),
        "supernatant-remove": lambda lh, r, dt, tc: p300_remove_to_waste(lh, r, cleanup.supernatant_remove_ul, dt, tc, "supernatant remove"),
        "ethanol-add1": lambda lh, r, dt, tc: p300_add_from_trough(lh, r, TROUGH_ETOH1, VOL_ETHANOL_ADD, dt, tc, "ethanol wash 1 add"),
        "ethanol-remove1": lambda lh, r, dt, tc: p300_remove_to_waste(lh, r, VOL_ETHANOL_REMOVE, dt, tc, "ethanol wash 1 remove"),
        "ethanol-add2": lambda lh, r, dt, tc: p300_add_from_trough(lh, r, TROUGH_ETOH2, VOL_ETHANOL_ADD, dt, tc, "ethanol wash 2 add"),
        "ethanol-remove2": lambda lh, r, dt, tc: p300_remove_to_waste(lh, r, VOL_ETHANOL_REMOVE, dt, tc, "ethanol wash 2 remove"),
        "residual-remove": lambda lh, r, dt, tc: p50_remove_residual_to_waste(lh, r, VOL_RESIDUAL_ETHANOL_REMOVE, dt, tc),
        "elution-add": lambda lh, r, dt, tc: elution_add(lh, r, cleanup.elution_source, cleanup.elution_ul, dt, tc, "elution add"),
    }


async def run_leg(lh, r, cleanup: Cleanup, name: str, discard_tips: bool, tip_col: int):
    print(f"\n=== TIP-seq {cleanup.name} cleanup ({cleanup.ratio_label}) - leg {name} ===")
    await build_legs(cleanup)[name](lh, r, discard_tips, tip_col)
    print(f"SUCCESS: {name} motion completed.")


async def run_all(lh: LiquidHandler, r: Dict[str, object], cleanup: Cleanup, discard_tips: bool):
    print(f"\n=== TIP-seq {cleanup.name} cleanup ({cleanup.ratio_label}, {cleanup.kind}) - all motions ===")
    print("Incubation, bead pelleting, and air-dry timings are operator/timed and not modeled.")
    if cleanup.kind != "sizeselect":
        print("This cleanup re-binds to the beads RETAINED in the well (adds binding buffer, not beads).")
    legs = build_legs(cleanup)
    tip_col = 1
    for name in LEG_ORDER:
        if name == "elution-add":
            print("\nAir-dry the beads (operator/timed; do not over-dry). Then elute:")
        await legs[name](lh, r, discard_tips, tip_col)
        if discard_tips:
            tip_col += 1
    print(f"\nSUCCESS: {cleanup.name} cleanup motions completed. Eluate {cleanup.keep_ul} uL.")
    if cleanup.kind == "reactivation-final":
        print("Transfer the clear eluate OFF the beads to a fresh column before PCR (off-deck).")
    if cleanup.kind == "sizeselect":
        print("Left-side size selection (> 200 bp); pool libraries to equimolar ratios (off-deck).")


def make_backend(dry: bool):
    if dry:
        print("Backend: STARChatterboxBackend (DRY - simulated, no hardware movement).")
        return STARChatterboxBackend()
    print("Backend: STARBackend (REAL hardware - human-gated).")
    return STARBackend()


async def main():
    parser = argparse.ArgumentParser(
        description="TIP-seq SPRI bead cleanup, column 1, mag pos2 + trough pos3."
    )
    parser.add_argument("--cleanup", choices=sorted(CLEANUPS.keys()), required=True,
                        help="post-ivt / post-ss / post-tag (2.0X reactivation), post-pcr (0.85X size select).")
    parser.add_argument("--mode", choices=["deck", "all"] + LEG_ORDER, default="deck",
                        help="deck = assignment only. all = full sequence. Or one leg name to tune it alone.")
    parser.add_argument("--dry", action="store_true",
                        help="Use STARChatterboxBackend (simulated, no movement). Default is real STARBackend.")
    parser.add_argument("--return-tips", action="store_true",
                        help="Return tips (dry rehearsal only). Real runs DISCARD (the default).")
    parser.add_argument("--tip-col", type=int, default=1, help="Tip column for a single-leg --mode. Default: 1.")
    args = parser.parse_args()

    if args.tip_col < 1 or args.tip_col > 12:
        raise ValueError("--tip-col must be 1..12")

    cleanup = CLEANUPS[args.cleanup]
    discard_tips = not args.return_tips

    print("Initializing STAR with skip_autoload=True...")
    print(f"Tip behavior: discard_tips={discard_tips} (real runs discard; --return-tips is dry-observe only).")
    lh = LiquidHandler(backend=make_backend(args.dry), deck=STARDeck())
    await lh.setup(skip_autoload=True)

    try:
        r = await assign_deck(lh, cleanup)
        if args.mode == "deck":
            print("\nMode deck: assignment only. No movement or liquid handling executed.")
            return
        if args.mode == "all":
            await run_all(lh, r, cleanup, discard_tips)
            return
        await run_leg(lh, r, cleanup, args.mode, discard_tips, args.tip_col)
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

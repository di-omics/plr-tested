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

# NEBNext Single Cell / Low Input RNA library prep (scRNA-seq) - SPRI bead cleanup, column 1,
# on the magnet.
#
# STATUS: written, simulation-first. NOT yet run on hardware. See scrnaseq/README.md.
#
# What this is
# ------------
# The E6420 Section 1 workflow has three SPRI cleanups. Two are standard single cleanups
# (post-ligation 0.8X, post-pcr 0.9X). The cDNA cleanup (post-cdna) is SPECIAL: a two-round
# SPRI on the SAME beads - 0.6X bind, wash, elute in 0.1X TE, then add NEBNext Bead
# Reconstitution Buffer to re-bind the cDNA to those beads, wash again, and elute in 1X TE
# (E6420 Section 1.6). The manual warns that skipping the second round reduces cDNA purity.
#
# This is the emseq cleanup script generalized: same mag+trough geometry (reused VERBATIM from
# the hardware-confirmed targeted PCR cleanup), same standard leg set, plus the extra reconstitution
# round for post-cdna. Only the per-cleanup volumes change. Any single leg is a valid --mode so
# heights can be tuned one step at a time on hardware. RNA runs DISCARD tips (the default);
# --return-tips is for dry rehearsal only.
#
#   --cleanup       kind      ratio  beads  ethanol  elute            source
#   post-cdna       double    0.6X   60 uL  2x200uL  50 then 33 uL    E6420 Section 1.6
#   post-ligation   standard  0.8X   57 uL  2x200uL  17 -> keep 15    E6420 Section 1.10
#   post-pcr        standard  0.9X   45 uL  2x200uL  33 -> keep 30    E6420 Section 1.12
#
# Deck (current 35/48 deck):
#   rail48 pos1 = p50 tips (elution add, residual ethanol removal)
#   rail48 pos2 = p300 tips (beads add, reconstitution add, supernatant/ethanol removal, 50 uL elute)
#   rail35 pos2 = magnet, holding the work plate (moved here by iSWAP), column 1
#   rail35 pos3 = 12-well reservoir/trough
#
# Reservoir map (rail35 pos3):
#   A1 = NEBNext SPRI beads          A2 = 80% ethanol wash 1     A3 = 80% ethanol wash 2
#   A4 = 0.1X TE elution buffer      A5 = NEBNext Bead Reconstitution Buffer (post-cdna only)
#   A6 = 1X TE elution buffer (post-cdna round 2)                A12 = waste
#
# Scope and honesty
# -----------------
# Beads/reconstitution/50 uL elution use p300; smaller elutions and residual ethanol use p50.
# This script does not incubate, does not mix, and does NOT model the final "transfer the clear
# eluate off the beads to a fresh column" step (operator/off-deck, as in the targeted PCR and EM-seq
# cleanups). Bead ratios, ethanol volume, and elution volumes are transcribed from E6420. All
# geometry is inherited, not re-tuned for scRNA, so every mode is sim-only until tuned.

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
TROUGH_ELUTION = "A4"     # 0.1X TE
TROUGH_RECON = "A5"       # NEBNext Bead Reconstitution Buffer (post-cdna round 2)
TROUGH_ELUTION2 = "A6"    # 1X TE (post-cdna round 2)
TROUGH_WASTE = "A12"

VOL_ETHANOL_ADD = 200.0
VOL_ETHANOL_REMOVE = 200.0
VOL_RESIDUAL_ETHANOL_REMOVE = 20.0

# Above this elution volume, add with p300 instead of the p50-low geometry.
P50_ELUTION_MAX_UL = 40.0


@dataclass
class Cleanup:
    name: str
    ratio_label: str
    kind: str                 # "standard" or "double"
    beads_ul: float
    supernatant_remove_ul: float
    elution_ul: float
    keep_ul: float
    source: str
    # double (post-cdna) only:
    recon_ul: float = 0.0
    supernatant_remove2_ul: float = 0.0
    elution2_ul: float = 0.0
    keep2_ul: float = 0.0


CLEANUPS: Dict[str, Cleanup] = {
    # cDNA double cleanup. Round 1: 100 uL PCR + 60 uL beads (0.6X) = 160 bound; remove 165.
    # Elute in 50 uL 0.1X TE, add 45 uL reconstitution buffer (95 uL) to re-bind; remove 100.
    # Elute round 2 in 33 uL 1X TE, keep 30.
    "post-cdna": Cleanup("post-cdna", "0.6X", "double", 60.0, 165.0, 50.0, 50.0,
                         "NEB #E6420 Section 1.6",
                         recon_ul=45.0, supernatant_remove2_ul=100.0, elution2_ul=33.0, keep2_ul=30.0),
    # 71.5 uL post-USER ligation + 57 uL beads (0.8X) = 128.5 bound; remove 133. Elute 17, keep 15.
    "post-ligation": Cleanup("post-ligation", "0.8X", "standard", 57.0, 133.0, 17.0, 15.0,
                             "NEB #E6420 Section 1.10"),
    # 50 uL PCR + 45 uL beads (0.9X) = 95 bound; remove 100. Elute 33, keep 30.
    "post-pcr": Cleanup("post-pcr", "0.9X", "standard", 45.0, 100.0, 33.0, 30.0,
                        "NEB #E6420 Section 1.12"),
}

# Geometry reused verbatim from the confirmed targeted PCR cleanup (via emseq_cleanup.py). No
# scRNA-specific tuning yet.
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
    print(f"Assigning scRNA-seq {cleanup.name} cleanup deck ({cleanup.ratio_label}, {cleanup.kind}): "
          "mag pos2 + trough pos3...")

    tip_carrier = TIP_CAR_480_A00(name="tip_car_rail48")
    labware_carrier = PLT_CAR_L5AC_A00(name="labware_car_rail35")
    lh.deck.assign_child_resource(tip_carrier, rails=TIP_RAIL)
    lh.deck.assign_child_resource(labware_carrier, rails=LABWARE_RAIL)

    p50_tips = make_p50_tips("r48_pos1_p50_filter_tips")
    p300_tips = make_p300_tips("r48_pos2_p300_filter_tips")
    mag_plate = CellTreat_96_wellplate_350ul_Fb(name="rail35_pos2_scrnaseq_cleanup_mag_96wp")
    trough = CellTreat_12_troughplate_15000ul_Vb(name="rail35_pos3_scrnaseq_cleanup_12w_reservoir")

    tip_carrier[P50_TIP_POS] = p50_tips
    tip_carrier[P300_TIP_POS] = p300_tips
    labware_carrier[MAG_POS] = mag_plate
    labware_carrier[TROUGH_POS] = trough

    print("\nDeck:")
    print("  rail48 pos1 = p50 tips (small elution, residual ethanol)")
    print("  rail48 pos2 = p300 tips (beads, reconstitution, supernatant/ethanol, 50 uL elute)")
    print("  rail35 pos2 = magnet + work plate, column 1")
    print("  rail35 pos3 = 12-well reservoir/trough")

    print("\nReservoir map:")
    print(f"  {TROUGH_BEADS} = SPRI beads   {TROUGH_ETOH1}/{TROUGH_ETOH2} = 80% ethanol   {TROUGH_ELUTION} = 0.1X TE")
    if cleanup.kind == "double":
        print(f"  {TROUGH_RECON} = Bead Reconstitution Buffer   {TROUGH_ELUTION2} = 1X TE   {TROUGH_WASTE} = waste")
    else:
        print(f"  {TROUGH_WASTE} = waste")

    print(f"\n{cleanup.name} volumes ({cleanup.source}):")
    print(f"  beads add = {cleanup.beads_ul} uL x8 ({cleanup.ratio_label}), p300")
    print(f"  supernatant remove = {cleanup.supernatant_remove_ul} uL x8, p300")
    print(f"  ethanol add/remove = {VOL_ETHANOL_ADD}/{VOL_ETHANOL_REMOVE} uL x8, p300 (x2 washes)")
    print(f"  residual ethanol remove = {VOL_RESIDUAL_ETHANOL_REMOVE} uL x8, p50")
    if cleanup.kind == "double":
        print(f"  elute round 1 = {cleanup.elution_ul} uL 0.1X TE (stays on beads)")
        print(f"  reconstitution add = {cleanup.recon_ul} uL, then re-bind, wash x2, residual")
        print(f"  elute round 2 = {cleanup.elution2_ul} uL 1X TE; keep {cleanup.keep2_ul} uL (off-deck)")
    else:
        print(f"  elution add = {cleanup.elution_ul} uL, p50; keep {cleanup.keep_ul} uL (off-deck transfer)")

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
    """Add elution buffer onto the beads: p300 for > 40 uL, else p50-low."""
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


def build_legs(cleanup: Cleanup):
    """Ordered {name: coro-factory(lh, r, discard_tips, tip_col)} for the selected cleanup."""
    legs = {
        "beads-add": lambda lh, r, dt, tc: p300_add_from_trough(lh, r, TROUGH_BEADS, cleanup.beads_ul, dt, tc, "beads add"),
        "supernatant-remove": lambda lh, r, dt, tc: p300_remove_to_waste(lh, r, cleanup.supernatant_remove_ul, dt, tc, "supernatant remove"),
        "ethanol-add1": lambda lh, r, dt, tc: p300_add_from_trough(lh, r, TROUGH_ETOH1, VOL_ETHANOL_ADD, dt, tc, "ethanol wash 1 add"),
        "ethanol-remove1": lambda lh, r, dt, tc: p300_remove_to_waste(lh, r, VOL_ETHANOL_REMOVE, dt, tc, "ethanol wash 1 remove"),
        "ethanol-add2": lambda lh, r, dt, tc: p300_add_from_trough(lh, r, TROUGH_ETOH2, VOL_ETHANOL_ADD, dt, tc, "ethanol wash 2 add"),
        "ethanol-remove2": lambda lh, r, dt, tc: p300_remove_to_waste(lh, r, VOL_ETHANOL_REMOVE, dt, tc, "ethanol wash 2 remove"),
        "residual-remove": lambda lh, r, dt, tc: p50_remove_residual_to_waste(lh, r, VOL_RESIDUAL_ETHANOL_REMOVE, dt, tc),
    }
    if cleanup.kind == "double":
        # Round 1 eluate stays on the beads; then reconstitution buffer re-binds and round 2 runs.
        legs["elute1-add"] = lambda lh, r, dt, tc: elution_add(lh, r, TROUGH_ELUTION, cleanup.elution_ul, dt, tc, "elute round 1 (0.1X TE, stays on beads)")
        legs["recon-add"] = lambda lh, r, dt, tc: p300_add_from_trough(lh, r, TROUGH_RECON, cleanup.recon_ul, dt, tc, "reconstitution buffer (re-bind)")
        legs["supernatant-remove2"] = lambda lh, r, dt, tc: p300_remove_to_waste(lh, r, cleanup.supernatant_remove2_ul, dt, tc, "supernatant remove (round 2)")
        legs["ethanol-add3"] = lambda lh, r, dt, tc: p300_add_from_trough(lh, r, TROUGH_ETOH1, VOL_ETHANOL_ADD, dt, tc, "ethanol wash 3 add")
        legs["ethanol-remove3"] = lambda lh, r, dt, tc: p300_remove_to_waste(lh, r, VOL_ETHANOL_REMOVE, dt, tc, "ethanol wash 3 remove")
        legs["ethanol-add4"] = lambda lh, r, dt, tc: p300_add_from_trough(lh, r, TROUGH_ETOH2, VOL_ETHANOL_ADD, dt, tc, "ethanol wash 4 add")
        legs["ethanol-remove4"] = lambda lh, r, dt, tc: p300_remove_to_waste(lh, r, VOL_ETHANOL_REMOVE, dt, tc, "ethanol wash 4 remove")
        legs["residual-remove2"] = lambda lh, r, dt, tc: p50_remove_residual_to_waste(lh, r, VOL_RESIDUAL_ETHANOL_REMOVE, dt, tc)
        legs["elute2-add"] = lambda lh, r, dt, tc: elution_add(lh, r, TROUGH_ELUTION2, cleanup.elution2_ul, dt, tc, "elute round 2 (1X TE)")
    else:
        legs["elution-add"] = lambda lh, r, dt, tc: elution_add(lh, r, TROUGH_ELUTION, cleanup.elution_ul, dt, tc, "elution add")
    return legs


def leg_order(cleanup: Cleanup) -> List[str]:
    base = ["beads-add", "supernatant-remove", "ethanol-add1", "ethanol-remove1",
            "ethanol-add2", "ethanol-remove2", "residual-remove"]
    if cleanup.kind == "double":
        return base + ["elute1-add", "recon-add", "supernatant-remove2",
                       "ethanol-add3", "ethanol-remove3", "ethanol-add4", "ethanol-remove4",
                       "residual-remove2", "elute2-add"]
    return base + ["elution-add"]


async def run_leg(lh, r, cleanup: Cleanup, name: str, discard_tips: bool, tip_col: int):
    print(f"\n=== scRNA-seq {cleanup.name} cleanup ({cleanup.ratio_label}) - leg {name} ===")
    await build_legs(cleanup)[name](lh, r, discard_tips, tip_col)
    print(f"SUCCESS: {name} motion completed.")


async def run_all(lh: LiquidHandler, r: Dict[str, object], cleanup: Cleanup, discard_tips: bool):
    print(f"\n=== scRNA-seq {cleanup.name} cleanup ({cleanup.ratio_label}, {cleanup.kind}) - all motions ===")
    print("Incubation, bead pelleting on the magnet, and air-dry timings are operator/timed and")
    print("not modeled here. For post-cdna the round-1 eluate stays on the beads and the")
    print("reconstitution buffer re-binds it before round 2.")
    legs = build_legs(cleanup)
    order = leg_order(cleanup)
    if discard_tips and len(order) > 12:
        print(f"\n[note] {cleanup.name} discards {len(order)} tip-columns, more than one 12-column rack. "
              "Tip columns cycle 1..12 here; a real run must replenish the p300/p50 tips mid-cleanup "
              "(the deck has one tip rack at rail48), or stage a second rack.")
    tip_col = 1
    discarded = 0
    for name in order:
        if name in ("elution-add", "elute2-add"):
            print("\nAir-dry the beads (operator/timed; do not over-dry). Then elute:")
        await legs[name](lh, r, discard_tips, tip_col)
        if discard_tips:
            discarded += 1
            tip_col = (discarded % 12) + 1
    keep = cleanup.keep2_ul if cleanup.kind == "double" else cleanup.keep_ul
    print(f"\nSUCCESS: {cleanup.name} cleanup motions completed. Transfer the clear {keep} uL off the")
    print("magnet to a fresh column (off-deck).")


def make_backend(dry: bool):
    if dry:
        print("Backend: STARChatterboxBackend (DRY - simulated, no hardware movement).")
        return STARChatterboxBackend()
    print("Backend: STARBackend (REAL hardware - human-gated).")
    return STARBackend()


async def main():
    parser = argparse.ArgumentParser(
        description="scRNA-seq (E6420) SPRI bead cleanup, column 1, mag pos2 + trough pos3."
    )
    parser.add_argument("--cleanup", choices=sorted(CLEANUPS.keys()), required=True,
                        help="post-cdna (0.6X double), post-ligation (0.8X), post-pcr (0.9X).")
    # --mode accepts deck, all, or any single leg name of the SELECTED cleanup (validated below).
    parser.add_argument("--mode", default="deck",
                        help="deck = assignment only. all = full sequence. Or one leg name to tune it alone.")
    parser.add_argument("--dry", action="store_true",
                        help="Use STARChatterboxBackend (simulated, no movement). Default is real STARBackend.")
    parser.add_argument("--return-tips", action="store_true",
                        help="Return tips (dry rehearsal only). RNA runs DISCARD (the default).")
    parser.add_argument("--tip-col", type=int, default=1, help="Tip column for a single-leg --mode. Default: 1.")
    args = parser.parse_args()

    if args.tip_col < 1 or args.tip_col > 12:
        raise ValueError("--tip-col must be 1..12")

    cleanup = CLEANUPS[args.cleanup]
    valid_modes = ["deck", "all"] + leg_order(cleanup)
    if args.mode not in valid_modes:
        raise SystemExit(f"--mode {args.mode!r} invalid for {cleanup.name}. Choose one of: {valid_modes}")

    discard_tips = not args.return_tips

    print("Initializing STAR with skip_autoload=True...")
    print(f"Tip behavior: discard_tips={discard_tips} (RNA runs discard; --return-tips is dry-observe only).")
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

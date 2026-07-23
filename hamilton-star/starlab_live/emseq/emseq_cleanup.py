import argparse
import asyncio
from dataclasses import dataclass
from typing import Dict, List, Optional

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

# EM-seq v2 (UltraShear-coupled) - SPRI bead cleanup, column 1 only, on the magnet.
#
# STATUS: written, simulation-first. NOT yet run on hardware. See emseq/README.md.
#
# What this is
# ------------
# The EM-seq v2 workflow has three NEBNext Sample Purification Bead cleanups, at three
# different bead ratios and three different elution volumes. This is one script with a
# --cleanup selector that picks the volume preset; the motions and the deck are the same
# for all three. It is the targeted PCR round 1 cleanup script (02_targeted_pcr_round1_cleanup_col1_dry_v2_
# p50low.py) generalized to the EM-seq volumes. The mag+trough geometry is reused VERBATIM
# from that hardware-confirmed script; only the per-cleanup volumes change.
#
#   --cleanup       ratio  beads  ethanol  elute/keep  source
#   post-ligation   1.1X   93 uL  2x200uL  29 / 28 uL  NEB #M7634 Section 3.4
#   post-tet2       1.0X   50 uL  2x200uL  17 / 16 uL  NEB #E8015 Section 1.6
#   post-pcr        0.8X   72 uL  2x200uL  21 / 20 uL  NEB #E8015 Section 1.10
#
# Deck (current 35/48 deck):
#   rail48 pos1 = p50 tips (elution add, residual ethanol removal)
#   rail48 pos2 = p300 tips (beads add, supernatant/ethanol removal)
#   rail35 pos2 = magnet, holding the work plate (moved here by iSWAP), column 1
#   rail35 pos3 = 12-well reservoir/trough
#
# Reservoir map (rail35 pos3):
#   A1 = NEBNext Sample Purification Beads
#   A2 = 80% ethanol wash 1
#   A3 = 80% ethanol wash 2
#   A4 = Elution Buffer
#   A12 = waste
#
# Scope and honesty
# -----------------
# Beads are added with p300 (EM-seq bead volumes 50-93 uL exceed the p50 tip); elution is
# added with the p50-low geometry. This script does not incubate, does not mix, and does
# NOT model the final "transfer the clear eluate off the beads to a fresh column" step
# (E8015 1.x.11 / M7634 3.4.9A.3): that needs a second destination plate and its own tuned
# transfer, and is left as an operator/off-deck step exactly as in the targeted_pcr cleanup. Bead
# ratios, ethanol volume, and elution volumes are transcribed from the two NEB manuals.
# All geometry is inherited, not re-tuned for EM-seq, so every mode is sim-only until a
# person tunes it on the deck.

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
TROUGH_ELUTION = "A4"
TROUGH_WASTE = "A12"

# 80% ethanol wash volume, both washes (E8015 / M7634: 200 uL per wash).
VOL_ETHANOL_ADD = 200.0
VOL_ETHANOL_REMOVE = 200.0
VOL_RESIDUAL_ETHANOL_REMOVE = 20.0


@dataclass
class Cleanup:
    name: str
    ratio_label: str
    beads_ul: float
    supernatant_remove_ul: float
    elution_ul: float
    keep_ul: float
    source: str


# supernatant_remove_ul is set a few uL ABOVE the exact reaction+beads sum so the aspirate
# clears the well after binding; the tip pulls air once the well is empty, which is fine.
CLEANUPS: Dict[str, Cleanup] = {
    # 82.5 uL ligation reaction + 93 uL beads = 175.5 uL bound; remove 180 (margin).
    "post-ligation": Cleanup("post-ligation", "1.1X", 93.0, 180.0, 29.0, 28.0, "NEB #M7634 Section 3.4"),
    # 51 uL stop reaction + 50 uL beads = 101 uL bound; remove 105 (margin).
    "post-tet2": Cleanup("post-tet2", "1.0X", 50.0, 105.0, 17.0, 16.0, "NEB #E8015 Section 1.6"),
    # 90 uL PCR reaction + 72 uL beads = 162 uL bound; remove 165 (margin).
    "post-pcr": Cleanup("post-pcr", "0.8X", 72.0, 165.0, 21.0, 20.0, "NEB #E8015 Section 1.10"),
}

# Geometry reused verbatim from 02_targeted_pcr_round1_cleanup_col1_dry_v2_p50low.py (mag pos2 +
# trough pos3). No EM-seq-specific tuning yet.
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
    print(f"Assigning EM-seq {cleanup.name} cleanup deck ({cleanup.ratio_label}): mag pos2 + trough pos3...")

    tip_carrier = TIP_CAR_480_A00(name="tip_car_rail48")
    labware_carrier = PLT_CAR_L5AC_A00(name="labware_car_rail35")
    lh.deck.assign_child_resource(tip_carrier, rails=TIP_RAIL)
    lh.deck.assign_child_resource(labware_carrier, rails=LABWARE_RAIL)

    p50_tips = make_p50_tips("r48_pos1_p50_filter_tips")
    p300_tips = make_p300_tips("r48_pos2_p300_filter_tips")
    mag_plate = CellTreat_96_wellplate_350ul_Fb(name="rail35_pos2_emseq_cleanup_mag_96wp")
    trough = CellTreat_12_troughplate_15000ul_Vb(name="rail35_pos3_emseq_cleanup_12w_reservoir")

    tip_carrier[P50_TIP_POS] = p50_tips
    tip_carrier[P300_TIP_POS] = p300_tips
    labware_carrier[MAG_POS] = mag_plate
    labware_carrier[TROUGH_POS] = trough

    print("\nDeck:")
    print("  rail48 pos1 = p50 tips (elution add, residual ethanol removal)")
    print("  rail48 pos2 = p300 tips (beads add, supernatant/ethanol removal)")
    print("  rail35 pos2 = magnet + work plate, column 1")
    print("  rail35 pos3 = 12-well reservoir/trough")

    print("\nReservoir map:")
    print(f"  {TROUGH_BEADS} = NEBNext Sample Purification Beads")
    print(f"  {TROUGH_ETOH1} = 80% ethanol wash 1")
    print(f"  {TROUGH_ETOH2} = 80% ethanol wash 2")
    print(f"  {TROUGH_ELUTION} = Elution Buffer")
    print(f"  {TROUGH_WASTE} = waste")

    print(f"\n{cleanup.name} volumes ({cleanup.source}):")
    print(f"  beads add = {cleanup.beads_ul} uL x8 ({cleanup.ratio_label}), p300")
    print(f"  supernatant remove = {cleanup.supernatant_remove_ul} uL x8, p300")
    print(f"  ethanol add/remove = {VOL_ETHANOL_ADD}/{VOL_ETHANOL_REMOVE} uL x8, p300 (x2 washes)")
    print(f"  residual ethanol remove = {VOL_RESIDUAL_ETHANOL_REMOVE} uL x8, p50")
    print(f"  elution add = {cleanup.elution_ul} uL x8, p50-low; keep {cleanup.keep_ul} uL (off-deck transfer)")

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


# The cleanup motion sequence, one leg per name, in order. Each leg is a coroutine
# factory bound to the selected cleanup's volumes. Any single leg is also a valid --mode,
# so heights can be tuned one step at a time on hardware (the same granularity the targeted_pcr
# cleanup script offers).
LEG_ORDER = [
    "beads-add", "supernatant-remove",
    "ethanol-add1", "ethanol-remove1", "ethanol-add2", "ethanol-remove2",
    "residual-remove", "elution-add",
]


def build_legs(cleanup: Cleanup):
    return {
        "beads-add": lambda lh, r, dt, tc: p300_add_from_trough(lh, r, TROUGH_BEADS, cleanup.beads_ul, dt, tc, "beads add"),
        "supernatant-remove": lambda lh, r, dt, tc: p300_remove_to_waste(lh, r, cleanup.supernatant_remove_ul, dt, tc, "supernatant remove"),
        "ethanol-add1": lambda lh, r, dt, tc: p300_add_from_trough(lh, r, TROUGH_ETOH1, VOL_ETHANOL_ADD, dt, tc, "ethanol wash 1 add"),
        "ethanol-remove1": lambda lh, r, dt, tc: p300_remove_to_waste(lh, r, VOL_ETHANOL_REMOVE, dt, tc, "ethanol wash 1 remove"),
        "ethanol-add2": lambda lh, r, dt, tc: p300_add_from_trough(lh, r, TROUGH_ETOH2, VOL_ETHANOL_ADD, dt, tc, "ethanol wash 2 add"),
        "ethanol-remove2": lambda lh, r, dt, tc: p300_remove_to_waste(lh, r, VOL_ETHANOL_REMOVE, dt, tc, "ethanol wash 2 remove"),
        "residual-remove": lambda lh, r, dt, tc: p50_remove_residual_to_waste(lh, r, VOL_RESIDUAL_ETHANOL_REMOVE, dt, tc),
        "elution-add": lambda lh, r, dt, tc: p50_add_from_trough_low(lh, r, TROUGH_ELUTION, cleanup.elution_ul, dt, tc, "elution add"),
    }


async def run_leg(lh, r, cleanup: Cleanup, name: str, discard_tips: bool, tip_col: int):
    print(f"\n=== EM-seq {cleanup.name} cleanup ({cleanup.ratio_label}) - leg {name} ===")
    await build_legs(cleanup)[name](lh, r, discard_tips, tip_col)
    print(f"SUCCESS: {name} motion completed.")


async def run_all(lh: LiquidHandler, r: Dict[str, object], cleanup: Cleanup, discard_tips: bool):
    print(f"\n=== EM-seq {cleanup.name} cleanup ({cleanup.ratio_label}) - all motions ===")
    print("Between beads-add and supernatant-remove: incubate 5 min RT, then let beads pellet on")
    print("the magnet (operator/timed; not modeled here). Same before elution.")
    legs = build_legs(cleanup)
    tip_col = 1
    for name in LEG_ORDER:
        if name == "elution-add":
            print("\nAir-dry the beads 30 s - 2 min (operator/timed; do not over-dry). Then elute:")
        await legs[name](lh, r, discard_tips, tip_col)
        if discard_tips:
            tip_col += 1
    print(f"\nSUCCESS: {cleanup.name} cleanup motions completed. Eluate ({cleanup.elution_ul} uL) is on the")
    print(f"beads; transfer the clear {cleanup.keep_ul} uL off the magnet to a fresh column (off-deck).")


def make_backend(dry: bool):
    if dry:
        print("Backend: STARChatterboxBackend (DRY - simulated, no hardware movement).")
        return STARChatterboxBackend()
    print("Backend: STARBackend (REAL hardware - human-gated).")
    return STARBackend()


async def main():
    parser = argparse.ArgumentParser(
        description="EM-seq v2 SPRI bead cleanup, column 1, mag pos2 + trough pos3. Three ratio presets."
    )
    parser.add_argument("--cleanup", choices=sorted(CLEANUPS.keys()), required=True,
                        help="Which EM-seq cleanup: post-ligation (1.1X), post-tet2 (1.0X), post-pcr (0.8X).")
    parser.add_argument("--mode", choices=["deck", "all"] + LEG_ORDER, default="deck",
                        help="deck = assignment only (no motion). all = full sequence. Or one leg name to tune it alone.")
    parser.add_argument("--dry", action="store_true",
                        help="Use STARChatterboxBackend (simulated, no movement). Default is real STARBackend.")
    parser.add_argument("--return-tips", action="store_true",
                        help="Return tips instead of discarding. Dry observation only; this cleanup handles "
                             "beads/ethanol, so real runs MUST discard (the default).")
    parser.add_argument("--tip-col", type=int, default=1, help="Tip column for a single-leg --mode. Default: 1.")
    args = parser.parse_args()

    if args.tip_col < 1 or args.tip_col > 12:
        raise ValueError("--tip-col must be 1..12")

    # Discard by default: this cleanup handles reagent-contaminated liquid (beads, ethanol),
    # so returning tips is a carryover hazard. --return-tips is for dry observation only.
    discard_tips = not args.return_tips
    cleanup = CLEANUPS[args.cleanup]

    print("Initializing STAR with skip_autoload=True...")
    print(f"Tip behavior: discard_tips={discard_tips} (production discards; --return-tips is dry-observe only).")
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

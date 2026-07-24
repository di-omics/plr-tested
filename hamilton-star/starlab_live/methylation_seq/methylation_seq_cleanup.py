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

from pathlib import Path as _MethodPath
import sys as _method_sys

_method_root = next(parent for parent in _MethodPath(__file__).resolve().parents if parent.name == "hamilton-star")
if str(_method_root) not in _method_sys.path:
    _method_sys.path.insert(0, str(_method_root))
from operator_parameters import required_positive, required_text

# Generic methylation-sequencing magnetic-cleanup motion scaffold. Cleanup
# volumes and ratio labels come only from an operator-approved local profile.
# Deck geometry and calibrated motion constants below remain unchanged.

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

VOL_ETHANOL_ADD = required_positive("methylation_seq.cleanup.wash_add_ul")
VOL_ETHANOL_REMOVE = required_positive("methylation_seq.cleanup.wash_remove_ul")
VOL_RESIDUAL_ETHANOL_REMOVE = required_positive("methylation_seq.cleanup.residual_remove_ul")


@dataclass
class Cleanup:
    name: str
    ratio_label: str
    beads_ul: float
    supernatant_remove_ul: float
    elution_ul: float
    keep_ul: float
    source: str


CLEANUPS: Dict[str, Cleanup] = {
    name: Cleanup(
        name,
        required_text(f"methylation_seq.cleanup.{key}.ratio_label"),
        required_positive(f"methylation_seq.cleanup.{key}.bead_volume_ul"),
        required_positive(f"methylation_seq.cleanup.{key}.supernatant_remove_ul"),
        required_positive(f"methylation_seq.cleanup.{key}.elution_ul"),
        required_positive(f"methylation_seq.cleanup.{key}.keep_ul"),
        "operator-approved local profile",
    )
    for name, key in (
        ("cleanup-1", "cleanup_1"),
        ("cleanup-2", "cleanup_2"),
        ("cleanup-3", "cleanup_3"),
    )
}

# Geometry reused verbatim from 02_pcr_enrichment_round1_cleanup_col1_dry_v2_p50low.py (mag pos2 +
# trough pos3). The physical and liquid-handling plate is the same CellTreat 350 uL work
# plate as the current working PCR enrichment playbook. The separate iSWAP subprocesses retain
# the hardware-proven Cor command stand-in intentionally; wet cleanup heights still
# require dye tuning.
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
    print(f"Assigning methylation sequencing {cleanup.name} cleanup deck ({cleanup.ratio_label}): mag pos2 + trough pos3...")

    tip_carrier = TIP_CAR_480_A00(name="tip_car_rail48")
    labware_carrier = PLT_CAR_L5AC_A00(name="labware_car_rail35")
    lh.deck.assign_child_resource(tip_carrier, rails=TIP_RAIL)
    lh.deck.assign_child_resource(labware_carrier, rails=LABWARE_RAIL)

    p50_tips = make_p50_tips("r48_pos1_p50_filter_tips")
    p300_tips = make_p300_tips("r48_pos2_p300_filter_tips")
    mag_plate = CellTreat_96_wellplate_350ul_Fb(name="rail35_pos2_methylation_seq_cleanup_mag_celltreat_350_96wp")
    trough = CellTreat_12_troughplate_15000ul_Vb(name="rail35_pos3_methylation_seq_cleanup_12w_reservoir")

    tip_carrier[P50_TIP_POS] = p50_tips
    tip_carrier[P300_TIP_POS] = p300_tips
    labware_carrier[MAG_POS] = mag_plate
    labware_carrier[TROUGH_POS] = trough

    print("\nDeck:")
    print("  rail48 pos1 = p50 tips (elution add, residual ethanol removal)")
    print("  rail48 pos2 = p300 tips (beads add, supernatant/ethanol removal)")
    print("  rail35 pos2 = magnet + CellTreat_96_wellplate_350ul_Fb work plate, column 1")
    print("  rail35 pos3 = 12-well reservoir/trough")

    print("\nReservoir map:")
    print(f"  {TROUGH_BEADS} = SPRI beads")
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
# so heights can be tuned one step at a time on hardware (the same granularity the PCR enrichment
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
    print(f"\n=== methylation sequencing {cleanup.name} cleanup ({cleanup.ratio_label}) - leg {name} ===")
    await build_legs(cleanup)[name](lh, r, discard_tips, tip_col)
    print(f"SUCCESS: {name} motion completed.")


async def run_all(lh: LiquidHandler, r: Dict[str, object], cleanup: Cleanup, discard_tips: bool):
    print(f"\n=== methylation sequencing {cleanup.name} cleanup ({cleanup.ratio_label}) - all motions ===")
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
        description="methylation-sequencing workflow SPRI bead cleanup, column 1, mag pos2 + trough pos3. Three ratio presets."
    )
    parser.add_argument("--cleanup", choices=sorted(CLEANUPS.keys()), required=True,
                        help="Which operator-configured cleanup: cleanup-1, cleanup-2, or cleanup-3.")
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

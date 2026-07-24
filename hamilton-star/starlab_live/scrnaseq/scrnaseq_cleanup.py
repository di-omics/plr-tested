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

from pathlib import Path as _MethodPath
import sys as _method_sys

_method_root = next(parent for parent in _MethodPath(__file__).resolve().parents if parent.name == "hamilton-star")
if str(_method_root) not in _method_sys.path:
    _method_sys.path.insert(0, str(_method_root))
from operator_parameters import (
    MethodParameterError,
    required_nonnegative,
    required_positive,
    required_text,
)

# Generic scRNA-seq magnetic-cleanup motion scaffold. Stage modes, ratio
# labels, and volumes come only from an operator-approved local profile.
# Deck geometry and calibrated motion constants below remain unchanged.

TIP_RAIL = 48
P50_TIP_POS = 1
P300_TIP_POS = 2

LABWARE_RAIL = 35
MAG_POS = 2
TROUGH_POS = 3

DEST_COL = 1

TROUGH_BINDING = "A1"
TROUGH_WASH1 = "A2"
TROUGH_WASH2 = "A3"
TROUGH_ELUTION = "A4"
TROUGH_REBINDING = "A5"   # operator-specified rebinding buffer (cleanup-1 round 2)
TROUGH_ELUTION2 = "A6"    # operator-specified elution solution
TROUGH_WASTE = "A12"

VOL_WASH_ADD = required_positive("scrnaseq.cleanup.wash_add_ul")
VOL_WASH_REMOVE = required_positive("scrnaseq.cleanup.wash_remove_ul")
VOL_RESIDUAL_WASH_REMOVE = required_positive("scrnaseq.cleanup.residual_remove_ul")

# Above this elution volume, add with p300 instead of the p50-low geometry.
P50_ELUTION_MAX_UL = 40.0


@dataclass
class Cleanup:
    name: str
    ratio_label: str
    stage_mode: str
    beads_ul: float
    supernatant_remove_ul: float
    elution_ul: float
    keep_ul: float
    source: str
    # double (cleanup-1) only:
    rebinding_ul: float = 0.0
    supernatant_remove2_ul: float = 0.0
    elution2_ul: float = 0.0
    keep2_ul: float = 0.0


def load_cleanup(name: str, key: str) -> Cleanup:
    stage_mode = required_text(f"scrnaseq.cleanup.{key}.stage_mode")
    if stage_mode not in {"single", "operator_defined_second_stage"}:
        raise MethodParameterError(
            f"scrnaseq.cleanup.{key}.stage_mode must be 'single' or "
            "'operator_defined_second_stage'"
        )
    second_stage_number = (
        required_positive
        if stage_mode == "operator_defined_second_stage"
        else required_nonnegative
    )
    return Cleanup(
        name,
        required_text(f"scrnaseq.cleanup.{key}.ratio_label"),
        stage_mode,
        required_positive(f"scrnaseq.cleanup.{key}.bead_volume_ul"),
        required_positive(f"scrnaseq.cleanup.{key}.supernatant_remove_ul"),
        required_positive(f"scrnaseq.cleanup.{key}.elution_ul"),
        required_positive(f"scrnaseq.cleanup.{key}.keep_ul"),
        "operator-approved local profile",
        rebinding_ul=required_nonnegative(f"scrnaseq.cleanup.{key}.rebinding_ul"),
        supernatant_remove2_ul=required_nonnegative(f"scrnaseq.cleanup.{key}.supernatant_remove_2_ul"),
        elution2_ul=required_nonnegative(f"scrnaseq.cleanup.{key}.elution_2_ul"),
        keep2_ul=required_nonnegative(f"scrnaseq.cleanup.{key}.keep_2_ul"),
    )


CLEANUPS: Dict[str, Cleanup] = {
    name: load_cleanup(name, key)
    for name, key in (
        ("cleanup-1", "cleanup_1"),
        ("cleanup-2", "cleanup_2"),
        ("cleanup-3", "cleanup_3"),
    )
}

# Geometry reused verbatim from the confirmed PCR enrichment cleanup (via methylation_seq_cleanup.py). No
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
    print(f"Assigning scRNA-seq {cleanup.name} cleanup deck ({cleanup.ratio_label}, {cleanup.stage_mode}): "
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
    print("  rail48 pos1 = p50 tips (small elution and residual-wash motions)")
    print("  rail48 pos2 = p300 tips (operator-specified cleanup liquids)")
    print("  rail35 pos2 = magnet + work plate, column 1")
    print("  rail35 pos3 = 12-well reservoir/trough")

    print("\nReservoir map:")
    print(f"  {TROUGH_BINDING} = operator-specified binding suspension   {TROUGH_WASH1}/{TROUGH_WASH2} = operator-specified wash solutions   {TROUGH_ELUTION} = operator-specified elution solution")
    if cleanup.kind == "double":
        print(f"  {TROUGH_REBINDING} = operator-specified rebinding buffer   {TROUGH_ELUTION2} = operator-specified elution solution   {TROUGH_WASTE} = waste")
    else:
        print(f"  {TROUGH_WASTE} = waste")

    print(f"\n{cleanup.name} volumes ({cleanup.source}):")
    print(f"  binding add = {cleanup.beads_ul} uL x8 ({cleanup.ratio_label}), p300")
    print(f"  supernatant remove = {cleanup.supernatant_remove_ul} uL x8, p300")
    print(f"  wash add/remove = {VOL_WASH_ADD}/{VOL_WASH_REMOVE} uL x8, p300 (x2 washes)")
    print(f"  residual wash remove = {VOL_RESIDUAL_WASH_REMOVE} uL x8, p50")
    if cleanup.kind == "double":
        print(f"  elute round 1 = {cleanup.elution_ul} uL (stays on the magnetic material)")
        print(f"  rebinding-buffer add = {cleanup.rebinding_ul} uL, then re-bind, wash x2, residual")
        print(f"  elute round 2 = {cleanup.elution2_ul} uL; keep {cleanup.keep2_ul} uL (off-deck)")
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
    """Add operator-specified elution solution using the calibrated tip range."""
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
        "binding-add": lambda lh, r, dt, tc: p300_add_from_trough(lh, r, TROUGH_BINDING, cleanup.beads_ul, dt, tc, "binding suspension add"),
        "supernatant-remove": lambda lh, r, dt, tc: p300_remove_to_waste(lh, r, cleanup.supernatant_remove_ul, dt, tc, "supernatant remove"),
        "wash-add1": lambda lh, r, dt, tc: p300_add_from_trough(lh, r, TROUGH_WASH1, VOL_WASH_ADD, dt, tc, "wash 1 add"),
        "wash-remove1": lambda lh, r, dt, tc: p300_remove_to_waste(lh, r, VOL_WASH_REMOVE, dt, tc, "wash 1 remove"),
        "wash-add2": lambda lh, r, dt, tc: p300_add_from_trough(lh, r, TROUGH_WASH2, VOL_WASH_ADD, dt, tc, "wash 2 add"),
        "wash-remove2": lambda lh, r, dt, tc: p300_remove_to_waste(lh, r, VOL_WASH_REMOVE, dt, tc, "wash 2 remove"),
        "residual-remove": lambda lh, r, dt, tc: p50_remove_residual_to_waste(lh, r, VOL_RESIDUAL_WASH_REMOVE, dt, tc),
    }
    if cleanup.kind == "double":
        # Round 1 eluate stays on the beads; then the operator-specified buffer
        # re-binds and round 2 runs.
        legs["elute1-add"] = lambda lh, r, dt, tc: elution_add(lh, r, TROUGH_ELUTION, cleanup.elution_ul, dt, tc, "elute round 1")
        legs["rebinding-add"] = lambda lh, r, dt, tc: p300_add_from_trough(lh, r, TROUGH_REBINDING, cleanup.rebinding_ul, dt, tc, "operator-specified rebinding buffer")
        legs["supernatant-remove2"] = lambda lh, r, dt, tc: p300_remove_to_waste(lh, r, cleanup.supernatant_remove2_ul, dt, tc, "supernatant remove (round 2)")
        legs["wash-add3"] = lambda lh, r, dt, tc: p300_add_from_trough(lh, r, TROUGH_WASH1, VOL_WASH_ADD, dt, tc, "wash 3 add")
        legs["wash-remove3"] = lambda lh, r, dt, tc: p300_remove_to_waste(lh, r, VOL_WASH_REMOVE, dt, tc, "wash 3 remove")
        legs["wash-add4"] = lambda lh, r, dt, tc: p300_add_from_trough(lh, r, TROUGH_WASH2, VOL_WASH_ADD, dt, tc, "wash 4 add")
        legs["wash-remove4"] = lambda lh, r, dt, tc: p300_remove_to_waste(lh, r, VOL_WASH_REMOVE, dt, tc, "wash 4 remove")
        legs["residual-remove2"] = lambda lh, r, dt, tc: p50_remove_residual_to_waste(lh, r, VOL_RESIDUAL_WASH_REMOVE, dt, tc)
        legs["elute2-add"] = lambda lh, r, dt, tc: elution_add(lh, r, TROUGH_ELUTION2, cleanup.elution2_ul, dt, tc, "elute round 2")
    else:
        legs["elution-add"] = lambda lh, r, dt, tc: elution_add(lh, r, TROUGH_ELUTION, cleanup.elution_ul, dt, tc, "elution add")
    return legs


def leg_order(cleanup: Cleanup) -> List[str]:
    base = ["binding-add", "supernatant-remove", "wash-add1", "wash-remove1",
            "wash-add2", "wash-remove2", "residual-remove"]
    if cleanup.kind == "double":
        return base + ["elute1-add", "rebinding-add", "supernatant-remove2",
                       "wash-add3", "wash-remove3", "wash-add4", "wash-remove4",
                       "residual-remove2", "elute2-add"]
    return base + ["elution-add"]


async def run_leg(lh, r, cleanup: Cleanup, name: str, discard_tips: bool, tip_col: int):
    print(f"\n=== scRNA-seq {cleanup.name} cleanup ({cleanup.ratio_label}) - leg {name} ===")
    await build_legs(cleanup)[name](lh, r, discard_tips, tip_col)
    print(f"SUCCESS: {name} motion completed.")


async def run_all(lh: LiquidHandler, r: Dict[str, object], cleanup: Cleanup, discard_tips: bool):
    print(f"\n=== scRNA-seq {cleanup.name} cleanup ({cleanup.ratio_label}, {cleanup.kind}) - all motions ===")
    print("Incubation, magnetic capture, and dry-handoff timings are operator/timed and")
    print("not modeled here. For cleanup-1 the round-1 eluate stays on the magnetic material")
    print("and the operator-specified rebinding buffer begins round 2.")
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
            print("\nComplete the operator-approved dry handoff, then elute:")
        await legs[name](lh, r, discard_tips, tip_col)
        if discard_tips:
            discarded += 1
            tip_col = (discarded % 12) + 1
    keep = (
        cleanup.second_stage_keep_ul
        if cleanup.stage_mode == "operator_defined_second_stage"
        else cleanup.keep_ul
    )
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
        description="scRNA-seq magnetic cleanup, column 1, mag pos2 + trough pos3."
    )
    parser.add_argument("--cleanup", choices=sorted(CLEANUPS.keys()), required=True,
                        help="Which operator-configured cleanup: cleanup-1, cleanup-2, or cleanup-3.")
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

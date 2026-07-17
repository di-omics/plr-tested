"""Plate normalization on the Hamilton STAR: add per-well water to a common target.

Consumes a per-well concentration source (a real Tecan PicoGreen read is the goal,
but the fluorescence path is unproven on this reader, so a captured CSV or a demo
set is the fallback), runs the pure planner in normalize_plan.py, then dispenses a
DIFFERENT water volume into every well from a reservoir. Every well ends at one
common concentration; the final volume differs per well.

Written 2026-07-16. STATUS: written, NOT run on hardware. This is the first script
in the repo to dispense a distinct volume per well; every validated transfer so far
is one volume x N channels. The motion below is single-channel, one reused tip,
dispensing ABOVE the liquid so the tip never touches sample (water is clean, so one
tip is safe for the whole plate). That dispense-from-above height is NEW geometry,
not the validated near-bottom 1.5 mm, and must be tuned dry before any wet run.

Deck (rail35 / rail48, same as the rhodamine QC):
  rail48 pos2 = p300 filter conductive tips
  rail35 pos0 = sample plate to normalize (concentrations were read from THIS plate)
  rail35 pos1 = reservoir; WATER_WELL holds the diluent water

Modes:
  deck  assign + print, no motion
  plan  compute + print the per-well water plan, no motion, no reader
  sim   run the motion on the STAR chatterbox backend (no hardware)
  run   run the motion on the real STAR

Concentration source (pick one), all in ng/uL after any assay-dilution multiply-back:
  --conc-csv FILE   rows "well,conc_ng_per_ul"
  --rfu-csv FILE    rows "well,rfu"  + --standards + --assay-dilution (fits the curve)
  --demo            a synthetic spread, for dry motion proof with no reader

Never-invent: --target, --start-volume, --min-transfer are required for plan/sim/run
and have no defaults. A run refuses to start while any protocol value is unpinned.
"""

import argparse
import asyncio
import csv
import math
import sys
from typing import Dict, List, Optional

import normalize_plan as NP


# --- geometry, inherited from the DRY-validated rhodamine script -------------
TIP_RAIL = 48
P300_TIP_POS = 2
LABWARE_RAIL = 35
WORK_POS = 0
RESERVOIR_POS = 1
WATER_WELL = "A1"

from pylabrobot.resources import Coordinate  # noqa: E402

# reservoir aspirate: validated cleanup trough geometry
RES_ASP_HEIGHT = 10.0
RES_ASP_OFFSET = Coordinate(0.0, 1.5, 0.0)
# work-plate XY: validated targeted PCR work dispense (Y must stay > 3.20, blacklisted)
PLATE_XY = Coordinate(-0.68, 3.22, 0.0)
# DISPENSE-FROM-ABOVE height. NEW, UNTUNED. The well is ~10 mm deep; dispensing near
# the rim keeps the tip out of the sample so one tip serves the whole plate. Tune dry.
PLATE_DSP_ABOVE_HEIGHT = 9.0
DSP_BLOWOUT_AIR_VOLUME = 5.0

# p300 usable single-aspirate volume (uL). Nominal 300 minus margin for the transport
# air gap and the dispense blowout. A water add larger than this is split across
# multiple aspirate/dispense cycles rather than silently truncated.
TIP_MAX_SINGLE_ASPIRATE = 280.0

# CellTreat 350 Fb well: bore 6.96 mm -> area ~38.05 mm2, so 1 uL is ~0.0263 mm of
# liquid height. Used to check the dispense-from-above tip stays above the fullest
# well by a real margin (a submerged reused tip would carry sample between wells).
WELL_AREA_MM2 = 38.05
MIN_DISPENSE_CLEARANCE_MM = 1.5


def fill_height_mm(volume_ul: float) -> float:
    return volume_ul / WELL_AREA_MM2

P300_TIP_FACTORY_CANDIDATES = [
    "hamilton_96_tiprack_300uL_filter",
    "hamilton_96_tiprack_300ul_filter",
    "hamilton_96_tiprack_300uL_filter_slim",
]

ROWS = "ABCDEFGH"
COLS = list(range(1, 13))


def all_wells() -> List[str]:
    # column-major, the order the head naturally travels
    return [f"{r}{c}" for c in COLS for r in ROWS]


# ---------------------------------------------------------------------------
# concentration sources
# ---------------------------------------------------------------------------

def read_conc_csv(path: str) -> Dict[str, float]:
    """Parse well,value rows. Fails loudly on a non-finite value or a duplicate well,
    and validates every name against the 96-well grid, so a bad CSV cannot reach the
    arm (the failure would otherwise surface mid-motion, after a tip is already up)."""
    grid = set(all_wells())
    out: Dict[str, float] = {}
    dupes: List[str] = []
    with open(path, newline="") as f:
        for lineno, row in enumerate(csv.reader(f), 1):
            if not row or row[0].strip().lower() in ("well", "#") or row[0].startswith("#"):
                continue
            if len(row) < 2:
                raise SystemExit(f"{path}:{lineno}: expected 'well,value', got {row!r}")
            well = row[0].strip()
            try:
                val = float(row[1])
            except ValueError:
                raise SystemExit(f"{path}:{lineno}: value {row[1]!r} for well {well} is not a number")
            if not math.isfinite(val):
                raise SystemExit(f"{path}:{lineno}: well {well} value {row[1]!r} is not finite")
            if well not in grid:
                raise SystemExit(f"{path}:{lineno}: well {well!r} is not on the 96-well grid (A1..H12)")
            if well in out:
                dupes.append(well)
            out[well] = val
    if dupes:
        raise SystemExit(f"{path}: duplicate wells (last value would silently win): {sorted(set(dupes))}")
    return out


def read_rfu_csv(path: str) -> Dict[str, float]:
    return read_conc_csv(path)  # same shape: well, value


def parse_standards(spec: str):
    """--standards "0:100,1:105,10:150,100:600,1000:5100" -> (conc_ng_per_ml[], rfu[])."""
    concs, rfus = [], []
    for pair in spec.split(","):
        c, r = pair.split(":")
        concs.append(float(c))
        rfus.append(float(r))
    return concs, rfus


def demo_concs() -> Dict[str, float]:
    """A synthetic ng/uL spread for a dry motion proof: a gradient across columns
    plus a couple of below-target and one over-capacity well, so every status path
    is exercised on the deck. NOT real data."""
    concs = {}
    wells = all_wells()
    for i, w in enumerate(wells):
        # 0.5 .. ~12 ng/uL sweep, deterministic, no randomness
        concs[w] = round(0.5 + (i % 24) * 0.5, 2)
    concs["A1"] = 0.0        # empty
    concs["B1"] = 1.0        # below a target of 2
    concs["H12"] = 500.0     # over capacity at target 2
    return concs


# ---------------------------------------------------------------------------
# STAR
# ---------------------------------------------------------------------------

def make_resource(label, name, candidates, terms):
    import pylabrobot.resources as R
    for fn in candidates:
        f = getattr(R, fn, None)
        if f is not None:
            print(f"Using {label} factory: {fn}")
            return f(name=name)
    raise RuntimeError(f"no factory for {label}; tried {candidates}")


async def assign_deck(lh):
    from pylabrobot.resources.hamilton import TIP_CAR_480_A00
    from pylabrobot.resources import PLT_CAR_L5AC_A00, CellTreat_12_troughplate_15000ul_Vb, CellTreat_96_wellplate_350ul_Fb
    tip_car = TIP_CAR_480_A00(name="tip_car_rail48")
    lab_car = PLT_CAR_L5AC_A00(name="labware_car_rail35")
    lh.deck.assign_child_resource(tip_car, rails=TIP_RAIL)
    lh.deck.assign_child_resource(lab_car, rails=LABWARE_RAIL)
    p300 = make_resource("p300 tips", "r48_pos2_p300", P300_TIP_FACTORY_CANDIDATES, ["tip", "300"])
    plate = CellTreat_96_wellplate_350ul_Fb(name="rail35_pos0_sample_plate")
    reservoir = CellTreat_12_troughplate_15000ul_Vb(name="rail35_pos1_water_reservoir")
    tip_car[P300_TIP_POS] = p300
    lab_car[WORK_POS] = plate
    lab_car[RESERVOIR_POS] = reservoir
    print("\nDeck:")
    print("  rail48 pos2 = p300 filter conductive tips")
    print("  rail35 pos0 = sample plate to normalize")
    print(f"  rail35 pos1 = reservoir, water in {WATER_WELL}")
    print("\nGeometry (dispense-from-above height is NEW, tune dry):")
    print(f"  RES_ASP_HEIGHT={RES_ASP_HEIGHT} offset={RES_ASP_OFFSET}")
    print(f"  PLATE_XY={PLATE_XY}  PLATE_DSP_ABOVE_HEIGHT={PLATE_DSP_ABOVE_HEIGHT}")
    return {"p300": p300, "plate": plate, "reservoir": reservoir}


def split_volume(total: float, chunk_max: float) -> List[float]:
    """Split a water add into aspirate/dispense chunks no larger than chunk_max, so a
    volume above one p300 aspiration is delivered in passes rather than truncated."""
    n = max(1, math.ceil(total / chunk_max - 1e-9))
    each = total / n
    return [each] * n


async def dispense_water(lh, r, plan: List[NP.WellNorm], discard_tips: bool):
    """Single channel, one reused tip: aspirate water from the reservoir and dispense
    it above each well's liquid. Only wells with water > 0 are touched; adds larger
    than one p300 aspiration are split into chunks."""
    plate = r["plate"]
    reservoir = r["reservoir"]
    active = [w for w in plan if w.water_ul > 0.0]
    print(f"\n=== WATER ADD: {len(active)} wells, single channel, one reused tip ===")
    if not active:
        print("  nothing to add (every well below/at target, empty, or invalid). No motion.")
        return

    await lh.pick_up_tips(r["p300"]["A1"])  # one tip, channel 0
    try:
        for wn in active:
            chunks = split_volume(wn.water_ul, TIP_MAX_SINGLE_ASPIRATE)
            note = "" if len(chunks) == 1 else f" in {len(chunks)} passes"
            print(f"  {wn.well}: +{wn.water_ul} uL water{note} (well -> {wn.final_ul} uL, "
                  f"{wn.final_ng_per_ul} ng/uL, {wn.status})")
            for vol in chunks:
                await lh.aspirate(
                    [reservoir[WATER_WELL][0]],
                    vols=[vol],
                    liquid_height=[RES_ASP_HEIGHT],
                    offsets=[RES_ASP_OFFSET],
                    blow_out_air_volume=[0.0],
                )
                await lh.dispense(
                    [plate[wn.well][0]],
                    vols=[vol],
                    liquid_height=[PLATE_DSP_ABOVE_HEIGHT],
                    offsets=[PLATE_XY],
                    blow_out_air_volume=[DSP_BLOWOUT_AIR_VOLUME],
                )
    finally:
        if discard_tips:
            print("Discarding tip...")
            await lh.discard_tips()
        else:
            print("Returning tip...")
            await lh.return_tips()

    # Honest close: only status==OK wells actually reached the target.
    reached = [w for w in active if w.status == NP.OK]
    off = [w for w in active if w.status != NP.OK]
    print(f"SUCCESS: water dispensed to {len(active)} wells; {len(reached)} reached the "
          f"target, {len(off)} touched but NOT at target.")
    if off:
        print("  off-target (touched, did not reach target):")
        for w in off:
            print(f"    {w.well}: {w.final_ng_per_ul} ng/uL ({w.status})")


def build_backend(sim: bool):
    if sim:
        from pylabrobot.liquid_handling.backends.hamilton.STAR_chatterbox import STARChatterboxBackend
        print("Using STARChatterboxBackend (simulation, no hardware).")
        return STARChatterboxBackend()
    from pylabrobot.liquid_handling.backends import STARBackend
    return STARBackend()


# ---------------------------------------------------------------------------

def build_config(args) -> NP.NormConfig:
    def val(x, note):
        return NP.sourced(x, note) if x is not None else None
    target = val(args.target, "operator --target")
    start = val(args.start_volume, "operator --start-volume")
    mintr = val(args.min_transfer, "operator --min-transfer (instrument low-vol floor)")
    cap = NP.sourced(args.well_capacity, "CellTreat 350 Fb useful volume / operator --well-capacity")
    # unset required values become blocking todos
    return NP.NormConfig(
        target=target or NP.todo("set --target ng/uL"),
        start_volume=start or NP.todo("set --start-volume uL"),
        min_transfer=mintr or NP.todo("set --min-transfer uL"),
        well_capacity=cap,
        min_vol_policy=args.min_vol_policy,
    )


def get_concentrations(args) -> Dict[str, float]:
    supplied = [n for n, v in (("--conc-csv", args.conc_csv),
                               ("--rfu-csv", args.rfu_csv),
                               ("--demo", args.demo)) if v]
    if len(supplied) > 1:
        raise SystemExit(f"pass exactly one concentration source, got {supplied}")
    if args.conc_csv:
        return read_conc_csv(args.conc_csv)
    if args.rfu_csv:
        if not args.standards:
            raise SystemExit("--rfu-csv needs --standards")
        sc, sr = parse_standards(args.standards)
        _, wells = NP.concentrations_from_rfu(sc, sr, read_rfu_csv(args.rfu_csv),
                                              assay_dilution=args.assay_dilution)
        return {w: wc.conc_ng_per_ul for w, wc in wells.items()}
    if args.demo:
        print("Concentration source: --demo (SYNTHETIC, not a real read).")
        return demo_concs()
    raise SystemExit("need a concentration source: --conc-csv, --rfu-csv, or --demo")


def print_plan(plan: List[NP.WellNorm]):
    s = NP.summarize(plan)
    print(f"\nPLAN: {s['wells']} wells | ok={s['counts'].get(NP.OK,0)} "
          f"below_target={s['counts'].get(NP.BELOW_TARGET,0)} "
          f"min_vol_clamped={s['counts'].get(NP.MIN_VOL_CLAMPED,0)} "
          f"exceeds_capacity={s['counts'].get(NP.EXCEEDS_CAPACITY,0)} "
          f"empty={s['counts'].get(NP.EMPTY,0)} invalid={s['counts'].get(NP.INVALID,0)}")
    print(f"total water = {s['total_water_ul']} uL | max final volume = {s['max_final_ul']} uL")
    # every status that did not reach target is flagged (this includes min_vol_clamped,
    # which is counted above and so must also be listed here).
    flagged = [w for w in plan if w.status in NP.OFF_TARGET_STATUSES]
    if flagged:
        print("FLAGGED wells (did not reach target):")
        for w in flagged:
            print(f"  {w.well}: {w.conc_ng_per_ul} ng/uL -> {w.final_ng_per_ul} ({w.status})")


def preflight(plan: List[NP.WellNorm], reservoir_usable_ul: float) -> List[str]:
    """Hardware-safety checks the pure planner cannot see. Returns blocking reasons."""
    problems = []
    active = [w for w in plan if w.water_ul > 0.0]
    # 1. reservoir must hold all the water (fixed-height aspiration has LLD off, so
    #    running dry would silently aspirate air well by well).
    need = sum(w.water_ul for w in active)
    if need > reservoir_usable_ul:
        problems.append(f"reservoir needs {need:.0f} uL of water above the aspirate height, "
                        f"but --reservoir-usable-ul is {reservoir_usable_ul:.0f}")
    # 2. the reused tip dispenses from above; the fullest well must stay clear of the
    #    tip by a margin, or a submerged tip would carry sample between wells.
    max_final = max((w.final_ul for w in active), default=0.0)
    fill = fill_height_mm(max_final)
    if fill > PLATE_DSP_ABOVE_HEIGHT - MIN_DISPENSE_CLEARANCE_MM:
        problems.append(f"fullest well is {max_final:.0f} uL = {fill:.2f} mm deep; the "
                        f"dispense-from-above height {PLATE_DSP_ABOVE_HEIGHT} mm leaves less than "
                        f"the {MIN_DISPENSE_CLEARANCE_MM} mm clearance the reused tip needs")
    return problems


async def main():
    ap = argparse.ArgumentParser(description="STAR plate normalization: add per-well water to a common target.")
    ap.add_argument("--mode", choices=["deck", "plan", "sim", "run"], default="deck")
    ap.add_argument("--target", type=float, help="common target concentration, ng/uL (required)")
    ap.add_argument("--start-volume", type=float, help="starting volume per well, uL (required)")
    ap.add_argument("--min-transfer", type=float, help="smallest reliable water add, uL (required)")
    ap.add_argument("--well-capacity", type=float, default=300.0, help="useful well volume, uL")
    ap.add_argument("--min-vol-policy", choices=["clamp", "skip"], default="clamp")
    ap.add_argument("--conc-csv", help="rows well,conc_ng_per_ul")
    ap.add_argument("--rfu-csv", help="rows well,rfu (with --standards)")
    ap.add_argument("--standards", help='"conc_ng_per_ml:rfu,..." for the PicoGreen curve')
    ap.add_argument("--assay-dilution", type=float, default=1.0)
    ap.add_argument("--demo", action="store_true", help="synthetic concentrations for a dry motion proof")
    ap.add_argument("--reservoir-usable-ul", type=float, default=12000.0,
                    help="water available in the reservoir above the aspirate height, uL")
    ap.add_argument("--return-tips", action="store_true")
    args = ap.parse_args()

    cfg = build_config(args)
    concs = get_concentrations(args)
    plan = NP.build_plan(concs, cfg)
    print_plan(plan)

    # a real run must refuse on unpinned/bad protocol values AND on hardware-safety
    # preflight failures; sim and deck print them as warnings so they surface early.
    blocking = cfg.blocking() + preflight(plan, args.reservoir_usable_ul)

    if args.mode == "plan":
        if blocking:
            print("\nNOTE: plan only. These would block a hardware run:")
            for b in blocking:
                print(f"  - {b}")
        return

    if args.mode == "run" and blocking:
        raise SystemExit("refusing hardware run:\n  " + "\n  ".join(blocking))
    if blocking:
        print("\nWARNING (would block a real run; sim/deck proceeds):")
        for b in blocking:
            print(f"  - {b}")

    from pylabrobot.liquid_handling import LiquidHandler
    from pylabrobot.resources.hamilton import STARDeck
    print(f"\nInitializing STAR (sim={args.mode=='sim'})...")
    lh = LiquidHandler(backend=build_backend(args.mode == "sim"), deck=STARDeck())
    await lh.setup(skip_autoload=True)
    try:
        r = await assign_deck(lh)
        if args.mode == "deck":
            print("\nMode deck: assignment only. No motion.")
            return
        await dispense_water(lh, r, plan, discard_tips=not args.return_tips)
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

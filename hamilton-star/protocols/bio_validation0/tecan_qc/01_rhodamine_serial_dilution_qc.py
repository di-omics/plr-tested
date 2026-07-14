import argparse
import asyncio
from typing import Dict, List

from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends import STARBackend
from pylabrobot.resources.hamilton import STARDeck, TIP_CAR_480_A00
from pylabrobot.resources import (
    PLT_CAR_L5AC_A00,
    CellTreat_12_troughplate_15000ul_Vb,
    CellTreat_96_wellplate_350ul_Fb,
    Coordinate,
)
import pylabrobot.resources as plr_resources

# Tecan Infinite QC - Rhodamine B 2-fold serial dilution, built on the STAR
#
# Written 2026-07-14. STATUS: written, NOT yet run on hardware.
# Geometry below is a STARTING ESTIMATE seeded from validated ampseq/cleanup
# scripts. Tune it dry on the physical deck (see run cards in README.md) before
# any wet run. Do not trust these heights until a --mode deck and a dry motion
# pass have been watched on the instrument.
#
# Purpose:
# - Build the Rhodamine B absorbance/linearity QC plate for the Tecan Infinite
#   (see instrument-integrations/tecan-infinite/doe-plate-map.html) on the robot,
#   so the dilution series is not pipetted by hand.
# - Produces a clear flat-bottom 96WP: rows A, B, C (triplicate), a 2-fold
#   series across columns 1-11, column 12 blank (diluent only), 100 uL per well.
#     col 1  = 1x    (strongest)
#     col 2  = 1/2
#     ...
#     col 11 = 1/1024
#     col 12 = blank (diluent only)
# - After the build, hand the plate to the reader go/no-go
#   (07_tecan_raw_absorbance.py --preloaded --wavelength 554 --wells A1,A12).
#
# Deck (rail35 / rail48, Bio Validation 0 layout):
#   rail48 pos2 = p300 filter conductive tips
#   rail35 pos0 = destination QC 96WP (clear flat-bottom)
#   rail35 pos1 = 12-well reservoir
#
# Reservoir map (rail35 pos1):
#   A1  = Rhodamine B 1x working solution (aim col 1 near OD 2-3 at 554 nm)
#   A2  = diluent (water or PBS), matched to the dye diluent
#   A12 = waste
#
# Reagent loading (dead volume included, load with margin):
#   A1  Rhodamine 1x  : used 3 x 200 uL = 600 uL   -> load >= 1.2 mL
#   A2  diluent       : used 3 x 100 uL x 11 = 3.3 mL -> load >= 4.5 mL
#
# Method (on-plate 2-fold serial dilution, 100 uL final in every well):
#   1. diluent : 100 uL diluent into cols 2-12, rows A-C.
#   2. dye     : 200 uL Rhodamine 1x into col 1, rows A-C.
#   3. serial  : for src in 1..10, transfer 100 uL src -> src+1 (rows A-C),
#                mix the destination 5x (--mix-cycles), fresh tips each step.
#                After col 10 -> 11, discard 100 uL from col 11 to waste so
#                col 11 ends at 100 uL.
#   Result: col 1 = 1x, halving each column to col 11 = 1/1024, col 12 = blank.
#
# Why the transient 200 uL is safe:
#   During a serial step the receiving well briefly holds 100 (diluent) + 100
#   (transfer) = 200 uL. The plate well useful volume is ~300 uL, so 200 uL is
#   within range. Every well is left at 100 uL, so the optical path length
#   matches across the plate.
#
# Tip plan (300 uL rack, 3 tips per rack column = rows A-C, fresh per serial step):
#   rack col 1  : diluent fill (reused across cols 2-12, diluent is clean)
#   rack col 2  : dye fill col 1
#   rack col 3  : serial col 1 -> 2
#   rack col 4  : serial col 2 -> 3
#   ...
#   rack col 12 : serial col 10 -> 11, and the col 11 -> waste discard (same tips)
#   -> exactly 12 rack columns, one full 300 uL rack.
#
# Modes:
#   deck     assign deck and print geometry, no motion
#   diluent  step 1 only
#   dye      step 2 only
#   serial   step 3 only (expects diluent + dye already placed)
#   all      steps 1 -> 2 -> 3
#
# Tips: production discards tips by default. Use --return-tips for dry/water
# rehearsals. Use --sim to run the STAR chatterbox backend (no hardware); the
# reservoir aspirate trips PLR's chatterbox _position_channels_wide check, which
# passes on real hardware (documented quirk, not a defect).

TIP_RAIL = 48
P300_TIP_POS = 2

LABWARE_RAIL = 35
WORK_POS = 0
RESERVOIR_POS = 1

REPLICATE_ROWS = 3          # rows A, B, C -> channels 0, 1, 2
N_CH = REPLICATE_ROWS
LAST_ROW = "ABCDEFGH"[REPLICATE_ROWS - 1]  # "C"

DILUTION_COLS = list(range(1, 12))   # 1..11, col 1 strongest
BLANK_COL = 12
DILUENT_FILL_COLS = list(range(2, 13))  # 2..12 (dilution wells + blank)

DYE_WELL = "A1"
DILUENT_WELL = "A2"
WASTE_WELL = "A12"

FINAL_VOL = 100.0            # final volume per well
DILUENT_PREFILL = 100.0      # diluent into cols 2-12
DYE_COL1_VOL = 200.0         # neat dye into col 1 (seeds the chain)
TRANSFER_VOL = 100.0         # 2-fold: transfer half the working volume
FINAL_DISCARD_VOL = 100.0    # col 11 -> waste, leaves col 11 at 100 uL
MIX_VOL = 80.0               # in-place mix at the destination
MIX_CYCLES = 5               # in-place mix cycles per destination (override with --mix-cycles)

# --- Geometry: STARTING ESTIMATES, tune dry first ---------------------------
# Reservoir aspirate, seeded from the validated cleanup trough geometry
# (04_cleanup_magpos2_troughpos3...: height 10.0, offset (0.0, 1.5, 0.0)).
P300_RES_ASP_HEIGHT = 10.0
P300_RES_ASP_OFFSET = Coordinate(0.0, 1.5, 0.0)

# Work-plate XY, seeded from the validated targeted PCR work dispense
# (Coordinate(-0.68, 3.22, 0.0)). Y MUST stay > 3.20: Y = 3.20 trips the
# <9 mm adjacent-channel spacing safety error and is blacklisted repo-wide.
P300_PLATE_XY = Coordinate(-0.68, 3.22, 0.0)
P300_PLATE_DSP_HEIGHT = 1.0   # dispense low into the receiving liquid, no splash
P300_PLATE_ASP_HEIGHT = 0.5   # aspirate near the bottom of a ~200 uL well
P300_PLATE_MIX_HEIGHT = 1.0   # in-place mix height

# Waste dispense, seeded from the validated cleanup waste geometry.
P300_WASTE_DSP_HEIGHT = 12.0
P300_WASTE_DSP_OFFSET = Coordinate(0.0, 1.5, 0.0)

DSP_BLOWOUT_AIR_VOLUME = 3.0
WASTE_BLOWOUT_AIR_VOLUME = 2.0

POST_DISPENSE_SETTLE_SECONDS = 1.0

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


def make_p300_tips(name: str):
    return make_resource("p300 filter tips", name, P300_TIP_FACTORY_CANDIDATES, ["tip", "300"])


def plate_col(plate, col: int):
    # rows A..C of a plate column
    return plate[f"A{col}:{LAST_ROW}{col}"]


def tip_col(r: Dict[str, object], rack_col: int):
    return r["p300_tips"][f"A{rack_col}:{LAST_ROW}{rack_col}"]


def reservoir_well(r: Dict[str, object], well: str):
    # broadcast one reservoir well across N_CH channels; the firmware spreads the
    # channels along the trough on hardware (chatterbox flags this, see header).
    return [r["reservoir"][well][0]] * N_CH


async def assign_deck(lh: LiquidHandler) -> Dict[str, object]:
    print("Assigning Tecan QC serial-dilution deck: p300 rail48 pos2, work rail35 pos0, reservoir rail35 pos1...")

    tip_carrier = TIP_CAR_480_A00(name="tip_car_rail48")
    labware_carrier = PLT_CAR_L5AC_A00(name="labware_car_rail35")
    lh.deck.assign_child_resource(tip_carrier, rails=TIP_RAIL)
    lh.deck.assign_child_resource(labware_carrier, rails=LABWARE_RAIL)

    p300_tips = make_p300_tips("r48_pos2_p300_filter_tips")
    work_plate = CellTreat_96_wellplate_350ul_Fb(name="rail35_pos0_tecan_qc_dilution_96wp")
    reservoir = CellTreat_12_troughplate_15000ul_Vb(name="rail35_pos1_12w_reservoir")

    tip_carrier[P300_TIP_POS] = p300_tips
    labware_carrier[WORK_POS] = work_plate
    labware_carrier[RESERVOIR_POS] = reservoir

    print("\nDeck:")
    print("  rail48 pos2 = p300 filter conductive tips")
    print("  rail35 pos0 = destination QC 96WP (clear flat-bottom)")
    print("  rail35 pos1 = 12-well reservoir")
    print("\nReservoir map:")
    print(f"  {DYE_WELL}  = Rhodamine B 1x working solution")
    print(f"  {DILUENT_WELL}  = diluent (water or PBS)")
    print(f"  {WASTE_WELL} = waste")
    print("\nPlate map (rows A-C, triplicate):")
    print("  col 1 = 1x ... halving each column ... col 11 = 1/1024; col 12 = blank")
    print(f"  final volume per well = {FINAL_VOL} uL")
    print("\nGeometry (STARTING ESTIMATE, tune dry first):")
    print(f"  P300_RES_ASP_HEIGHT   = {P300_RES_ASP_HEIGHT}, offset {P300_RES_ASP_OFFSET}")
    print(f"  P300_PLATE_XY         = {P300_PLATE_XY}  (Y must stay > 3.20)")
    print(f"  P300_PLATE_ASP_HEIGHT = {P300_PLATE_ASP_HEIGHT}")
    print(f"  P300_PLATE_DSP_HEIGHT = {P300_PLATE_DSP_HEIGHT}")
    print(f"  P300_PLATE_MIX_HEIGHT = {P300_PLATE_MIX_HEIGHT}")
    print(f"  P300_WASTE_DSP_HEIGHT = {P300_WASTE_DSP_HEIGHT}, offset {P300_WASTE_DSP_OFFSET}")

    return {
        "p300_tips": p300_tips,
        "work_plate": work_plate,
        "reservoir": reservoir,
    }


async def finish_tips(lh: LiquidHandler, discard_tips: bool):
    if discard_tips:
        print("Discarding p300 tips...")
        await lh.discard_tips()
    else:
        print("Returning p300 tips to rack...")
        await lh.return_tips()


async def fill_diluent(lh: LiquidHandler, r: Dict[str, object], discard_tips: bool, rack_col: int):
    plate = r["work_plate"]
    vols = [DILUENT_PREFILL] * N_CH
    print(f"\n=== DILUENT: {DILUENT_PREFILL} uL into cols {DILUENT_FILL_COLS[0]}-{DILUENT_FILL_COLS[-1]}, rows A-{LAST_ROW} ===")
    print(f"Using p300 rack column {rack_col}; discard_tips={discard_tips}")
    await lh.pick_up_tips(tip_col(r, rack_col))
    try:
        for col in DILUENT_FILL_COLS:
            print(f"  reservoir {DILUENT_WELL} -> col {col}")
            await lh.aspirate(
                reservoir_well(r, DILUENT_WELL),
                vols=vols,
                liquid_height=[P300_RES_ASP_HEIGHT] * N_CH,
                offsets=[P300_RES_ASP_OFFSET] * N_CH,
                blow_out_air_volume=[0.0] * N_CH,
            )
            await lh.dispense(
                plate_col(plate, col),
                vols=vols,
                liquid_height=[P300_PLATE_DSP_HEIGHT] * N_CH,
                offsets=[P300_PLATE_XY] * N_CH,
                blow_out_air_volume=[DSP_BLOWOUT_AIR_VOLUME] * N_CH,
            )
    finally:
        await finish_tips(lh, discard_tips)
    print("SUCCESS: diluent fill complete.")


async def fill_dye(lh: LiquidHandler, r: Dict[str, object], discard_tips: bool, rack_col: int):
    plate = r["work_plate"]
    vols = [DYE_COL1_VOL] * N_CH
    print(f"\n=== DYE: {DYE_COL1_VOL} uL Rhodamine 1x into col 1, rows A-{LAST_ROW} ===")
    print(f"Using p300 rack column {rack_col}; discard_tips={discard_tips}")
    await lh.pick_up_tips(tip_col(r, rack_col))
    try:
        await lh.aspirate(
            reservoir_well(r, DYE_WELL),
            vols=vols,
            liquid_height=[P300_RES_ASP_HEIGHT] * N_CH,
            offsets=[P300_RES_ASP_OFFSET] * N_CH,
            blow_out_air_volume=[0.0] * N_CH,
        )
        await lh.dispense(
            plate_col(plate, 1),
            vols=vols,
            liquid_height=[P300_PLATE_DSP_HEIGHT] * N_CH,
            offsets=[P300_PLATE_XY] * N_CH,
            blow_out_air_volume=[DSP_BLOWOUT_AIR_VOLUME] * N_CH,
        )
    finally:
        await finish_tips(lh, discard_tips)
    print("SUCCESS: dye fill complete.")


async def mix_column(lh: LiquidHandler, plate, col: int, mix_cycles: int):
    vols = [MIX_VOL] * N_CH
    for i in range(mix_cycles):
        await lh.aspirate(
            plate_col(plate, col),
            vols=vols,
            liquid_height=[P300_PLATE_MIX_HEIGHT] * N_CH,
            offsets=[P300_PLATE_XY] * N_CH,
            blow_out_air_volume=[0.0] * N_CH,
        )
        await lh.dispense(
            plate_col(plate, col),
            vols=vols,
            liquid_height=[P300_PLATE_MIX_HEIGHT] * N_CH,
            offsets=[P300_PLATE_XY] * N_CH,
            blow_out_air_volume=[0.0] * N_CH,
        )


async def run_serial(lh: LiquidHandler, r: Dict[str, object], discard_tips: bool, first_rack_col: int, mix_cycles: int):
    plate = r["work_plate"]
    xfer = [TRANSFER_VOL] * N_CH
    print(f"\n=== SERIAL: 10 x {TRANSFER_VOL} uL, col 1 -> 2 -> ... -> 11, mix each destination {mix_cycles}x ===")
    rack_col = first_rack_col
    for src in DILUTION_COLS[:-1]:   # 1..10
        dst = src + 1
        print(f"\n  step col {src} -> col {dst}  (p300 rack column {rack_col})")
        await lh.pick_up_tips(tip_col(r, rack_col))
        try:
            await lh.aspirate(
                plate_col(plate, src),
                vols=xfer,
                liquid_height=[P300_PLATE_ASP_HEIGHT] * N_CH,
                offsets=[P300_PLATE_XY] * N_CH,
                blow_out_air_volume=[0.0] * N_CH,
            )
            await lh.dispense(
                plate_col(plate, dst),
                vols=xfer,
                liquid_height=[P300_PLATE_DSP_HEIGHT] * N_CH,
                offsets=[P300_PLATE_XY] * N_CH,
                blow_out_air_volume=[DSP_BLOWOUT_AIR_VOLUME] * N_CH,
            )
            print(f"    mixing col {dst} ({mix_cycles} x {MIX_VOL} uL)")
            await mix_column(lh, plate, dst, mix_cycles)

            if dst == DILUTION_COLS[-1]:   # col 11: discard the extra 100 uL to waste
                print(f"    discard {FINAL_DISCARD_VOL} uL col {dst} -> waste {WASTE_WELL} (same tips)")
                await lh.aspirate(
                    plate_col(plate, dst),
                    vols=[FINAL_DISCARD_VOL] * N_CH,
                    liquid_height=[P300_PLATE_ASP_HEIGHT] * N_CH,
                    offsets=[P300_PLATE_XY] * N_CH,
                    blow_out_air_volume=[0.0] * N_CH,
                )
                await lh.dispense(
                    reservoir_well(r, WASTE_WELL),
                    vols=[FINAL_DISCARD_VOL] * N_CH,
                    liquid_height=[P300_WASTE_DSP_HEIGHT] * N_CH,
                    offsets=[P300_WASTE_DSP_OFFSET] * N_CH,
                    blow_out_air_volume=[WASTE_BLOWOUT_AIR_VOLUME] * N_CH,
                )
            await asyncio.sleep(POST_DISPENSE_SETTLE_SECONDS)
        finally:
            await finish_tips(lh, discard_tips)
        rack_col += 1
    print("\nSUCCESS: serial dilution complete. Every well A-C, cols 1-12 holds 100 uL.")


async def run_all(lh: LiquidHandler, r: Dict[str, object], discard_tips: bool, mix_cycles: int):
    print("\n=== ALL: diluent -> dye -> serial ===")
    await fill_diluent(lh, r, discard_tips, rack_col=1)
    await fill_dye(lh, r, discard_tips, rack_col=2)
    await run_serial(lh, r, discard_tips, first_rack_col=3, mix_cycles=mix_cycles)
    print("\nSUCCESS: QC plate built. Hand to the Tecan reader go/no-go.")
    print("  07_tecan_raw_absorbance.py --preloaded --wavelength 554 --wells A1,A12")


def build_backend(sim: bool):
    if sim:
        from pylabrobot.liquid_handling.backends.hamilton.STAR_chatterbox import STARChatterboxBackend
        print("Using STARChatterboxBackend (simulation, no hardware).")
        return STARChatterboxBackend()
    return STARBackend()


async def main():
    parser = argparse.ArgumentParser(
        description="Tecan Infinite QC: Rhodamine B 2-fold serial dilution built on the Hamilton STAR."
    )
    parser.add_argument("--mode", choices=["deck", "diluent", "dye", "serial", "all"], default="deck")
    parser.add_argument(
        "--return-tips",
        action="store_true",
        help="Return tips instead of discarding. Use for dry/water rehearsals. Default is production discard.",
    )
    parser.add_argument(
        "--sim",
        action="store_true",
        help="Use the STAR chatterbox backend (no hardware). Reservoir aspirate trips the chatterbox geometry check; that is expected.",
    )
    parser.add_argument(
        "--mix-cycles",
        type=int,
        default=MIX_CYCLES,
        help=f"In-place mix cycles at each serial destination. Default {MIX_CYCLES}.",
    )
    args = parser.parse_args()

    if args.mix_cycles < 0:
        raise ValueError("--mix-cycles must be >= 0")

    discard_tips = not args.return_tips

    print(f"Initializing STAR (sim={args.sim}) with skip_autoload=True...")
    lh = LiquidHandler(backend=build_backend(args.sim), deck=STARDeck())
    await lh.setup(skip_autoload=True)

    try:
        r = await assign_deck(lh)

        if args.mode == "deck":
            print("\nMode deck: assignment only. No motion or liquid handling executed.")
            return

        print(f"Tip behavior: discard_tips={discard_tips}")
        if args.mode == "diluent":
            await fill_diluent(lh, r, discard_tips, rack_col=1)
        elif args.mode == "dye":
            await fill_dye(lh, r, discard_tips, rack_col=2)
        elif args.mode == "serial":
            await run_serial(lh, r, discard_tips, first_rack_col=3, mix_cycles=args.mix_cycles)
        elif args.mode == "all":
            await run_all(lh, r, discard_tips, args.mix_cycles)
        else:
            raise RuntimeError(f"Unhandled mode: {args.mode}")

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

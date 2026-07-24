import asyncio
import sys
from pathlib import Path

_method_root = next(
    parent for parent in Path(__file__).resolve().parents if parent.name == "hamilton-star"
)
if str(_method_root) not in sys.path:
    sys.path.insert(0, str(_method_root))
from operator_parameters import required_integer, required_positive

from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends import STARBackend
from pylabrobot.resources.hamilton import STARDeck, TIP_CAR_480_A00
from pylabrobot.resources import (
    PLT_CAR_L5AC_A00,
    CellTreat_12_troughplate_15000ul_Vb,
    CellTreat_96_wellplate_350ul_Fb,
    CellTreat_96_wellplate_350ul_Ub,
    hamilton_96_tiprack_1000uL_filter,
    hamilton_96_tiprack_50uL_filter,
    Coordinate,
)

# ---------------------------------------------------------------------
# whole-genome sequencing WGS preparation - liquid handling first pass
#
# Assumptions for this scaffold:
# - Working/sample plate is at rail 33 pos 0.
# - Magnetic cleanup plate position is rail 40 pos 0.
# - For now, rail 40 pos 0 reuses the same p1000 destination settings
#   as rail 33 pos 0 until magnet-position-specific tuning is done.
# - iSWAP / ODTC moves are NOT implemented yet. This file only covers
#   liquid movements.
# - Start with 8 samples in column 1. Scaling to additional columns is
#   done by extending DEST_COLUMNS.
# - Stage identities, volumes, and any sample-specific assignments come from
#   an operator-approved local method profile.
# ---------------------------------------------------------------------

TIP_RAIL = 19
P1000_TIP_POS = 0
P50_TIP_POS = 1

SOURCE_RAIL = 26
SOURCE_POS = 1
TROUGH_POS = 2

WORK_RAIL = 33
WORK_POS = 0

MAG_RAIL = 40
MAG_POS = 0

DEST_COLUMNS = [1]   # v1: 8 samples only; extend later to [1,2,...]

# -----------------------------
# Tuned p50 settings
# -----------------------------
P50_ASP_HEIGHT = [4.5] * 8
P50_ASP_OFFSETS = [Coordinate(0.20, 2.30, 0.5)] * 8

P50_WORK_DSP_HEIGHT = [5.0] * 8
P50_WORK_DSP_OFFSETS = [Coordinate(0.10, 2.45, 27.0)] * 8

# -----------------------------
# Tuned p1000 settings
# -----------------------------
P1000_ASP_HEIGHT = [1.5] * 8
P1000_ASP_OFFSETS = [Coordinate(0.0, 1.5, 0.0)] * 8

P1000_WORK_DSP_HEIGHT = [5.0] * 8
P1000_WORK_DSP_OFFSETS = [Coordinate(0.10, 2.20, 30.0)] * 8

# Placeholder: use same destination behavior for rail 40 pos 0 cleanup
P1000_MAG_DSP_HEIGHT = P1000_WORK_DSP_HEIGHT
P1000_MAG_DSP_OFFSETS = P1000_WORK_DSP_OFFSETS

# -----------------------------
# Source layout
# 96-well source plate columns
# -----------------------------
SRC_STAGE_1_COL = 1
SRC_STAGE_2_COL = 2
SRC_STAGE_3_COL = 3
SRC_STAGE_4_COL = 4
SRC_STAGE_6_COL = 5
SRC_STAGE_7_COL = 6

# -----------------------------
# Trough layout
# -----------------------------
TROUGH_CLEANUP_REAGENT = "A1"
TROUGH_WASH1 = "A2"
TROUGH_WASH2 = "A3"
TROUGH_RECOVERY = "A4"

# -----------------------------
# Required wet-method parameters. Import fails before hardware setup unless
# PLR_METHOD_PARAMETERS_FILE points to an operator-approved local profile.
# -----------------------------
VOL_STAGE_1 = required_positive("wgs.stage_1_volume_ul")
VOL_STAGE_2 = required_positive("wgs.stage_2_volume_ul")
VOL_STAGE_3 = required_positive("wgs.stage_3_volume_ul")
VOL_STAGE_4 = required_positive("wgs.stage_4_volume_ul")
VOL_STAGE_5 = required_positive("wgs.stage_5_volume_ul")
VOL_STAGE_6 = required_positive("wgs.stage_6_volume_ul")
VOL_STAGE_7 = required_positive("wgs.stage_7_volume_ul")

VOL_CLEANUP_REAGENT = required_positive("wgs.cleanup.bead_volume_ul")
VOL_WASH_ADD = required_positive("wgs.cleanup.wash_add_ul")
VOL_RECOVERY = required_positive("wgs.cleanup.elution_ul")
VOL_FINAL_TRANSFER = required_positive("wgs.cleanup.final_transfer_ul")
WASH_COUNT = required_integer("wgs.cleanup.wash_count", minimum=1, maximum=2)


async def transfer_column(
    lh,
    source_wells,
    target_wells,
    vol,
    asp_height,
    asp_offsets,
    dsp_height,
    dsp_offsets,
    label,
):
    volumes = [vol] * 8

    print(f"Aspirating {vol} uL from {label}...")
    await lh.aspirate(
        source_wells,
        vols=volumes,
        liquid_height=asp_height,
        offsets=asp_offsets,
        blow_out_air_volume=[0.0] * 8,
    )

    print(f"Dispensing {vol} uL into destination wells...")
    await lh.dispense(
        target_wells,
        vols=volumes,
        liquid_height=dsp_height,
        offsets=dsp_offsets,
        blow_out_air_volume=[0.0] * 8,
    )


async def transfer_from_trough(
    lh,
    source_well,
    target_wells,
    vol,
    asp_height,
    asp_offsets,
    dsp_height,
    dsp_offsets,
    label,
):
    volumes = [vol] * 8

    print(f"Aspirating {vol} uL from trough {label}...")
    await lh.aspirate(
        [source_well] * 8,
        vols=volumes,
        liquid_height=asp_height,
        offsets=asp_offsets,
        blow_out_air_volume=[0.0] * 8,
    )

    print(f"Dispensing {vol} uL into destination wells...")
    await lh.dispense(
        target_wells,
        vols=volumes,
        liquid_height=dsp_height,
        offsets=dsp_offsets,
        blow_out_air_volume=[0.0] * 8,
    )


def wells_for_column(plate, col: int):
    return plate[f"A{col}:H{col}"]


async def run_wgs_prep_additions(lh, p50_tips, source_plate, work_plate):
    print("\n=== WGS preparation ADDITIONS ===")
    await lh.pick_up_tips(p50_tips["A1:H1"])

    for col in DEST_COLUMNS:
        await transfer_column(
            lh,
            source_plate[f"A{SRC_STAGE_1_COL}:H{SRC_STAGE_1_COL}"],
            wells_for_column(work_plate, col),
            VOL_STAGE_1,
            P50_ASP_HEIGHT,
            P50_ASP_OFFSETS,
            P50_WORK_DSP_HEIGHT,
            P50_WORK_DSP_OFFSETS,
            f"operator-defined stage 1 source, column {SRC_STAGE_1_COL}",
        )

    for col in DEST_COLUMNS:
        await transfer_column(
            lh,
            source_plate[f"A{SRC_STAGE_2_COL}:H{SRC_STAGE_2_COL}"],
            wells_for_column(work_plate, col),
            VOL_STAGE_2,
            P50_ASP_HEIGHT,
            P50_ASP_OFFSETS,
            P50_WORK_DSP_HEIGHT,
            P50_WORK_DSP_OFFSETS,
            f"operator-defined stage 2 source, column {SRC_STAGE_2_COL}",
        )

    await lh.return_tips()

    print("Operator handoff after stages 1-2: follow the approved local method.")


async def run_library_prep_additions(lh, p50_tips, source_plate, work_plate):
    print("\n=== LIBRARY PREP ADDITIONS ===")
    await lh.pick_up_tips(p50_tips["A1:H1"])

    for col in DEST_COLUMNS:
        await transfer_column(
            lh,
            source_plate[f"A{SRC_STAGE_3_COL}:H{SRC_STAGE_3_COL}"],
            wells_for_column(work_plate, col),
            VOL_STAGE_3,
            P50_ASP_HEIGHT,
            P50_ASP_OFFSETS,
            P50_WORK_DSP_HEIGHT,
            P50_WORK_DSP_OFFSETS,
            f"operator-defined stage 3 source, column {SRC_STAGE_3_COL}",
        )

    for col in DEST_COLUMNS:
        await transfer_column(
            lh,
            source_plate[f"A{SRC_STAGE_4_COL}:H{SRC_STAGE_4_COL}"],
            wells_for_column(work_plate, col),
            VOL_STAGE_4,
            P50_ASP_HEIGHT,
            P50_ASP_OFFSETS,
            P50_WORK_DSP_HEIGHT,
            P50_WORK_DSP_OFFSETS,
            f"operator-defined stage 4 source, column {SRC_STAGE_4_COL}",
        )

    print(
        "Operator handoff for stage 5: use the approved sample-specific assignment "
        f"and volume ({VOL_STAGE_5} uL)."
    )

    for col in DEST_COLUMNS:
        await transfer_column(
            lh,
            source_plate[f"A{SRC_STAGE_6_COL}:H{SRC_STAGE_6_COL}"],
            wells_for_column(work_plate, col),
            VOL_STAGE_6,
            P50_ASP_HEIGHT,
            P50_ASP_OFFSETS,
            P50_WORK_DSP_HEIGHT,
            P50_WORK_DSP_OFFSETS,
            f"operator-defined stage 6 source, column {SRC_STAGE_6_COL}",
        )

    for col in DEST_COLUMNS:
        await transfer_column(
            lh,
            source_plate[f"A{SRC_STAGE_7_COL}:H{SRC_STAGE_7_COL}"],
            wells_for_column(work_plate, col),
            VOL_STAGE_7,
            P50_ASP_HEIGHT,
            P50_ASP_OFFSETS,
            P50_WORK_DSP_HEIGHT,
            P50_WORK_DSP_OFFSETS,
            f"operator-defined stage 7 source, column {SRC_STAGE_7_COL}",
        )

    await lh.return_tips()

    print("Operator handoff after stages 3-7: follow the approved local method.")


async def run_cleanup_on_magnet(lh, p1000_tips, trough, mag_plate, output_plate):
    print("\n=== CLEANUP AT MAGNET POSITION (rail 40 pos 0) ===")
    await lh.pick_up_tips(p1000_tips["A1:H1"])

    for col in DEST_COLUMNS:
        await transfer_from_trough(
            lh,
            trough[TROUGH_CLEANUP_REAGENT][0],
            wells_for_column(mag_plate, col),
            VOL_CLEANUP_REAGENT,
            P1000_ASP_HEIGHT,
            P1000_ASP_OFFSETS,
            P1000_MAG_DSP_HEIGHT,
            P1000_MAG_DSP_OFFSETS,
            f"{TROUGH_CLEANUP_REAGENT} (operator-defined cleanup reagent)",
        )

    print("Operator handoff after cleanup reagent addition.")

    print("TODO: remove supernatant on magnet.")

    for col in DEST_COLUMNS:
        await transfer_from_trough(
            lh,
            trough[TROUGH_WASH1][0],
            wells_for_column(mag_plate, col),
            VOL_WASH_ADD,
            P1000_ASP_HEIGHT,
            P1000_ASP_OFFSETS,
            P1000_MAG_DSP_HEIGHT,
            P1000_MAG_DSP_OFFSETS,
            f"{TROUGH_WASH1} (operator-defined wash 1)",
        )

    print("TODO: remove ethanol wash 1 on magnet.")

    if WASH_COUNT == 2:
        for col in DEST_COLUMNS:
            await transfer_from_trough(
                lh,
                trough[TROUGH_WASH2][0],
                wells_for_column(mag_plate, col),
                VOL_WASH_ADD,
                P1000_ASP_HEIGHT,
                P1000_ASP_OFFSETS,
                P1000_MAG_DSP_HEIGHT,
                P1000_MAG_DSP_OFFSETS,
                f"{TROUGH_WASH2} (operator-defined wash 2)",
            )

        print("TODO: remove wash 2 on the magnet.")
    print("TODO: complete the operator-approved residual-removal / air-dry handoff.")

    for col in DEST_COLUMNS:
        await transfer_from_trough(
            lh,
            trough[TROUGH_RECOVERY][0],
            wells_for_column(mag_plate, col),
            VOL_RECOVERY,
            P1000_ASP_HEIGHT,
            P1000_ASP_OFFSETS,
            P1000_MAG_DSP_HEIGHT,
            P1000_MAG_DSP_OFFSETS,
            f"{TROUGH_RECOVERY} (operator-defined recovery solution)",
        )

    print("TODO after elution: incubate / magnet clear.")

    print(
        "TODO: final operator-defined transfer from magnet plate to output plate "
        f"({VOL_FINAL_TRANSFER} uL)."
    )
    # Placeholder only; real supernatant removal settings need separate tuning.

    await lh.return_tips()


async def main():
    print("Initializing STAR...")
    lh = LiquidHandler(backend=STARBackend(), deck=STARDeck())
    await lh.setup(skip_autoload=True)

    print("Assigning deck resources...")

    tip_carrier = TIP_CAR_480_A00(name=f"tip_car_rail{TIP_RAIL}")
    lh.deck.assign_child_resource(tip_carrier, rails=TIP_RAIL)

    source_carrier = PLT_CAR_L5AC_A00(name=f"source_car_rail{SOURCE_RAIL}")
    lh.deck.assign_child_resource(source_carrier, rails=SOURCE_RAIL)

    work_carrier = PLT_CAR_L5AC_A00(name=f"work_car_rail{WORK_RAIL}")
    lh.deck.assign_child_resource(work_carrier, rails=WORK_RAIL)

    mag_carrier = PLT_CAR_L5AC_A00(name=f"mag_car_rail{MAG_RAIL}")
    lh.deck.assign_child_resource(mag_carrier, rails=MAG_RAIL)

    p1000_tips = hamilton_96_tiprack_1000uL_filter(name="p1000_filter_tips")
    p50_tips = hamilton_96_tiprack_50uL_filter(name="p50_filter_tips")

    source_plate = CellTreat_96_wellplate_350ul_Ub(name="source_reagent_plate")
    trough = CellTreat_12_troughplate_15000ul_Vb(name="bulk_liquid_trough")

    work_plate = CellTreat_96_wellplate_350ul_Fb(name="work_plate")
    mag_plate = CellTreat_96_wellplate_350ul_Fb(name="mag_cleanup_plate")
    output_plate = CellTreat_96_wellplate_350ul_Fb(name="cleanup_output_plate")

    tip_carrier[P1000_TIP_POS] = p1000_tips
    tip_carrier[P50_TIP_POS] = p50_tips

    source_carrier[SOURCE_POS] = source_plate
    source_carrier[TROUGH_POS] = trough

    work_carrier[WORK_POS] = work_plate
    mag_carrier[MAG_POS] = mag_plate

    # output_plate is not placed yet in this first-pass scaffold;
    # final placement can be decided once iSWAP / deck layout is finalized.

    await run_wgs_prep_additions(lh, p50_tips, source_plate, work_plate)
    await run_library_prep_additions(lh, p50_tips, source_plate, work_plate)

    print("TODO: iSWAP move work_plate -> mag_plate before cleanup.")
    await run_cleanup_on_magnet(lh, p1000_tips, trough, mag_plate, output_plate)

    print("Stopping...")
    await lh.stop()
    print("Done.")


asyncio.run(main())

# run_pcr_enrichment_odtc_LIDDED_1col_full_v2_singlehome_dry.py
#
# SINGLE-HOME V2 of the LIDDED PCR enrichment column-1 + ODTC thermocycler choreography.
#
# Copied from run_pcr_enrichment_odtc_1col_full_v2_singlehome_dry.py (the 9-leg, non-lidded
# single-home V2) and extended with the four lid legs, so it is the single-home
# equivalent of run_pcr_enrichment_odtc_LIDDED_1col_full_dry.py.
#
# WHY: the LIDDED subprocess orchestrator launches all 13 legs as separate OS
# processes, so it homes / sets up / stops the STAR THIRTEEN times (one home per
# leg). This builds ONE LiquidHandler, homes ONCE via lh.setup(skip_autoload=True),
# assigns the FULL unified deck ONCE, runs all 13 legs in-process against the shared
# handler, then parks the iSWAP and stops ONCE.
#
# PATCH LOG
#   2026-07-16  Created. Two findings made this NOT a mechanical merge; both are
#               load-bearing and are why the constants below are what they are.
#
#     (1) PLATE MODEL. The subprocess legs disagree about what the work plate IS,
#         and get away with it because each leg builds its own resource tree. The
#         liquid legs model it CellTreat_96_wellplate_350ul_Fb; every iSWAP leg
#         models it Cor_96_wellplate_360ul_Fb. Single-home forces one answer.
#         The two plates differ by 1.25 mm at the WELL BOTTOM, because
#         material_z_thickness is 0.50 (Cor) vs 1.75 (CellTreat). Unifying on Cor
#         would silently shift the dispense from the tuned 1.5 mm to an effective
#         0.25 mm -- BELOW the 0.5 mm that was already crushing tips into the well
#         (see 87b6e52). Chatterbox cannot catch that; it shows up as crushed tips
#         on hardware. So the work plate STAYS CellTreat and the pipetting geometry
#         is carried over byte-for-byte. Motion uses the explicit Cor-equivalent
#         compensation added below. Do not "simplify" this to one plate class.
#
#     (2) THE LID. CellTreat_96_wellplate_350ul_Fb cannot model a lid at all in PLR
#         0.2.1 (with_lid=True raises TypeError), so the lid cannot live on the work
#         plate. It parks at rail35 pos4 on a Cor_96_wellplate_360ul_Fb(with_lid=True),
#         exactly as the confirmed lid mover models it, and moves cross-model onto the
#         CellTreat work plate. Cross-model move_lid re-parents correctly, but the
#         destination plate model changes the emitted pickup/drop Z. The motion-only
#         compensation below restores the exact proven Corning command.
#
#   2026-07-16  Dispense geometry carried forward from the mastermix legs (01_/03_):
#               dispense height 1.5 mm, firmware in-well Mix 3x 10 uL @ 50 uL/s with the
#               tip planted in the well, blowout 10 uL.
#   2026-07-16  mix_position_from_liquid_surface corrected 2.0 -> 1.0. It is a DOWNWARD
#               depth (proven on hardware, test_mix_position_sign_SAFE.py), so 2.0 against
#               liquid_height 1.5 drove the tips to well_bottom - 0.5 mm. 1.0 puts the mix
#               at well_bottom + 0.5 mm. See the PATCH note above MIX_CYCLES.
#   2026-07-21  RELEASE BLOCKER FIX. Directly carrying the CellTreat model through
#               iSWAP did NOT preserve the proven component commands. PLR 0.2.1 gives
#               CellTreat a carrier-local z -4.05 anchor versus Corning z -3.03 and
#               different x/y centers and grip width. The uncorrected one-session trace
#               shifted critical commands x/y by 0.1 mm, z by 0.9 mm, and grip width by
#               0.2 mm. This is material because lid-off has only about 2 mm between the
#               known-bad plate-grab z5 and the proven lid-grab z7. Added model locks and
#               motion-only x0.075/y0.120/z0.920 compensation plus the proven Corning
#               grip width. The resulting 20 C0PP/C0PR commands are byte-identical,
#               after command-id normalization, to the hardware-proven standalone legs.
#   2026-07-21  Guarded physical release: exact intent/deck/labware tokens, PLR/model/
#               geometry locks before backend creation, connection-free deck mode,
#               resource-parent and pristine-site assertions at every handoff, no iSWAP
#               auto-park after failure, and no automatic tip disposition after a failed
#               liquid command.
#
# The 13 legs, in order (identical to the LIDDED subprocess orchestrator):
#   1  PCR1 master mix add        (p50, tip col1)      rail35 pos0 work plate
#   2  iSWAP  rail35 pos0        -> rail20 pos1 ODTC nest   (PCR1 handoff)
#   2b LID ON   rail35 pos4      -> plate in ODTC nest      (seal for PCR1)
#      <-- in a REAL run the ODTC PCR1 thermal program runs HERE, lid sealed -->
#   2c LID OFF  ODTC nest        -> rail35 pos4             (unseal before lifting)
#   3  iSWAP  rail20 pos1 nest   -> rail35 pos0            (return, pickup z0 / drop z8.5)
#   4  iSWAP  rail35 pos0        -> rail35 pos2 magnet      (bead-clean handoff)
#   5  PCR1 cleanup all-dry on magnet (operator-profile sequence)
#   6  iSWAP  rail35 pos2 magnet -> rail35 pos0            (return, pickup z14 / drop z8.5)
#   7  PCR2 master mix add        (p50, tip col2)      rail35 pos0 work plate
#   8  iSWAP  rail35 pos0        -> rail20 pos1 ODTC nest   (PCR2 handoff)
#   8b LID ON   rail35 pos4      -> plate in ODTC nest      (seal for PCR2)
#      <-- in a REAL run the ODTC PCR2 thermal program runs HERE, lid sealed -->
#   8c LID OFF  ODTC nest        -> rail35 pos4             (unseal before lifting)
#   9  iSWAP  rail20 pos1 nest   -> rail35 pos0            (return, pickup z0 / drop z8.5)
#
# Every tuned geometry value is preserved EXACTLY from the standalone legs
# (aspirate/dispense heights + offsets + blowouts, and all iSWAP pickup/drop
# offsets: ODTC fwd pickup z5 / drop x2 y36.5 z12, ODTC ret pickup z0 / drop z8.5,
# magnet fwd pickup z8.5 / drop z18, magnet ret pickup z14 / drop z8.5). Tips are
# RETURNED (dry) throughout.
#
# The plate is modeled as ONE moving CellTreat sample plate threaded through every
# iSWAP handoff. The standalone iSWAP test scripts used a Cor_96 stand-in plate; the
# merged model uses the real CellTreat sample plate so the liquid-handling legs
# address the same object wherever it currently sits (pos0 for PCR1/PCR2, pos2 for
# cleanup, rail20 pos1 for the ODTC trips).
#
# Precisely what the plate-type choice moves (measured, PLR 0.2.1):
#   iSWAP command: CellTreat versus Cor shifts x/y center, top Z, and grip width. The
#                  motion-only compensation below restores exact Cor command parity.
#   Well bottom:   1.25 mm apart (material_z_thickness 0.50 vs 1.75). Liquid geometry
#                  therefore remains paired with the truthful CellTreat model.
#
# Per-leg teach-point mutations are applied immediately before each move and
# restored to pristine afterward, so there is no cross-leg coordinate bleed across
# the shared deck (the single-session hazard the standalone legs never hit because
# each ran in its own process).
#
# SAFETY / RUN ORDER: run --mode chatterbox (no hardware) FIRST to rehearse the
# whole sequence, THEN --mode deck (assign + print geometry, NO motion) to eyeball
# the teach points, and ONLY THEN use --mode star with all three exact release tokens.
# Confirm deck staging and E-stop reachability before any hardware run: the arm makes
# 13 protocol legs including two ODTC round trips WITH lid on/off and one magnet round
# trip. Only ONE driver may hold the STAR at a time.
#
# DECK STAGING (all of it, before a hardware run):
#   rail48 pos0 p10 tips (unused) / pos1 p50 tips / pos2 p300 tips
#   rail35 pos0 work plate (CellTreat, sacrificial) / pos1 mm source / pos2 magnet
#          pos3 reservoir-waste trough / pos4 LID parked on a Cor plate
#   rail20 pos1 ODTC nest, EMPTY and open
# The magnet MUST be physically at rail35 pos2, the lid on pos4, and the ODTC nest
# empty, or an iSWAP releases into open space.
#
# The equivalent 13-leg subprocess choreography passed on hardware on 2026-07-16,
# including both ODTC lid cycles and the magnet round trip. This ONE-session composition
# is Chatterbox-validated but has not yet been run on hardware. It does not connect to,
# heat, initialize, or move the ODTC; the ODTC is only a physical landing nest here.
#
# ASCII only.

import argparse
import asyncio
import importlib
from importlib.metadata import PackageNotFoundError, version
from types import SimpleNamespace
from typing import Dict

from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.resources.hamilton import STARDeck, TIP_CAR_480_A00
from pylabrobot.resources import (
    PLT_CAR_L5AC_A00,
    CellTreat_96_wellplate_350ul_Fb,
    CellTreat_12_troughplate_15000ul_Vb,
    Cor_96_wellplate_360ul_Fb,
    Coordinate,
)
import pylabrobot.resources as plr_resources
from pylabrobot.liquid_handling.standard import Mix

from pathlib import Path as _MethodPath
import sys as _method_sys

_method_root = next(
    parent for parent in _MethodPath(__file__).resolve().parents
    if parent.name == "hamilton-star"
)
if str(_method_root) not in _method_sys.path:
    _method_sys.path.insert(0, str(_method_root))
from operator_parameters import required_positive, required_integer


# ---------------------------------------------------------------------------
# Release gates
# ---------------------------------------------------------------------------
CONFIRM_TOKEN = "RUN_PCR_ENRICHMENT_ODTC_LIDDED_SINGLEHOME_DRY"
DECK_ACK = "R48_P10_P50_P300_R35_WORK_SOURCE_MAGNET_TROUGH_LID_R20_ODTC_EMPTY_OPEN"
LABWARE_ACK = "CELLTREAT_229195_WORK_SOURCE_CORNING_3603_LID"
EXPECTED_PLR_VERSION = "0.2.1"


# ---------------------------------------------------------------------------
# Deck layout constants (unified single deck; assigned ONCE)
# ---------------------------------------------------------------------------
TIP_RAIL = 48
P10_TIP_POS = 0        # deck parity only, unused by any leg
P50_TIP_POS = 1
P300_TIP_POS = 2

LABWARE_RAIL = 35
WORK_POS = 0           # sacrificial work plate (moved around by the iSWAP)
SOURCE_96WP_POS = 1    # PCR1 / PCR2 master-mix source (operator swaps contents between legs)
MAG_POS = 2            # magnet block; plate arrives here by iSWAP for the bead clean
TROUGH_POS = 3         # reservoir / waste
LID_POS = 4            # LID parked here (on a Cor plate); rides to the ODTC nest and back

ODTC_RAIL = 20
ODTC_POSITION = 1      # ODTC nest; must be empty + open to receive the plate

SOURCE_COL = 1
DEST_COL = 1


# ---------------------------------------------------------------------------
# Tip factory candidates (first available name wins), from the leg specs
# ---------------------------------------------------------------------------
P10_TIP_FACTORY_CANDIDATES = [
    "hamilton_96_tiprack_10uL_filter",
    "hamilton_96_tiprack_10ul_filter",
]
P50_TIP_FACTORY_CANDIDATES = [
    "hamilton_96_tiprack_50uL_filter",
    "hamilton_96_tiprack_50ul_filter",
]
P300_TIP_FACTORY_CANDIDATES = [
    "hamilton_96_tiprack_300uL_filter",
    "hamilton_96_tiprack_300ul_filter",
    "hamilton_96_tiprack_300uL_filter_slim",
    "hamilton_96_tiprack_300ul_filter_slim",
]


# ---------------------------------------------------------------------------
# PCR1 / PCR2 master-mix geometry (identical p50 geometry; volumes differ)
# ---------------------------------------------------------------------------
VOL_PCR1_MASTER_MIX = required_positive("pcr_enrichment.round_1_transfer_ul")
VOL_PCR2_MASTER_MIX = required_positive("pcr_enrichment.round_2_transfer_ul")
PCR1_REACTION_VOLUME_UL = required_positive("pcr_enrichment.round_1_reaction_volume_ul")
PCR2_REACTION_VOLUME_UL = required_positive("pcr_enrichment.round_2_reaction_volume_ul")
PCR2_INPUT_VOLUME_UL = required_positive("pcr_enrichment.round_2_input_volume_ul")

# Carried over EXACTLY from the current mastermix legs (01_/03_, 87b6e52). The older
# single-home V2 still had 0.5 here; at 0.5 the tips crushed into the well at dispense.
P50_WORK_DSP_HEIGHT = [1.5] * 8   # raised 0.5 -> 1.5 (2026-07-12)
P50_WORK_DSP_OFFSETS = [Coordinate(-0.68, 3.22, 0.0)] * 8
P50_SOURCE_ASP_HEIGHT = [0.0] * 8
P50_SOURCE_ASP_OFFSETS = [Coordinate(-0.65, 3.35, 0.0)] * 8
P50_BLOWOUT_AIR_VOLUME = 6.0      # master-mix dispense blowout; the mix loop below ends with its own

# IN-WELL MIX (firmware Mix): the tip stays planted IN the well and the plunger cycles in
# place. This is real mixing. A Python aspirate/dispense loop is NOT: it retracts the whole
# head between cycles, which is squirt-and-repeat. Observed on the instrument 2026-07-16 and
# rejected for that reason.
#
# THE SIGN IS PROVEN, DO NOT GUESS IT AGAIN. A comment previously here claimed
# "mix_position_from_liquid_surface must be POSITIVE: the STAR mixes at liquid_surface +
# this value". That is FALSE and it is the belief that produced the crush.
# test_mix_position_sign_SAFE.py ran on the instrument 2026-07-16 (declared surface 10 mm,
# param 5 mm -> the tips went DOWN to 5 mm, inside the well): the parameter is a DEPTH
# measured DOWNWARD.
#
#     mix Z = well_bottom + liquid_height - mix_position_from_liquid_surface
#
# lld_mode defaults to LLDMode.OFF and is never passed, so the modelled surface is
# well_bottom + liquid_height. With liquid_height = 1.5:
#     param 2.0 -> mix Z = -0.5 mm   eight tips INTO the plastic  (the 87b6e52 bug)
#     param 1.0 -> mix Z = +0.5 mm   the aspirate height the on-camera build already used
# PLR 0.2.1's STARBackend.dispense docstring says the value moves ABOVE the surface and is
# WRONG; dispense_pip ("Z- direction", default 250 = 25 mm) is right. Nothing guards it:
# 2.0 -> 20 is inside 0..900, dispense_pip uses `assert any(...)` not `all(...)`, and
# chatterbox has no well-geometry model. The number below is load-bearing.
#
# Reaction and destination-input volumes are required from the operator profile.
# The motion values below are hardware calibration; verify the locally approved
# volumes keep the mix position safe for the selected well before any wet run.
# Sample is low-input DNA: blowout stays 10 uL so nothing is left in tip.
MIX_CYCLES = 3
MIX_VOLUME_UL = 10.0
MIX_FLOW_RATE = 10.0                     # uL/s, plunger speed for the in-well mix. 50 -> 10
                                         # (2026-07-16): at 50 the whole 3x 10 uL mix took 1.2 s,
                                         # too fast to see or hear. At 10 it takes ~6 s.
MIX_POSITION_FROM_SURFACE = [1.0] * 8    # -> mix Z = 1.5 - 1.0 = 0.5 mm above the well bottom
P50_MIX_BLOWOUT_AIR_VOLUME = 10.0        # dialed 12 -> 10 (12 risked splashing the shallow well)

POST_DISPENSE_SETTLE_SECONDS = 1.0


# ---------------------------------------------------------------------------
# PCR1 cleanup geometry (02_pcr_enrichment_round1_cleanup_col1_dry_v2_p50low.py)
# ---------------------------------------------------------------------------
TROUGH_BEADS = "A1"
TROUGH_ETOH1 = "A2"
TROUGH_ETOH2 = "A3"
TROUGH_ELUTION = "A4"
TROUGH_WASTE = "A12"

VOL_BEADS = required_positive("pcr_enrichment.cleanup.bead_volume_ul")
VOL_SUPERNATANT_REMOVE = required_positive("pcr_enrichment.cleanup.supernatant_remove_ul")
VOL_ETHANOL_ADD = required_positive("pcr_enrichment.cleanup.wash_add_ul")
VOL_ETHANOL_REMOVE = required_positive("pcr_enrichment.cleanup.wash_remove_ul")
VOL_RESIDUAL_ETHANOL_REMOVE = required_positive("pcr_enrichment.cleanup.residual_remove_ul")
VOL_ELUTION = required_positive("pcr_enrichment.cleanup.elution_ul")
WASH_COUNT = required_integer("pcr_enrichment.cleanup.wash_count", minimum=1, maximum=2)

# p300 add-from-trough
P300_TROUGH_ASP_HEIGHT = [0.3] * 8
P300_TROUGH_ASP_OFFSETS = [Coordinate(0.0, 1.5, 0.0)] * 8
P300_MAG_DSP_HEIGHT = [4.0] * 8
P300_MAG_DSP_OFFSETS = [Coordinate(0.28, 3.00, 14.5)] * 8
P300_ADD_BLOWOUT_AIR_VOLUME = 3.0

# p300 remove-to-waste
P300_MAG_REMOVE_ASP_HEIGHT = [16.0] * 8
P300_MAG_REMOVE_ASP_OFFSETS = [Coordinate(0.28, 3.35, 0.0)] * 8
P300_WASTE_DSP_HEIGHT = [12.0] * 8
P300_WASTE_DSP_OFFSETS = [Coordinate(0.0, 1.5, 0.0)] * 8
P300_REMOVE_BLOWOUT_AIR_VOLUME = 2.0

# p50 residual-ethanol remove-to-waste
P50_MAG_RESIDUAL_ASP_HEIGHT = [8.0] * 8
P50_MAG_RESIDUAL_ASP_OFFSETS = [Coordinate(0.28, 3.35, 0.0)] * 8
P50_WASTE_DSP_HEIGHT = [8.0] * 8
P50_WASTE_DSP_OFFSETS = [Coordinate(0.0, 1.5, 0.0)] * 8
P50_RESIDUAL_BLOWOUT_AIR_VOLUME = 2.0

# p50 low-volume add-from-trough (beads + elution onto beads)
P50_LOW_TROUGH_ASP_HEIGHT = [2.0] * 8
P50_LOW_TROUGH_ASP_OFFSETS = [Coordinate(0.0, 1.5, 0.0)] * 8
P50_LOW_MAG_DSP_HEIGHT = [3.0] * 8
P50_LOW_MAG_DSP_OFFSETS = [Coordinate(0.28, 2.20, 16.0)] * 8
P50_LOW_ADD_BLOWOUT_AIR_VOLUME = 4.0


# ---------------------------------------------------------------------------
# iSWAP handoff geometry (offsets applied to plate / carrier-site .location)
# Exactly as the standalone iSWAP legs were invoked by the old wrapper.
# ---------------------------------------------------------------------------
# ODTC forward: rail35 pos0 -> rail20 pos1 nest. Pickup offset applied to the PLATE.
ODTC_FWD_PICKUP_DZ = 5.0
ODTC_FWD_DROP_DX = 2.0
ODTC_FWD_DROP_DY = 36.5
ODTC_FWD_DROP_DZ = 12.0

# ODTC return: rail20 pos1 nest -> rail35 pos0. Pickup offset applied to the SLOT
# (frame fix so pickup offsets mean the same thing as the forward-mover drop offsets);
# wrapper passes --odtc-pickup-z-offset-mm 0.
ODTC_RET_PICKUP_DX = 2.0
ODTC_RET_PICKUP_DY = 36.5
ODTC_RET_PICKUP_DZ = 0.0
ODTC_RET_DROP_DZ = 8.5

# Magnet forward: rail35 pos0 -> rail35 pos2. Pickup offset applied to the PLATE.
MAG_FWD_PICKUP_DZ = 8.5
MAG_FWD_DROP_DX = 0.0
MAG_FWD_DROP_DY = 0.0
MAG_FWD_DROP_DZ = 18.0

# Magnet return: rail35 pos2 -> rail35 pos0. Pickup offset applied to the PLATE.
# Wrapper OVERRIDES the leg default (18.0) with --pickup-z-offset-mm 14.0 --drop-z-offset-mm 8.5.
MAG_RET_PICKUP_DZ = 14.0
MAG_RET_DROP_DX = 0.0
MAG_RET_DROP_DY = 0.0
MAG_RET_DROP_DZ = 8.5


# ---------------------------------------------------------------------------
# Lid legs (test_iswap_lid_variable.py, confirmed on hardware 2026-07-12; the
# LID OFF pickup z was corrected 5 -> 7 in 6420b40)
# ---------------------------------------------------------------------------
# LID ON: rail35 pos4 -> the plate sitting in the ODTC nest. The x2/y36.5 line the
# lid up over the nest, matching the plate mover's nest offsets.
LID_ON_PICKUP_DX = 0.0
LID_ON_PICKUP_DY = 0.0
LID_ON_PICKUP_DZ = 9.0
LID_ON_DROP_DX = 2.0
LID_ON_DROP_DY = 36.5
LID_ON_DROP_DZ = 12.0

# LID OFF: ODTC nest -> rail35 pos4. z7, NOT z5: at z5 the grip closes on the PLATE
# and lifts it out of the nest, and the firmware reports SUCCESS because its grip check
# compares WIDTH and the plate and lid share an identical footprint. The fault then
# surfaces one leg later as 'Plate not found' on the return. If a grip ever catches the
# plate again, keep raising in 1-2 mm steps.
LID_OFF_PICKUP_DX = 2.0
LID_OFF_PICKUP_DY = 36.5
LID_OFF_PICKUP_DZ = 7.0
LID_OFF_DROP_DX = 0.0
LID_OFF_DROP_DY = 0.0
LID_OFF_DROP_DZ = 4.0


# ---------------------------------------------------------------------------
# Release invariants
# ---------------------------------------------------------------------------
CONFIRMED_MOVEMENT_GEOMETRY = (
    # ODTC forward, ODTC return.
    (5.0, 2.0, 36.5, 12.0),
    (2.0, 36.5, 0.0, 8.5),
    # Magnet forward, magnet return.
    (8.5, 0.0, 0.0, 18.0),
    (14.0, 0.0, 0.0, 8.5),
    # Lid on, lid off.
    (0.0, 0.0, 9.0, 2.0, 36.5, 12.0),
    (2.0, 36.5, 7.0, 0.0, 0.0, 4.0),
)

# The physically proven component movers represented the real CellTreat work plate
# with a Corning motion stand-in. PLR 0.2.1 centers and anchors those models
# differently, so using the truthful CellTreat model without compensation shifts the
# firmware commands by x 0.1 mm, y 0.1 mm, and z 0.9 mm and changes grip width by
# 0.2 mm. The lid-off z window is only about 2 mm. These motion-only values make the
# shared CellTreat resource emit the exact hardware-proven Corning commands while its
# wells keep the truthful CellTreat pipetting geometry.
COR_MOTION_OFFSET = Coordinate(0.075, 0.120, 0.920)
COR_MOTION_PLATE_WIDTH = 127.76
COR_MOTION_OPEN_GRIP = 130.76
CELLTREAT_LID_Z_COMPENSATION = 0.920

CONFIRMED_MOTION_MODEL = (
    127.61, 85.24, 14.30, -4.05,  # CellTreat size xyz and carrier-local z.
    127.76, 85.48, 14.20, -3.03,  # Corning size xyz and carrier-local z.
    0.075, 0.120, 0.920, 0.920,   # center x/y, plate-top z, and lid-seat z deltas.
)


def movement_geometry():
    return (
        (ODTC_FWD_PICKUP_DZ, ODTC_FWD_DROP_DX, ODTC_FWD_DROP_DY, ODTC_FWD_DROP_DZ),
        (ODTC_RET_PICKUP_DX, ODTC_RET_PICKUP_DY, ODTC_RET_PICKUP_DZ, ODTC_RET_DROP_DZ),
        (MAG_FWD_PICKUP_DZ, MAG_FWD_DROP_DX, MAG_FWD_DROP_DY, MAG_FWD_DROP_DZ),
        (MAG_RET_PICKUP_DZ, MAG_RET_DROP_DX, MAG_RET_DROP_DY, MAG_RET_DROP_DZ),
        (
            LID_ON_PICKUP_DX,
            LID_ON_PICKUP_DY,
            LID_ON_PICKUP_DZ,
            LID_ON_DROP_DX,
            LID_ON_DROP_DY,
            LID_ON_DROP_DZ,
        ),
        (
            LID_OFF_PICKUP_DX,
            LID_OFF_PICKUP_DY,
            LID_OFF_PICKUP_DZ,
            LID_OFF_DROP_DX,
            LID_OFF_DROP_DY,
            LID_OFF_DROP_DZ,
        ),
    )


def validate_geometry_lock():
    actual = movement_geometry()
    if actual != CONFIRMED_MOVEMENT_GEOMETRY:
        raise RuntimeError(
            "PCR enrichment movement geometry lock failed; refusing to build or run the deck: "
            "{} != {}".format(actual, CONFIRMED_MOVEMENT_GEOMETRY)
        )


def motion_model_snapshot():
    cell_carrier = PLT_CAR_L5AC_A00(name="motion_lock_cell_carrier")
    cor_carrier = PLT_CAR_L5AC_A00(name="motion_lock_cor_carrier")
    cell = CellTreat_96_wellplate_350ul_Fb(name="motion_lock_cell")
    cor = Cor_96_wellplate_360ul_Fb(name="motion_lock_cor", with_lid=True)
    cell_carrier[0] = cell
    cor_carrier[0] = cor
    lid = cor.lid
    if lid is None:
        raise RuntimeError("Motion-model lock could not create the Corning lid")

    center_dx = cor.center().x - cell.center().x
    center_dy = cor.center().y - cell.center().y
    plate_top_dz = (
        cor.location.z + cor.get_size_z() - cell.location.z - cell.get_size_z()
    )
    lid_seat_dz = (
        cor.location.z
        + cor.get_lid_location(lid).z
        - cell.location.z
        - cell.get_lid_location(lid).z
    )
    return tuple(
        round(value, 3)
        for value in (
            cell.get_size_x(),
            cell.get_size_y(),
            cell.get_size_z(),
            cell.location.z,
            cor.get_size_x(),
            cor.get_size_y(),
            cor.get_size_z(),
            cor.location.z,
            center_dx,
            center_dy,
            plate_top_dz,
            lid_seat_dz,
        )
    )


def validate_motion_model_lock():
    actual = motion_model_snapshot()
    if actual != CONFIRMED_MOTION_MODEL:
        raise RuntimeError(
            "PCR enrichment CellTreat/Corning motion-model lock failed: {} != {}".format(
                actual, CONFIRMED_MOTION_MODEL
            )
        )
    compensation = (
        round(COR_MOTION_OFFSET.x, 3),
        round(COR_MOTION_OFFSET.y, 3),
        round(COR_MOTION_OFFSET.z, 3),
        round(CELLTREAT_LID_Z_COMPENSATION, 3),
    )
    if compensation != CONFIRMED_MOTION_MODEL[-4:]:
        raise RuntimeError(
            "PCR enrichment motion compensation drifted: {} != {}".format(
                compensation, CONFIRMED_MOTION_MODEL[-4:]
            )
        )
    if (
        round(COR_MOTION_PLATE_WIDTH, 2),
        round(COR_MOTION_OPEN_GRIP, 2),
    ) != (127.76, 130.76):
        raise RuntimeError("PCR enrichment Corning grip-width lock failed")


def validate_plr_version():
    try:
        installed = version("pylabrobot")
    except PackageNotFoundError as exc:
        raise RuntimeError("PyLabRobot is not installed; refusing to build an PCR enrichment run") from exc
    if installed != EXPECTED_PLR_VERSION:
        raise RuntimeError(
            "PyLabRobot version lock failed: this runner is tested against {}, found {}".format(
                EXPECTED_PLR_VERSION, installed
            )
        )


# ---------------------------------------------------------------------------
# Resource helpers (from the leg specs)
# ---------------------------------------------------------------------------
def make_resource(label, name, candidates):
    """Return the first available PyLabRobot factory from candidates, called as
    factory(name=name); raise a clear error if none is present in this install."""
    for factory_name in candidates:
        factory = getattr(plr_resources, factory_name, None)
        if factory is not None:
            return factory(name=name)
    nearby = sorted(
        n for n in dir(plr_resources)
        if any(term in n.lower() for term in ("tiprack", "tip_rack"))
    )
    raise RuntimeError(
        "No factory found for {}; tried {}. Nearby tip names: {}".format(
            label, candidates, nearby[:20]
        )
    )


def make_p10_tips(name):
    return make_resource("p10 filter tips", name, P10_TIP_FACTORY_CANDIDATES)


def make_p50_tips(name):
    return make_resource("p50 filter tips", name, P50_TIP_FACTORY_CANDIDATES)


def make_p300_tips(name):
    return make_resource("p300 filter tips", name, P300_TIP_FACTORY_CANDIDATES)


def wells_for_column(plate, col):
    """8-well vertical column selector: A<col>:H<col>."""
    return plate["A{c}:H{c}".format(c=col)]


def shifted(coord, dx=0.0, dy=0.0, dz=0.0):
    """Pure coordinate offset helper (no clamping), as used by every iSWAP leg."""
    return Coordinate(coord.x + dx, coord.y + dy, coord.z + dz)


# ---------------------------------------------------------------------------
# Unified deck assignment (ONCE)
# ---------------------------------------------------------------------------
def assign_unified_deck(lh: LiquidHandler) -> Dict[str, object]:
    """Assign the union of every leg's deck into ONE STARDeck. Each carrier gets a
    single unambiguous name so nothing collides.

    rail48  TIP_CAR_480_A00
        pos0  p10 tips  (deck parity, unused)
        pos1  p50 tips  (PCR1 col1, PCR2 col2, cleanup beads/residual/elution)
        pos2  p300 tips (cleanup EtOH add + supernatant/EtOH removal)
    rail35  PLT_CAR_L5AC_A00
        pos0  work plate (CellTreat 96wp) - the single plate the iSWAP threads around
        pos1  source master-mix plate (CellTreat 96wp)
        pos2  magnet block (EMPTY at start; work plate arrives by iSWAP for the clean)
        pos3  reservoir / waste (CellTreat 12-well trough)
    rail20  PLT_CAR_L5AC_A00
        pos1  ODTC nest (EMPTY; receives the plate for thermocycling)
    """
    validate_geometry_lock()
    validate_plr_version()
    validate_motion_model_lock()

    tip_carrier = TIP_CAR_480_A00(name="tip_car_rail48")
    lh.deck.assign_child_resource(tip_carrier, rails=TIP_RAIL)

    labware_carrier = PLT_CAR_L5AC_A00(name="labware_car_rail35")
    lh.deck.assign_child_resource(labware_carrier, rails=LABWARE_RAIL)

    odtc_carrier = PLT_CAR_L5AC_A00(name="odtc_carrier_rail20")
    lh.deck.assign_child_resource(odtc_carrier, rails=ODTC_RAIL)

    p10_tips = make_p10_tips("r48_pos0_p10_filter_tips")
    tip_carrier[P10_TIP_POS] = p10_tips
    p50_tips = make_p50_tips("r48_pos1_p50_filter_tips")
    tip_carrier[P50_TIP_POS] = p50_tips
    p300_tips = make_p300_tips("r48_pos2_p300_filter_tips")
    tip_carrier[P300_TIP_POS] = p300_tips

    work_plate = CellTreat_96_wellplate_350ul_Fb(name="rail35_pos0_pcr_enrichment_work_96wp")
    labware_carrier[WORK_POS] = work_plate
    source_96wp = CellTreat_96_wellplate_350ul_Fb(name="rail35_pos1_pcr_enrichment_mm_source_96wp")
    labware_carrier[SOURCE_96WP_POS] = source_96wp
    trough = CellTreat_12_troughplate_15000ul_Vb(name="rail35_pos3_pcr_enrichment_cleanup_12w_reservoir")
    labware_carrier[TROUGH_POS] = trough

    # rail35 pos4: the LID park. Modeled as a Cor plate carrying the lid, exactly as the
    # confirmed lid mover models it. It must be Cor and not CellTreat: CellTreat cannot
    # model a lid at all in PLR 0.2.1 (with_lid=True raises TypeError). The lid then moves
    # cross-model onto the CellTreat work plate; verified on chatterbox.
    lid_park = Cor_96_wellplate_360ul_Fb(name="rail35_pos4_pcr_enrichment_lid_park", with_lid=True)
    labware_carrier[LID_POS] = lid_park
    lid = lid_park.lid
    if lid is None:
        raise RuntimeError("Expected the Corning park plate to carry a lid")

    # rail35 pos2 (magnet) and rail20 pos1 (ODTC nest) are intentionally left EMPTY:
    # the single work plate is delivered to each by the iSWAP mid-choreography.

    return {
        "tip_carrier": tip_carrier,
        "labware_carrier": labware_carrier,
        "odtc_carrier": odtc_carrier,
        "p10_tips": p10_tips,
        "p50_tips": p50_tips,
        "p300_tips": p300_tips,
        "work_plate": work_plate,
        "source_96wp": source_96wp,
        "trough": trough,
        "lid_park": lid_park,
        "lid": lid,
        "work_site": labware_carrier[WORK_POS],
        "source_site": labware_carrier[SOURCE_96WP_POS],
        "mag_site": labware_carrier[MAG_POS],
        "trough_site": labware_carrier[TROUGH_POS],
        "lid_site": labware_carrier[LID_POS],
        "odtc_site": odtc_carrier[ODTC_POSITION],
    }


def coordinate_tuple(coord):
    return (coord.x, coord.y, coord.z)


def site_snapshot(r):
    return {
        name: coordinate_tuple(r[name].location)
        for name in (
            "work_site",
            "source_site",
            "mag_site",
            "trough_site",
            "lid_site",
            "odtc_site",
        )
    }


def assert_sites_pristine(r, expected, label):
    actual = site_snapshot(r)
    if actual != expected:
        raise RuntimeError(
            "Persistent site-coordinate bleed after {}: {} != {}".format(label, actual, expected)
        )


def assert_modeled_state(r, *, plate_site, lid_parent, label):
    checks = (
        (r["work_plate"].parent, plate_site, "work plate"),
        (r["lid"].parent, lid_parent, "lid"),
        (r["source_96wp"].parent, r["source_site"], "source plate"),
        (r["trough"].parent, r["trough_site"], "trough"),
        (r["lid_park"].parent, r["lid_site"], "lid park plate"),
        (r["p10_tips"].parent, r["tip_carrier"][P10_TIP_POS], "p10 tips"),
        (r["p50_tips"].parent, r["tip_carrier"][P50_TIP_POS], "p50 tips"),
        (r["p300_tips"].parent, r["tip_carrier"][P300_TIP_POS], "p300 tips"),
    )
    for actual, expected, resource_name in checks:
        if actual is not expected:
            raise RuntimeError(
                "Modeled deck state mismatch {}: {} is not at its expected parent".format(
                    label, resource_name
                )
            )


# ---------------------------------------------------------------------------
# Tip disposition (dry = return)
# ---------------------------------------------------------------------------
async def finish_tips(lh, discard_tips):
    if discard_tips:
        await lh.discard_tips()
    else:
        await lh.return_tips()


async def finish_tips_after_success(lh, discard_tips, operation_succeeded, label):
    if not operation_succeeded:
        print(
            "SAFETY HOLD: {} did not complete; automatic tip return/discard skipped. "
            "Tip and channel state are UNKNOWN.".format(label)
        )
        return
    await finish_tips(lh, discard_tips)


# ---------------------------------------------------------------------------
# Leg bodies: PCR1 / PCR2 master mix (single 8-channel col1 -> col1 transfer)
# ---------------------------------------------------------------------------
async def transfer_mastermix(lh, r, volume_ul, discard_tips=False, tip_col=1):
    vols = [volume_ul] * 8
    await lh.pick_up_tips(r["p50_tips"]["A{c}:H{c}".format(c=tip_col)])
    operation_succeeded = False
    try:
        await lh.aspirate(
            wells_for_column(r["source_96wp"], SOURCE_COL),
            vols=vols,
            liquid_height=P50_SOURCE_ASP_HEIGHT,
            offsets=P50_SOURCE_ASP_OFFSETS,
            blow_out_air_volume=[0.0] * 8,
        )
        # Dispense AND mix in place: the firmware Mix cycles the plunger with the tip still
        # IN the well (no head retraction per cycle), then a heavy blowout so no sample is
        # left in the tip. mix Z = 1.5 - 1.0 = 0.5 mm above the well bottom; see the PATCH
        # note above, the sign is proven on hardware, not assumed.
        print(f"Dispensing {vols[0]} uL x8 to dest col {DEST_COL}; in-well mix "
              f"{MIX_CYCLES}x {MIX_VOLUME_UL} uL @ {MIX_FLOW_RATE} uL/s at mix Z "
              f"{P50_WORK_DSP_HEIGHT[0] - MIX_POSITION_FROM_SURFACE[0]} mm above the well bottom; "
              f"blowout {P50_MIX_BLOWOUT_AIR_VOLUME} uL...")
        await lh.dispense(
            wells_for_column(r["work_plate"], DEST_COL),
            vols=vols,
            liquid_height=P50_WORK_DSP_HEIGHT,
            offsets=P50_WORK_DSP_OFFSETS,
            blow_out_air_volume=[P50_MIX_BLOWOUT_AIR_VOLUME] * 8,
            mix=[Mix(volume=MIX_VOLUME_UL, repetitions=MIX_CYCLES, flow_rate=MIX_FLOW_RATE)] * 8,
            mix_position_from_liquid_surface=MIX_POSITION_FROM_SURFACE,
        )
        await asyncio.sleep(POST_DISPENSE_SETTLE_SECONDS)
        operation_succeeded = True
    finally:
        await finish_tips_after_success(
            lh, discard_tips, operation_succeeded, "master-mix transfer"
        )


# ---------------------------------------------------------------------------
# Leg body: PCR1 cleanup all-dry on the magnet (8-step bead clean)
# ---------------------------------------------------------------------------
async def p50_add_from_trough_low(lh, r, source_well_name, volume_ul, discard_tips, tip_col):
    vols = [volume_ul] * 8
    await lh.pick_up_tips(r["p50_tips"]["A{c}:H{c}".format(c=tip_col)])
    operation_succeeded = False
    try:
        await lh.aspirate(
            [r["trough"][source_well_name][0]] * 8,
            vols=vols,
            liquid_height=P50_LOW_TROUGH_ASP_HEIGHT,
            offsets=P50_LOW_TROUGH_ASP_OFFSETS,
            blow_out_air_volume=[0.0] * 8,
        )
        await lh.dispense(
            wells_for_column(r["mag_plate"], DEST_COL),
            vols=vols,
            liquid_height=P50_LOW_MAG_DSP_HEIGHT,
            offsets=P50_LOW_MAG_DSP_OFFSETS,
            blow_out_air_volume=[P50_LOW_ADD_BLOWOUT_AIR_VOLUME] * 8,
        )
        operation_succeeded = True
    finally:
        await finish_tips_after_success(
            lh, discard_tips, operation_succeeded, "p50 trough add"
        )


async def p300_add_from_trough(lh, r, source_well_name, volume_ul, discard_tips, tip_col):
    vols = [volume_ul] * 8
    await lh.pick_up_tips(r["p300_tips"]["A{c}:H{c}".format(c=tip_col)])
    operation_succeeded = False
    try:
        await lh.aspirate(
            [r["trough"][source_well_name][0]] * 8,
            vols=vols,
            liquid_height=P300_TROUGH_ASP_HEIGHT,
            offsets=P300_TROUGH_ASP_OFFSETS,
            blow_out_air_volume=[0.0] * 8,
        )
        await lh.dispense(
            wells_for_column(r["mag_plate"], DEST_COL),
            vols=vols,
            liquid_height=P300_MAG_DSP_HEIGHT,
            offsets=P300_MAG_DSP_OFFSETS,
            blow_out_air_volume=[P300_ADD_BLOWOUT_AIR_VOLUME] * 8,
        )
        operation_succeeded = True
    finally:
        await finish_tips_after_success(
            lh, discard_tips, operation_succeeded, "p300 trough add"
        )


async def p300_remove_to_waste(lh, r, volume_ul, discard_tips, tip_col):
    vols = [volume_ul] * 8
    await lh.pick_up_tips(r["p300_tips"]["A{c}:H{c}".format(c=tip_col)])
    operation_succeeded = False
    try:
        await lh.aspirate(
            wells_for_column(r["mag_plate"], DEST_COL),
            vols=vols,
            liquid_height=P300_MAG_REMOVE_ASP_HEIGHT,
            offsets=P300_MAG_REMOVE_ASP_OFFSETS,
            blow_out_air_volume=[0.0] * 8,
        )
        await lh.dispense(
            [r["trough"][TROUGH_WASTE][0]] * 8,
            vols=vols,
            liquid_height=P300_WASTE_DSP_HEIGHT,
            offsets=P300_WASTE_DSP_OFFSETS,
            blow_out_air_volume=[P300_REMOVE_BLOWOUT_AIR_VOLUME] * 8,
        )
        operation_succeeded = True
    finally:
        await finish_tips_after_success(
            lh, discard_tips, operation_succeeded, "p300 waste removal"
        )


async def p50_remove_residual_ethanol_to_waste(lh, r, volume_ul, discard_tips, tip_col):
    vols = [volume_ul] * 8
    await lh.pick_up_tips(r["p50_tips"]["A{c}:H{c}".format(c=tip_col)])
    operation_succeeded = False
    try:
        await lh.aspirate(
            wells_for_column(r["mag_plate"], DEST_COL),
            vols=vols,
            liquid_height=P50_MAG_RESIDUAL_ASP_HEIGHT,
            offsets=P50_MAG_RESIDUAL_ASP_OFFSETS,
            blow_out_air_volume=[0.0] * 8,
        )
        await lh.dispense(
            [r["trough"][TROUGH_WASTE][0]] * 8,
            vols=vols,
            liquid_height=P50_WASTE_DSP_HEIGHT,
            offsets=P50_WASTE_DSP_OFFSETS,
            blow_out_air_volume=[P50_RESIDUAL_BLOWOUT_AIR_VOLUME] * 8,
        )
        operation_succeeded = True
    finally:
        await finish_tips_after_success(
            lh, discard_tips, operation_succeeded, "p50 residual removal"
        )


async def cleanup_all_dry(lh, r, discard_tips=False):
    """Operator-profile dry cleanup on the magnet.
    In dry mode (discard_tips=False) tips are RETURNED and tip_col stays at 1;
    the increment path is preserved for the production/discard case."""
    col = 1
    await p50_add_from_trough_low(lh, r, TROUGH_BEADS, VOL_BEADS, discard_tips, col)
    if discard_tips:
        col += 1
    await p300_remove_to_waste(lh, r, VOL_SUPERNATANT_REMOVE, discard_tips, col)
    if discard_tips:
        col += 1
    await p300_add_from_trough(lh, r, TROUGH_ETOH1, VOL_ETHANOL_ADD, discard_tips, col)
    if discard_tips:
        col += 1
    await p300_remove_to_waste(lh, r, VOL_ETHANOL_REMOVE, discard_tips, col)
    if discard_tips:
        col += 1
    if WASH_COUNT == 2:
        await p300_add_from_trough(lh, r, TROUGH_ETOH2, VOL_ETHANOL_ADD, discard_tips, col)
        if discard_tips:
            col += 1
        await p300_remove_to_waste(lh, r, VOL_ETHANOL_REMOVE, discard_tips, col)
        if discard_tips:
            col += 1
    await p50_remove_residual_ethanol_to_waste(lh, r, VOL_RESIDUAL_ETHANOL_REMOVE, discard_tips, col)
    if discard_tips:
        col += 1
    await p50_add_from_trough_low(lh, r, TROUGH_ELUTION, VOL_ELUTION, discard_tips, col)


# ---------------------------------------------------------------------------
# Leg body: one slow-iSWAP plate move
# ---------------------------------------------------------------------------
async def iswap_leg(
    lh,
    plate,
    drop_site,
    pickup_dx=0.0,
    pickup_dy=0.0,
    pickup_dz=0.0,
    drop_dx=0.0,
    drop_dy=0.0,
    drop_dz=0.0,
    pickup_target="plate",
):
    """Move `plate` onto `drop_site` at reduced iSWAP speed, applying the tuned
    teach-point offsets immediately before the move and restoring any permanent
    deck-slot mutation immediately after, so each leg sees pristine teach points
    (no cross-leg coordinate bleed on the shared deck).

    pickup_target:
        "plate" -> pickup offset raises the plate within its current slot (forward movers)
        "slot"  -> pickup offset shifts the source SLOT itself (ODTC-return frame fix)

    move_resource re-parents the plate to drop_site, so the pickup-plate shift and
    the plate's per-leg location are reset by PyLabRobot on the next leg; only the
    persistent carrier-site shifts are restored here.
    """
    if pickup_target not in ("plate", "slot"):
        raise ValueError("Unknown plate pickup target: {}".format(pickup_target))

    original_parent = plate.parent
    pickup_slot = original_parent
    plate_base = plate.location
    pickup_slot_base = pickup_slot.location if pickup_slot is not None else None
    drop_base = drop_site.location
    try:
        if pickup_target == "slot" and pickup_slot is not None:
            pickup_slot.location = shifted(pickup_slot_base, dx=pickup_dx, dy=pickup_dy, dz=pickup_dz)
        else:
            plate.location = shifted(plate_base, dx=pickup_dx, dy=pickup_dy, dz=pickup_dz)
        drop_site.location = shifted(drop_base, dx=drop_dx, dy=drop_dy, dz=drop_dz)
        async with lh.backend.slow_iswap():
            await lh.move_resource(
                plate,
                drop_site,
                pickup_offset=COR_MOTION_OFFSET,
                destination_offset=COR_MOTION_OFFSET,
                plate_width=COR_MOTION_PLATE_WIDTH,
                open_gripper_position=COR_MOTION_OPEN_GRIP,
            )
    finally:
        if pickup_target == "slot" and pickup_slot is not None and pickup_slot_base is not None:
            pickup_slot.location = pickup_slot_base
        if pickup_target == "plate" and plate.parent is original_parent:
            plate.location = plate_base
        drop_site.location = drop_base


# ---------------------------------------------------------------------------
# Leg body: one lid move (move_lid), same restore-pristine discipline as iswap_leg
# ---------------------------------------------------------------------------
async def lid_leg(
    lh,
    lid,
    dst_plate,
    src_site,
    dst_site,
    pickup_dx=0.0,
    pickup_dy=0.0,
    pickup_dz=0.0,
    drop_dx=0.0,
    drop_dy=0.0,
    drop_dz=0.0,
    pickup_model_dz=0.0,
    drop_model_dz=0.0,
):
    """Move `lid` onto `dst_plate`, applying the tuned teach-point offsets to the SOURCE
    and DEST SITES immediately before the move and restoring them immediately after.

    Shifting the sites (not the lid) is what the confirmed standalone lid mover does: it
    offsets src_site.location / dst_site.location before assigning the plates, and the
    lid's absolute pickup point follows its parent chain. Doing it here per-leg and
    restoring in `finally` keeps the shared single-session deck pristine, so no leg
    inherits another leg's teach-point mutation.

    move_lid re-parents the lid to dst_plate, so after LID ON the lid lives on the work
    plate and LID OFF picks it up from there.
    """
    src_base = src_site.location
    dst_base = dst_site.location
    try:
        src_site.location = shifted(src_base, dx=pickup_dx, dy=pickup_dy, dz=pickup_dz)
        dst_site.location = shifted(dst_base, dx=drop_dx, dy=drop_dy, dz=drop_dz)
        async with lh.backend.slow_iswap():
            await lh.move_lid(
                lid,
                dst_plate,
                pickup_offset=Coordinate(0.0, 0.0, pickup_model_dz),
                destination_offset=Coordinate(0.0, 0.0, drop_model_dz),
            )
    finally:
        src_site.location = src_base
        dst_site.location = dst_base


# ---------------------------------------------------------------------------
# The 13-leg choreography against the shared handler + unified deck
# ---------------------------------------------------------------------------
def _banner(label):
    print("")
    print("=" * 88)
    print(label)
    print("=" * 88)


async def run_choreography(lh, r):
    _work_site = r["work_site"]
    _mag_site = r["mag_site"]
    _lid_site = r["lid_site"]
    _nest_site = r["odtc_site"]
    pristine_sites = site_snapshot(r)

    assert_sites_pristine(r, pristine_sites, "initial deck")
    assert_modeled_state(
        r, plate_site=_work_site, lid_parent=r["lid_park"], label="initial deck"
    )

    # LEG 1: PCR1 master mix add (p50 col1) -> rail35 pos0 work plate
    _banner("LEG 1/13  PCR1 master mix add (p50 tip col1) -> rail35 pos0 work plate")
    await transfer_mastermix(
        lh,
        {"p50_tips": r["p50_tips"], "source_96wp": r["source_96wp"], "work_plate": r["work_plate"]},
        volume_ul=VOL_PCR1_MASTER_MIX,
        discard_tips=False,
        tip_col=1,
    )
    assert_modeled_state(
        r, plate_site=_work_site, lid_parent=r["lid_park"], label="PCR1 transfer"
    )

    # LEG 2: iSWAP rail35 pos0 -> rail20 pos1 ODTC nest (PCR1 handoff)
    _banner("LEG 2/13  iSWAP rail35 pos0 -> rail20 pos1 ODTC nest (PCR1 handoff)")
    await iswap_leg(
        lh, r["work_plate"], r["odtc_carrier"][ODTC_POSITION],
        pickup_dz=ODTC_FWD_PICKUP_DZ,
        drop_dx=ODTC_FWD_DROP_DX, drop_dy=ODTC_FWD_DROP_DY, drop_dz=ODTC_FWD_DROP_DZ,
        pickup_target="plate",
    )
    assert_sites_pristine(r, pristine_sites, "PCR1 ODTC forward")
    assert_modeled_state(
        r, plate_site=_nest_site, lid_parent=r["lid_park"], label="PCR1 ODTC forward"
    )

    # LEG 2b: LID ON rail35 pos4 -> the plate now in the ODTC nest (seal for PCR1)
    _banner("LEG 2b/13  LID ON  rail35 pos4 -> plate in ODTC nest (seal for PCR1)")
    await lid_leg(
        lh, r["lid"], r["work_plate"],
        src_site=_lid_site, dst_site=_nest_site,
        pickup_dx=LID_ON_PICKUP_DX, pickup_dy=LID_ON_PICKUP_DY, pickup_dz=LID_ON_PICKUP_DZ,
        drop_dx=LID_ON_DROP_DX, drop_dy=LID_ON_DROP_DY, drop_dz=LID_ON_DROP_DZ,
        drop_model_dz=CELLTREAT_LID_Z_COMPENSATION,
    )
    assert_sites_pristine(r, pristine_sites, "PCR1 lid on")
    assert_modeled_state(
        r, plate_site=_nest_site, lid_parent=r["work_plate"], label="PCR1 lid on"
    )

    # In a REAL run the ODTC PCR1 thermal program executes HERE, lid sealed.
    _banner("LEG 2t/13  (REAL RUN: ODTC PCR1 thermal program would execute here, lid sealed)")

    # LEG 2c: LID OFF ODTC nest -> rail35 pos4 (unseal before lifting the plate out)
    _banner("LEG 2c/13  LID OFF ODTC nest -> rail35 pos4 (unseal; pickup z7 grabs lid not plate)")
    await lid_leg(
        lh, r["lid"], r["lid_park"],
        src_site=_nest_site, dst_site=_lid_site,
        pickup_dx=LID_OFF_PICKUP_DX, pickup_dy=LID_OFF_PICKUP_DY, pickup_dz=LID_OFF_PICKUP_DZ,
        drop_dx=LID_OFF_DROP_DX, drop_dy=LID_OFF_DROP_DY, drop_dz=LID_OFF_DROP_DZ,
        pickup_model_dz=CELLTREAT_LID_Z_COMPENSATION,
    )
    assert_sites_pristine(r, pristine_sites, "PCR1 lid off")
    assert_modeled_state(
        r, plate_site=_nest_site, lid_parent=r["lid_park"], label="PCR1 lid off"
    )

    # LEG 3: iSWAP rail20 pos1 ODTC nest -> rail35 pos0 (return, pickup z0 / drop z8.5)
    _banner("LEG 3/13  iSWAP rail20 pos1 ODTC nest -> rail35 pos0 (return, pickup z0 / drop z8.5)")
    await iswap_leg(
        lh, r["work_plate"], r["labware_carrier"][WORK_POS],
        pickup_dx=ODTC_RET_PICKUP_DX, pickup_dy=ODTC_RET_PICKUP_DY, pickup_dz=ODTC_RET_PICKUP_DZ,
        drop_dz=ODTC_RET_DROP_DZ,
        pickup_target="slot",
    )
    assert_sites_pristine(r, pristine_sites, "PCR1 ODTC return")
    assert_modeled_state(
        r, plate_site=_work_site, lid_parent=r["lid_park"], label="PCR1 ODTC return"
    )

    # LEG 4: iSWAP rail35 pos0 -> rail35 pos2 magnet (bead-clean handoff)
    _banner("LEG 4/13  iSWAP rail35 pos0 -> rail35 pos2 magnet (bead-clean handoff)")
    await iswap_leg(
        lh, r["work_plate"], r["labware_carrier"][MAG_POS],
        pickup_dz=MAG_FWD_PICKUP_DZ,
        drop_dx=MAG_FWD_DROP_DX, drop_dy=MAG_FWD_DROP_DY, drop_dz=MAG_FWD_DROP_DZ,
        pickup_target="plate",
    )
    assert_sites_pristine(r, pristine_sites, "magnet forward")
    assert_modeled_state(
        r, plate_site=_mag_site, lid_parent=r["lid_park"], label="magnet forward"
    )

    # LEG 5: PCR1 cleanup all-dry on magnet using the operator-profile sequence.
    _banner("LEG 5/13  PCR1 cleanup all-dry on magnet (operator-profile sequence)")
    await cleanup_all_dry(
        lh,
        {"p50_tips": r["p50_tips"], "p300_tips": r["p300_tips"],
         "mag_plate": r["work_plate"], "trough": r["trough"]},
        discard_tips=False,
    )
    assert_modeled_state(
        r, plate_site=_mag_site, lid_parent=r["lid_park"], label="cleanup"
    )

    # LEG 6: iSWAP rail35 pos2 magnet -> rail35 pos0 (return, pickup z14 / drop z8.5)
    _banner("LEG 6/13  iSWAP rail35 pos2 magnet -> rail35 pos0 (return, pickup z14 / drop z8.5)")
    await iswap_leg(
        lh, r["work_plate"], r["labware_carrier"][WORK_POS],
        pickup_dz=MAG_RET_PICKUP_DZ,
        drop_dx=MAG_RET_DROP_DX, drop_dy=MAG_RET_DROP_DY, drop_dz=MAG_RET_DROP_DZ,
        pickup_target="plate",
    )
    assert_sites_pristine(r, pristine_sites, "magnet return")
    assert_modeled_state(
        r, plate_site=_work_site, lid_parent=r["lid_park"], label="magnet return"
    )

    # LEG 7: PCR2 master mix add (p50 col2) -> rail35 pos0 work plate
    _banner("LEG 7/13  PCR2 master mix add (p50 tip col2) -> rail35 pos0 work plate")
    await transfer_mastermix(
        lh,
        {"p50_tips": r["p50_tips"], "source_96wp": r["source_96wp"], "work_plate": r["work_plate"]},
        volume_ul=VOL_PCR2_MASTER_MIX,
        discard_tips=False,
        tip_col=2,
    )
    assert_modeled_state(
        r, plate_site=_work_site, lid_parent=r["lid_park"], label="PCR2 transfer"
    )

    # LEG 8: iSWAP rail35 pos0 -> rail20 pos1 ODTC nest (PCR2 handoff; byte-identical to LEG 2)
    _banner("LEG 8/13  iSWAP rail35 pos0 -> rail20 pos1 ODTC nest (PCR2 handoff)")
    await iswap_leg(
        lh, r["work_plate"], r["odtc_carrier"][ODTC_POSITION],
        pickup_dz=ODTC_FWD_PICKUP_DZ,
        drop_dx=ODTC_FWD_DROP_DX, drop_dy=ODTC_FWD_DROP_DY, drop_dz=ODTC_FWD_DROP_DZ,
        pickup_target="plate",
    )
    assert_sites_pristine(r, pristine_sites, "PCR2 ODTC forward")
    assert_modeled_state(
        r, plate_site=_nest_site, lid_parent=r["lid_park"], label="PCR2 ODTC forward"
    )

    # LEG 8b: LID ON rail35 pos4 -> plate in ODTC nest (byte-identical to LEG 2b)
    _banner("LEG 8b/13  LID ON  rail35 pos4 -> plate in ODTC nest (seal for PCR2)")
    await lid_leg(
        lh, r["lid"], r["work_plate"],
        src_site=_lid_site, dst_site=_nest_site,
        pickup_dx=LID_ON_PICKUP_DX, pickup_dy=LID_ON_PICKUP_DY, pickup_dz=LID_ON_PICKUP_DZ,
        drop_dx=LID_ON_DROP_DX, drop_dy=LID_ON_DROP_DY, drop_dz=LID_ON_DROP_DZ,
        drop_model_dz=CELLTREAT_LID_Z_COMPENSATION,
    )
    assert_sites_pristine(r, pristine_sites, "PCR2 lid on")
    assert_modeled_state(
        r, plate_site=_nest_site, lid_parent=r["work_plate"], label="PCR2 lid on"
    )

    # In a REAL run the ODTC PCR2 thermal program executes HERE, lid sealed.
    _banner("LEG 8t/13  (REAL RUN: ODTC PCR2 thermal program would execute here, lid sealed)")

    # LEG 8c: LID OFF ODTC nest -> rail35 pos4 (byte-identical to LEG 2c)
    _banner("LEG 8c/13  LID OFF ODTC nest -> rail35 pos4 (unseal; pickup z7 grabs lid not plate)")
    await lid_leg(
        lh, r["lid"], r["lid_park"],
        src_site=_nest_site, dst_site=_lid_site,
        pickup_dx=LID_OFF_PICKUP_DX, pickup_dy=LID_OFF_PICKUP_DY, pickup_dz=LID_OFF_PICKUP_DZ,
        drop_dx=LID_OFF_DROP_DX, drop_dy=LID_OFF_DROP_DY, drop_dz=LID_OFF_DROP_DZ,
        pickup_model_dz=CELLTREAT_LID_Z_COMPENSATION,
    )
    assert_sites_pristine(r, pristine_sites, "PCR2 lid off")
    assert_modeled_state(
        r, plate_site=_nest_site, lid_parent=r["lid_park"], label="PCR2 lid off"
    )

    # LEG 9: iSWAP rail20 pos1 ODTC nest -> rail35 pos0 (return; byte-identical to LEG 3)
    _banner("LEG 9/13  iSWAP rail20 pos1 ODTC nest -> rail35 pos0 (return, pickup z0 / drop z8.5)")
    await iswap_leg(
        lh, r["work_plate"], r["labware_carrier"][WORK_POS],
        pickup_dx=ODTC_RET_PICKUP_DX, pickup_dy=ODTC_RET_PICKUP_DY, pickup_dz=ODTC_RET_PICKUP_DZ,
        drop_dz=ODTC_RET_DROP_DZ,
        pickup_target="slot",
    )
    assert_sites_pristine(r, pristine_sites, "PCR2 ODTC return")
    assert_modeled_state(
        r, plate_site=_work_site, lid_parent=r["lid_park"], label="final deck"
    )


# ---------------------------------------------------------------------------
# --mode deck: print deck map + tuned geometry, NO motion
# ---------------------------------------------------------------------------
def print_deck_and_geometry(r):
    print("")
    print("=" * 88)
    print("UNIFIED DECK (assigned once; no motion in deck mode)")
    print("=" * 88)
    print("rail48  TIP_CAR_480_A00 'tip_car_rail48'")
    print("    pos0  p10 filter tips  '{}'  (deck parity, unused)".format(r["p10_tips"].name))
    print("    pos1  p50 filter tips  '{}'".format(r["p50_tips"].name))
    print("    pos2  p300 filter tips '{}'".format(r["p300_tips"].name))
    print("rail35  PLT_CAR_L5AC_A00 'labware_car_rail35'")
    print("    pos0  work plate       '{}'  (single plate threaded by the iSWAP)".format(r["work_plate"].name))
    print("    pos1  mm source plate  '{}'".format(r["source_96wp"].name))
    print("    pos2  magnet block     (EMPTY; work plate arrives by iSWAP)")
    print("    pos3  reservoir/waste  '{}'".format(r["trough"].name))
    print("    pos4  LID park         '{}'  (Cor plate carrying the lid; rides to the nest and back)".format(
        r["lid_park"].name))
    print("          lid              '{}'".format(r["lid"].name))
    print("rail20  PLT_CAR_L5AC_A00 'odtc_carrier_rail20'")
    print("    pos1  ODTC nest        (EMPTY; receives the plate for thermocycling)")
    print("")
    print("PLATE MODELS (deliberate; see the PATCH LOG):")
    print("    work plate = CellTreat  -> keeps the tuned liquid geometry exact")
    print("    lid park   = Cor        -> CellTreat cannot model a lid (with_lid raises)")
    print("    the 1.25 mm well-bottom gap between the two models is why they are NOT unified")
    print("    motion-only CellTreat compensation = x{} y{} z{}; Cor grip width {}".format(
        COR_MOTION_OFFSET.x, COR_MOTION_OFFSET.y, COR_MOTION_OFFSET.z,
        COR_MOTION_PLATE_WIDTH))
    print("    this locks iSWAP/lid firmware commands to the hardware-proven Cor stand-in")
    print("")
    print("LID LEGS  on  pickup z{} / drop x{} y{} z{}   off  pickup x{} y{} z{} / drop z{}".format(
        LID_ON_PICKUP_DZ, LID_ON_DROP_DX, LID_ON_DROP_DY, LID_ON_DROP_DZ,
        LID_OFF_PICKUP_DX, LID_OFF_PICKUP_DY, LID_OFF_PICKUP_DZ, LID_OFF_DROP_DZ))

    print("")
    print("-" * 88)
    print("TUNED iSWAP HANDOFF GEOMETRY (mm offsets on plate / carrier-site .location)")
    print("-" * 88)
    print("LEG 2/8  ODTC fwd  rail35 pos0 -> rail20 pos1 : pickup(plate) dz +{}"
          " | drop(slot) dx +{} dy +{} dz +{}".format(
              ODTC_FWD_PICKUP_DZ, ODTC_FWD_DROP_DX, ODTC_FWD_DROP_DY, ODTC_FWD_DROP_DZ))
    print("LEG 3/13  ODTC ret  rail20 pos1 -> rail35 pos0 : pickup(slot) dx +{} dy +{} dz +{}"
          " | drop(slot) dz +{}".format(
              ODTC_RET_PICKUP_DX, ODTC_RET_PICKUP_DY, ODTC_RET_PICKUP_DZ, ODTC_RET_DROP_DZ))
    print("LEG 4    MAG fwd   rail35 pos0 -> rail35 pos2 : pickup(plate) dz +{}"
          " | drop(slot) dx +{} dy +{} dz +{}".format(
              MAG_FWD_PICKUP_DZ, MAG_FWD_DROP_DX, MAG_FWD_DROP_DY, MAG_FWD_DROP_DZ))
    print("LEG 6    MAG ret   rail35 pos2 -> rail35 pos0 : pickup(plate) dz +{}"
          " | drop(slot) dx +{} dy +{} dz +{}  (wrapper override 14.0 / 8.5)".format(
              MAG_RET_PICKUP_DZ, MAG_RET_DROP_DX, MAG_RET_DROP_DY, MAG_RET_DROP_DZ))

    print("")
    print("-" * 88)
    print("TUNED LIQUID-HANDLING GEOMETRY")
    print("-" * 88)
    print("PCR1 mm  {} uL  p50 col1  src A1:H1 (h {} off {}) -> work A1:H1 (h {} off {} blow {})".format(
        VOL_PCR1_MASTER_MIX, P50_SOURCE_ASP_HEIGHT[0], _c(P50_SOURCE_ASP_OFFSETS[0]),
        P50_WORK_DSP_HEIGHT[0], _c(P50_WORK_DSP_OFFSETS[0]), P50_MIX_BLOWOUT_AIR_VOLUME))
    print("PCR2 mm  {} uL  p50 col2  src A1:H1 (h {} off {}) -> work A1:H1 (h {} off {} blow {})".format(
        VOL_PCR2_MASTER_MIX, P50_SOURCE_ASP_HEIGHT[0], _c(P50_SOURCE_ASP_OFFSETS[0]),
        P50_WORK_DSP_HEIGHT[0], _c(P50_WORK_DSP_OFFSETS[0]), P50_MIX_BLOWOUT_AIR_VOLUME))
    print(
        "operator-profile reaction volumes: PCR1 {} uL; PCR2 input {} uL; PCR2 final {} uL".format(
            PCR1_REACTION_VOLUME_UL, PCR2_INPUT_VOLUME_UL, PCR2_REACTION_VOLUME_UL
        )
    )
    print("operator-profile cleanup wash count: {}".format(WASH_COUNT))
    print("cleanup beads    {} uL  p50-low  trough A1 (h {} off {}) -> mag (h {} off {} blow {})".format(
        VOL_BEADS, P50_LOW_TROUGH_ASP_HEIGHT[0], _c(P50_LOW_TROUGH_ASP_OFFSETS[0]),
        P50_LOW_MAG_DSP_HEIGHT[0], _c(P50_LOW_MAG_DSP_OFFSETS[0]), P50_LOW_ADD_BLOWOUT_AIR_VOLUME))
    print("cleanup sup rm   {} uL  p300     mag (h {} off {}) -> waste A12 (h {} off {} blow {})".format(
        VOL_SUPERNATANT_REMOVE, P300_MAG_REMOVE_ASP_HEIGHT[0], _c(P300_MAG_REMOVE_ASP_OFFSETS[0]),
        P300_WASTE_DSP_HEIGHT[0], _c(P300_WASTE_DSP_OFFSETS[0]), P300_REMOVE_BLOWOUT_AIR_VOLUME))
    print("cleanup EtOH add {} uL  p300     trough A2/A3 (h {} off {}) -> mag (h {} off {} blow {})".format(
        VOL_ETHANOL_ADD, P300_TROUGH_ASP_HEIGHT[0], _c(P300_TROUGH_ASP_OFFSETS[0]),
        P300_MAG_DSP_HEIGHT[0], _c(P300_MAG_DSP_OFFSETS[0]), P300_ADD_BLOWOUT_AIR_VOLUME))
    print("cleanup EtOH rm  {} uL  p300     mag (h {} off {}) -> waste A12 (h {} off {} blow {})".format(
        VOL_ETHANOL_REMOVE, P300_MAG_REMOVE_ASP_HEIGHT[0], _c(P300_MAG_REMOVE_ASP_OFFSETS[0]),
        P300_WASTE_DSP_HEIGHT[0], _c(P300_WASTE_DSP_OFFSETS[0]), P300_REMOVE_BLOWOUT_AIR_VOLUME))
    print("cleanup resid rm {} uL  p50      mag (h {} off {}) -> waste A12 (h {} off {} blow {})".format(
        VOL_RESIDUAL_ETHANOL_REMOVE, P50_MAG_RESIDUAL_ASP_HEIGHT[0], _c(P50_MAG_RESIDUAL_ASP_OFFSETS[0]),
        P50_WASTE_DSP_HEIGHT[0], _c(P50_WASTE_DSP_OFFSETS[0]), P50_RESIDUAL_BLOWOUT_AIR_VOLUME))
    print("cleanup elute    {} uL  p50-low  trough A4 (h {} off {}) -> mag (h {} off {} blow {})".format(
        VOL_ELUTION, P50_LOW_TROUGH_ASP_HEIGHT[0], _c(P50_LOW_TROUGH_ASP_OFFSETS[0]),
        P50_LOW_MAG_DSP_HEIGHT[0], _c(P50_LOW_MAG_DSP_OFFSETS[0]), P50_LOW_ADD_BLOWOUT_AIR_VOLUME))
    print("")
    print("Tips RETURNED (dry) throughout. No motion performed in deck mode.")
    print("No ODTC connection, initialization, door command, or heating is present in this runner.")


def _c(coord):
    return "({}, {}, {})".format(coord.x, coord.y, coord.z)


# ---------------------------------------------------------------------------
# Chatterbox backend loader (import path varies across PyLabRobot versions)
# ---------------------------------------------------------------------------
def load_star_chatterbox_backend():
    candidates = [
        ("pylabrobot.liquid_handling.backends", "STARChatterboxBackend"),
        ("pylabrobot.liquid_handling.backends.hamilton.STAR_chatterbox", "STARChatterboxBackend"),
        ("pylabrobot.liquid_handling.backends.hamilton.chatterbox", "STARChatterboxBackend"),
    ]
    for module_name, attr in candidates:
        try:
            mod = importlib.import_module(module_name)
        except ImportError:
            continue
        backend_cls = getattr(mod, attr, None)
        if backend_cls is not None:
            return backend_cls()
    raise RuntimeError(
        "STARChatterboxBackend not found in this PyLabRobot install; tried: "
        + ", ".join(m for m, _ in candidates)
    )


# ---------------------------------------------------------------------------
# Guarded lifecycle and entry point
# ---------------------------------------------------------------------------
def create_backend(name):
    if name == "chatterbox":
        return load_star_chatterbox_backend()
    if name == "star":
        from pylabrobot.liquid_handling.backends import STARBackend

        return STARBackend()
    raise ValueError("Unknown backend: {}".format(name))


def make_handler(backend_name):
    return LiquidHandler(backend=create_backend(backend_name), deck=STARDeck())


async def stop_handler(
    lh,
    *,
    park_iswap,
    suppress_errors,
    setup_complete,
):
    """Disconnect, but issue a park movement only after complete choreography success."""
    cleanup_error = None
    if park_iswap:
        try:
            await lh.backend.park_iswap()
        except Exception as exc:
            cleanup_error = exc
            print("park_iswap failure: {!r}".format(exc))
    else:
        print(
            "SAFETY HOLD: choreography did not complete; iSWAP auto-park skipped. "
            "Plate, lid, tip, and gripper state are UNKNOWN and must be reconciled."
        )
    try:
        if setup_complete:
            await lh.stop()
        else:
            await lh.backend.stop()
    except Exception as exc:
        print("backend stop failure: {!r}".format(exc))
        if cleanup_error is None:
            cleanup_error = exc
    if cleanup_error is not None and not suppress_errors:
        raise cleanup_error


async def run_full(backend_name):
    lh = make_handler(backend_name)
    setup_complete = False
    choreography_succeeded = False
    try:
        await lh.setup(skip_autoload=True)
        setup_complete = True
        r = assign_unified_deck(lh)
        print(
            "MOTION LOCK: CellTreat liquid model plus Cor-equivalent iSWAP offset "
            "x{} y{} z{}, grip width {}; exact component-command parity required.".format(
                COR_MOTION_OFFSET.x,
                COR_MOTION_OFFSET.y,
                COR_MOTION_OFFSET.z,
                COR_MOTION_PLATE_WIDTH,
            )
        )
        print("DRY ONLY: empty sacrificial labware, no samples/reagents, tips returned.")
        print("ODTC is not contacted, initialized, heated, cycled, or commanded.")
        await run_choreography(lh, r)
        choreography_succeeded = True
    finally:
        await stop_handler(
            lh,
            park_iswap=choreography_succeeded,
            suppress_errors=not choreography_succeeded,
            setup_complete=setup_complete,
        )
    print("")
    print("SUCCESS: full LIDDED PCR enrichment column-1 dry choreography completed in one STAR")
    print("session. Plate r35p0; lid r35p4; magnet and ODTC landing sites empty.")


def run_deck():
    shell = SimpleNamespace(deck=STARDeck())
    r = assign_unified_deck(shell)
    pristine = site_snapshot(r)
    assert_sites_pristine(r, pristine, "deck preview")
    assert_modeled_state(
        r, plate_site=r["work_site"], lid_parent=r["lid_park"], label="deck preview"
    )
    print_deck_and_geometry(r)
    print("")
    print("Deck mode complete: no backend, connection, setup/home, ODTC call, or motion.")


def validate_release(args):
    validate_geometry_lock()
    validate_motion_model_lock()
    validate_plr_version()
    if args.mode not in ("star", "run"):
        return
    if args.confirm != CONFIRM_TOKEN:
        raise RuntimeError(
            "Refusing physical PCR enrichment run. Add: --confirm {}".format(CONFIRM_TOKEN)
        )
    if args.acknowledge != DECK_ACK:
        raise RuntimeError(
            "Refusing physical PCR enrichment run until the exact full deck is confirmed. Add: "
            "--acknowledge {}".format(DECK_ACK)
        )
    if args.labware_ack != LABWARE_ACK:
        raise RuntimeError(
            "Refusing physical PCR enrichment run until the CellTreat/Corning combination is "
            "confirmed. Add: --labware-ack {}".format(LABWARE_ACK)
        )


def print_plan():
    validate_geometry_lock()
    print("SINGLE-HOME LIDDED PCR ENRICHMENT COLUMN-1 DRY PLAN")
    print("One setup/home, one unified deck, 13 protocol legs, one success-only park/stop.")
    print("PCR1 -> ODTC plate/lid round trip -> magnet cleanup round trip -> PCR2")
    print("-> second ODTC plate/lid round trip -> final r35p0 return.")
    print("No operator pause occurs after physical STAR release.")
    print("Dry only: empty sacrificial labware, no samples/reagents, tips returned.")
    print("No ODTC connection, initialization, door command, thermocycling, or heating.")
    print("The 10 slow-iSWAP moves are golden-locked to hardware-proven component commands.")
    print("STAR confirm: --confirm {}".format(CONFIRM_TOKEN))
    print("Deck acknowledgement: --acknowledge {}".format(DECK_ACK))
    print("Labware acknowledgement: --labware-ack {}".format(LABWARE_ACK))


def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Single-home LIDDED PCR enrichment column-1 + ODTC landing choreography "
            "(dry, tips returned, no thermocycling)."
        )
    )
    parser.add_argument(
        "--mode",
        choices=("plan", "deck", "chatterbox", "star", "run"),
        default="plan",
        help=(
            "plan/deck are inert; chatterbox simulates; star runs all 13 legs. "
            "run is retained as a star alias."
        ),
    )
    parser.add_argument("--confirm", default="")
    parser.add_argument("--acknowledge", default="")
    parser.add_argument("--labware-ack", default="")
    return parser


async def main_async(args):
    if args.mode == "plan":
        print_plan()
        return
    if args.mode == "deck":
        print("DECK MODEL ONLY: no backend, connection, setup/home, ODTC call, or motion.")
        run_deck()
        return

    validate_release(args)
    if args.mode in ("star", "run"):
        print("PHYSICAL STAR CONTINUOUS MODE: no pause after release.")
        print("Attended dry run only; one driver; hand at E-stop for the entire sequence.")
    else:
        print("CHATTERBOX MODE: no hardware connection, ODTC call, or motion.")
    await run_full("star" if args.mode in ("star", "run") else "chatterbox")


def main():
    args = build_parser().parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()

# run_ampseq_odtc_LIDDED_1col_full_v2_singlehome_dry.py
#
# SINGLE-HOME V2 of the LIDDED ampseq column-1 + ODTC thermocycler choreography.
#
# Copied from run_ampseq_odtc_1col_full_v2_singlehome_dry.py (the 9-leg, non-lidded
# single-home V2) and extended with the four lid legs, so it is the single-home
# equivalent of run_ampseq_odtc_LIDDED_1col_full_dry.py.
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
#         MEASURED, not assumed: the two plates differ by only 0.10 mm in height
#         (Cor 14.20 / CellTreat 14.30), so the tuned iSWAP grip offsets survive
#         either choice. But they differ by 1.25 mm at the WELL BOTTOM, because
#         material_z_thickness is 0.50 (Cor) vs 1.75 (CellTreat). Unifying on Cor
#         would silently shift the dispense from the tuned 1.5 mm to an effective
#         0.25 mm -- BELOW the 0.5 mm that was already crushing tips into the well
#         (see 87b6e52). Chatterbox cannot catch that; it shows up as crushed tips
#         on hardware. So the work plate STAYS CellTreat and the pipetting geometry
#         is carried over byte-for-byte. Do not "simplify" this to one plate class.
#
#     (2) THE LID. CellTreat_96_wellplate_350ul_Fb cannot model a lid at all in PLR
#         0.2.1 (with_lid=True raises TypeError), so the lid cannot live on the work
#         plate. It parks at rail35 pos4 on a Cor_96_wellplate_360ul_Fb(with_lid=True),
#         exactly as the confirmed lid mover models it, and moves cross-model onto the
#         CellTreat work plate. Cross-model move_lid was VERIFIED on chatterbox before
#         this file was written (lid re-parents; real C0PP/C0PR emitted). The lid-on
#         drop lands relative to the dest plate top, so the 0.10 mm model delta is
#         inside the ~2 mm grip window and the confirmed lid offsets carry over.
#
#   2026-07-16  Dispense geometry carried forward from the CURRENT mastermix legs
#               (87b6e52 / fbed99b / 6022969), NOT from the older single-home V2,
#               which still had the stale crushing 0.5 mm height and no in-well mix:
#               dispense height 1.5 mm, firmware in-well Mix (18 uL x3 @ 100 uL/s) at
#               mix_position_from_liquid_surface 2.0 mm, blowout 10 uL.
#
# The 13 legs, in order (identical to the LIDDED subprocess orchestrator):
#   1  PCR1 master mix add        (p50, tip col1)      rail35 pos0 work plate
#   2  iSWAP  rail35 pos0        -> rail20 pos1 ODTC nest   (PCR1 handoff)
#   2b LID ON   rail35 pos4      -> plate in ODTC nest      (seal for PCR1)
#      <-- in a REAL run the ODTC PCR1 thermal program runs HERE, lid sealed -->
#   2c LID OFF  ODTC nest        -> rail35 pos4             (unseal before lifting)
#   3  iSWAP  rail20 pos1 nest   -> rail35 pos0            (return, pickup z0 / drop z8.5)
#   4  iSWAP  rail35 pos0        -> rail35 pos2 magnet      (bead-clean handoff)
#   5  PCR1 cleanup all-dry on magnet (beads, 2x EtOH, elute)
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
# Precisely what the plate-type choice does and does not move (measured, PLR 0.2.1):
#   iSWAP grip:  Cor 14.20 vs CellTreat 14.30 tall -> 0.10 mm. Inside the ~2 mm grip
#                window, so every tuned iSWAP offset VALUE carries over unchanged.
#   Well bottom: 1.25 mm apart (material_z_thickness 0.50 vs 1.75). This one is NOT
#                negligible and is why the liquid geometry may only be paired with the
#                CellTreat model it was tuned against. See the PATCH LOG above.
#
# Per-leg teach-point mutations are applied immediately before each move and
# restored to pristine afterward, so there is no cross-leg coordinate bleed across
# the shared deck (the single-session hazard the standalone legs never hit because
# each ran in its own process).
#
# SAFETY / RUN ORDER: run  --mode chatterbox  (no hardware) FIRST to rehearse the
# whole sequence, THEN  --mode deck  (assign + print geometry, NO motion) to eyeball
# the teach points, and ONLY THEN  --mode run --confirm RUN_AMPSEQ_ODTC_LIDDED_V2 on
# the instrument. Confirm deck staging and E-stop reachability before any hardware
# run: the arm makes 13 transfers including two ODTC round trips WITH lid on/off and
# one magnet round trip. Only ONE driver may hold the STAR at a time.
#
# DECK STAGING (all of it, before a hardware run):
#   rail48 pos1 p50 tips / pos2 p300 tips
#   rail35 pos0 work plate (CellTreat, sacrificial) / pos1 mm source / pos2 magnet
#          pos3 reservoir-waste trough / pos4 LID parked on a Cor plate
#   rail20 pos1 ODTC nest, EMPTY and open
# The magnet MUST be physically at rail35 pos2, the lid on pos4, and the ODTC nest
# empty, or an iSWAP releases into open space.
#
# NOT YET RUN ON HARDWARE. Chatterbox-validated only.
#
# ASCII only.

import argparse
import asyncio
import importlib
from typing import Dict

from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends import STARBackend
from pylabrobot.liquid_handling.standard import Mix
from pylabrobot.resources.hamilton import STARDeck, TIP_CAR_480_A00
from pylabrobot.resources import (
    PLT_CAR_L5AC_A00,
    CellTreat_96_wellplate_350ul_Fb,
    CellTreat_12_troughplate_15000ul_Vb,
    Cor_96_wellplate_360ul_Fb,
    Coordinate,
)
import pylabrobot.resources as plr_resources


# ---------------------------------------------------------------------------
# Confirm gate
# ---------------------------------------------------------------------------
CONFIRM_TOKEN = "RUN_AMPSEQ_ODTC_LIDDED_V2"


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
VOL_PCR1_MASTER_MIX = 22.5
VOL_PCR2_MASTER_MIX = 20.5

# Carried over EXACTLY from the current mastermix legs (01_/03_, 87b6e52). The older
# single-home V2 still had 0.5 here; at 0.5 the tips crushed into the well at dispense.
P50_WORK_DSP_HEIGHT = [1.5] * 8   # raised 0.5 -> 1.5 (2026-07-12)
P50_WORK_DSP_OFFSETS = [Coordinate(-0.68, 3.22, 0.0)] * 8
P50_SOURCE_ASP_HEIGHT = [0.0] * 8
P50_SOURCE_ASP_OFFSETS = [Coordinate(-0.65, 3.35, 0.0)] * 8
P50_BLOWOUT_AIR_VOLUME = 6.0      # aspirate-side; the dispense uses the mix blowout below

# In-well mix on the dispense (fbed99b / 87b6e52): the firmware Mix cycles the plunger
# while the tip stays IN the well (no head retraction per cycle), then a heavy blowout so
# no sample is left in the tip. mix_position_from_liquid_surface must be POSITIVE: the STAR
# mixes at liquid_surface + this value, and the default 0 mixes AT the surface and crushes
# in a shallow well.
MIX_CYCLES = 3
MIX_VOLUME_UL = 18.0
MIX_FLOW_RATE = 100.0                    # uL/s, PLR Mix.flow_rate
MIX_POSITION_FROM_SURFACE = [2.0] * 8    # raise the mix 2 mm above the surface
P50_MIX_BLOWOUT_AIR_VOLUME = 10.0        # dialed 12 -> 10 (12 risked splashing the shallow well)

POST_DISPENSE_SETTLE_SECONDS = 1.0


# ---------------------------------------------------------------------------
# PCR1 cleanup geometry (02_ampseq_pcr1_cleanup_col1_dry_v2_p50low.py)
# ---------------------------------------------------------------------------
TROUGH_BEADS = "A1"
TROUGH_ETOH1 = "A2"
TROUGH_ETOH2 = "A3"
TROUGH_ELUTION = "A4"
TROUGH_WASTE = "A12"

VOL_BEADS = 22.5
VOL_SUPERNATANT_REMOVE = 45.0
VOL_ETHANOL_ADD = 150.0
VOL_ETHANOL_REMOVE = 150.0
VOL_RESIDUAL_ETHANOL_REMOVE = 20.0
VOL_ELUTION = 25.0

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

    work_plate = CellTreat_96_wellplate_350ul_Fb(name="rail35_pos0_ampseq_work_96wp")
    labware_carrier[WORK_POS] = work_plate
    source_96wp = CellTreat_96_wellplate_350ul_Fb(name="rail35_pos1_ampseq_mm_source_96wp")
    labware_carrier[SOURCE_96WP_POS] = source_96wp
    trough = CellTreat_12_troughplate_15000ul_Vb(name="rail35_pos3_ampseq_cleanup_12w_reservoir")
    labware_carrier[TROUGH_POS] = trough

    # rail35 pos4: the LID park. Modeled as a Cor plate carrying the lid, exactly as the
    # confirmed lid mover models it. It must be Cor and not CellTreat: CellTreat cannot
    # model a lid at all in PLR 0.2.1 (with_lid=True raises TypeError). The lid then moves
    # cross-model onto the CellTreat work plate; verified on chatterbox.
    lid_park = Cor_96_wellplate_360ul_Fb(name="rail35_pos4_ampseq_lid_park", with_lid=True)
    labware_carrier[LID_POS] = lid_park

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
    }


# ---------------------------------------------------------------------------
# Tip disposition (dry = return)
# ---------------------------------------------------------------------------
async def finish_tips(lh, discard_tips):
    if discard_tips:
        await lh.discard_tips()
    else:
        await lh.return_tips()


# ---------------------------------------------------------------------------
# Leg bodies: PCR1 / PCR2 master mix (single 8-channel col1 -> col1 transfer)
# ---------------------------------------------------------------------------
async def transfer_mastermix(lh, r, volume_ul, discard_tips=False, tip_col=1):
    vols = [volume_ul] * 8
    await lh.pick_up_tips(r["p50_tips"]["A{c}:H{c}".format(c=tip_col)])
    try:
        await lh.aspirate(
            wells_for_column(r["source_96wp"], SOURCE_COL),
            vols=vols,
            liquid_height=P50_SOURCE_ASP_HEIGHT,
            offsets=P50_SOURCE_ASP_OFFSETS,
            blow_out_air_volume=[0.0] * 8,
        )
        # Dispense AND mix in place: the firmware Mix cycles the plunger with the tip
        # still IN the well, then a heavy blowout so no sample is left in the tip.
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
    finally:
        await finish_tips(lh, discard_tips)


# ---------------------------------------------------------------------------
# Leg body: PCR1 cleanup all-dry on the magnet (8-step bead clean)
# ---------------------------------------------------------------------------
async def p50_add_from_trough_low(lh, r, source_well_name, volume_ul, discard_tips, tip_col):
    vols = [volume_ul] * 8
    await lh.pick_up_tips(r["p50_tips"]["A{c}:H{c}".format(c=tip_col)])
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
    finally:
        await finish_tips(lh, discard_tips)


async def p300_add_from_trough(lh, r, source_well_name, volume_ul, discard_tips, tip_col):
    vols = [volume_ul] * 8
    await lh.pick_up_tips(r["p300_tips"]["A{c}:H{c}".format(c=tip_col)])
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
    finally:
        await finish_tips(lh, discard_tips)


async def p300_remove_to_waste(lh, r, volume_ul, discard_tips, tip_col):
    vols = [volume_ul] * 8
    await lh.pick_up_tips(r["p300_tips"]["A{c}:H{c}".format(c=tip_col)])
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
    finally:
        await finish_tips(lh, discard_tips)


async def p50_remove_residual_ethanol_to_waste(lh, r, volume_ul, discard_tips, tip_col):
    vols = [volume_ul] * 8
    await lh.pick_up_tips(r["p50_tips"]["A{c}:H{c}".format(c=tip_col)])
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
    finally:
        await finish_tips(lh, discard_tips)


async def cleanup_all_dry(lh, r, discard_tips=False):
    """8-step dry bead clean on the magnet, mirroring the leg's run_all_dry order.
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
    pickup_slot = plate.parent
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
            await lh.move_resource(plate, drop_site)
    finally:
        if pickup_target == "slot" and pickup_slot is not None and pickup_slot_base is not None:
            pickup_slot.location = pickup_slot_base
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
            await lh.move_lid(lid, dst_plate)
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
    _lid_site = r["labware_carrier"][LID_POS]
    _nest_site = r["odtc_carrier"][ODTC_POSITION]

    # LEG 1: PCR1 master mix add (p50 col1) -> rail35 pos0 work plate
    _banner("LEG 1/13  PCR1 master mix add (p50 tip col1) -> rail35 pos0 work plate")
    await transfer_mastermix(
        lh,
        {"p50_tips": r["p50_tips"], "source_96wp": r["source_96wp"], "work_plate": r["work_plate"]},
        volume_ul=VOL_PCR1_MASTER_MIX,
        discard_tips=False,
        tip_col=1,
    )

    # LEG 2: iSWAP rail35 pos0 -> rail20 pos1 ODTC nest (PCR1 handoff)
    _banner("LEG 2/13  iSWAP rail35 pos0 -> rail20 pos1 ODTC nest (PCR1 handoff)")
    await iswap_leg(
        lh, r["work_plate"], r["odtc_carrier"][ODTC_POSITION],
        pickup_dz=ODTC_FWD_PICKUP_DZ,
        drop_dx=ODTC_FWD_DROP_DX, drop_dy=ODTC_FWD_DROP_DY, drop_dz=ODTC_FWD_DROP_DZ,
        pickup_target="plate",
    )

    # LEG 2b: LID ON rail35 pos4 -> the plate now in the ODTC nest (seal for PCR1)
    _banner("LEG 2b/13  LID ON  rail35 pos4 -> plate in ODTC nest (seal for PCR1)")
    await lid_leg(
        lh, r["lid_park"].lid, r["work_plate"],
        src_site=_lid_site, dst_site=_nest_site,
        pickup_dx=LID_ON_PICKUP_DX, pickup_dy=LID_ON_PICKUP_DY, pickup_dz=LID_ON_PICKUP_DZ,
        drop_dx=LID_ON_DROP_DX, drop_dy=LID_ON_DROP_DY, drop_dz=LID_ON_DROP_DZ,
    )

    # In a REAL run the ODTC PCR1 thermal program executes HERE, lid sealed.
    _banner("LEG 2t/13  (REAL RUN: ODTC PCR1 thermal program would execute here, lid sealed)")

    # LEG 2c: LID OFF ODTC nest -> rail35 pos4 (unseal before lifting the plate out)
    _banner("LEG 2c/13  LID OFF ODTC nest -> rail35 pos4 (unseal; pickup z7 grabs lid not plate)")
    await lid_leg(
        lh, r["work_plate"].lid, r["lid_park"],
        src_site=_nest_site, dst_site=_lid_site,
        pickup_dx=LID_OFF_PICKUP_DX, pickup_dy=LID_OFF_PICKUP_DY, pickup_dz=LID_OFF_PICKUP_DZ,
        drop_dx=LID_OFF_DROP_DX, drop_dy=LID_OFF_DROP_DY, drop_dz=LID_OFF_DROP_DZ,
    )

    # LEG 3: iSWAP rail20 pos1 ODTC nest -> rail35 pos0 (return, pickup z0 / drop z8.5)
    _banner("LEG 3/13  iSWAP rail20 pos1 ODTC nest -> rail35 pos0 (return, pickup z0 / drop z8.5)")
    await iswap_leg(
        lh, r["work_plate"], r["labware_carrier"][WORK_POS],
        pickup_dx=ODTC_RET_PICKUP_DX, pickup_dy=ODTC_RET_PICKUP_DY, pickup_dz=ODTC_RET_PICKUP_DZ,
        drop_dz=ODTC_RET_DROP_DZ,
        pickup_target="slot",
    )

    # LEG 4: iSWAP rail35 pos0 -> rail35 pos2 magnet (bead-clean handoff)
    _banner("LEG 4/13  iSWAP rail35 pos0 -> rail35 pos2 magnet (bead-clean handoff)")
    await iswap_leg(
        lh, r["work_plate"], r["labware_carrier"][MAG_POS],
        pickup_dz=MAG_FWD_PICKUP_DZ,
        drop_dx=MAG_FWD_DROP_DX, drop_dy=MAG_FWD_DROP_DY, drop_dz=MAG_FWD_DROP_DZ,
        pickup_target="plate",
    )

    # LEG 5: PCR1 cleanup all-dry on magnet (beads, 2x EtOH, elute)
    _banner("LEG 5/13  PCR1 cleanup all-dry on magnet (beads, 2x EtOH, elute)")
    await cleanup_all_dry(
        lh,
        {"p50_tips": r["p50_tips"], "p300_tips": r["p300_tips"],
         "mag_plate": r["work_plate"], "trough": r["trough"]},
        discard_tips=False,
    )

    # LEG 6: iSWAP rail35 pos2 magnet -> rail35 pos0 (return, pickup z14 / drop z8.5)
    _banner("LEG 6/13  iSWAP rail35 pos2 magnet -> rail35 pos0 (return, pickup z14 / drop z8.5)")
    await iswap_leg(
        lh, r["work_plate"], r["labware_carrier"][WORK_POS],
        pickup_dz=MAG_RET_PICKUP_DZ,
        drop_dx=MAG_RET_DROP_DX, drop_dy=MAG_RET_DROP_DY, drop_dz=MAG_RET_DROP_DZ,
        pickup_target="plate",
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

    # LEG 8: iSWAP rail35 pos0 -> rail20 pos1 ODTC nest (PCR2 handoff; byte-identical to LEG 2)
    _banner("LEG 8/13  iSWAP rail35 pos0 -> rail20 pos1 ODTC nest (PCR2 handoff)")
    await iswap_leg(
        lh, r["work_plate"], r["odtc_carrier"][ODTC_POSITION],
        pickup_dz=ODTC_FWD_PICKUP_DZ,
        drop_dx=ODTC_FWD_DROP_DX, drop_dy=ODTC_FWD_DROP_DY, drop_dz=ODTC_FWD_DROP_DZ,
        pickup_target="plate",
    )

    # LEG 8b: LID ON rail35 pos4 -> plate in ODTC nest (byte-identical to LEG 2b)
    _banner("LEG 8b/13  LID ON  rail35 pos4 -> plate in ODTC nest (seal for PCR2)")
    await lid_leg(
        lh, r["lid_park"].lid, r["work_plate"],
        src_site=_lid_site, dst_site=_nest_site,
        pickup_dx=LID_ON_PICKUP_DX, pickup_dy=LID_ON_PICKUP_DY, pickup_dz=LID_ON_PICKUP_DZ,
        drop_dx=LID_ON_DROP_DX, drop_dy=LID_ON_DROP_DY, drop_dz=LID_ON_DROP_DZ,
    )

    # In a REAL run the ODTC PCR2 thermal program executes HERE, lid sealed.
    _banner("LEG 8t/13  (REAL RUN: ODTC PCR2 thermal program would execute here, lid sealed)")

    # LEG 8c: LID OFF ODTC nest -> rail35 pos4 (byte-identical to LEG 2c)
    _banner("LEG 8c/13  LID OFF ODTC nest -> rail35 pos4 (unseal; pickup z7 grabs lid not plate)")
    await lid_leg(
        lh, r["work_plate"].lid, r["lid_park"],
        src_site=_nest_site, dst_site=_lid_site,
        pickup_dx=LID_OFF_PICKUP_DX, pickup_dy=LID_OFF_PICKUP_DY, pickup_dz=LID_OFF_PICKUP_DZ,
        drop_dx=LID_OFF_DROP_DX, drop_dy=LID_OFF_DROP_DY, drop_dz=LID_OFF_DROP_DZ,
    )

    # LEG 9: iSWAP rail20 pos1 ODTC nest -> rail35 pos0 (return; byte-identical to LEG 3)
    _banner("LEG 9/13  iSWAP rail20 pos1 ODTC nest -> rail35 pos0 (return, pickup z0 / drop z8.5)")
    await iswap_leg(
        lh, r["work_plate"], r["labware_carrier"][WORK_POS],
        pickup_dx=ODTC_RET_PICKUP_DX, pickup_dy=ODTC_RET_PICKUP_DY, pickup_dz=ODTC_RET_PICKUP_DZ,
        drop_dz=ODTC_RET_DROP_DZ,
        pickup_target="slot",
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
    print("          lid              '{}'".format(r["lid_park"].lid.name))
    print("rail20  PLT_CAR_L5AC_A00 'odtc_carrier_rail20'")
    print("    pos1  ODTC nest        (EMPTY; receives the plate for thermocycling)")
    print("")
    print("PLATE MODELS (deliberate; see the PATCH LOG):")
    print("    work plate = CellTreat  -> keeps the tuned liquid geometry exact")
    print("    lid park   = Cor        -> CellTreat cannot model a lid (with_lid raises)")
    print("    the 1.25 mm well-bottom gap between the two models is why they are NOT unified")
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
        P50_WORK_DSP_HEIGHT[0], _c(P50_WORK_DSP_OFFSETS[0]), P50_BLOWOUT_AIR_VOLUME))
    print("PCR2 mm  {} uL  p50 col2  src A1:H1 (h {} off {}) -> work A1:H1 (h {} off {} blow {})".format(
        VOL_PCR2_MASTER_MIX, P50_SOURCE_ASP_HEIGHT[0], _c(P50_SOURCE_ASP_OFFSETS[0]),
        P50_WORK_DSP_HEIGHT[0], _c(P50_WORK_DSP_OFFSETS[0]), P50_BLOWOUT_AIR_VOLUME))
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
# Entry point
# ---------------------------------------------------------------------------
def parse_args():
    p = argparse.ArgumentParser(
        description=(
            "Single-home V2 LIDDED ampseq column-1 + ODTC choreography (dry, tips returned). "
            "One home, one deck, THIRTEEN legs, one stop. Replaces the 13-subprocess wrapper."
        )
    )
    p.add_argument(
        "--mode",
        choices=["deck", "chatterbox", "run"],
        default="deck",
        help=(
            "deck = assign the unified deck and print geometry, NO motion (default). "
            "chatterbox = run all 13 legs on STARChatterboxBackend, no hardware. "
            "run = run all 13 legs on the real STAR (requires --confirm %s)." % CONFIRM_TOKEN
        ),
    )
    p.add_argument(
        "--confirm",
        default="",
        help="Required for --mode run: --confirm %s" % CONFIRM_TOKEN,
    )
    return p.parse_args()


async def main():
    args = parse_args()

    print("")
    print("#" * 88)
    print("# SINGLE-HOME V2  LIDDED ampseq col1 + ODTC  (dry, tips returned)")
    print("# mode = {}".format(args.mode))
    print("# 13 legs: PCR1 -> ODTC fwd / lid on / lid off / ret -> MAG fwd -> cleanup -> MAG ret")
    print("#          -> PCR2 -> ODTC fwd / lid on / lid off / ret ; ONE home / ONE deck / ONE stop")
    print("# WARNING: confirm deck staging + E-stop reach before any hardware run.")
    print("#" * 88)

    # --- Backend selection -------------------------------------------------
    if args.mode == "chatterbox":
        backend = load_star_chatterbox_backend()
    else:
        backend = STARBackend()

    lh = LiquidHandler(backend=backend, deck=STARDeck())

    # --- deck mode: assign + print geometry, NO motion (no setup/home, no stop)
    if args.mode == "deck":
        r = assign_unified_deck(lh)
        print_deck_and_geometry(r)
        print("\ndeck mode complete: unified deck assigned, geometry printed, no motion.")
        return

    # --- run mode gate -----------------------------------------------------
    if args.mode == "run" and args.confirm != CONFIRM_TOKEN:
        print("")
        print("Refusing to move the STAR.")
        print("This runs 13 iSWAP/liquid-handling legs including two ODTC round trips WITH lid on/off")
        print("and one magnet round trip on real hardware.")
        print("Rehearse first:  --mode chatterbox   then   --mode deck")
        print("Then to run:     --mode run --confirm %s" % CONFIRM_TOKEN)
        return

    # --- chatterbox / run: HOME ONCE, assign ONCE, run 9 legs, STOP ONCE ---
    await lh.setup(skip_autoload=True)  # single home for the whole choreography
    try:
        r = assign_unified_deck(lh)
        await run_choreography(lh, r)
        print("")
        print("SUCCESS: full LIDDED ampseq + ODTC column-1 choreography completed in one STAR")
        print("session (single home). Plate back on rail35 pos0, lid back on pos4.")
    finally:
        try:
            await lh.backend.park_iswap()
        except Exception as e:  # noqa: BLE001 - park is best-effort, never abort the stop
            print("park_iswap warning: {!r}".format(e))
        await lh.stop()
        print("Done.")


if __name__ == "__main__":
    asyncio.run(main())

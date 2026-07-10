"""
odtc_protocols.py - the thermal programs of the whole-genome Single-Cell
Core Kit, expressed as PyLabRobot Protocol objects for the Inheco ODTC.

Every temperature, every time, and every cycle count in this file is transcribed
from a source document. Nothing is invented and nothing is rounded. The source is
cited on the line where the value is used, so a reviewer can check it against the
PDF without leaving the file.

Primary source
--------------
  the kit vendor, "whole-genome Single-Cell Core Kit, 96 Reactions",
  document the kit user guide, revision 05/2025.
    Table 1  DNA Amplification   (lid 70 C)   page 11
    Table 4  DNAPREP             (lid 105 C)  page 14
    Table 5  FERAT              (lid 105 C)  page 14
    Table 8  LIB-AMP           (lid 105 C)  page 17
    Ligation incubation                      page 16, section IV step 7

Two ODTC-specific translations
------------------------------
1. "4 C infinite hold" has no direct encoding. The ODTC method XML carries a finite
   `PlateauTime` per step, plus a per-method `PostHeating` flag whose backend
   docstring reads "keep last temperature after method end". So an infinite hold is
   a final 4 C step with `hold_seconds=0` and `post_heating=True`. PLR's own ODTC
   notebook writes the 4 C hold exactly this way. The block then sits at 4 C until
   something stops the method.

2. The backend writes one lid temperature for every step of a method
   (`_generate_method_xml` sets `LidTemp` to `start_lid_temperature` on each step,
   with a comment saying per-step lid temperatures are not implemented). Each
   program below therefore carries a single lid temperature, which is what the
   source tables specify anyway.

PlateauTime unit: seconds (confirmed on the instrument, 2026-07-10)
-------------------------------------------------------------------
`PlateauTime` carries `hold_seconds` directly, and the unit is seconds. This was
PyLabRobot's assumption, not Inheco's, so it was checked: the `timecheck` program
(one 50 C step, 60 s) held the block at 50 C for about 56 to 60 seconds on the
temperature trace. So the durations below are scaled correctly. Re-run
`05_odtc_run_protocol.py --program timecheck` after any firmware change before
trusting the long holds.
"""

from odtc_compat import import_plr

_plr = import_plr()
Protocol = _plr.Protocol
Stage = _plr.Stage
Step = _plr.Step

# See translation note 1. Encode "hold at this temperature until stopped".
INFINITE_HOLD_SECONDS = 0

# The block starts a method from wherever it happens to be. the kit user guide never specifies
# a start block temperature, so use the one PLR's ODTC notebook uses: room temperature.
START_BLOCK_C_DEFAULT = 25.0

# the kit user guide lid temperatures, per table.
LID_C_WGA = 70.0        # Table 1 caption: "lid temperature 70 C"
LID_C_DNAPREP = 105.0   # Table 4 caption: "lid temperature 105 C"
LID_C_FERAT = 105.0     # Table 5 caption: "lid temperature 105 C"
LID_C_LIGATION = 50.0   # page 16 IV.7: "lid temperature disabled or set to 50 C".
#                         The backend cannot disable the lid, so 50 C it is.
LID_C_LIBAMP = 105.0    # Table 8 caption: "lid temperature 105 C"

# Reaction volumes, summed from the pipetting steps. These set `block_max_volume`,
# which the backend buckets into the ODTC's FluidQuantity field (<30 uL -> 0,
# <75 uL -> 1, else 2).
VOL_UL_WGA = 12.0       # 3 cells/Cell Buffer (p10 II.10) + 3 Lysis Mix (Table 2)
#                         + 6 Reaction Mix (Table 3)
VOL_UL_DNAPREP = 6.0    # 3 WGA product in Elution Buffer (II.1) + 3 DNA Prep MM (II.5)
VOL_UL_FERAT = 10.0     # 6 carried from DNAPREP + 4 FERAT Master Mix (III.6, Table 7)
VOL_UL_LIGATION = 20.0  # 10 carried from FERAT + 5 adapters (IV.4) + 5 LP2L (IV.5)
VOL_UL_LIBAMP = 40.0    # 20 carried from ligation + 20 Amplification Master Mix (V.5)


# ---------------------------------------------------------------------------
# Table 1. DNA Amplification (lid temperature 70 C). Total ~2.6 hours.
#   Hold 1   30 C   2.5 hours
#   Hold 2   65 C   3 minutes
#   Hold 3    4 C   infinite
# ---------------------------------------------------------------------------
WGA_DNA_AMPLIFICATION = Protocol(stages=[
    Stage(steps=[Step(temperature=[30.0], hold_seconds=2.5 * 60 * 60)], repeats=1),
    Stage(steps=[Step(temperature=[65.0], hold_seconds=3 * 60)], repeats=1),
    Stage(steps=[Step(temperature=[4.0], hold_seconds=INFINITE_HOLD_SECONDS)], repeats=1),
])

# ---------------------------------------------------------------------------
# Table 4. DNAPREP (lid temperature 105 C). Total ~10 minutes.
#   Hold 1   37 C   10 minutes
#   Hold 2    4 C   infinite
# ---------------------------------------------------------------------------
DNAPREP = Protocol(stages=[
    Stage(steps=[Step(temperature=[37.0], hold_seconds=10 * 60)], repeats=1),
    Stage(steps=[Step(temperature=[4.0], hold_seconds=INFINITE_HOLD_SECONDS)], repeats=1),
])

# ---------------------------------------------------------------------------
# Table 5. FERAT (lid temperature 105 C). Total ~40 minutes.
#   Hold 1    4 C   30 seconds
#   Hold 2   30 C   5 minutes
#   Hold 3   65 C   30 minutes
#   Hold 4    4 C   infinite
# ---------------------------------------------------------------------------
FERAT = Protocol(stages=[
    Stage(steps=[Step(temperature=[4.0], hold_seconds=30)], repeats=1),
    Stage(steps=[Step(temperature=[30.0], hold_seconds=5 * 60)], repeats=1),
    Stage(steps=[Step(temperature=[65.0], hold_seconds=30 * 60)], repeats=1),
    Stage(steps=[Step(temperature=[4.0], hold_seconds=INFINITE_HOLD_SECONDS)], repeats=1),
])

# ---------------------------------------------------------------------------
# Ligation, page 16 section IV step 7:
#   "Incubate the plate at 20 C for 15 min in a thermal cycler with the lid
#    temperature disabled or set to 50 C."
# No infinite hold is specified: the protocol says proceed immediately to library
# amplification. post_heating is therefore left to the caller's default.
# ---------------------------------------------------------------------------
LIGATION = Protocol(stages=[
    Stage(steps=[Step(temperature=[20.0], hold_seconds=15 * 60)], repeats=1),
])

# ---------------------------------------------------------------------------
# Table 8. LIB-AMP (lid temperature 105 C).
#   Hold 1, Hot Start          98 C   45 seconds   1 cycle
#   Hold 2, Denaturation       98 C   15 seconds  \
#   Hold 3, Annealing          60 C   30 seconds   > 8 cycles
#   Hold 4, Extension          72 C   45 seconds  /
#   Hold 5, Final Extension    72 C   60 seconds   1 cycle
#   Hold 6                      4 C   infinite     1 cycle
#
# The three cycled holds are one Stage with repeats=8. The backend turns that into
# a GotoNumber/LoopNumber jump on the last step of the stage, with
# LoopNumber = repeats - 1 = 7, because the first pass through the steps is not a
# loop iteration. odtc_offline_checks.py asserts that the emitted XML says exactly
# GotoNumber 2 / LoopNumber 7.
# ---------------------------------------------------------------------------
LIB_AMP = Protocol(stages=[
    Stage(steps=[Step(temperature=[98.0], hold_seconds=45)], repeats=1),
    Stage(steps=[
        Step(temperature=[98.0], hold_seconds=15),
        Step(temperature=[60.0], hold_seconds=30),
        Step(temperature=[72.0], hold_seconds=45),
    ], repeats=8),
    Stage(steps=[Step(temperature=[72.0], hold_seconds=60)], repeats=1),
    Stage(steps=[Step(temperature=[4.0], hold_seconds=INFINITE_HOLD_SECONDS)], repeats=1),
])


# ===========================================================================
# Targeted PCR library prep. A DIFFERENT protocol from the whole-genome sequencing the kit user guide
# programs above.
#
# Source: "Targeted PCR Library Prep" protocol, di-omics internal, updated
# 2026-05-28. Values are transcribed from the protocol's two PCR cycling tables the
# same way as everything else here, and only the thermal profile is encoded; primer
# sequences and reagent volumes live in the liquid-handling protocol, not here.
# Enzyme is NEBNext Q5U 2X (PCR1) / Q5 2X (PCR2), 25 uL reactions.
#
# Three values are NOT pinned down by the protocol and are flagged at each use:
#   - Lid temperature. The amplicon protocol does not give one. 105 C is the standard
#     heated-lid temperature for Q5 PCR and matches the kit user guide LIB-AMP program,
#     which is also a Q5 indexing PCR. It is a default, not a transcription. Tunable.
#   - PCR1 annealing temperature. The protocol's default is "~67 C" and it explicitly
#     says to recompute Ta with the NEB Tm calculator (Q5U Hot Start selected) for
#     your primer set. 67 C is the default; pass anneal_c to override.
#   - PCR2 cycle count. The protocol gives a RANGE, 8 to 10 cycles, "1-2 more if bands
#     were faint". Encoded with a conservative default of 8; pass num_cycles to change.
#
# The holds differ between the two PCRs, and both are transcribed as written:
# PCR1 ends at a 10 C hold, PCR2 at a 4 C hold.
#
# On-instrument finding (ampseq-pcr1, 2026-07-10): the run completed all 30 cycles and
# held every setpoint to a mean 0.27 C, BUT the 98 C denaturation sits only 1 C under the
# ODTC's 99 C block ceiling, so the block grazed it on the ramp-in (peak 99.04 C) and the
# device logged 91 "temperature out of specification" warnings, about three per cycle.
# They are warnings, not faults, and the method finished. The program keeps 98 C because
# that is the protocol value; an operator worried about the ceiling can pass
# ampseq_pcr1(...) with a 97 C denaturation via a custom protocol, or soften the overshoot.
# ===========================================================================

LID_C_AMPSEQ = 105.0        # NOT from the protocol. Standard Q5 PCR lid, see note above.
AMPSEQ_ANNEAL_C = 67.0      # protocol default "~67 C", primer-dependent (NEB Tm calc).
VOL_UL_AMPSEQ = 25.0        # PCR1 and PCR2 TOTAL reaction = 25 uL.


def ampseq_pcr1(anneal_c: float = AMPSEQ_ANNEAL_C, num_cycles: int = 30) -> "Protocol":
    """Targeted PCR PCR1 (target amplification).

    Source: Targeted PCR Library Prep, PCR1 cycling table.
      98 C 30 s            x1
      98 C 10 s / anneal 15 s / 72 C 15 s   x30
      72 C 60 s            x1
      10 C hold            (as written; this protocol holds at 10 C, not 4 C)
    """
    return Protocol(stages=[
        Stage(steps=[Step(temperature=[98.0], hold_seconds=30)], repeats=1),
        Stage(steps=[
            Step(temperature=[98.0], hold_seconds=10),
            Step(temperature=[anneal_c], hold_seconds=15),
            Step(temperature=[72.0], hold_seconds=15),
        ], repeats=num_cycles),
        Stage(steps=[Step(temperature=[72.0], hold_seconds=60)], repeats=1),
        Stage(steps=[Step(temperature=[10.0], hold_seconds=INFINITE_HOLD_SECONDS)], repeats=1),
    ])


def ampseq_pcr2(anneal_c: float = AMPSEQ_ANNEAL_C, num_cycles: int = 8) -> "Protocol":
    """Targeted PCR PCR2 (Nextera indexing).

    Source: Targeted PCR Library Prep, PCR2 cycling table.
      98 C 30 s            x1
      98 C 10 s / anneal 15 s / 72 C 15 s   x8-10  (default 8, see note)
      72 C 60 s            x1
      4 C hold
    """
    return Protocol(stages=[
        Stage(steps=[Step(temperature=[98.0], hold_seconds=30)], repeats=1),
        Stage(steps=[
            Step(temperature=[98.0], hold_seconds=10),
            Step(temperature=[anneal_c], hold_seconds=15),
            Step(temperature=[72.0], hold_seconds=15),
        ], repeats=num_cycles),
        Stage(steps=[Step(temperature=[72.0], hold_seconds=60)], repeats=1),
        Stage(steps=[Step(temperature=[4.0], hold_seconds=INFINITE_HOLD_SECONDS)], repeats=1),
    ])


AMPSEQ_PCR1 = ampseq_pcr1()
AMPSEQ_PCR2 = ampseq_pcr2()


# ---------------------------------------------------------------------------
# Not biology. Hardware exercises.
#
# These two are NOT from any protocol and have no biological meaning. They exist so
# that the first live run of the ODTC is short and legible instead of a 2.6 hour
# WGA hold. Temperatures sit inside the documented 4 C to 99 C block range and the
# lid sits at a lid temperature the sources already use.
# ---------------------------------------------------------------------------

# Times one step against a stopwatch to settle the PlateauTime unit question. One
# step, 60 s, at a temperature the block reaches quickly from room temperature.
LID_C_HARDWARE_EXERCISE = 105.0
TIMECHECK = Protocol(stages=[
    Stage(steps=[Step(temperature=[50.0], hold_seconds=60)], repeats=1),
])

# Exercises what a PCR program actually stresses: a fast ramp, and a stage loop.
# Three cycles, ten seconds a side.
SELFTEST = Protocol(stages=[
    Stage(steps=[
        Step(temperature=[95.0], hold_seconds=10),
        Step(temperature=[60.0], hold_seconds=10),
    ], repeats=3),
    Stage(steps=[Step(temperature=[25.0], hold_seconds=INFINITE_HOLD_SECONDS)], repeats=1),
])


class Program:
    """A protocol plus the two run parameters the source document pins down."""

    def __init__(self, name, protocol, lid_c, block_max_volume_ul, source, is_biology=True):
        self.name = name
        self.protocol = protocol
        self.lid_c = lid_c
        self.block_max_volume_ul = block_max_volume_ul
        self.source = source
        self.is_biology = is_biology


PROGRAMS = {
    "wga": Program("wga", WGA_DNA_AMPLIFICATION, LID_C_WGA, VOL_UL_WGA,
                   "the kit user guide Table 1, DNA Amplification"),
    "dnaprep": Program("dnaprep", DNAPREP, LID_C_DNAPREP, VOL_UL_DNAPREP,
                       "the kit user guide Table 4, DNAPREP"),
    "ferat": Program("ferat", FERAT, LID_C_FERAT, VOL_UL_FERAT,
                     "the kit user guide Table 5, FERAT"),
    "ligation": Program("ligation", LIGATION, LID_C_LIGATION, VOL_UL_LIGATION,
                        "the kit user guide page 16, section IV step 7"),
    "libamp": Program("libamp", LIB_AMP, LID_C_LIBAMP, VOL_UL_LIBAMP,
                      "the kit user guide Table 8, LIB-AMP"),
    "ampseq-pcr1": Program("ampseq-pcr1", AMPSEQ_PCR1, LID_C_AMPSEQ, VOL_UL_AMPSEQ,
                           "Amplicon-seq Library Prep (di-omics internal, 2026-05-28), PCR1"),
    "ampseq-pcr2": Program("ampseq-pcr2", AMPSEQ_PCR2, LID_C_AMPSEQ, VOL_UL_AMPSEQ,
                           "Amplicon-seq Library Prep (di-omics internal, 2026-05-28), PCR2"),
    "timecheck": Program("timecheck", TIMECHECK, LID_C_HARDWARE_EXERCISE, 20.0,
                         "hardware exercise, not biology", is_biology=False),
    "selftest": Program("selftest", SELFTEST, LID_C_HARDWARE_EXERCISE, 20.0,
                        "hardware exercise, not biology", is_biology=False),
}

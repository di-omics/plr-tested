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


# ===========================================================================
# NEBNext Enzymatic Methyl-seq v2, run with UltraShear enzymatic fragmentation.
# A DIFFERENT protocol from everything above.
#
# Sources (public NEB kit manuals, transcribed the same way as the rest of this
# file: every temperature, time, and cycle count is copied from the document and
# cited on the line where it is used, nothing invented or rounded):
#   - NEBNext UltraShear, NEB #M7634 manual, Section 3, "UltraShear fragmentation
#     coupled with NEBNext Enzymatic Methyl-seq v2 Kit (E8015)". This is the coupled
#     protocol; it is NOT interchangeable with the standalone E8015 protocol (the
#     manual says so). The shear and the coupled End Prep come from here.
#   - NEBNext Enzymatic Methyl-seq v2, NEB #E8015 manual (v1.3). TET2 protection,
#     denaturation, deamination, and the final PCR come from here.
#
# The thermal programs only. Reagent volumes and the liquid-handling map live in the
# STAR scripts under hamilton-star/starlab_live/emseq/, not here, exactly as the
# targeted PCR primer volumes live in the liquid-handling protocol and not in this file.
#
# Two device translations, identical to the ones already used above:
#   - "Hold at 4 C" with no time is encoded as a final 4 C step, hold_seconds=0,
#     post_heating=True (see translation note 1 at the top of this file).
#   - The manual's "heated lid off" for the ligation step cannot be honored: this
#     backend writes one lid temperature per method and cannot disable the lid. The
#     existing `ligation` program above hit the same wall and resolved it to 50 C;
#     emseq-ligation follows that precedent. Flagged again at the constant below.
#
# Two values are NOT pinned down by the documents and are flagged at each use:
#   - emseq-shear fragmentation time. The coupled manual (M7634 Section 3.1.6) gives
#     a RANGE, 25 to 35 minutes at 37 C, and says to optimize per sample. The operator
#     runs 30 minutes, the midpoint, so 30 is the default; pass shear_minutes to change.
#   - emseq-pcr cycle count. E8015 Section 1.9.3 gives an input-dependent table
#     (200 ng: 4-5, 50 ng: 5-6, 10 ng: 8, 1 ng: 11, 0.1 ng: 14). Encoded with a
#     default of 8 (the 10 ng row); pass num_cycles to match the input.
#
# Block-ceiling caution, same as ampseq-pcr1: the EM-seq PCR denaturation is 98 C,
# 1 C under the ODTC's 99 C block ceiling, so the block can graze it on the ramp-in
# and the device may log "temperature out of specification" warnings (warnings, not
# faults; see the ampseq-pcr1 note above and the odtc README). 98 C is the protocol
# value and is kept; an operator worried about the ceiling can build emseq_pcr(...)
# from a custom 97 C protocol.
#
# Denaturation substitution: E8015 Section 1.7A.4 says to move the plate to a cold
# block on ice immediately after the 85 C hold and let it cool ~2 minutes. On the
# ODTC there is no off-instrument ice step, so the program models that as a final
# 4 C hold. The cool-down happens in the block, not on ice; note it when validating.
# ===========================================================================

LID_C_EMSEQ_SHEAR = 75.0        # M7634 Section 3.1.6: "heated lid set to 75 C".
LID_C_EMSEQ_ENDPREP = 75.0      # M7634 Section 3.2.3: "heated lid set to >= 75 C or on".
LID_C_EMSEQ_LIGATION = 50.0     # M7634 Section 3.3.3 / E8015 1.3.3: "heated lid off".
#                                 Backend cannot disable the lid; 50 C mirrors the
#                                 existing `ligation` program. See header note.
LID_C_EMSEQ_TET2 = 45.0         # E8015 Section 1.5.5 / 1.5.7: "heated lid set to >= 45 C or on".
LID_C_EMSEQ_DENATURE = 105.0    # E8015 Section 1.7A.1: "heated lid set to >= 105 C or on".
LID_C_EMSEQ_DEAMINATE = 45.0    # E8015 Section 1.8.3: "heated lid set to >= 45 C or on".
LID_C_EMSEQ_PCR = 105.0         # E8015 Section 1.9.3: "heated lid set to 105 C".

# Reaction volumes at the point each program runs, summed from the pipetting steps in
# the coupled workflow (single column). These set block_max_volume -> FluidQuantity
# (<30 uL -> 0, <75 uL -> 1, else 2).
VOL_UL_EMSEQ_SHEAR = 44.0       # 26 gDNA+controls (M7634 3.1.1) + 18 shear MM (3.1.4)
VOL_UL_EMSEQ_ENDPREP = 49.0     # 44 fragmented (3.1.6) + 5 End Prep MM (3.2.1)
VOL_UL_EMSEQ_LIGATION = 82.5    # 49 End Prep (3.2.3) + 2.5 adaptor + 31 ligation MM (3.3.1)
VOL_UL_EMSEQ_TET2 = 50.0        # 45 TET2 reaction (E8015 1.5.3) + 5 Fe(II) (1.5.4)
VOL_UL_EMSEQ_TET2_STOP = 51.0   # 50 TET2 (1.5.5) + 1 Stop Reagent (1.5.6)
VOL_UL_EMSEQ_DENATURE = 20.0    # 16 protected DNA (1.6.11) + 4 formamide (1.7A.2)
VOL_UL_EMSEQ_DEAMINATE = 40.0   # 20 denatured (1.7A.4) + 20 deamination MM (1.8.1)
VOL_UL_EMSEQ_PCR = 90.0         # 40 deaminated (1.8.3) + 5 UDI primer + 45 Q5U MM (1.9.1)


# ---------------------------------------------------------------------------
# M7634 Section 3.1.6. UltraShear fragmentation, coupled to EM-seq v2. Lid 75 C.
#   25-35 minutes at 37 C   (fragmentation; default 30, see header)
#   15 minutes at 65 C      (enzyme inactivation)
#   Hold at 4 C
# ---------------------------------------------------------------------------
def emseq_shear(shear_minutes: float = 30.0) -> "Protocol":
    """UltraShear enzymatic fragmentation for the EM-seq v2 coupled workflow.

    Source: NEB #M7634 manual, Section 3.1.6. The 37 C hold is a documented range of
    25 to 35 minutes, optimized per sample; the default 30 is the midpoint the operator
    runs. Longer time gives a smaller average fragment size.
    """
    return Protocol(stages=[
        Stage(steps=[Step(temperature=[37.0], hold_seconds=shear_minutes * 60)], repeats=1),
        Stage(steps=[Step(temperature=[65.0], hold_seconds=15 * 60)], repeats=1),
        Stage(steps=[Step(temperature=[4.0], hold_seconds=INFINITE_HOLD_SECONDS)], repeats=1),
    ])


# ---------------------------------------------------------------------------
# M7634 Section 3.2.3. End Prep of fragmented DNA (coupled version). Lid >= 75 C.
#   15 minutes at 20 C
#   15 minutes at 65 C
#   Hold at 4 C
# ---------------------------------------------------------------------------
EMSEQ_ENDPREP = Protocol(stages=[
    Stage(steps=[Step(temperature=[20.0], hold_seconds=15 * 60)], repeats=1),
    Stage(steps=[Step(temperature=[65.0], hold_seconds=15 * 60)], repeats=1),
    Stage(steps=[Step(temperature=[4.0], hold_seconds=INFINITE_HOLD_SECONDS)], repeats=1),
])

# ---------------------------------------------------------------------------
# M7634 Section 3.3.3 (= E8015 Section 1.3.3). Adaptor ligation. Lid "off" -> 50 C.
#   15 minutes at 20 C
#   Hold at 4 C
# ---------------------------------------------------------------------------
EMSEQ_LIGATION = Protocol(stages=[
    Stage(steps=[Step(temperature=[20.0], hold_seconds=15 * 60)], repeats=1),
    Stage(steps=[Step(temperature=[4.0], hold_seconds=INFINITE_HOLD_SECONDS)], repeats=1),
])

# ---------------------------------------------------------------------------
# E8015 Section 1.5.5. TET2 protection of 5mC/5hmC. Lid >= 45 C.
#   1 hour at 37 C
#   Hold at 4 C
# ---------------------------------------------------------------------------
EMSEQ_TET2 = Protocol(stages=[
    Stage(steps=[Step(temperature=[37.0], hold_seconds=60 * 60)], repeats=1),
    Stage(steps=[Step(temperature=[4.0], hold_seconds=INFINITE_HOLD_SECONDS)], repeats=1),
])

# ---------------------------------------------------------------------------
# E8015 Section 1.5.7. Stop-reagent incubation, after Stop Reagent is added. Lid >= 45 C.
#   30 minutes at 37 C
#   Hold at 4 C
# ---------------------------------------------------------------------------
EMSEQ_TET2_STOP = Protocol(stages=[
    Stage(steps=[Step(temperature=[37.0], hold_seconds=30 * 60)], repeats=1),
    Stage(steps=[Step(temperature=[4.0], hold_seconds=INFINITE_HOLD_SECONDS)], repeats=1),
])

# ---------------------------------------------------------------------------
# E8015 Section 1.7A.3. Formamide denaturation. Lid >= 105 C.
#   10 minutes at 85 C
#   Hold at 4 C   (models the "cool on ice ~2 min" step; see header substitution note)
# ---------------------------------------------------------------------------
EMSEQ_DENATURE = Protocol(stages=[
    Stage(steps=[Step(temperature=[85.0], hold_seconds=10 * 60)], repeats=1),
    Stage(steps=[Step(temperature=[4.0], hold_seconds=INFINITE_HOLD_SECONDS)], repeats=1),
])

# ---------------------------------------------------------------------------
# E8015 Section 1.8.3. APOBEC deamination of cytosines. Lid >= 45 C.
#   3 hours at 37 C
#   Hold at 4 C
# ---------------------------------------------------------------------------
EMSEQ_DEAMINATE = Protocol(stages=[
    Stage(steps=[Step(temperature=[37.0], hold_seconds=3 * 60 * 60)], repeats=1),
    Stage(steps=[Step(temperature=[4.0], hold_seconds=INFINITE_HOLD_SECONDS)], repeats=1),
])

# ---------------------------------------------------------------------------
# E8015 Section 1.9.3. Library PCR amplification (Q5U). Lid 105 C.
#   Initial Denaturation   98 C   30 seconds   1 cycle
#   Denaturation           98 C   10 seconds  \
#   Annealing              62 C   30 seconds   > 4-14 cycles (default 8, see header)
#   Extension              65 C   60 seconds  /
#   Final Extension        65 C   5 minutes    1 cycle   (65 C, not 72 C, as written)
#   Hold                    4 C   infinite     1 cycle
#
# As with the other cycled programs here, the three cycled holds are one Stage with
# repeats=num_cycles; the backend emits the GotoNumber/LoopNumber jump.
# ---------------------------------------------------------------------------
def emseq_pcr(anneal_c: float = 62.0, num_cycles: int = 8) -> "Protocol":
    """EM-seq v2 library PCR amplification.

    Source: NEB #E8015 manual, Section 1.9.3 cycling table. Cycle count is
    input-dependent (see header); default 8 matches the 10 ng row. The 98 C
    denaturation grazes the ODTC's 99 C block ceiling (see header caution).
    """
    return Protocol(stages=[
        Stage(steps=[Step(temperature=[98.0], hold_seconds=30)], repeats=1),
        Stage(steps=[
            Step(temperature=[98.0], hold_seconds=10),
            Step(temperature=[anneal_c], hold_seconds=30),
            Step(temperature=[65.0], hold_seconds=60),
        ], repeats=num_cycles),
        Stage(steps=[Step(temperature=[65.0], hold_seconds=5 * 60)], repeats=1),
        Stage(steps=[Step(temperature=[4.0], hold_seconds=INFINITE_HOLD_SECONDS)], repeats=1),
    ])


EMSEQ_SHEAR = emseq_shear()
EMSEQ_PCR = emseq_pcr()


# ===========================================================================
# NEBNext Single Cell / Low Input RNA Library Prep for Illumina (scRNA-seq).
# A DIFFERENT protocol from everything above: RNA -> cDNA (reverse transcription +
# template switching) -> cDNA amplification -> fragment/end-prep -> adaptor ligation
# -> library PCR.
#
# Source (public NEB kit manual, transcribed the same way as the rest of this file,
# every temperature/time/cycle copied and cited on the line where it is used):
#   NEBNext Single Cell/Low Input RNA Library Prep Kit for Illumina, NEB #E6420
#   manual, Version 6.0 (01/24), Section 1 "Protocol for Cells". Section 2 "Low Input
#   RNA" shares the same thermal profiles; the only difference is the cDNA
#   amplification mix and the front-end sample handling, not the ODTC programs.
#
# The thermal programs only. Reagent volumes and the liquid-handling map live in the
# STAR scripts under hamilton-star/starlab_live/scrnaseq/, not here.
#
# Two device translations, identical to the ones already used above:
#   - "Hold at 4 C" with no time is a final 4 C step, hold_seconds=0, post_heating=True.
#   - The manual's "heated lid off" for the ligation step cannot be honored (the backend
#     writes one lid temperature per method and cannot disable the lid). As with the
#     existing `ligation` and `emseq-ligation` programs, sc-ligation runs the lid at 50 C.
#     Flagged again at the constant below.
#
# Two values are NOT pinned down by the document and are flagged at each use:
#   - sc-cdna-pcr cycle count. E6420 Section 1.5.3 gives an input-dependent table
#     (HEK single cell 18, HeLa 17, Jurkat 20, 10 cells 14-17, 100 cells 11-14,
#     2 pg 20-21, ... range 11-21). Default 18 (HEK single cell); pass num_cycles.
#   - sc-lib-pcr cycle count. E6420 Section 1.11.3: default 8 for 1-20 ng cDNA input,
#     input-dependent (100 pg-1 ng: 9-12, 20-100 ng: 3-6). Default 8; pass num_cycles.
#
# Block-ceiling caution, same as ampseq-pcr1 and emseq-pcr: both PCR programs denature
# at 98 C, 1 C under the ODTC's 99 C block ceiling, so the block can graze it on the
# ramp-in and the device may log "temperature out of specification" warnings (warnings,
# not faults; see the ampseq-pcr1 note above and the odtc README).
# ===========================================================================

LID_C_SC_ANNEAL = 105.0     # E6420 Section 1.3.3: "heated lid set to 105 C".
LID_C_SC_RT = 105.0         # E6420 Section 1.4.4: "heated lid set to 105 C".
LID_C_SC_CDNA_PCR = 105.0   # E6420 Section 1.5.3: "heated lid set to 105 C".
LID_C_SC_FS = 75.0          # E6420 Section 1.8.5: "heated lid set to 75 C".
LID_C_SC_LIGATION = 50.0    # E6420 Section 1.9.5: "heated lid off". Backend cannot
#                             disable the lid; 50 C mirrors ligation / emseq-ligation.
LID_C_SC_USER = 47.0        # E6420 Section 1.9.7: "heated lid set to >= 47 C".
LID_C_SC_LIB_PCR = 105.0    # E6420 Section 1.11.3 gives no lid temperature; 105 C is the
#                             standard Q5 heated-lid default (matches the cDNA PCR here). Not transcribed.

# Reaction volumes at the point each program runs (single reaction), summed from the
# pipetting steps. These set block_max_volume -> FluidQuantity (<30 -> 0, <75 -> 1, else 2).
VOL_UL_SC_ANNEAL = 9.0      # 5 lysed cells + 1 RT primer mix + 3 water (1.3.1A)
VOL_UL_SC_RT = 20.0         # 9 annealed (1.3.3) + 11 RT mix (1.4.1)
VOL_UL_SC_CDNA_PCR = 100.0  # 20 RT product (1.4.4) + 80 cDNA amplification mix (1.5.1)
VOL_UL_SC_FS = 35.0         # 26 cleaned cDNA (1.6.20) + 9 FS mix (1.8.3)
VOL_UL_SC_LIGATION = 68.5   # 35 FS reaction (1.8.5) + 2.5 adaptor + 31 ligation mix (1.9.3)
VOL_UL_SC_USER = 71.5       # 68.5 ligation (1.9.5) + 3 USER enzyme (1.9.6)
VOL_UL_SC_LIB_PCR = 50.0    # 15 adaptor-ligated (1.10.11) + 25 Q5 MM + 10 index primers (1.11.1)


# ---------------------------------------------------------------------------
# E6420 Section 1.3.3. Primer annealing for first-strand synthesis. Lid 105 C.
#   5 minutes at 70 C
#   Hold at 4 C
# ---------------------------------------------------------------------------
SC_ANNEAL = Protocol(stages=[
    Stage(steps=[Step(temperature=[70.0], hold_seconds=5 * 60)], repeats=1),
    Stage(steps=[Step(temperature=[4.0], hold_seconds=INFINITE_HOLD_SECONDS)], repeats=1),
])

# ---------------------------------------------------------------------------
# E6420 Section 1.4.4. Reverse transcription and template switching. Lid 105 C.
#   90 minutes at 42 C
#   10 minutes at 70 C
#   Hold at 4 C
# ---------------------------------------------------------------------------
SC_RT = Protocol(stages=[
    Stage(steps=[Step(temperature=[42.0], hold_seconds=90 * 60)], repeats=1),
    Stage(steps=[Step(temperature=[70.0], hold_seconds=10 * 60)], repeats=1),
    Stage(steps=[Step(temperature=[4.0], hold_seconds=INFINITE_HOLD_SECONDS)], repeats=1),
])

# ---------------------------------------------------------------------------
# E6420 Section 1.5.3. cDNA amplification by PCR. Lid 105 C.
#   Initial Denaturation   98 C   45 seconds   1 cycle
#   Denaturation           98 C   10 seconds  \
#   Annealing              62 C   15 seconds   > 11-21 cycles (default 18, see header)
#   Extension              72 C   3 minutes   /
#   Final Extension        72 C   5 minutes    1 cycle
#   Hold                    4 C   infinite
# ---------------------------------------------------------------------------
def sc_cdna_pcr(num_cycles: int = 18) -> "Protocol":
    """Single-cell cDNA amplification PCR.

    Source: E6420 Section 1.5.3 cycling table. Cycle count is input-dependent (see
    header); default 18 matches a HEK293 single cell. The 98 C denaturation grazes
    the ODTC's 99 C block ceiling (see header caution).
    """
    return Protocol(stages=[
        Stage(steps=[Step(temperature=[98.0], hold_seconds=45)], repeats=1),
        Stage(steps=[
            Step(temperature=[98.0], hold_seconds=10),
            Step(temperature=[62.0], hold_seconds=15),
            Step(temperature=[72.0], hold_seconds=3 * 60),
        ], repeats=num_cycles),
        Stage(steps=[Step(temperature=[72.0], hold_seconds=5 * 60)], repeats=1),
        Stage(steps=[Step(temperature=[4.0], hold_seconds=INFINITE_HOLD_SECONDS)], repeats=1),
    ])

# ---------------------------------------------------------------------------
# E6420 Section 1.8.5. Fragmentation / End Prep (Ultra II FS). Lid 75 C.
#   25 minutes at 37 C
#   30 minutes at 65 C
#   Hold at 4 C
# ---------------------------------------------------------------------------
SC_FS = Protocol(stages=[
    Stage(steps=[Step(temperature=[37.0], hold_seconds=25 * 60)], repeats=1),
    Stage(steps=[Step(temperature=[65.0], hold_seconds=30 * 60)], repeats=1),
    Stage(steps=[Step(temperature=[4.0], hold_seconds=INFINITE_HOLD_SECONDS)], repeats=1),
])

# ---------------------------------------------------------------------------
# E6420 Section 1.9.5. Adaptor ligation. Lid "off" -> 50 C (see header).
#   15 minutes at 20 C
#   Hold at 4 C
# ---------------------------------------------------------------------------
SC_LIGATION = Protocol(stages=[
    Stage(steps=[Step(temperature=[20.0], hold_seconds=15 * 60)], repeats=1),
    Stage(steps=[Step(temperature=[4.0], hold_seconds=INFINITE_HOLD_SECONDS)], repeats=1),
])

# ---------------------------------------------------------------------------
# E6420 Section 1.9.7. USER enzyme incubation (cleaves the NEBNext adaptor). Lid >= 47 C.
#   15 minutes at 37 C
#   Hold at 4 C
# ---------------------------------------------------------------------------
SC_USER = Protocol(stages=[
    Stage(steps=[Step(temperature=[37.0], hold_seconds=15 * 60)], repeats=1),
    Stage(steps=[Step(temperature=[4.0], hold_seconds=INFINITE_HOLD_SECONDS)], repeats=1),
])

# ---------------------------------------------------------------------------
# E6420 Section 1.11.3. PCR enrichment of adaptor-ligated DNA (Q5, 2-step). Lid 105 C.
#   Initial Denaturation   98 C   30 seconds   1 cycle
#   Denaturation           98 C   10 seconds  \  > 8 cycles (default, see header)
#   Annealing/Extension    65 C   75 seconds  /
#   Final Extension        65 C   5 minutes    1 cycle
#   Hold                    4 C   infinite
# ---------------------------------------------------------------------------
def sc_lib_pcr(num_cycles: int = 8) -> "Protocol":
    """Single-cell library enrichment PCR.

    Source: E6420 Section 1.11.3 cycling table. Two-step PCR (combined annealing/
    extension at 65 C). Default 8 cycles for 1-20 ng cDNA input (see header).
    """
    return Protocol(stages=[
        Stage(steps=[Step(temperature=[98.0], hold_seconds=30)], repeats=1),
        Stage(steps=[
            Step(temperature=[98.0], hold_seconds=10),
            Step(temperature=[65.0], hold_seconds=75),
        ], repeats=num_cycles),
        Stage(steps=[Step(temperature=[65.0], hold_seconds=5 * 60)], repeats=1),
        Stage(steps=[Step(temperature=[4.0], hold_seconds=INFINITE_HOLD_SECONDS)], repeats=1),
    ])


SC_CDNA_PCR = sc_cdna_pcr()
SC_LIB_PCR = sc_lib_pcr()


# ===========================================================================
# TIP-seq (targeted insertion of promoters sequencing). A DIFFERENT protocol: it
# combines CUT&Tag pA-Tn5 tagmentation with T7 RNA-polymerase linear amplification.
# The CUT&Tag/tagmentation/FACS front end (conA beads, antibody incubations, pA-Tn5,
# tagmentation, FACS) is operator/off-deck; these programs cover the automatable T7
# linear-amplification + library back half, which the paper calls a single-tube protocol.
#
# Source (public, peer-reviewed method, transcribed the same way as the rest of this file,
# every temperature/time/cycle copied and cited to the section where it appears):
#   Bartlett, Dileep, Handa, Ohkawa, Kimura, Henikoff, Gilbert. "High-throughput single-cell
#   epigenomic profiling by targeted insertion of promoters (TIP-seq)." J. Cell Biol. 2021,
#   220(12):e202103078. https://doi.org/10.1083/jcb.202103078 . Materials and methods,
#   "Bulk TIP-seq" (the linear-amp + library steps) and the PCR profile from "CUT&Tag".
#
# The thermal programs only. Reagent volumes and the liquid-handling map live in the STAR
# scripts under hamilton-star/starlab_live/tipseq/, not here.
#
# Two values are flagged as choices, not transcriptions:
#   - tip-ivt duration. The paper incubates T7 IVT for 16-19 h; default 17 h (pass ivt_hours).
#     This ties up the ODTC overnight; launch it detached on the Pi.
#   - tip-ivt / tip-rnaseh lid temperature. The paper uses an incubator/thermal cycler and does
#     not give a lid temperature for the 37 C steps. The ODTC must set a lid; 47 C is used (well
#     above the 37 C sample to limit condensation over a long hold, well under any bake risk).
#     Not transcribed. tip-pcr uses the CUT&Tag 8 C hold as written (not 4 C).
#
# Block-ceiling caution, same as the other PCR programs here: tip-pcr denatures at 98 C, 1 C
# under the ODTC 99 C block ceiling, so the block can graze it and log out-of-spec warnings.
# ===========================================================================

LID_C_TIP_GAPFILL = 105.0    # Taq gap-fill 72 C 3 min; standard heated lid.
LID_C_TIP_IVT = 47.0         # 37 C long hold; lid not given by the paper (choice, see header).
LID_C_TIP_RT_ANNEAL = 105.0  # random-hexamer anneal 70 C 3 min.
LID_C_TIP_RT = 105.0         # SMART MMLV RT.
LID_C_TIP_RNASEH = 47.0      # 37 C 20 min; lid not given (choice, see header).
LID_C_TIP_SS_ANNEAL = 105.0  # second-strand primer anneal 65 C 2 min.
LID_C_TIP_SS = 105.0         # second-strand synthesis 72 C 8 min (Taq).
LID_C_TIP_TAG = 105.0        # cDNA Tn5 fragmentation 55 C 6 min.
LID_C_TIP_PCR = 105.0        # NEBNext High-Fidelity 2X PCR; standard heated lid.

# Reaction volumes at the point each program runs (single reaction), from the pipetting steps.
VOL_UL_TIP_GAPFILL = 10.0    # 8 DNA+beads in water + 2 Taq 5X MM
VOL_UL_TIP_IVT = 16.3        # 10 gap-fill + 2 NTP + 2 T7 buffer + 2 T7 pol + 0.3 RNase inhibitor
VOL_UL_TIP_RT_ANNEAL = 11.5  # 9 purified RNA + 2.5 random hexamer
VOL_UL_TIP_RT = 20.0         # 11.5 + 4 first-strand buffer + 2 dNTP + 2 DTT + 0.5 MMLV
VOL_UL_TIP_RNASEH = 21.0     # 20 + 1 RNase H (1:10)
VOL_UL_TIP_SS_ANNEAL = 23.5  # 21 + 2.5 sss oligo
VOL_UL_TIP_SS = 29.4         # 23.5 + 5.9 Taq 5X MM
VOL_UL_TIP_TAG = 11.0        # 7 purified cDNA + 2 TAPS buffer + 2 Tn5 (ME-B)
VOL_UL_TIP_PCR = 40.0        # 16 purified DNA + 20 2X PCR MM + 2 index primer + 2 i7 index


# ---------------------------------------------------------------------------
# Bulk TIP-seq. Taq gap-fill of tagmented, purified gDNA (beads retained). Lid 105 C.
#   3 minutes at 72 C
#   Hold at 4 C
# ---------------------------------------------------------------------------
TIP_GAPFILL = Protocol(stages=[
    Stage(steps=[Step(temperature=[72.0], hold_seconds=3 * 60)], repeats=1),
    Stage(steps=[Step(temperature=[4.0], hold_seconds=INFINITE_HOLD_SECONDS)], repeats=1),
])

# ---------------------------------------------------------------------------
# Bulk TIP-seq. T7 in vitro transcription (HiScribe T7). Lid 47 C (choice, see header).
#   16-19 hours at 37 C  (default 17)
#   Hold at 4 C
# ---------------------------------------------------------------------------
def tip_ivt(ivt_hours: float = 17.0) -> "Protocol":
    """T7 IVT linear amplification. Source: Bulk TIP-seq, 37 C for 16-19 h; default 17.

    This is an overnight hold that ties up the ODTC. Launch it detached on the Pi.
    """
    return Protocol(stages=[
        Stage(steps=[Step(temperature=[37.0], hold_seconds=ivt_hours * 60 * 60)], repeats=1),
        Stage(steps=[Step(temperature=[4.0], hold_seconds=INFINITE_HOLD_SECONDS)], repeats=1),
    ])

# ---------------------------------------------------------------------------
# Bulk TIP-seq. Random-hexamer anneal before first-strand synthesis. Lid 105 C.
#   3 minutes at 70 C
#   Hold at 4 C  (the paper says "immediately placing on ice")
# ---------------------------------------------------------------------------
TIP_RT_ANNEAL = Protocol(stages=[
    Stage(steps=[Step(temperature=[70.0], hold_seconds=3 * 60)], repeats=1),
    Stage(steps=[Step(temperature=[4.0], hold_seconds=INFINITE_HOLD_SECONDS)], repeats=1),
])

# ---------------------------------------------------------------------------
# Bulk TIP-seq. First-strand synthesis (SMART MMLV Reverse Transcriptase). Lid 105 C.
#   10 minutes at 22 C
#   60 minutes at 42 C
#   10 minutes at 70 C
#   Hold at 4 C
# ---------------------------------------------------------------------------
TIP_RT = Protocol(stages=[
    Stage(steps=[Step(temperature=[22.0], hold_seconds=10 * 60)], repeats=1),
    Stage(steps=[Step(temperature=[42.0], hold_seconds=60 * 60)], repeats=1),
    Stage(steps=[Step(temperature=[70.0], hold_seconds=10 * 60)], repeats=1),
    Stage(steps=[Step(temperature=[4.0], hold_seconds=INFINITE_HOLD_SECONDS)], repeats=1),
])

# ---------------------------------------------------------------------------
# Bulk TIP-seq. RNase H digestion of cDNA-RNA hybrids. Lid 47 C (choice, see header).
#   20 minutes at 37 C
#   Hold at 4 C
# ---------------------------------------------------------------------------
TIP_RNASEH = Protocol(stages=[
    Stage(steps=[Step(temperature=[37.0], hold_seconds=20 * 60)], repeats=1),
    Stage(steps=[Step(temperature=[4.0], hold_seconds=INFINITE_HOLD_SECONDS)], repeats=1),
])

# ---------------------------------------------------------------------------
# Bulk TIP-seq. Second-strand primer anneal (sss oligo). Lid 105 C.
#   2 minutes at 65 C
#   Hold at 4 C  (the paper says "placing immediately on ice")
# ---------------------------------------------------------------------------
TIP_SS_ANNEAL = Protocol(stages=[
    Stage(steps=[Step(temperature=[65.0], hold_seconds=2 * 60)], repeats=1),
    Stage(steps=[Step(temperature=[4.0], hold_seconds=INFINITE_HOLD_SECONDS)], repeats=1),
])

# ---------------------------------------------------------------------------
# Bulk TIP-seq. Second-strand synthesis (Taq 5X Master Mix). Lid 105 C.
#   8 minutes at 72 C
#   Hold at 4 C  (the paper says "then cooling on ice")
# ---------------------------------------------------------------------------
TIP_SS = Protocol(stages=[
    Stage(steps=[Step(temperature=[72.0], hold_seconds=8 * 60)], repeats=1),
    Stage(steps=[Step(temperature=[4.0], hold_seconds=INFINITE_HOLD_SECONDS)], repeats=1),
])

# ---------------------------------------------------------------------------
# Bulk TIP-seq. cDNA fragmentation / 3' adapter tagging (Tn5, ME-B only). Lid 105 C.
#   6 minutes at 55 C
#   Hold at 4 C  (the paper says "briefly cooled on ice" before GuHCl)
# ---------------------------------------------------------------------------
TIP_TAG = Protocol(stages=[
    Stage(steps=[Step(temperature=[55.0], hold_seconds=6 * 60)], repeats=1),
    Stage(steps=[Step(temperature=[4.0], hold_seconds=INFINITE_HOLD_SECONDS)], repeats=1),
])

# ---------------------------------------------------------------------------
# TIP-seq PCR indexing (NEBNext High-Fidelity 2X). Profile from the CUT&Tag section. Lid 105 C.
#   Gap fill            72 C   5 minutes    1 cycle
#   Denaturation        98 C   30 seconds   1 cycle
#   Denaturation        98 C   10 seconds  \  > N cycles (bulk ~7-9, sciTIP 7-12; default 8)
#   Annealing           63 C   30 seconds  /
#   Final Extension     72 C   60 seconds   1 cycle
#   Hold                 8 C   infinite     (as written; the paper holds at 8 C, not 4 C)
# ---------------------------------------------------------------------------
def tip_pcr(num_cycles: int = 8) -> "Protocol":
    """TIP-seq library indexing PCR.

    Source: TIP-seq PCR ("optimal number of PCR cycles ~7-9", sciTIP 7-12); the cycling
    profile is the CUT&Tag program (72 C 5 min gap fill; 98 C 30 s; N x [98 C 10 s, 63 C 30 s];
    72 C 1 min; hold 8 C). Default 8 cycles. The 98 C denaturation grazes the 99 C ceiling.
    """
    return Protocol(stages=[
        Stage(steps=[Step(temperature=[72.0], hold_seconds=5 * 60)], repeats=1),
        Stage(steps=[Step(temperature=[98.0], hold_seconds=30)], repeats=1),
        Stage(steps=[
            Step(temperature=[98.0], hold_seconds=10),
            Step(temperature=[63.0], hold_seconds=30),
        ], repeats=num_cycles),
        Stage(steps=[Step(temperature=[72.0], hold_seconds=60)], repeats=1),
        Stage(steps=[Step(temperature=[8.0], hold_seconds=INFINITE_HOLD_SECONDS)], repeats=1),
    ])


TIP_IVT = tip_ivt()
TIP_PCR = tip_pcr()


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
    "emseq-shear": Program("emseq-shear", EMSEQ_SHEAR, LID_C_EMSEQ_SHEAR, VOL_UL_EMSEQ_SHEAR,
                           "NEB #M7634 UltraShear manual, Section 3.1.6 (coupled to E8015)"),
    "emseq-endprep": Program("emseq-endprep", EMSEQ_ENDPREP, LID_C_EMSEQ_ENDPREP, VOL_UL_EMSEQ_ENDPREP,
                             "NEB #M7634 UltraShear manual, Section 3.2.3 (coupled End Prep)"),
    "emseq-ligation": Program("emseq-ligation", EMSEQ_LIGATION, LID_C_EMSEQ_LIGATION, VOL_UL_EMSEQ_LIGATION,
                              "NEB #M7634 Section 3.3.3 / #E8015 Section 1.3.3, adaptor ligation"),
    "emseq-tet2": Program("emseq-tet2", EMSEQ_TET2, LID_C_EMSEQ_TET2, VOL_UL_EMSEQ_TET2,
                          "NEB #E8015 EM-seq v2 manual, Section 1.5.5, TET2 protection"),
    "emseq-tet2-stop": Program("emseq-tet2-stop", EMSEQ_TET2_STOP, LID_C_EMSEQ_TET2, VOL_UL_EMSEQ_TET2_STOP,
                               "NEB #E8015 EM-seq v2 manual, Section 1.5.7, stop incubation"),
    "emseq-denature": Program("emseq-denature", EMSEQ_DENATURE, LID_C_EMSEQ_DENATURE, VOL_UL_EMSEQ_DENATURE,
                              "NEB #E8015 EM-seq v2 manual, Section 1.7A.3, formamide denaturation"),
    "emseq-deaminate": Program("emseq-deaminate", EMSEQ_DEAMINATE, LID_C_EMSEQ_DEAMINATE, VOL_UL_EMSEQ_DEAMINATE,
                               "NEB #E8015 EM-seq v2 manual, Section 1.8.3, APOBEC deamination"),
    "emseq-pcr": Program("emseq-pcr", EMSEQ_PCR, LID_C_EMSEQ_PCR, VOL_UL_EMSEQ_PCR,
                         "NEB #E8015 EM-seq v2 manual, Section 1.9.3, library PCR"),
    "sc-anneal": Program("sc-anneal", SC_ANNEAL, LID_C_SC_ANNEAL, VOL_UL_SC_ANNEAL,
                         "NEB #E6420 Single Cell RNA manual, Section 1.3.3, primer annealing"),
    "sc-rt": Program("sc-rt", SC_RT, LID_C_SC_RT, VOL_UL_SC_RT,
                     "NEB #E6420 Single Cell RNA manual, Section 1.4.4, RT + template switching"),
    "sc-cdna-pcr": Program("sc-cdna-pcr", SC_CDNA_PCR, LID_C_SC_CDNA_PCR, VOL_UL_SC_CDNA_PCR,
                           "NEB #E6420 Single Cell RNA manual, Section 1.5.3, cDNA amplification"),
    "sc-fs": Program("sc-fs", SC_FS, LID_C_SC_FS, VOL_UL_SC_FS,
                     "NEB #E6420 Single Cell RNA manual, Section 1.8.5, fragmentation / end prep"),
    "sc-ligation": Program("sc-ligation", SC_LIGATION, LID_C_SC_LIGATION, VOL_UL_SC_LIGATION,
                           "NEB #E6420 Single Cell RNA manual, Section 1.9.5, adaptor ligation"),
    "sc-user": Program("sc-user", SC_USER, LID_C_SC_USER, VOL_UL_SC_USER,
                       "NEB #E6420 Single Cell RNA manual, Section 1.9.7, USER enzyme"),
    "sc-lib-pcr": Program("sc-lib-pcr", SC_LIB_PCR, LID_C_SC_LIB_PCR, VOL_UL_SC_LIB_PCR,
                          "NEB #E6420 Single Cell RNA manual, Section 1.11.3, library enrichment PCR"),
    "tip-gapfill": Program("tip-gapfill", TIP_GAPFILL, LID_C_TIP_GAPFILL, VOL_UL_TIP_GAPFILL,
                           "TIP-seq (JCB 2021, e202103078), Bulk TIP-seq, Taq gap-fill"),
    "tip-ivt": Program("tip-ivt", TIP_IVT, LID_C_TIP_IVT, VOL_UL_TIP_IVT,
                       "TIP-seq (JCB 2021, e202103078), Bulk TIP-seq, T7 IVT (16-19 h)"),
    "tip-rt-anneal": Program("tip-rt-anneal", TIP_RT_ANNEAL, LID_C_TIP_RT_ANNEAL, VOL_UL_TIP_RT_ANNEAL,
                             "TIP-seq (JCB 2021, e202103078), Bulk TIP-seq, random-hexamer anneal"),
    "tip-rt": Program("tip-rt", TIP_RT, LID_C_TIP_RT, VOL_UL_TIP_RT,
                      "TIP-seq (JCB 2021, e202103078), Bulk TIP-seq, SMART MMLV first-strand"),
    "tip-rnaseh": Program("tip-rnaseh", TIP_RNASEH, LID_C_TIP_RNASEH, VOL_UL_TIP_RNASEH,
                          "TIP-seq (JCB 2021, e202103078), Bulk TIP-seq, RNase H"),
    "tip-ss-anneal": Program("tip-ss-anneal", TIP_SS_ANNEAL, LID_C_TIP_SS_ANNEAL, VOL_UL_TIP_SS_ANNEAL,
                             "TIP-seq (JCB 2021, e202103078), Bulk TIP-seq, second-strand anneal"),
    "tip-ss": Program("tip-ss", TIP_SS, LID_C_TIP_SS, VOL_UL_TIP_SS,
                      "TIP-seq (JCB 2021, e202103078), Bulk TIP-seq, second-strand synthesis"),
    "tip-tag": Program("tip-tag", TIP_TAG, LID_C_TIP_TAG, VOL_UL_TIP_TAG,
                       "TIP-seq (JCB 2021, e202103078), Bulk TIP-seq, cDNA Tn5 fragmentation"),
    "tip-pcr": Program("tip-pcr", TIP_PCR, LID_C_TIP_PCR, VOL_UL_TIP_PCR,
                       "TIP-seq (JCB 2021, e202103078), library indexing PCR (CUT&Tag profile)"),
    "timecheck": Program("timecheck", TIMECHECK, LID_C_HARDWARE_EXERCISE, 20.0,
                         "hardware exercise, not biology", is_biology=False),
    "selftest": Program("selftest", SELFTEST, LID_C_HARDWARE_EXERCISE, 20.0,
                        "hardware exercise, not biology", is_biology=False),
}

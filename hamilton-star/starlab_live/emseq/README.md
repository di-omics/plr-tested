# EM-seq v2 (UltraShear-coupled), Hamilton STAR + Inheco ODTC

End-to-end liquid handling and thermocycling for NEBNext Enzymatic Methyl-seq v2 with
UltraShear enzymatic fragmentation upstream, single column, on the current 35/48 deck.

Status: **full physical empty-deck dry choreography passed on the Hamilton STAR on
2026-07-21**: 36 of 36 legs, all 11 reagent-add modes, all three cleanup presets, eight
ODTC round trips, and three magnet round trips. The plate self-returned to rail35 p0 and
the log had no command or USB fault. See [`qc/`](qc/) for the raw instrument log and
judgment record. No liquid or ODTC heat ran, so wet, thermal, and biological execution
remain unvalidated and blocked. The chatterbox simulations remain the compute-level
checks described below.

## What this automates

The coupled UltraShear + EM-seq v2 workflow, one 8-well column (A-H). The sample plate
(rail35 pos0) is the single plate that moves: to the ODTC nest for each thermal program,
to the magnet for each bead cleanup, and back. Reagents are added one per run from a
swap-source column (rail35 pos1), the same stepwise pattern as the confirmed whole-genome sequencing and
targeted PCR work in this repo.

Workflow order (this is the choreography in `run_emseq_odtc_1col_full_dry.py`):

1. DNA prep (off-deck): 0.1-200 ng gDNA + control DNAs made up to 26 uL in 1X TE.
2. Fragmentation: add UltraShear master mix, ODTC `emseq-shear` (37 C 30 min, 65 C 15 min).
3. End Prep: add coupled End Prep mix (M7634 DTT + End Prep enzyme), ODTC `emseq-endprep`.
4. Adaptor ligation: add adaptor, then ligation enhancer + master mix, ODTC `emseq-ligation`.
5. Cleanup 1 (1.1X SPRI).
6. TET2 protection: add TET2 mix, add diluted Fe(II), ODTC `emseq-tet2` (37 C 1 h); then add
   Stop reagent, ODTC `emseq-tet2-stop` (37 C 30 min).
7. Cleanup 2 (1.0X SPRI).
8. Denaturation: add formamide, ODTC `emseq-denature` (85 C 10 min).
9. Deamination: add APOBEC mix, ODTC `emseq-deaminate` (37 C 3 h).
10. Library PCR: add index primer, then Q5U master mix, ODTC `emseq-pcr`.
11. Cleanup 3 (0.8X SPRI). Final library eluate is 20 uL.

## Files

- `emseq_reagent_adds.py` - one reagent addition per `--mode`, swap-source into work col 1.
  Modes: `shear-mm`, `endprep-mm`, `adaptor`, `ligation-mm`, `tet2-mm`, `feii`, `stop`,
  `formamide`, `deaminate-mm`, `pcr-primer`, `pcr-mm`. `--mode deck` assigns only.
- `emseq_cleanup.py` - the three SPRI cleanups. `--cleanup {post-ligation,post-tet2,post-pcr}`
  selects the bead ratio and elution volume; `--mode all` runs the motion sequence.
- `run_emseq_odtc_1col_full_dry.py` - the full choreography (36 executed legs + ODTC notes).
  `--print` shows the plan, `--deck` initializes and prints every distinct real-STAR deck
  assignment (normal setup/homing, no protocol transfer), `--sim-lh` runs the
  liquid-handling legs on the chatterbox,
  and `--confirm RUN_EMSEQ_ODTC_FULL --labware-ack CELLTREAT_229195_WORK_SOURCE`
  runs the dry rehearsal on hardware.
- ODTC thermal programs live in `instrument-integrations/odtc/odtc_protocols.py`
  (`emseq-shear`, `emseq-endprep`, `emseq-ligation`, `emseq-tet2`, `emseq-tet2-stop`,
  `emseq-denature`, `emseq-deaminate`, `emseq-pcr`) and run via `05_odtc_run_protocol.py`.

## Deck (current 35/48 deck)

```
rail48 p0 (first slot) = p10 tips     p1 (second) = p50     p2 (third) = p300
rail35 p0 (first slot) = CellTreat 350 uL work plate (moves)
rail35 p1 (second slot) = CellTreat 350 uL reagent source (swap between legs)
rail35 p2 (third slot) = magnet       p3 (fourth slot) = 12-well reservoir
rail20 p1 (ODTC modeled target) = ODTC nest (empty, open to receive the plate)
```

Exact physical liquid-handling resources: both the moving work plate and stationary
source are `CellTreat_96_wellplate_350ul_Fb`; the reservoir is
`CellTreat_12_troughplate_15000ul_Vb`. This matches the current working Targeted PCR
playbook. Its subprocess iSWAP legs intentionally use the Cor 360 resource as a motion
command stand-in for the physical CellTreat plate; EM-seq reuses those exact legs. Do
not put a Cor plate at rail35 p0, and do not substitute either CellTreat plate.

Reservoir map (rail35 pos3): A1 beads, A2 ethanol wash 1, A3 ethanol wash 2, A4 elution
buffer, A12 waste.

## Reagent volumes (per reaction, single column)

All volumes are transcribed from the two NEB manuals, no rounding. The default path is the
> 10 ng input path (undiluted T4-BGT, elution option A). Control-DNA spike-in, the Fe(II)
1:1250 dilution, and (for <= 10 ng) the T4-BGT 1:10 dilution are off-deck operator prep.

| Step | Add | Tip | Reaction after |
|---|---|---|---|
| shear-mm | 18 uL (14 buffer + 4 UltraShear) | p50 | 44 uL |
| endprep-mm | 5 uL (2 DTT + 3 enzyme) | p10 | 49 uL |
| adaptor | 2.5 uL | p10 | 51.5 uL |
| ligation-mm | 31 uL (1 enhancer + 30 ligation MM) | p50 | 82.5 uL |
| cleanup 1 | 93 uL beads (1.1X), elute 29, keep 28 | p300/p50 | 28 uL |
| tet2-mm | 17 uL (10 buffer + 1 UDP-Glc + 1 DTT + 1 T4-BGT + 4 TET2) | p50 | 45 uL |
| feii | 5 uL diluted Fe(II) | p10 | 50 uL |
| stop | 1 uL | p10 | 51 uL |
| cleanup 2 | 50 uL beads (1.0X), elute 17, keep 16 | p300/p50 | 16 uL |
| formamide | 4 uL | p10 | 20 uL |
| deaminate-mm | 20 uL (14 water + 4 buffer + 1 albumin + 1 APOBEC) | p50 | 40 uL |
| pcr-primer | 5 uL UDI (per-well index) | p10 | 45 uL |
| pcr-mm | 45 uL Q5U MM | p50 | 90 uL |
| cleanup 3 | 72 uL beads (0.8X), elute 21, keep 20 | p300/p50 | 20 uL |

## Sourcing

- NEB #M7634 NEBNext UltraShear manual, Section 3 (UltraShear coupled with EM-seq v2).
  This is the coupled protocol and is NOT interchangeable with the standalone E8015
  protocol. The shear reaction and the modified coupled End Prep come from here.
- NEB #E8015 NEBNext Enzymatic Methyl-seq v2 manual (v1.3). TET2 protection, cleanups,
  denaturation, deamination, and the library PCR come from here.

Only functional parameters (volumes, temperatures, times, bead ratios) are transcribed,
each cited on the line where it is used in the code, the same way the whole-genome sequencing ODTC
programs cite the kit user guide.

## What "tested" means here (status)

"sim" means a device-free chatterbox run and proves command structure only. "physical
dry" means the empty-deck motion ran on the real STAR with an operator present; it proves
the recorded motion path completed, not wet accuracy, heat, timing, or chemistry.

ODTC thermal programs (`instrument-integrations/odtc`):

| What | Result |
|---|---|
| 8 emseq-* programs generate valid method XML, all temps in 4-99 C, lids <= 105 C | passed, sim (chatterbox + real XML generator) |
| emseq-pcr 8-cycle loop encodes GotoNumber 2 / LoopNumber 7 | passed, sim |
| Run any emseq-* program on the instrument at real temperatures | written, not yet run |

STAR liquid handling (`hamilton-star/starlab_live/emseq`):

| What | Result |
|---|---|
| All 11 reagent-add modes, `--mode deck` and `--dry` | passed, sim |
| All 3 SPRI cleanups, `--mode all --dry` | passed, sim |
| Full choreography liquid-handling legs, `--sim-lh` (14 legs, exit 0) | passed, sim |
| Full 36-leg choreography: 11 adds, 3 cleanups, 8 ODTC round trips, 3 magnet round trips | **passed, physical dry, 2026-07-21** ([raw evidence and boundaries](qc/)) |
| All 11 reagent adds and all 3 cleanup presets on the instrument | passed, physical dry inside the full choreography; no liquid present |
| iSWAP handoff into the ODTC nest for the EM-seq plate | passed across 8 physical dry round trips using the Targeted PCR geometry |
| Any wet reagent add or cleanup on the instrument | written, not yet run |

Known gaps that MUST be closed on hardware before trusting a real run:

- Source and destination plate models and heights now follow the working Targeted PCR logic.
  The p50 path is source 0.0 mm / destination 1.5 mm; Targeted PCR raised the destination from
  0.5 mm after the lower value crushed tips. The proven p10 path remains source 0.0 mm /
  destination 0.5 mm. Several EM-seq adds enter a much fuller well (pcr-mm 45 uL into
  45 uL; ligation-mm 31 uL into 51.5 uL), so submergence, splash, and withdrawal still
  need stepwise dye/gravimetric tuning before a wet run.
- No on-deck mixing. The manual asks for 10x pipette mixing at most steps; these scripts
  add and blow out only. Mixing is an operator step until tuned.
- SPRI cleanup does not model the final "transfer clear eluate off the beads to a fresh
  column" step, or the RT bead incubation and air-dry timings. Those are operator/off-deck.
- The inherited iSWAP-into-ODTC geometry completed eight dry round trips in this workflow,
  but the ODTC child-location model still says `ODTC_CHILD_LOCATION_IS_MEASURED = False`.
  No EM-seq thermal program or heated-lid behavior ran during the dry rehearsal; the
  modeled coordinate, heat, hold, and cool-down still require separate qualification.

## Controls and acceptance criteria

Controls. The EM-seq chemistry has built-in conversion controls: unmethylated lambda DNA
and CpG-methylated pUC19 are spiked into every sample at DNA prep (M7634 Section 3.1.1,
dilution by input per the table). They report deamination efficiency directly from the
sequencing data. For the automation itself, reserve at least one column well as a
no-template control (control DNAs and reagents, no sample gDNA) to catch cross-well
carryover; single-column runs can dedicate well H.

Acceptance criteria. None of this is met yet; these are the bars a real run must clear
before any leg is marked validated, in the repo's usual sense.

- Liquid handling (per leg, on hardware): the dispense lands in-well with no splash or
  climbing, tips leave clean, and delivered volume is within tolerance by gravimetric or
  dye check. The high-volume adds (pcr-mm 45 uL, ligation-mm 31 uL) and every SPRI step
  need their own dye/gravimetric confirmation, not just a dry motion pass.
- SPRI cleanups: elution recovers the expected volume (28 / 16 / 20 uL kept) with no bead
  carryover into the eluate (carryover degrades deamination and sequencing).
- Thermocycling: each ODTC program holds every setpoint within about +/- 0.3 C (the bar
  the ampseq-pcr1 run met), and the PCR completes despite the 98 C / 99 C-ceiling warnings.
- End to end: conversion controls show high deamination of unmethylated lambda and
  protection of methylated pUC19; the final library has the expected size distribution
  (420-620 bp) and yield on a TapeStation/Bioanalyzer; the no-template control is clean.

## Tip handling defaults

Reagent adds and the full choreography follow the repo convention: default `--mode deck`
(no motion), an explicit mode is required to move, and `--dry` runs the chatterbox. The
cleanup script discards tips by default (it handles beads and ethanol; carryover is a
hazard); `--return-tips` is for dry observation only. A runtime guard rejects any add
whose liquid volume would exceed the tip (blowout is trailing air, not summed against it).

## Running

Scripts execute on the Pi wired to the instruments, via each tree's `run_on_pi.sh`.

```bash
# review first
python run_emseq_odtc_1col_full_dry.py --print

# on the Pi: initialize every deck/geometry view; setup/homing, no protocol transfer
./hamilton-star/run_on_pi.sh starlab_live/emseq/run_emseq_odtc_1col_full_dry.py --deck

# exercise the liquid-handling legs locally, no hardware
python run_emseq_odtc_1col_full_dry.py --sim-lh

# motion-only dry rehearsal on the real STAR; human present at the E-stop
./hamilton-star/run_on_pi.sh starlab_live/emseq/run_emseq_odtc_1col_full_dry.py \
  --confirm RUN_EMSEQ_ODTC_FULL \
  --labware-ack CELLTREAT_229195_WORK_SOURCE

# an ODTC program (this heats; human at the E-stop)
./instrument-integrations/run_on_pi.sh odtc/05_odtc_run_protocol.py --program emseq-shear --dry
```

The reagent PCR cycle count is input-dependent (E8015: 200 ng 4-5, 50 ng 5-6, 10 ng 8,
1 ng 11, 0.1 ng 14). `emseq-pcr` defaults to 8; build `emseq_pcr(num_cycles=...)` to change.

## Safety

Same rules as the rest of this repo. Assume a script drives real hardware unless it names
an exception (`--mode deck`, `--deck`, `--dry`, `--sim-lh`, `--print`). Never run unattended, a
person watches with a hand near the E-stop. Run `--mode deck` first. The full choreography
moves the arm through 8 ODTC round trips and 3 magnet round trips and is gated behind
`--confirm RUN_EMSEQ_ODTC_FULL`. The ODTC block reaches 98 C on the PCR (1 C under the
99 C ceiling, expect "out of specification" warnings, not faults) and stays hot after a
program ends. Only one process may drive an instrument at a time.

## Research use only

Automates published NEBNext kit protocols (public NEB manuals E8015 and M7634). Not a
product, not validated for diagnostic use.

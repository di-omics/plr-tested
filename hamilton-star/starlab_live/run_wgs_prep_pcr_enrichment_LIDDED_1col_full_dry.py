#!/usr/bin/env python3
"""Guarded full WGS preparation/HHS then PCR enrichment/ODTC one-column dry runner.

This is the release-candidate composition for the next attended bench run. It
does not copy or reinterpret any liquid or iSWAP geometry. Instead, it executes
the two current single-home runners in their proven order:

  1. WGS preparation dry lysis/reaction, HHS plate move, lid on/off, plate return.
  2. PCR enrichment dry PCR1/cleanup/PCR2, ODTC lid cycles, magnet round trip.

Each child owns one LiquidHandler session, homes once, and preserves its own
geometry/model/version locks. The handoff state is explicit: after WGS preparation, the work
plate is back at rail35 pos0, the lid is back at rail35 pos4, and HHS is empty;
that is the exact start state required by PCR enrichment. The first composed physical
release is deliberately NOT continuous across that boundary: the operator must
inspect the physical deck and type the exact interphase token before PCR enrichment can
spawn. A child exit code or resource model cannot prove that a plate/lid is
physically seated.

DRY ENGINEERING ONLY:

* empty sacrificial labware; no samples or reagents;
* tips are returned, never discarded;
* HHS is not heated or shaken;
* ODTC is not connected, initialized, closed, heated, or cycled;
* sample count means biological samples only; no NTCs or controls are added;
* the robot still actuates all eight channels in column 1 for sample counts 1-8.

This is not a wet whole-genome sequencing protocol. The wet protocol still requires biology
holds, source changes, fresh/discard-tip accounting, bead dwell/dry timing, and
validated HHS/ODTC control. Those are deliberately not hidden behind a flag.

Run plan and both child deck previews before any physical release. STAR mode
requires the exact intent, full-deck, and labware tokens below. A trained human
must watch the complete run with the E-stop immediately reachable.
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Sequence


ROOT = Path(__file__).resolve().parent
WGS_PREP_SCRIPT = ROOT / "run_wgs_prep_pipetting_hhs_LIDDED_1col_singlehome_dry.py"
PCR_ENRICHMENT_SCRIPT = ROOT / "run_pcr_enrichment_odtc_LIDDED_1col_full_v2_singlehome_dry.py"

CONFIRM_TOKEN = "RUN_WGS_PREP_PCR_ENRICHMENT_LIDDED_1COL_FULL_DRY"
DECK_ACK = (
    "R48_P10_P50_P300_R35_WORK_SOURCE_MAGNET_TROUGH_LID_"
    "R27_HHS_EMPTY_R20_ODTC_EMPTY_OPEN"
)
LABWARE_ACK = "CELLTREAT_229195_WORK_SOURCE_CORNING_3603_LID"
INTERPHASE_ACK = (
    "WGS_PREP_FINAL_PLATE_R35P0_LID_R35P4_HHS_EMPTY_"
    "TIPS_CLEAR_ISWAP_PARKED"
)

WGS_PREP_CONFIRM_TOKEN = "RUN_WGS_PREP_HHS_LIDDED_FULL_DRY"
WGS_PREP_DECK_ACK = "FULL_DRY_DECK_LID_FLAT_HHS_EMPTY"
WGS_PREP_LABWARE_ACK = "CELLTREAT_229195_WITH_CORNING_3603_LID"

PCR_ENRICHMENT_CONFIRM_TOKEN = "RUN_PCR_ENRICHMENT_ODTC_LIDDED_SINGLEHOME_DRY"
PCR_ENRICHMENT_DECK_ACK = (
    "R48_P10_P50_P300_R35_WORK_SOURCE_MAGNET_TROUGH_LID_"
    "R20_ODTC_EMPTY_OPEN"
)
PCR_ENRICHMENT_LABWARE_ACK = "CELLTREAT_229195_WORK_SOURCE_CORNING_3603_LID"

MIN_SAMPLE_COUNT = 1
MAX_SAMPLE_COUNT = 8


def validate_sample_count(sample_count: int) -> None:
    if not MIN_SAMPLE_COUNT <= sample_count <= MAX_SAMPLE_COUNT:
        raise RuntimeError(
            "No released one-column dry plan for sample_count={}. "
            "Use 1..8; counts above 8 require a separately validated multi-column "
            "runner.".format(sample_count)
        )


def validate_release(args: argparse.Namespace) -> None:
    validate_sample_count(args.sample_count)
    if args.mode != "star":
        return
    if args.confirm != CONFIRM_TOKEN:
        raise RuntimeError(
            "Refusing physical full dry run. Add: --confirm {}".format(CONFIRM_TOKEN)
        )
    if args.acknowledge != DECK_ACK:
        raise RuntimeError(
            "Refusing physical full dry run until the complete combined deck is "
            "confirmed. Add: --acknowledge {}".format(DECK_ACK)
        )
    if args.labware_ack != LABWARE_ACK:
        raise RuntimeError(
            "Refusing physical full dry run until the exact CellTreat/Corning "
            "labware is confirmed. Add: --labware-ack {}".format(LABWARE_ACK)
        )


def preflight_files() -> None:
    missing = [path for path in (WGS_PREP_SCRIPT, PCR_ENRICHMENT_SCRIPT) if not path.is_file()]
    if missing:
        raise RuntimeError(
            "Required child runner(s) missing: {}".format(
                ", ".join(str(path) for path in missing)
            )
        )


def child_command(script: Path, mode: str) -> list[str]:
    base = [sys.executable, str(script), "--mode", mode]
    if mode != "star":
        return base
    if script == WGS_PREP_SCRIPT:
        return base + [
            "--confirm",
            WGS_PREP_CONFIRM_TOKEN,
            "--acknowledge",
            WGS_PREP_DECK_ACK,
            "--labware-ack",
            WGS_PREP_LABWARE_ACK,
        ]
    if script == PCR_ENRICHMENT_SCRIPT:
        return base + [
            "--confirm",
            PCR_ENRICHMENT_CONFIRM_TOKEN,
            "--acknowledge",
            PCR_ENRICHMENT_DECK_ACK,
            "--labware-ack",
            PCR_ENRICHMENT_LABWARE_ACK,
        ]
    raise RuntimeError("Unknown child runner: {}".format(script))


def banner(label: str) -> None:
    print("")
    print("=" * 92)
    print(label)
    print("=" * 92, flush=True)


def run_command(label: str, command: Sequence[str]) -> None:
    banner(label)
    print(shlex.join(command), flush=True)
    print("", flush=True)
    subprocess.run(list(command), cwd=str(ROOT), check=True)


def require_interphase_reconciliation(input_fn=None) -> None:
    """Require fresh human evidence after WGS preparation, never a pre-supplied CLI flag."""
    if input_fn is None:
        input_fn = input
    banner("MANDATORY PHYSICAL HANDOFF: reconcile WGS preparation final state before PCR enrichment")
    print("Confirm with your eyes:")
    print("  work plate square at rail35 pos0")
    print("  lid flat at rail35 pos4")
    print("  HHS rail27 pos2 empty")
    print("  tips/channels and iSWAP clear; iSWAP parked")
    print("  magnet rail35 pos2 and ODTC rail20 pos1 still empty/open")
    print("  every PCR enrichment iSWAP path is clear around the installed HHS")
    print("")
    print("Type this exact token after inspection:")
    print(INTERPHASE_ACK, flush=True)
    try:
        observed = input_fn("interphase> ").strip()
    except EOFError as exc:
        raise RuntimeError(
            "Interphase physical reconciliation could not be read; PCR enrichment was not started."
        ) from exc
    if observed != INTERPHASE_ACK:
        raise RuntimeError(
            "Interphase physical reconciliation did not match; PCR enrichment was not started."
        )


def run_children(mode: str, input_fn=None) -> None:
    run_command(
        "PHASE 1/2: WGS preparation + HHS lidded one-column dry sequence",
        child_command(WGS_PREP_SCRIPT, mode),
    )
    if mode == "star":
        require_interphase_reconciliation(input_fn=input_fn)
    run_command(
        "PHASE 2/2: PCR enrichment + ODTC/magnet lidded one-column dry sequence",
        child_command(PCR_ENRICHMENT_SCRIPT, mode),
    )


def run_star_preflight() -> None:
    """Run both connection-free deck/model checks before the first STAR backend."""
    banner("STATIC PREFLIGHT: both child deck/model locks, no hardware connection")
    for script in (WGS_PREP_SCRIPT, PCR_ENRICHMENT_SCRIPT):
        command = child_command(script, "deck")
        print(shlex.join(command), flush=True)
        subprocess.run(command, cwd=str(ROOT), check=True)


def print_deck() -> None:
    print("COMBINED WGS preparation + PCR ENRICHMENT DRY START DECK")
    print("  rail48 pos0  p10 filter tips; columns 1 and 2 intact")
    print("  rail48 pos1  p50 filter tips; columns 1 and 2 intact")
    print("  rail48 pos2  p300 filter tips; column 1 intact")
    print("  rail35 pos0  bare empty CellTreat 229195 work plate")
    print("  rail35 pos1  empty CellTreat source plate")
    print("                WGS preparation dry reads columns 1 and 3; PCR enrichment dry reads column 1")
    print("  rail35 pos2  correct magnet installed; landing position empty")
    print("  rail35 pos3  empty 12-well trough; A1/A2/A3/A4/A12 modeled")
    print("  rail35 pos4  Corning 3603 park plate with the correct lid seated flat")
    print("  rail27 pos2  HHS installed, empty, open, and idle")
    print("  rail20 pos1  ODTC nest empty, open, cool, and idle")
    print("  iSWAP empty; channels untipped; all carriers locked; paths clear")
    print("  operator at the deck with the E-stop immediately reachable")
    print("  NOTE: each child models its active subset; the human gate confirms this full")
    print("        physical union and re-checks the WGS preparation-to-PCR enrichment handoff in place")


def print_plan(sample_count: int) -> None:
    validate_sample_count(sample_count)
    blanks = MAX_SAMPLE_COUNT - sample_count
    print("FULL WGS preparation/HHS -> PCR ENRICHMENT/ODTC ONE-COLUMN DRY PLAN")
    print("  requested sample positions: {}".format(sample_count))
    print("  count policy: biological samples only; no NTC or control wells")
    print("  robot actuation: one full 8-well column (A1:H1)")
    print("  explicit blanks in that column: {}".format(blanks))
    print("  phase 1: six-operation WGS preparation/HHS single-home dry sequence")
    print("  phase 2: thirteen-leg PCR enrichment/ODTC/magnet single-home dry sequence")
    print("  mandatory handoff: visually reconcile phase 1 before phase 2 can spawn")
    print("  phase 1 target: plate r35p0; lid r35p4; HHS empty; iSWAP parked")
    print("  final target: plate r35p0; lid r35p4; HHS/magnet/ODTC empty")
    print("  no HHS or ODTC program; no samples/reagents; tips returned")
    print("  physical confirm: --confirm {}".format(CONFIRM_TOKEN))
    print("  deck acknowledgement: --acknowledge {}".format(DECK_ACK))
    print("  labware acknowledgement: --labware-ack {}".format(LABWARE_ACK))
    print("")
    print_deck()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Guarded WGS preparation/HHS then PCR enrichment/ODTC one-column dry release candidate."
        )
    )
    parser.add_argument(
        "--mode",
        choices=("plan", "deck", "chatterbox", "star"),
        default="plan",
        help=(
            "plan is inert; deck runs both connection-free deck previews; chatterbox "
            "simulates both phases; star moves the physical instrument"
        ),
    )
    parser.add_argument("--sample-count", type=int, default=8)
    parser.add_argument("--confirm", default="")
    parser.add_argument("--acknowledge", default="")
    parser.add_argument("--labware-ack", default="")
    return parser


def main(argv: Iterable[str] | None = None, input_fn=None) -> None:
    args = build_parser().parse_args(argv)
    validate_release(args)
    preflight_files()

    if args.mode == "plan":
        print_plan(args.sample_count)
        return
    if args.mode == "deck":
        print("DECK MODE: child resource trees only; no backend, setup, home, or motion.")
        print_deck()
        run_children("deck")
        return
    if args.mode == "chatterbox":
        print("CHATTERBOX MODE: no hardware connection or motion.")
        print_plan(args.sample_count)
        run_children("chatterbox")
        print("")
        print("SUCCESS: both dry phases completed in Chatterbox.")
        return

    print("PHYSICAL STAR MODE: attended two-phase dry engineering run.")
    print("Mandatory visual handoff between phases. One driver; hand at E-stop throughout.")
    print_plan(args.sample_count)
    run_star_preflight()
    run_children("star", input_fn=input_fn)
    print("")
    print("=" * 92)
    print("SUCCESS: full WGS preparation/HHS -> PCR enrichment/ODTC one-column dry sequence completed.")
    print("Reconcile physical final state before recording the run as passed.")
    print("=" * 92)


if __name__ == "__main__":
    main()

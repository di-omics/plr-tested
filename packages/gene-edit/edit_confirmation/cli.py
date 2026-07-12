"""
cli.py - the operator entrypoint.

    edit-confirm run  <manifest> [--out DIR] [--hardware] [--poor-deck]
    edit-confirm plan <manifest>
    edit-confirm demo [--out DIR]

`run` executes the flow and writes a run folder: the dossier (HTML), the machine outcome
(JSON), and the sequencing sample sheet (CSV). `plan` validates a manifest and prints the
resolved plan and the acceptance criteria without touching anything. `demo` runs the
bundled example in simulation, which is the fastest way to see the whole thing work.

Also runnable as `python -m edit_confirmation ...`.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from typing import Optional

from .config import RunMode
from .doctor import Status, format_report, run_doctor
from .manifest import ManifestError, load_run
from .orchestrator import RunOutcome, RunStatus, run
from .reporting.report import render_dossier
from .simulation import POORLY_TUNED_DECK
from .version import __version__

_EXIT = {RunStatus.COMPLETED: 0, RunStatus.STOPPED: 2, RunStatus.AWAITING_DATA: 3}


def _now() -> str:
    return datetime.datetime.now().replace(microsecond=0).isoformat()


def _write_run(outcome: RunOutcome, out_dir: str) -> str:
    run_dir = os.path.join(out_dir, outcome.config.run_id)
    os.makedirs(run_dir, exist_ok=True)

    dossier_path = os.path.join(run_dir, "dossier.html")
    with open(dossier_path, "w", encoding="utf-8") as fh:
        fh.write(render_dossier(outcome))

    with open(os.path.join(run_dir, "outcome.json"), "w", encoding="utf-8") as fh:
        json.dump(outcome.to_dict(), fh, indent=2)

    # Sample sheet, if the run reached handoff.
    for st in outcome.stages:
        csv = st.data.get("samplesheet_csv")
        if csv:
            with open(os.path.join(run_dir, "samplesheet.csv"), "w", encoding="utf-8") as fh:
                fh.write(csv)
    return run_dir


def _print_summary(outcome: RunOutcome) -> None:
    print(f"run {outcome.config.run_id}: {outcome.status.value.upper()}  ({outcome.message})")
    for st in outcome.stages:
        gate = ""
        if st.gate:
            gate = f"  gate={st.gate.decision.value}"
            drop = st.gate.dropped_sample_ids()
            if drop:
                gate += f"  dropped={','.join(drop)}"
        print(f"  [{st.status.value:9}] {st.title}{gate}")
    if outcome.guard_blocking:
        print("  provenance blocking a hardware run:")
        for b in outcome.guard_blocking:
            print(f"    - {b}")
    print(f"  survivors: {', '.join(outcome.final_active_sample_ids) or 'none'}")


def cmd_run(args) -> int:
    try:
        cfg = load_run(args.manifest, output_dir=args.out)
    except ManifestError as exc:
        print(f"manifest error: {exc}", file=sys.stderr)
        return 1
    if args.hardware:
        cfg.mode = RunMode.HARDWARE
    deck = POORLY_TUNED_DECK if args.poor_deck else None
    outcome = run(cfg, timestamp=_now(), deck_quality=deck)
    run_dir = _write_run(outcome, args.out)
    _print_summary(outcome)
    print(f"  wrote {run_dir}/dossier.html, outcome.json"
          + (", samplesheet.csv" if os.path.exists(os.path.join(run_dir, 'samplesheet.csv')) else ""))
    return _EXIT[outcome.status]


def cmd_plan(args) -> int:
    try:
        cfg = load_run(args.manifest)
    except ManifestError as exc:
        print(f"manifest error: {exc}", file=sys.stderr)
        return 1
    ac = cfg.acceptance
    print(f"run_id     : {cfg.run_id}")
    print(f"operator   : {cfg.operator}")
    print(f"mode       : {cfg.mode.value}")
    print(f"edit_type  : {cfg.edit_type.value}")
    print(f"locus      : {cfg.locus.name}  amplicon {cfg.locus.amplicon_bp} bp"
          + (f"  anneal {cfg.locus.pcr1_anneal_c} C" if cfg.locus.pcr1_anneal_c else ""))
    print(f"deck       : {cfg.deck.name}")
    print(f"pcr2_cycles: {cfg.pcr2_cycles}")
    print("samples    :")
    for s in cfg.samples:
        print(f"  - {s.id:14} {s.well:4} {s.sample_type.value}")
    print("acceptance criteria:")
    print(f"  Gate 0 liquid-handling CV     <= {ac.lh_cv_max_percent} %  "
          f"over {ac.lh_qualified_volumes_ul} uL")
    print(f"  standard curve R-squared      >= {ac.curve_r2_min}")
    print(f"  Gate 1 post-PTA yield         >= {ac.pta_yield_min_ng} ng  "
          f"(uniformity CV <= {ac.pta_uniformity_cv_max_percent} %)")
    print(f"  Gate 2 post-ampseq conc       {ac.ampseq_conc_min_ng_per_ul} to "
          f"{ac.ampseq_conc_max_ng_per_ul} ng/uL")
    return 0


def cmd_doctor(args) -> int:
    checks = run_doctor(hardware=args.hardware)
    if args.json:
        print(json.dumps([c.to_dict() for c in checks], indent=2))
    else:
        print(format_report(checks, hardware=args.hardware))
    return 0 if all(c.status is not Status.MISSING for c in checks) else 4


def cmd_demo(args) -> int:
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    manifest = os.path.join(here, "configs", "example_run.yaml")
    if not os.path.exists(manifest):
        manifest = os.path.join(here, "configs", "example_run.json")
    args.manifest = manifest
    args.hardware = False
    args.poor_deck = False
    print(f"demo manifest: {manifest}")
    return cmd_run(args)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="edit-confirm",
                                description="QC-gated PTA + amplicon-seq for gene-edit confirmation")
    p.add_argument("--version", action="version", version=f"edit-confirm {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run a manifest and write the dossier")
    r.add_argument("manifest")
    r.add_argument("--out", default="runs", help="output directory (default: runs)")
    r.add_argument("--hardware", action="store_true", help="force hardware mode")
    r.add_argument("--poor-deck", action="store_true",
                   help="simulation only: model a poorly tuned deck to see Gate 0 stop")
    r.set_defaults(func=cmd_run)

    pl = sub.add_parser("plan", help="validate a manifest and print the resolved plan")
    pl.add_argument("manifest")
    pl.set_defaults(func=cmd_plan)

    d = sub.add_parser("demo", help="run the bundled example in simulation")
    d.add_argument("--out", default="runs", help="output directory (default: runs)")
    d.set_defaults(func=cmd_demo)

    doc = sub.add_parser("doctor", help="check whether this lab can run it, and what is missing")
    doc.add_argument("--hardware", action="store_true",
                     help="also check the hardware tier (PyLabRobot fork, instrument addresses, calibration)")
    doc.add_argument("--json", action="store_true", help="machine-readable output")
    doc.set_defaults(func=cmd_doctor)
    return p


def main(argv: Optional[list] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

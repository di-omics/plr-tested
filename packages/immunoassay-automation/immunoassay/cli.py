"""
cli.py - the operator entrypoint.

    immunoassay run    <manifest> [--out DIR] [--hardware]
                              [--poor-washer] [--high-background] [--dead-cells]
    immunoassay plan   <manifest>
    immunoassay demo   [--out DIR]
    immunoassay doctor [--hardware] [--json]

`run` executes the flow and writes a run folder: the dossier (HTML), the machine outcome
(JSON), and the results sheet (CSV). `plan` validates a manifest and prints the resolved plate
layout and acceptance criteria without touching anything. `demo` runs the bundled example in
simulation, the fastest way to see the whole thing work. The three simulation flags force a
failure scenario so you can watch a gate do its job: a poorly qualified washer stops Gate 0,
high background or dead cells void the plate at Gate 2.

Also runnable as `python -m immunoassay ...`.
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
from .simulation import DEAD_CELLS_PLATE, GOOD_PLATE, HIGH_BACKGROUND_PLATE, POOR_WASHER, WELL_TUNED_WASHER
from .version import __version__

_EXIT = {RunStatus.COMPLETED: 0, RunStatus.STOPPED: 2, RunStatus.AWAITING_DATA: 3}


def _now() -> str:
    return datetime.datetime.now().replace(microsecond=0).isoformat()


def _write_run(outcome: RunOutcome, out_dir: str) -> str:
    run_dir = os.path.join(out_dir, outcome.config.run_id)
    os.makedirs(run_dir, exist_ok=True)

    with open(os.path.join(run_dir, "dossier.html"), "w", encoding="utf-8") as fh:
        fh.write(render_dossier(outcome))
    with open(os.path.join(run_dir, "outcome.json"), "w", encoding="utf-8") as fh:
        json.dump(outcome.to_dict(), fh, indent=2)
    for st in outcome.stages:
        csv = st.data.get("results_csv")
        if csv:
            with open(os.path.join(run_dir, "results.csv"), "w", encoding="utf-8") as fh:
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


def cmd_run(args) -> int:
    try:
        cfg = load_run(args.manifest, output_dir=args.out)
    except ManifestError as exc:
        print(f"manifest error: {exc}", file=sys.stderr)
        return 1
    if args.hardware:
        cfg.mode = RunMode.HARDWARE

    washer = POOR_WASHER if args.poor_washer else WELL_TUNED_WASHER
    biology = GOOD_PLATE
    if args.high_background:
        biology = HIGH_BACKGROUND_PLATE
    if args.dead_cells:
        biology = DEAD_CELLS_PLATE

    outcome = run(cfg, timestamp=_now(), washer_quality=washer, biology=biology)
    run_dir = _write_run(outcome, args.out)
    _print_summary(outcome)
    print(f"  wrote {run_dir}/dossier.html, outcome.json"
          + (", results.csv" if os.path.exists(os.path.join(run_dir, 'results.csv')) else ""))
    return _EXIT[outcome.status]


def cmd_plan(args) -> int:
    try:
        cfg = load_run(args.manifest)
    except ManifestError as exc:
        print(f"manifest error: {exc}", file=sys.stderr)
        return 1
    ac = cfg.acceptance
    print(f"run_id   : {cfg.run_id}")
    print(f"operator : {cfg.operator}")
    print(f"mode     : {cfg.mode.value}")
    print(f"cytokine : {cfg.cytokine}    precoated: {cfg.precoated_plate}")
    print(f"site     : {cfg.site.name}  cells/well {cfg.site.cells_per_well}  "
          f"wash {cfg.site.wash_cycles}x{cfg.site.wash_volume_ul}uL")
    groups = cfg.plate.test_groups()
    print(f"plate    : {len(cfg.plate.wells)} wells, {len(groups)} test antigen(s), "
          f"{len(cfg.plate.positive_wells())} pos-ctrl, {len(cfg.plate.negative_wells())} neg-ctrl, "
          f"{len(cfg.plate.blank_wells())} blank")
    for antigen, wells in groups.items():
        print(f"  - {antigen:16} {' '.join(w.address for w in wells)}")
    print("acceptance criteria:")
    print(f"  Gate 0 dispense CV        <= {ac.lh_cv_max_percent} %  over {ac.lh_qualified_volumes_ul} uL")
    print(f"  Gate 0 aspiration residual<= {ac.residual_volume_max_ul} uL")
    print(f"  Gate 1 pre-wet CV         <= {ac.prewet_cv_max_percent} %")
    print(f"  Gate 2 positive control   >= {ac.pos_ctrl_min_sfu} SFU")
    print(f"  Gate 2 background         <= {ac.neg_ctrl_background_max_sfu} SFU")
    print(f"  Gate 2 replicate CV       <= {ac.replicate_cv_max_percent} %")
    print(f"  response call             net >= {ac.response_min_net_sfu} SFU and "
          f"SI >= {ac.response_min_stimulation_index}")
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
    args.poor_washer = args.high_background = args.dead_cells = False
    print(f"demo manifest: {manifest}")
    return cmd_run(args)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="immunoassay",
                                description="QC-gated ELISpot automation across a washer, "
                                            "liquid handler, and spot imager")
    p.add_argument("--version", action="version", version=f"immunoassay {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run a manifest and write the dossier")
    r.add_argument("manifest")
    r.add_argument("--out", default="runs", help="output directory (default: runs)")
    r.add_argument("--hardware", action="store_true", help="force hardware mode")
    r.add_argument("--poor-washer", action="store_true",
                   help="simulation only: model a poorly qualified washer to see Gate 0 stop")
    r.add_argument("--high-background", action="store_true",
                   help="simulation only: model high background to see Gate 2 void the plate")
    r.add_argument("--dead-cells", action="store_true",
                   help="simulation only: model a failed positive control to see Gate 2 void the plate")
    r.set_defaults(func=cmd_run)

    pl = sub.add_parser("plan", help="validate a manifest and print the resolved plan")
    pl.add_argument("manifest")
    pl.set_defaults(func=cmd_plan)

    d = sub.add_parser("demo", help="run the bundled example in simulation")
    d.add_argument("--out", default="runs", help="output directory (default: runs)")
    d.set_defaults(func=cmd_demo)

    doc = sub.add_parser("doctor", help="check whether this lab can run it, and what is missing")
    doc.add_argument("--hardware", action="store_true",
                     help="also check the hardware tier (PyLabRobot, integrations, calibration)")
    doc.add_argument("--json", action="store_true", help="machine-readable output")
    doc.set_defaults(func=cmd_doctor)
    return p


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

"""Command-line interface: doctor, plan, demo, and run."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from .doctor import format_report, run_doctor
from .manifest import ManifestError, load_run
from .orchestrator import RunStatus, run
from .protocol import build_protocol
from .provenance import blocking, protocol_values
from .reporting import write_artifacts


def _metrics(path: Optional[str]) -> Optional[Dict[str, Any]]:
    if not path:
        return None
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ManifestError("metrics file must contain a JSON mapping")
    return data


def _print_plan(config) -> None:
    print(f"methylation-sequencing plan: {config.run_id}")
    print(
        f"profile={config.profile_kind.value}  "
        f"method={config.method.get('method_name', 'operator-configured')}  "
        f"samples={len(config.samples)}"
    )
    print("")
    for step in build_protocol(config):
        after = "" if step.reaction_after_ul is None else f" -> {step.reaction_after_ul:g} uL"
        print(f"{step.number:>2}. {step.name} [{step.operation}]{after}")
        if step.note:
            print(f"    {step.note}")
    blockers = blocking(protocol_values(config))
    print("")
    print(f"hardware readiness: BLOCKED ({len(blockers)} unresolved qualification item(s))")
    for item in blockers:
        print(f"  - {item.name}: {item.source}")


def _execute(manifest: str, metrics_path: Optional[str], output: str) -> int:
    config = load_run(manifest, output_dir=output)
    timestamp = datetime.now(timezone.utc).isoformat()
    outcome = run(config, metrics=_metrics(metrics_path), timestamp=timestamp)
    run_dir = write_artifacts(outcome, output)
    print(f"{outcome.status.value}: {outcome.message}")
    print(f"artifacts: {run_dir}")
    return {RunStatus.COMPLETED: 0, RunStatus.STOPPED: 2, RunStatus.BLOCKED: 3}[outcome.status]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="methylation_seq-run",
        description="Profile-driven methylation-sequencing run-card automation",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    doctor = sub.add_parser("doctor", help="check simulation or hardware readiness")
    doctor.add_argument("--hardware", action="store_true")
    plan = sub.add_parser("plan", help="validate a manifest and print the resolved run")
    plan.add_argument("manifest")
    run_parser = sub.add_parser("run", help="simulate/evaluate a run and write the dossier")
    run_parser.add_argument("manifest")
    run_parser.add_argument("--metrics", help="JSON measurements; omit for deterministic simulation")
    run_parser.add_argument("--output", default="runs")
    demo = sub.add_parser("demo", help="run the bundled passing simulation")
    demo.add_argument("--output", default="runs")
    args = parser.parse_args(argv)

    try:
        if args.command == "doctor":
            print(format_report(run_doctor(args.hardware), args.hardware))
            return 0
        if args.command == "plan":
            _print_plan(load_run(args.manifest))
            return 0
        if args.command == "demo":
            manifest = Path(__file__).resolve().parents[1] / "configs/example_run.json"
            return _execute(str(manifest), None, args.output)
        return _execute(args.manifest, args.metrics, args.output)
    except (ManifestError, json.JSONDecodeError, OSError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

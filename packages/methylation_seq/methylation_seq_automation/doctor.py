"""Compute and hardware-readiness checks that never move an instrument."""

from __future__ import annotations

import importlib
import os
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import List

from .manifest import build_run
from .orchestrator import RunStatus, run
from .provenance import protocol_values


class CheckStatus(str, Enum):
    OK = "OK"
    WARN = "WARN"
    MISS = "MISS"


@dataclass(frozen=True)
class Check:
    name: str
    status: CheckStatus
    detail: str
    fix: str = ""


def _selftest() -> Check:
    try:
        config = build_run({
            "run_id": "DOCTOR", "operator": "doctor", "mode": "simulation",
            "profile_kind": "synthetic_water",
            "samples": [{"id": "water", "well": "A1"}],
        })
        result = run(config, timestamp="doctor")
        ok = result.status is RunStatus.COMPLETED
        return Check("deterministic simulation", CheckStatus.OK if ok else CheckStatus.MISS,
                     f"ran to {result.status.value}", "run the test suite to localize the failure")
    except Exception as exc:  # noqa: BLE001 - doctor must report rather than crash
        return Check("deterministic simulation", CheckStatus.MISS, str(exc),
                     "run the test suite to localize the failure")


def run_doctor(hardware: bool = False) -> List[Check]:
    checks = [
        Check("Python >=3.9", CheckStatus.OK if sys.version_info >= (3, 9) else CheckStatus.MISS,
              f"found {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
              "install Python 3.9 or newer"),
        _selftest(),
    ]
    try:
        importlib.import_module("yaml")
        checks.append(Check("PyYAML", CheckStatus.OK, "YAML manifests available"))
    except ImportError:
        checks.append(Check("PyYAML", CheckStatus.WARN, "absent; JSON manifests still work",
                            "pip install -e '.[yaml]'"))

    if hardware:
        root = Path(__file__).resolve().parents[3]
        required = [
            root / "hamilton-star/starlab_live/methylation_seq/methylation_seq_reagent_adds.py",
            root / "hamilton-star/starlab_live/methylation_seq/methylation_seq_cleanup.py",
            root / "hamilton-star/starlab_live/methylation_seq/run_methylation_seq_odtc_1col_full_dry.py",
            root / "instrument-integrations/odtc/05_odtc_run_protocol.py",
        ]
        for path in required:
            checks.append(Check(
                f"repo script {path.name}", CheckStatus.OK if path.exists() else CheckStatus.MISS,
                str(path), "restore the script from plr-tested",
            ))
        if not os.environ.get("ODTC_IP"):
            checks.append(Check("ODTC_IP", CheckStatus.MISS, "not set",
                                "export the measured ODTC address on the instrument Pi"))
        checks.append(Check(
            "external operator method profile",
            CheckStatus.MISS,
            "hardware review requires a private schema-versioned method and QC profile",
            "provide the approved profile through the run manifest",
        ))
    return checks


def format_report(checks: List[Check], hardware: bool) -> str:
    lines = [f"methylation_seq-run doctor ({'compute + hardware' if hardware else 'compute'} tier)", ""]
    for check in checks:
        lines.append(f"  [{check.status.value:4}] {check.name}: {check.detail}")
        if check.status is CheckStatus.MISS and check.fix:
            lines.append(f"         fix: {check.fix}")
    missing = sum(check.status is CheckStatus.MISS for check in checks)
    lines += ["", ("ready for simulation" if missing == 0 else f"{missing} blocking item(s)")]
    if hardware:
        lines.append("A live run remains blocked until every qualification item is resolved on hardware.")
    return "\n".join(lines)

"""
doctor.py - "can this lab run it yet", answered by the machine.

The point of the package is that a partner site clones the repo and runs it. This command
tells them exactly how far along they are: it checks each requirement and prints OK / WARN /
MISSING with the one line that fixes a MISSING. Two tiers, because the package has two:

  compute tier   the simulation and all the QC math. Needs nothing but Python. If this is
                 green, the site can run `elispot demo` right now and read a dossier before an
                 instrument is even unboxed.
  hardware tier  driving the washer, the liquid handler, and the imager. Needs PyLabRobot, the
                 not-yet-built washer/imager integrations, the taught membrane clearance, the
                 reader calibration, and the kit concentrations transcribed. This tier lists
                 what is still missing rather than pretending it is done.

It never raises. A check that cannot be evaluated is reported, not thrown, so the doctor runs
on the barest environment.
"""

from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional


class Status(str, Enum):
    OK = "ok"
    WARN = "warn"
    MISSING = "missing"


@dataclass
class Check:
    name: str
    status: Status
    detail: str = ""
    fix: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "status": self.status.value,
                "detail": self.detail, "fix": self.fix}


def _try_import(module: str) -> Optional[str]:
    try:
        importlib.import_module(module)
        return None
    except Exception as exc:  # noqa: BLE001 - the doctor must survive anything
        return str(exc)


def _compute_checks() -> List[Check]:
    checks: List[Check] = []

    v = sys.version_info
    checks.append(Check(
        "python >= 3.9",
        Status.OK if v >= (3, 9) else Status.MISSING,
        detail=f"found {v.major}.{v.minor}.{v.micro}",
        fix="install Python 3.9 or newer",
    ))

    core_err = _try_import("elispot.orchestrator")
    checks.append(Check(
        "package core importable",
        Status.OK if core_err is None else Status.MISSING,
        detail="stdlib-only core" if core_err is None else core_err,
        fix="run from the package root, or `pip install -e .`",
    ))

    yaml_err = _try_import("yaml")
    checks.append(Check(
        "pyyaml (YAML manifests)",
        Status.OK if yaml_err is None else Status.WARN,
        detail="present" if yaml_err is None else "absent; JSON manifests still work",
        fix="pip install pyyaml   (or write the manifest as JSON)",
    ))

    sim_ok, sim_detail = _simulation_selftest()
    checks.append(Check(
        "simulation self-test",
        Status.OK if sim_ok else Status.MISSING,
        detail=sim_detail,
        fix="the core is broken; run `pytest` to localize it",
    ))
    return checks


def _simulation_selftest() -> tuple:
    try:
        from .manifest import build_run
        from .orchestrator import run
        cfg = build_run({
            "run_id": "DOCTOR", "operator": "doctor", "mode": "simulation",
            "wells": [
                {"well": "A1", "role": "test", "antigen": "CEF"},
                {"well": "A2", "role": "pos_ctrl", "antigen": "PHA"},
                {"well": "A3", "role": "neg_ctrl", "antigen": "medium"},
            ],
        })
        out = run(cfg, timestamp="doctor")
        return out.status.value == "completed", f"ran to {out.status.value}"
    except Exception as exc:  # noqa: BLE001
        return False, f"failed: {exc}"


def _hardware_checks() -> List[Check]:
    checks: List[Check] = []

    plr_err = _try_import("pylabrobot")
    if plr_err is None:
        try:
            plr_version = importlib.import_module("pylabrobot").__version__  # type: ignore
        except Exception:  # noqa: BLE001
            plr_version = "unknown"
        checks.append(Check("PyLabRobot installed", Status.OK, detail=f"version {plr_version}"))
    else:
        checks.append(Check(
            "PyLabRobot installed", Status.MISSING, detail=plr_err,
            fix="install PyLabRobot on the Pi; the washer, OT-2/Flex, and imager backends drive "
                "the line from there",
        ))

    # The ELISpot instrument integrations are not in this repo yet; the doctor says so.
    checks.append(Check(
        "washer / imager integrations", Status.WARN,
        detail="not built in this repo yet (sim-first package)",
        fix="build instrument-integrations/biotek-405ts and instrument-integrations/imager, "
            "validate on the Pi, then point the adapters at them; see the README status",
    ))

    for c in _calibration_checks():
        checks.append(c)
    return checks


def _calibration_checks() -> List[Check]:
    """The CALIBRATE / TODO values a hardware run is blocked on until resolved."""
    checks: List[Check] = []
    try:
        from .membrane import default_constraints
        from .reagents.elispot_kit import for_cytokine
        from .reagents.rhodamine_b import default_prep

        blocking = []
        blocking += default_constraints().guard_values()   # membrane clearance (untaught)
        blocking += default_prep().guard_values()          # reader working conc + gain
        blocking += for_cytokine().guard_values()          # kit concentrations + substrate endpoint

        for v in blocking:
            checks.append(Check(
                f"resolve: {v.name}",
                Status.MISSING if v.blocks_hardware else Status.OK,
                detail=f"[{v.origin.value}] {v.source}",
                fix="measure it (or transcribe it from the kit), then pin it in the site "
                    "profile / manifest",
            ))
    except Exception as exc:  # noqa: BLE001
        checks.append(Check("calibration values", Status.WARN, detail=f"could not enumerate: {exc}"))
    return checks


def run_doctor(hardware: bool = False) -> List[Check]:
    checks = _compute_checks()
    if hardware:
        checks += _hardware_checks()
    return checks


_GLYPH = {Status.OK: "OK  ", Status.WARN: "WARN", Status.MISSING: "MISS"}


def format_report(checks: List[Check], hardware: bool) -> str:
    lines = []
    tier = "compute + hardware" if hardware else "compute"
    lines.append(f"elispot doctor  ({tier} tier)")
    lines.append("")
    for c in checks:
        lines.append(f"  [{_GLYPH[c.status]}] {c.name}")
        if c.detail:
            lines.append(f"         {c.detail}")
        if c.status is Status.MISSING and c.fix:
            lines.append(f"         fix: {c.fix}")
    n_missing = sum(1 for c in checks if c.status is Status.MISSING)
    lines.append("")
    if not hardware:
        compute_ok = all(c.status is not Status.MISSING for c in checks)
        if compute_ok:
            lines.append("compute tier ready: run `elispot demo`.")
            lines.append("For a real run, check the hardware tier: `elispot doctor --hardware`.")
        else:
            lines.append("compute tier NOT ready; fix the MISS items above.")
    else:
        if n_missing == 0:
            lines.append("hardware tier ready. Qualify the instrument (Gate 0) before the first plate.")
        else:
            lines.append(f"{n_missing} item(s) to resolve before a hardware run. "
                         "Simulation works regardless: `elispot demo`.")
    return "\n".join(lines)

"""
doctor.py - "can this lab run it yet", answered by the machine.

The point of the package is that a partner site clones the repo and runs it. This is the
command that tells them exactly how far along they are: it checks each requirement and
prints OK / WARN / MISSING with the one line that fixes a MISSING. Two tiers, because the
package has two:

  compute tier   the simulation and all the QC math. Needs nothing but Python. If this
                 is green, the site can run `edit-confirm demo` right now and read a
                 dossier before an instrument is even unboxed.
  hardware tier  driving the STAR, ODTC, and Tecan. Needs the PyLabRobot fork, the Pi
                 wiring, the instrument addresses, and the Gate 0 / reader calibration.
                 `edit-confirm doctor --hardware` lists what is still missing.

It never raises. A check that cannot be evaluated is reported, not thrown, so the doctor
runs on the barest environment.
"""

from __future__ import annotations

import importlib
import os
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
    """Return None if importable, else the error string. Never raises."""
    try:
        importlib.import_module(module)
        return None
    except Exception as exc:  # noqa: BLE001 - the doctor must survive anything
        return str(exc)


# ---------------------------------------------------------------------------
# Compute tier
# ---------------------------------------------------------------------------

def _compute_checks() -> List[Check]:
    checks: List[Check] = []

    v = sys.version_info
    checks.append(Check(
        "python >= 3.9",
        Status.OK if v >= (3, 9) else Status.MISSING,
        detail=f"found {v.major}.{v.minor}.{v.micro}",
        fix="install Python 3.9 or newer",
    ))

    core_err = _try_import("edit_confirmation.orchestrator")
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

    # The real proof of the compute tier: run a tiny simulation end to end.
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
            "edit": {"type": "unknown"},
            "locus": {"name": "L", "amplicon_bp": 200},
            "samples": [{"id": "a", "well": "A1"}, {"id": "ntc", "well": "H1", "type": "ntc"}],
        })
        out = run(cfg, timestamp="doctor")
        return out.status.value == "completed", f"ran to {out.status.value}"
    except Exception as exc:  # noqa: BLE001
        return False, f"failed: {exc}"


# ---------------------------------------------------------------------------
# Hardware tier
# ---------------------------------------------------------------------------

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
            fix="install the di-omics PyLabRobot fork (ships the STAR/ODTC/Tecan backends): "
                "pip install -e '.[usb]' from a checkout of the fork",
        ))

    star_err = _try_import("pylabrobot.liquid_handling.backends")
    checks.append(Check(
        "STAR backend importable",
        Status.OK if star_err is None else Status.MISSING,
        detail="pylabrobot.liquid_handling.backends" if star_err is None else star_err,
        fix="install PyLabRobot (STARBackend); connect the STAR over USB on starpi",
    ))

    tecan_err = _try_import("pylabrobot.tecan.infinite")
    checks.append(Check(
        "Tecan Infinite backend importable (fork-only)",
        Status.OK if tecan_err is None else Status.MISSING,
        detail="pylabrobot.tecan.infinite" if tecan_err is None else tecan_err,
        fix="use the di-omics fork commit that ships pylabrobot/tecan/; see "
            "instrument-integrations/tecan-infinite/",
    ))

    odtc_ip = os.environ.get("ODTC_IP")
    checks.append(Check(
        "ODTC_IP set",
        Status.OK if odtc_ip else Status.MISSING,
        detail=f"ODTC_IP={odtc_ip}" if odtc_ip else "not set",
        fix="discover the ODTC link-local address and export ODTC_IP; see "
            "instrument-integrations/odtc/README.md (eth1, 169.254/16)",
    ))

    # The provenance the package itself refuses to run without.
    for c in _calibration_checks():
        checks.append(c)
    return checks


def _calibration_checks() -> List[Check]:
    """The CALIBRATE/TODO values a hardware run is blocked on until measured."""
    checks: List[Check] = []
    try:
        from .reagents.rhodamine_b import default_prep
        from .provenance import Origin
        prep = default_prep()
        for v in prep.guard_values():
            checks.append(Check(
                f"calibration: {v.name}",
                Status.MISSING if v.blocks_hardware else Status.OK,
                detail=f"[{v.origin.value}] {v.source}",
                fix="measure it on this reader during Gate 0 calibration, then pin it",
            ))
    except Exception as exc:  # noqa: BLE001
        checks.append(Check("calibration values", Status.WARN, detail=f"could not enumerate: {exc}"))
    return checks


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def run_doctor(hardware: bool = False) -> List[Check]:
    checks = _compute_checks()
    if hardware:
        checks += _hardware_checks()
    return checks


_GLYPH = {Status.OK: "OK  ", Status.WARN: "WARN", Status.MISSING: "MISS"}


def format_report(checks: List[Check], hardware: bool) -> str:
    lines = []
    tier = "compute + hardware" if hardware else "compute"
    lines.append(f"edit-confirm doctor  ({tier} tier)")
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
            lines.append("compute tier ready: run `edit-confirm demo`.")
            lines.append("For a real run, check the hardware tier: `edit-confirm doctor --hardware`.")
        else:
            lines.append("compute tier NOT ready; fix the MISS items above.")
    else:
        if n_missing == 0:
            lines.append("hardware tier ready. Qualify the deck (Gate 0) before the first sample.")
        else:
            lines.append(f"{n_missing} item(s) to resolve before a hardware run. "
                         "Simulation works regardless: `edit-confirm demo`.")
    return "\n".join(lines)

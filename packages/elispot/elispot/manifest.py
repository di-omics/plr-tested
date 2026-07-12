"""
manifest.py - sparse input in, a full validated run plan out.

An operator writes the few things specific to their plate - which cytokine, which wells hold
which antigen, which are the controls, and whether this is a dry simulation or the real thing -
and the package supplies everything else from pinned defaults: the reagent chain, the QC
cutoffs, the site profile. This module is that expansion.

A manifest is JSON or YAML. JSON needs nothing installed, which matters for a partner site
with a bare Python; YAML is nicer to read and is used if pyyaml is present. The loader
validates as it goes and fails with a message an operator can act on, not a traceback. The one
structural rule it enforces is the one the science depends on: a scorable ELISpot plate has at
least one negative control, one positive control, and one test well.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from .config import (
    AcceptanceCriteria,
    Antigen,
    AntigenKind,
    PlateLayout,
    RunConfig,
    RunMode,
    SiteProfile,
    Well,
    WellRole,
)


class ManifestError(ValueError):
    """The manifest is missing something or has something that does not make sense."""


def _load_raw(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        raise ManifestError(f"manifest not found: {path}")
    text = open(path, "r", encoding="utf-8").read()
    if path.endswith((".yaml", ".yml")):
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise ManifestError(
                f"{path} is YAML but pyyaml is not installed. "
                "Install pyyaml, or convert the manifest to JSON."
            ) from exc
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    if not isinstance(data, dict):
        raise ManifestError(f"{path} did not parse to a mapping at the top level")
    return data


def _require(data: Dict[str, Any], key: str, where: str) -> Any:
    if key not in data:
        raise ManifestError(f"{where} is missing required field {key!r}")
    return data[key]


def _default_kind(role: WellRole) -> AntigenKind:
    return {
        WellRole.POSITIVE_CONTROL: AntigenKind.MITOGEN,
        WellRole.NEGATIVE_CONTROL: AntigenKind.MEDIUM,
        WellRole.TEST: AntigenKind.PEPTIDE_POOL,
    }.get(role, AntigenKind.PEPTIDE_POOL)


def _parse_wells(raw: Any) -> List[Well]:
    if not isinstance(raw, list) or not raw:
        raise ManifestError("`wells` must be a non-empty list")
    wells: List[Well] = []
    seen = set()
    for i, item in enumerate(raw):
        where = f"wells[{i}]"
        if not isinstance(item, dict):
            raise ManifestError(f"{where} must be a mapping")
        addr = str(_require(item, "well", where)).upper()
        if addr in seen:
            raise ManifestError(f"two wells share address {addr!r}")
        seen.add(addr)
        role_raw = item.get("role", "test")
        try:
            role = WellRole(role_raw)
        except ValueError:
            valid = ", ".join(r.value for r in WellRole)
            raise ManifestError(f"{where} role {role_raw!r} is not one of: {valid}")
        antigen = str(item.get("antigen", "")).strip()
        if role is WellRole.NEGATIVE_CONTROL and not antigen:
            antigen = "medium"
        cells = item.get("cells")
        try:
            wells.append(Well(
                address=addr, role=role, antigen=antigen,
                cells_per_well=(int(cells) if cells is not None else None),
                notes=str(item.get("notes", "")),
            ))
        except ValueError as exc:
            raise ManifestError(f"{where}: {exc}") from exc
    return wells


def _derive_antigens(wells: List[Well], declared: List[Antigen]) -> List[Antigen]:
    by_name = {a.name: a for a in declared}
    for w in wells:
        if w.antigen and w.antigen not in by_name:
            by_name[w.antigen] = Antigen(name=w.antigen, kind=_default_kind(w.role))
    return list(by_name.values())


def _parse_declared_antigens(raw: Any) -> List[Antigen]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ManifestError("`antigens` must be a list if present")
    out = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ManifestError(f"antigens[{i}] must be a mapping")
        name = str(_require(item, "name", f"antigens[{i}]"))
        kind_raw = item.get("kind", "peptide_pool")
        try:
            kind = AntigenKind(kind_raw)
        except ValueError:
            valid = ", ".join(k.value for k in AntigenKind)
            raise ManifestError(f"antigens[{i}] kind {kind_raw!r} is not one of: {valid}")
        out.append(Antigen(name=name, kind=kind, notes=str(item.get("notes", ""))))
    return out


def _parse_acceptance(raw: Any) -> AcceptanceCriteria:
    ac = AcceptanceCriteria()
    if raw is None:
        return ac
    if not isinstance(raw, dict):
        raise ManifestError("`acceptance` must be a mapping if present")
    for key, value in raw.items():
        if not hasattr(ac, key):
            raise ManifestError(
                f"acceptance criterion {key!r} is not recognized; "
                f"see configs/acceptance_criteria.yaml for the valid keys"
            )
        setattr(ac, key, value)
    return ac


def _parse_site(raw: Any) -> SiteProfile:
    sp = SiteProfile()
    if raw is None:
        return sp
    if not isinstance(raw, dict):
        raise ManifestError("`site` must be a mapping if present")
    for key, value in raw.items():
        if not hasattr(sp, key):
            raise ManifestError(
                f"site profile field {key!r} is not recognized; valid keys are: "
                f"{', '.join(sp.__dataclass_fields__)}"
            )
        setattr(sp, key, value)
    return sp


def load_run(path: str, output_dir: str = "runs") -> RunConfig:
    """Load and validate a manifest file into a RunConfig."""
    return build_run(_load_raw(path), output_dir=output_dir)


def build_run(data: Dict[str, Any], output_dir: str = "runs") -> RunConfig:
    """Build a RunConfig from an already-parsed manifest mapping."""
    run_id = str(_require(data, "run_id", "manifest"))
    operator = str(_require(data, "operator", "manifest"))

    mode_raw = data.get("mode", "simulation")
    try:
        mode = RunMode(mode_raw)
    except ValueError:
        raise ManifestError(f"mode {mode_raw!r} is not valid; use 'simulation' or 'hardware'")

    wells = _parse_wells(_require(data, "wells", "manifest"))
    plate = PlateLayout(wells=wells)

    # The science-level structural requirement.
    if not plate.negative_wells():
        raise ManifestError("no negative-control well; a plate cannot be scored without a "
                            "medium-only background (role: neg_ctrl)")
    if not plate.positive_wells():
        raise ManifestError("no positive-control well; a plate cannot be validated without a "
                            "mitogen control (role: pos_ctrl)")
    if not plate.test_groups():
        raise ManifestError("no test well; nothing to measure (role: test)")

    antigens = _derive_antigens(wells, _parse_declared_antigens(data.get("antigens")))
    acceptance = _parse_acceptance(data.get("acceptance"))
    site = _parse_site(data.get("site"))

    return RunConfig(
        run_id=run_id,
        operator=operator,
        mode=mode,
        plate=plate,
        antigens=antigens,
        acceptance=acceptance,
        site=site,
        cytokine=str(data.get("cytokine", "IFN-gamma")),
        precoated_plate=bool(data.get("precoated_plate", False)),
        output_dir=output_dir,
        notes=str(data.get("notes", "")),
    )

"""Manifest loading with synthetic-water and external operator profiles."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Set

from .config import (
    AcceptanceCriteria,
    DeckLayout,
    MetricRule,
    ProfileKind,
    RunConfig,
    RunMode,
    Sample,
    SampleType,
)


class ManifestError(ValueError):
    pass


_WELL_RE = re.compile(r"^[A-H]1$")
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _load_raw(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        raise ManifestError(f"manifest not found: {path}")
    text = Path(path).read_text(encoding="utf-8")
    if path.endswith((".yaml", ".yml")):
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise ManifestError("YAML support requires pyyaml; JSON remains available") from exc
        raw = yaml.safe_load(text)
    else:
        raw = json.loads(text)
    if not isinstance(raw, dict):
        raise ManifestError("manifest root must be a mapping")
    return raw


def _required(data: Dict[str, Any], key: str, where: str = "manifest") -> Any:
    if key not in data:
        raise ManifestError(f"{where} is missing required field {key!r}")
    return data[key]


def _parse_samples(raw: Any) -> List[Sample]:
    if not isinstance(raw, list) or not raw:
        raise ManifestError("samples must be a non-empty list")
    if len(raw) > 8:
        raise ManifestError("the current motion scaffold supports one eight-well column")
    samples: List[Sample] = []
    ids: Set[str] = set()
    wells: Set[str] = set()
    for index, item in enumerate(raw):
        where = f"samples[{index}]"
        if not isinstance(item, dict):
            raise ManifestError(f"{where} must be a mapping")
        sid = str(_required(item, "id", where)).strip()
        well = str(_required(item, "well", where)).upper()
        try:
            sample_type = SampleType(item.get("type", "sample"))
        except ValueError as exc:
            raise ManifestError(f"{where}.type is not supported") from exc
        if not sid or sid in ids:
            raise ManifestError(f"{where}.id must be non-empty and unique")
        if not _WELL_RE.match(well) or well in wells:
            raise ManifestError(f"{where}.well must be a unique A1-H1 position")
        ids.add(sid)
        wells.add(well)
        samples.append(Sample(
            id=sid,
            well=well,
            sample_type=sample_type,
            input_ng=float(item.get("input_ng", 0.0)),
            udi=str(item.get("udi", "operator-configured")),
            control_dilution=str(item.get("control_dilution", "operator-configured")),
            notes=str(item.get("notes", "")),
        ))
    if not any(sample.sample_type is not SampleType.PROCESS_BLANK for sample in samples):
        raise ManifestError("at least one non-blank sample is required")
    return samples


def _rule(raw: Any, where: str) -> MetricRule:
    if not isinstance(raw, dict):
        raise ManifestError(f"{where} must be a mapping")
    metric = str(_required(raw, "metric", where)).strip()
    if not metric:
        raise ManifestError(f"{where}.metric cannot be empty")
    minimum = raw.get("minimum")
    maximum = raw.get("maximum")
    if minimum is None and maximum is None:
        raise ManifestError(f"{where} requires minimum and/or maximum")
    return MetricRule(
        metric=metric,
        label=str(raw.get("label", metric)),
        unit=str(raw.get("unit", "")),
        minimum=float(minimum) if minimum is not None else None,
        maximum=float(maximum) if maximum is not None else None,
    )


def _acceptance(raw: Any) -> AcceptanceCriteria:
    if not isinstance(raw, dict):
        raise ManifestError("method profile acceptance must be a mapping")
    cv = float(_required(raw, "lh_cv_max_percent", "acceptance"))
    if cv <= 0:
        raise ManifestError("acceptance.lh_cv_max_percent must be positive")
    return AcceptanceCriteria(
        lh_cv_max_percent=cv,
        sample_rules=[
            _rule(item, f"acceptance.sample_rules[{index}]")
            for index, item in enumerate(raw.get("sample_rules", []))
        ],
        blank_rules=[
            _rule(item, f"acceptance.blank_rules[{index}]")
            for index, item in enumerate(raw.get("blank_rules", []))
        ],
    )


def _synthetic_method() -> Dict[str, Any]:
    return {
        "schema_version": 1,
        "method_name": "synthetic water-only methylation-sequencing rehearsal",
        "water_only": True,
        "qualified_volumes_ul": [20.0],
        "acceptance": {
            "lh_cv_max_percent": 5.0,
            "sample_rules": [
                {"metric": "synthetic_qc_signal", "label": "synthetic QC signal", "minimum": 0.5, "unit": "a.u."}
            ],
            "blank_rules": [
                {"metric": "synthetic_blank_signal", "label": "synthetic blank signal", "maximum": 0.5, "unit": "a.u."}
            ],
        },
    }


def _operator_method(path: str) -> Dict[str, Any]:
    profile_path = Path(path).expanduser()
    try:
        data = json.loads(profile_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"cannot load operator method profile {profile_path}: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ManifestError("operator method profile must be a schema_version 1 mapping")
    if data.get("water_only") is True:
        raise ManifestError("operator method profile cannot be marked water_only")
    volumes = data.get("qualified_volumes_ul")
    if not isinstance(volumes, list) or not volumes:
        raise ManifestError("operator method profile requires qualified_volumes_ul")
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0 for value in volumes):
        raise ManifestError("qualified_volumes_ul must contain positive numbers")
    _acceptance(_required(data, "acceptance", "operator method profile"))
    return data


def build_run(data: Dict[str, Any], output_dir: str = "runs") -> RunConfig:
    try:
        mode = RunMode(data.get("mode", "simulation"))
        profile_kind = ProfileKind(data.get("profile_kind", "synthetic_water"))
    except ValueError as exc:
        raise ManifestError("mode or profile_kind is not supported") from exc
    profile_path = data.get("method_profile")
    if profile_kind is ProfileKind.SYNTHETIC_WATER:
        if mode is RunMode.HARDWARE:
            raise ManifestError("hardware mode requires profile_kind 'operator'")
        if profile_path:
            raise ManifestError("synthetic_water does not accept method_profile")
        method = _synthetic_method()
    else:
        if not profile_path:
            raise ManifestError("profile_kind 'operator' requires method_profile")
        method = _operator_method(str(profile_path))

    run_id = str(_required(data, "run_id"))
    if not _RUN_ID_RE.match(run_id):
        raise ManifestError("run_id must use letters, numbers, '.', '_' or '-'")
    operator = str(_required(data, "operator")).strip()
    if not operator:
        raise ManifestError("operator cannot be empty")
    samples = _parse_samples(_required(data, "samples"))
    return RunConfig(
        run_id=run_id,
        operator=operator,
        mode=mode,
        samples=samples,
        profile_kind=profile_kind,
        method=method,
        method_profile_path=str(profile_path) if profile_path else None,
        reaction_batch_size=len(samples),
        deck=DeckLayout.validation(),
        acceptance=_acceptance(method["acceptance"]),
        output_dir=output_dir,
        notes=str(data.get("notes", "")),
    )


def load_run(path: str, output_dir: str = "runs") -> RunConfig:
    return build_run(_load_raw(path), output_dir=output_dir)

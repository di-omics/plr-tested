"""Sparse JSON/YAML manifest loading with chemistry-aware validation."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Iterable, List, Optional, Set

from .config import (
    AcceptanceCriteria,
    DeckLayout,
    InputTier,
    RunConfig,
    RunMode,
    Sample,
    SampleType,
)


class ManifestError(ValueError):
    pass


_WELL_RE = re.compile(r"^[A-H]1$")
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_CONTROL_DILUTIONS = {0.1: "1:1000", 1.0: "1:250", 10.0: "1:100", 200.0: "1:50"}
_PCR_CHOICES = {0.1: {14}, 1.0: {11}, 10.0: {8}, 50.0: {5, 6}, 200.0: {4, 5}}


def _load_raw(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        raise ManifestError(f"manifest not found: {path}")
    with open(path, "r", encoding="utf-8") as handle:
        text = handle.read()
    if path.endswith((".yaml", ".yml")):
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise ManifestError(
                "YAML manifest requested but pyyaml is absent; install .[yaml] or use JSON"
            ) from exc
        raw = yaml.safe_load(text)
    else:
        raw = json.loads(text)
    if not isinstance(raw, dict):
        raise ManifestError("manifest must contain a mapping at the top level")
    return raw


def _required(data: Dict[str, Any], key: str, where: str = "manifest") -> Any:
    if key not in data:
        raise ManifestError(f"{where} is missing required field {key!r}")
    return data[key]


def _near(value: float, reference: float) -> bool:
    return abs(value - reference) < 1e-9


def _lookup(mapping: Dict[float, Any], input_ng: float) -> Optional[Any]:
    for amount, value in mapping.items():
        if _near(input_ng, amount):
            return value
    return None


def _parse_samples(raw: Any) -> List[Sample]:
    if not isinstance(raw, list) or not raw:
        raise ManifestError("samples must be a non-empty list")
    if len(raw) > 8:
        raise ManifestError("the current STAR implementation supports one column (8 wells) only")

    samples: List[Sample] = []
    ids: Set[str] = set()
    wells: Set[str] = set()
    udis: Set[str] = set()
    for index, item in enumerate(raw):
        where = f"samples[{index}]"
        if not isinstance(item, dict):
            raise ManifestError(f"{where} must be a mapping")
        sid = str(_required(item, "id", where)).strip()
        well = str(_required(item, "well", where)).upper()
        udi = str(_required(item, "udi", where)).strip()
        try:
            sample_type = SampleType(item.get("type", "sample"))
        except ValueError as exc:
            valid = ", ".join(item.value for item in SampleType)
            raise ManifestError(f"{where}.type must be one of: {valid}") from exc

        if not sid:
            raise ManifestError(f"{where}.id cannot be empty")
        if not _WELL_RE.match(well):
            raise ManifestError(
                f"{where}.well={well!r}; current hardware code accepts A1-H1 only"
            )
        if not udi:
            raise ManifestError(f"{where}.udi cannot be empty")
        if sid in ids:
            raise ManifestError(f"duplicate sample id {sid!r}")
        if well in wells:
            raise ManifestError(f"two samples share well {well!r}")
        if udi in udis:
            raise ManifestError(f"UDI {udi!r} is assigned more than once")
        ids.add(sid)
        wells.add(well)
        udis.add(udi)

        input_ng = float(item.get("input_ng", 0.0 if sample_type is SampleType.PROCESS_BLANK else -1.0))
        if sample_type is SampleType.PROCESS_BLANK:
            if input_ng != 0.0:
                raise ManifestError(f"{where}: a process_blank must have input_ng: 0")
        elif not (0.1 <= input_ng <= 200.0):
            raise ManifestError(f"{where}.input_ng must be within the M7634 range 0.1-200 ng")

        dilution = item.get("control_dilution")
        if dilution is None and sample_type is not SampleType.PROCESS_BLANK:
            dilution = _lookup(_CONTROL_DILUTIONS, input_ng)
            if dilution is None:
                raise ManifestError(
                    f"{where}: M7634 gives no automatic control dilution for {input_ng:g} ng; "
                    "set control_dilution explicitly and record the choice"
                )
        if dilution is None:
            dilution = "operator-set"
        dilution = str(dilution)
        if not re.match(r"^1:\d+$", dilution) and dilution != "operator-set":
            raise ManifestError(f"{where}.control_dilution must look like '1:100'")

        samples.append(Sample(
            id=sid,
            well=well,
            input_ng=input_ng,
            udi=udi,
            control_dilution=dilution,
            sample_type=sample_type,
            notes=str(item.get("notes", "")),
        ))

    if not any(s.sample_type is not SampleType.PROCESS_BLANK for s in samples):
        raise ManifestError("at least one non-blank sample or positive control is required")
    return samples


def _input_tier(samples: Iterable[Sample]) -> InputTier:
    tiers = {s.input_tier for s in samples if s.input_tier is not None}
    if len(tiers) != 1:
        raise ManifestError(
            "one column cannot mix <=10 ng and >10 ng inputs: the carrier-DNA, T4-BGT, "
            "and post-ligation elution routes differ; split them into separate runs"
        )
    return next(iter(tiers))


def _pcr_cycles(data: Dict[str, Any], samples: Iterable[Sample]) -> int:
    active = [s for s in samples if s.sample_type is not SampleType.PROCESS_BLANK]
    supplied = data.get("pcr_cycles")
    if supplied is None:
        choices = [_lookup(_PCR_CHOICES, s.input_ng) for s in active]
        if any(choice is None or len(choice) != 1 for choice in choices):
            raise ManifestError(
                "pcr_cycles is required for this input: M7634 gives a range or no exact row, "
                "so the package will not choose for you"
            )
        unique = {next(iter(choice)) for choice in choices if choice is not None}
        if len(unique) != 1:
            raise ManifestError("samples require different PCR cycle counts; split them into separate runs")
        supplied = next(iter(unique))

    cycles = int(supplied)
    if not (4 <= cycles <= 14):
        raise ManifestError("pcr_cycles must be within the published 4-14 cycle range")
    for sample in active:
        choices = _lookup(_PCR_CHOICES, sample.input_ng)
        if choices is not None and cycles not in choices:
            valid = "/".join(str(choice) for choice in sorted(choices))
            raise ManifestError(
                f"pcr_cycles={cycles} conflicts with M7634 for {sample.input_ng:g} ng "
                f"({valid} cycle(s)); split inputs or correct the manifest"
            )
    return cycles


def _acceptance(raw: Any) -> AcceptanceCriteria:
    criteria = AcceptanceCriteria()
    if raw is None:
        return criteria
    if not isinstance(raw, dict):
        raise ManifestError("acceptance must be a mapping")
    for key, value in raw.items():
        if not hasattr(criteria, key):
            raise ManifestError(f"unknown acceptance criterion {key!r}")
        current = getattr(criteria, key)
        try:
            setattr(criteria, key, int(value) if isinstance(current, int) else float(value))
        except (TypeError, ValueError) as exc:
            raise ManifestError(f"acceptance.{key} must be numeric") from exc
    if criteria.lh_cv_max_percent <= 0:
        raise ManifestError("acceptance.lh_cv_max_percent must be positive")
    if not (0 <= criteria.lambda_conversion_min_percent <= 100):
        raise ManifestError("acceptance.lambda_conversion_min_percent must be 0-100")
    if not (0 <= criteria.puc19_protection_min_percent <= 100):
        raise ManifestError("acceptance.puc19_protection_min_percent must be 0-100")
    if criteria.library_mean_bp_min >= criteria.library_mean_bp_max:
        raise ManifestError("acceptance library size minimum must be below the maximum")
    return criteria


def build_run(data: Dict[str, Any], output_dir: str = "runs") -> RunConfig:
    try:
        mode = RunMode(data.get("mode", "simulation"))
    except ValueError as exc:
        raise ManifestError("mode must be 'simulation' or 'hardware'") from exc
    samples = _parse_samples(_required(data, "samples"))
    tier = _input_tier(samples)
    shear_minutes = float(data.get("shear_minutes", 30.0))
    if not (25.0 <= shear_minutes <= 35.0):
        raise ManifestError("shear_minutes must be within M7634 3.1.6's 25-35 minute range")
    kit_size = int(data.get("kit_size", 24))
    if kit_size not in (24, 96):
        raise ManifestError("kit_size must be 24 or 96 reactions")
    denaturation = str(data.get("denaturation", "formamide"))
    if denaturation != "formamide":
        raise ManifestError(
            "the current STAR mode implements the recommended formamide route only; "
            "NaOH needs a separately reviewed reagent mode"
        )
    deck = data.get("deck", "bio_validation_0")
    if deck != "bio_validation_0":
        raise ManifestError("only deck 'bio_validation_0' is implemented")

    run_id = str(_required(data, "run_id"))
    if not _RUN_ID_RE.match(run_id):
        raise ManifestError(
            "run_id must be 1-128 characters using letters, numbers, '.', '_' or '-'"
        )
    operator = str(_required(data, "operator")).strip()
    if not operator:
        raise ManifestError("operator cannot be empty")

    return RunConfig(
        run_id=run_id,
        operator=operator,
        mode=mode,
        samples=samples,
        input_tier=tier,
        shear_minutes=shear_minutes,
        pcr_cycles=_pcr_cycles(data, samples),
        kit_size=kit_size,
        denaturation=denaturation,
        deck=DeckLayout.bio_validation_0(),
        acceptance=_acceptance(data.get("acceptance")),
        output_dir=output_dir,
        notes=str(data.get("notes", "")),
    )


def load_run(path: str, output_dir: str = "runs") -> RunConfig:
    return build_run(_load_raw(path), output_dir=output_dir)

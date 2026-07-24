"""Manifest loading for explicit, auditable run plans.

The package supplies deck geometry and orchestration, but no biological reagent,
thermal, cycle, cleanup, or acceptance defaults. Each run must provide those values in
``method`` and ``acceptance`` blocks. Public examples use a clearly labeled synthetic
water-only profile.

A manifest is JSON or YAML. JSON needs nothing installed, which matters for a partner
site with a bare Python; YAML is nicer to read and is used if pyyaml is present. The
loader validates as it goes and fails with a message an operator can act on, not a
traceback.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict

from .config import (
    AcceptanceCriteria,
    DeckLayout,
    AssayType,
    AssayTarget,
    MethodParameters,
    ProfileKind,
    RunConfig,
    RunMode,
    Sample,
    SampleType,
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


def _parse_samples(raw: Any) -> list:
    if not isinstance(raw, list) or not raw:
        raise ManifestError("`samples` must be a non-empty list")
    samples = []
    seen_ids = set()
    seen_wells = set()
    for i, item in enumerate(raw):
        where = f"samples[{i}]"
        if not isinstance(item, dict):
            raise ManifestError(f"{where} must be a mapping")
        sid = str(_require(item, "id", where))
        well = str(_require(item, "well", where)).upper()
        stype_raw = item.get("type", "test")
        try:
            stype = SampleType(stype_raw)
        except ValueError:
            valid = ", ".join(s.value for s in SampleType)
            raise ManifestError(f"{where} type {stype_raw!r} is not one of: {valid}")
        if sid in seen_ids:
            raise ManifestError(f"duplicate sample id {sid!r}")
        if well in seen_wells:
            raise ManifestError(f"two samples share well {well!r}")
        seen_ids.add(sid)
        seen_wells.add(well)
        try:
            samples.append(Sample(id=sid, well=well, sample_type=stype,
                                  notes=str(item.get("notes", ""))))
        except ValueError as exc:
            raise ManifestError(f"{where}: {exc}") from exc
    return samples


def _parse_target(raw: Any) -> AssayTarget:
    if not isinstance(raw, dict):
        raise ManifestError("`target` must be a mapping")
    name = str(_require(raw, "name", "target"))
    target_product_bp = int(_require(raw, "target_product_bp", "target"))
    return AssayTarget(
        name=name,
        target_product_bp=target_product_bp,
        primer_f=(str(raw["primer_f"]) if raw.get("primer_f") else None),
        primer_r=(str(raw["primer_r"]) if raw.get("primer_r") else None),
        position_of_interest_bp=(int(raw["position_of_interest_bp"]) if "position_of_interest_bp" in raw else None),
    )


def _parse_acceptance(raw: Any) -> AcceptanceCriteria:
    if not isinstance(raw, dict):
        raise ManifestError("`acceptance` must be a mapping")
    fields = (
        "lh_cv_max_percent",
        "lh_recovery_tolerance_percent",
        "lh_qualified_volumes_ul",
        "curve_r2_min",
        "wgs_prep_yield_min_ng",
        "wgs_prep_uniformity_cv_max_percent",
        "pcr_enrichment_conc_min_ng_per_ul",
        "pcr_enrichment_conc_max_ng_per_ul",
    )
    unknown = sorted(set(raw) - set(fields))
    if unknown:
        raise ManifestError(
            f"acceptance contains unknown field(s): {', '.join(unknown)}"
        )
    missing = [field for field in fields if field not in raw]
    if missing:
        raise ManifestError(
            f"acceptance is missing required field(s): {', '.join(missing)}"
        )
    try:
        return AcceptanceCriteria(
            lh_cv_max_percent=float(raw["lh_cv_max_percent"]),
            lh_recovery_tolerance_percent=float(
                raw["lh_recovery_tolerance_percent"]
            ),
            lh_qualified_volumes_ul=[
                float(value) for value in raw["lh_qualified_volumes_ul"]
            ],
            curve_r2_min=float(raw["curve_r2_min"]),
            wgs_prep_yield_min_ng=float(raw["wgs_prep_yield_min_ng"]),
            wgs_prep_uniformity_cv_max_percent=float(
                raw["wgs_prep_uniformity_cv_max_percent"]
            ),
            pcr_enrichment_conc_min_ng_per_ul=float(
                raw["pcr_enrichment_conc_min_ng_per_ul"]
            ),
            pcr_enrichment_conc_max_ng_per_ul=float(
                raw["pcr_enrichment_conc_max_ng_per_ul"]
            ),
        )
    except (TypeError, ValueError) as exc:
        raise ManifestError(f"acceptance: {exc}") from exc


def _parse_method(raw: Any) -> MethodParameters:
    if not isinstance(raw, dict):
        raise ManifestError("`method` must be a mapping")
    fields = (
        "profile_kind",
        "parameter_source",
        "wgs_input_preparation_ul",
        "wgs_reaction_mix_ul",
        "wgs_odtc_profile",
        "pcr1_mastermix_ul",
        "pcr2_mastermix_ul",
        "pcr_reaction_volume_ul",
        "post_pcr1_cleanup_ratio",
        "post_pcr2_cleanup_ratio",
        "supernatant_margin_ul",
        "pcr1_anneal_c",
        "pcr2_cycles",
        "pcr1_odtc_profile",
        "pcr2_odtc_profile",
        "wgs_qc_dilution",
        "pcr_qc_dilution",
        "wgs_product_volume_ul",
        "pcr_library_volume_ul",
        "fluorescent_dsdna_excitation_nm",
        "fluorescent_dsdna_emission_nm",
        "fluorescent_dsdna_standards_ng_per_ml",
    )
    unknown = sorted(set(raw) - set(fields))
    if unknown:
        raise ManifestError(f"method contains unknown field(s): {', '.join(unknown)}")
    missing = [field for field in fields if field not in raw]
    if missing:
        raise ManifestError(f"method is missing required field(s): {', '.join(missing)}")
    try:
        kind = ProfileKind(raw["profile_kind"])
    except ValueError as exc:
        raise ManifestError(
            "method profile_kind must be 'synthetic_water' or 'operator'"
        ) from exc
    try:
        return MethodParameters(
            profile_kind=kind,
            parameter_source=str(raw["parameter_source"]),
            wgs_input_preparation_ul=float(raw["wgs_input_preparation_ul"]),
            wgs_reaction_mix_ul=float(raw["wgs_reaction_mix_ul"]),
            wgs_odtc_profile=str(raw["wgs_odtc_profile"]),
            pcr1_mastermix_ul=float(raw["pcr1_mastermix_ul"]),
            pcr2_mastermix_ul=float(raw["pcr2_mastermix_ul"]),
            pcr_reaction_volume_ul=float(raw["pcr_reaction_volume_ul"]),
            post_pcr1_cleanup_ratio=float(raw["post_pcr1_cleanup_ratio"]),
            post_pcr2_cleanup_ratio=float(raw["post_pcr2_cleanup_ratio"]),
            supernatant_margin_ul=float(raw["supernatant_margin_ul"]),
            pcr1_anneal_c=float(raw["pcr1_anneal_c"]),
            pcr2_cycles=int(raw["pcr2_cycles"]),
            pcr1_odtc_profile=str(raw["pcr1_odtc_profile"]),
            pcr2_odtc_profile=str(raw["pcr2_odtc_profile"]),
            wgs_qc_dilution=float(raw["wgs_qc_dilution"]),
            pcr_qc_dilution=float(raw["pcr_qc_dilution"]),
            wgs_product_volume_ul=float(raw["wgs_product_volume_ul"]),
            pcr_library_volume_ul=float(raw["pcr_library_volume_ul"]),
            fluorescent_dsdna_excitation_nm=float(
                raw["fluorescent_dsdna_excitation_nm"]
            ),
            fluorescent_dsdna_emission_nm=float(
                raw["fluorescent_dsdna_emission_nm"]
            ),
            fluorescent_dsdna_standards_ng_per_ml=[
                float(value)
                for value in raw["fluorescent_dsdna_standards_ng_per_ml"]
            ],
        )
    except (TypeError, ValueError) as exc:
        raise ManifestError(f"method: {exc}") from exc


def load_run(path: str, output_dir: str = "runs") -> RunConfig:
    """Load and validate a manifest file into a RunConfig."""
    data = _load_raw(path)
    return build_run(data, output_dir=output_dir)


def build_run(data: Dict[str, Any], output_dir: str = "runs") -> RunConfig:
    """Build a RunConfig from an already-parsed manifest mapping."""
    run_id = str(_require(data, "run_id", "manifest"))
    operator = str(_require(data, "operator", "manifest"))

    mode_raw = data.get("mode", "simulation")
    try:
        mode = RunMode(mode_raw)
    except ValueError:
        raise ManifestError(
            f"mode {mode_raw!r} is not valid; use 'simulation' or 'hardware'"
        )

    assay_raw = data.get("assay", {})
    assay_type_raw = assay_raw.get("type", "generic") if isinstance(assay_raw, dict) else "generic"
    try:
        assay_type = AssayType(assay_type_raw)
    except ValueError:
        valid = ", ".join(e.value for e in AssayType)
        raise ManifestError(f"assay type {assay_type_raw!r} is not one of: {valid}")

    samples = _parse_samples(_require(data, "samples", "manifest"))
    target = _parse_target(_require(data, "target", "manifest"))
    method = _parse_method(data.get("method"))
    acceptance = _parse_acceptance(data.get("acceptance"))
    if mode is RunMode.HARDWARE and method.profile_kind is ProfileKind.SYNTHETIC_WATER:
        raise ManifestError(
            "hardware mode requires method.profile_kind='operator'; "
            "the public synthetic profile is water-only"
        )

    deck = DeckLayout.validation()
    if data.get("deck") not in (None, "validation"):
        raise ManifestError(
            f"deck {data.get('deck')!r} is not defined; only 'validation' ships. "
            "Add a DeckLayout for a new deck before referencing it."
        )

    tip_column = int(data.get("tip_column", 1))
    if not (1 <= tip_column <= 12):
        raise ManifestError(
            f"tip_column={tip_column} is not a 1..12 tip-rack column"
        )

    return RunConfig(
        run_id=run_id,
        operator=operator,
        mode=mode,
        samples=samples,
        target=target,
        assay_type=assay_type,
        deck=deck,
        method=method,
        acceptance=acceptance,
        output_dir=output_dir,
        tip_column=tip_column,
        notes=str(data.get("notes", "")),
    )

"""
manifest.py - explicit input in, a validated run plan out.

The package supplies deck geometry and orchestration, but biological reagent,
thermal, cycle, and cleanup values must be present in a ``method`` block. Public
examples use a clearly labeled synthetic water-only profile.

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
    AnalysisType,
    FluorescentDsDNAProfile,
    LocusTarget,
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


def _parse_locus(raw: Any) -> LocusTarget:
    if not isinstance(raw, dict):
        raise ManifestError("`locus` must be a mapping")
    fields = {"name", "pcr_product_bp", "primer_f", "primer_r", "target_position_bp"}
    unknown = sorted(set(raw) - fields)
    if unknown:
        raise ManifestError(f"locus contains unknown field(s): {', '.join(unknown)}")
    name = str(_require(raw, "name", "locus"))
    pcr_product_bp = int(_require(raw, "pcr_product_bp", "locus"))
    return LocusTarget(
        name=name,
        pcr_product_bp=pcr_product_bp,
        primer_f=(str(raw["primer_f"]) if raw.get("primer_f") else None),
        primer_r=(str(raw["primer_r"]) if raw.get("primer_r") else None),
        target_position_bp=(int(raw["target_position_bp"]) if "target_position_bp" in raw else None),
    )


def _parse_acceptance(raw: Any) -> AcceptanceCriteria:
    """Acceptance criteria: start from the documented rubric, then apply overrides.

    This is deliberate. The defaults ARE the standard; a manifest that overrides a
    cutoff is making an explicit, visible choice, and the report shows the value that
    was in force. An empty or absent block means "use the standard", which is what an
    operator at a new site should do until they have a reason not to.
    """
    defaults = AcceptanceCriteria()
    if raw is None:
        return defaults
    if not isinstance(raw, dict):
        raise ManifestError("`acceptance` must be a mapping if present")
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
    values = {field: getattr(defaults, field) for field in fields}
    values.update(raw)
    try:
        return AcceptanceCriteria(
            lh_cv_max_percent=float(values["lh_cv_max_percent"]),
            lh_recovery_tolerance_percent=float(
                values["lh_recovery_tolerance_percent"]
            ),
            lh_qualified_volumes_ul=[
                float(value) for value in values["lh_qualified_volumes_ul"]
            ],
            curve_r2_min=float(values["curve_r2_min"]),
            wgs_prep_yield_min_ng=float(values["wgs_prep_yield_min_ng"]),
            wgs_prep_uniformity_cv_max_percent=float(
                values["wgs_prep_uniformity_cv_max_percent"]
            ),
            pcr_enrichment_conc_min_ng_per_ul=float(
                values["pcr_enrichment_conc_min_ng_per_ul"]
            ),
            pcr_enrichment_conc_max_ng_per_ul=float(
                values["pcr_enrichment_conc_max_ng_per_ul"]
            ),
        )
    except (TypeError, ValueError) as exc:
        raise ManifestError(f"acceptance: {exc}") from exc


def _parse_fluorescent_dsdna(raw: Any) -> FluorescentDsDNAProfile:
    if not isinstance(raw, dict):
        raise ManifestError("`fluorescent_dsdna` must be an operator-supplied mapping")
    required = (
        "profile_label",
        "excitation_nm",
        "emission_nm",
        "standards_ng_per_ml",
    )
    unknown = sorted(set(raw) - set(required))
    if unknown:
        raise ManifestError(
            f"fluorescent_dsdna has unrecognized fields: {', '.join(unknown)}"
        )
    try:
        return FluorescentDsDNAProfile(
            profile_label=str(_require(raw, "profile_label", "fluorescent_dsdna")),
            excitation_nm=float(_require(raw, "excitation_nm", "fluorescent_dsdna")),
            emission_nm=float(_require(raw, "emission_nm", "fluorescent_dsdna")),
            standards_ng_per_ml=[
                float(value)
                for value in _require(
                    raw, "standards_ng_per_ml", "fluorescent_dsdna"
                )
            ],
        )
    except (TypeError, ValueError) as exc:
        raise ManifestError(f"fluorescent_dsdna: {exc}") from exc


def _parse_method(raw: Any) -> MethodParameters:
    if not isinstance(raw, dict):
        raise ManifestError("`method` must be an operator-supplied mapping")
    fields = (
        "profile_kind",
        "parameter_source",
        "wgs_stage_1_ul",
        "wgs_stage_2_ul",
        "wgs_odtc_profile",
        "pcr_stage_1_transfer_ul",
        "pcr_stage_2_transfer_ul",
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
        "indexing_overhang_bp",
        "pool_target_mass_ng",
        "fragment_window_below_bp",
        "fragment_window_above_bp",
        "dimer_flag_below_bp",
    )
    unknown = sorted(set(raw) - set(fields))
    if unknown:
        raise ManifestError(f"method contains unknown field(s): {', '.join(unknown)}")
    missing = [field for field in fields if field not in raw]
    if missing:
        raise ManifestError(f"method is missing required field(s): {', '.join(missing)}")
    try:
        return MethodParameters(
            profile_kind=ProfileKind(raw["profile_kind"]),
            parameter_source=str(raw["parameter_source"]),
            wgs_stage_1_ul=float(raw["wgs_stage_1_ul"]),
            wgs_stage_2_ul=float(raw["wgs_stage_2_ul"]),
            wgs_odtc_profile=str(raw["wgs_odtc_profile"]),
            pcr_stage_1_transfer_ul=float(raw["pcr_stage_1_transfer_ul"]),
            pcr_stage_2_transfer_ul=float(raw["pcr_stage_2_transfer_ul"]),
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
            indexing_overhang_bp=int(raw["indexing_overhang_bp"]),
            pool_target_mass_ng=float(raw["pool_target_mass_ng"]),
            fragment_window_below_bp=int(raw["fragment_window_below_bp"]),
            fragment_window_above_bp=int(raw["fragment_window_above_bp"]),
            dimer_flag_below_bp=int(raw["dimer_flag_below_bp"]),
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

    analysis_raw = data.get("analysis", {})
    analysis_type_raw = analysis_raw.get("type", "unknown") if isinstance(analysis_raw, dict) else "unknown"
    try:
        analysis_type = AnalysisType(analysis_type_raw)
    except ValueError:
        valid = ", ".join(e.value for e in AnalysisType)
        raise ManifestError(f"analysis type {analysis_type_raw!r} is not one of: {valid}")

    samples = _parse_samples(_require(data, "samples", "manifest"))
    locus = _parse_locus(_require(data, "locus", "manifest"))
    acceptance = _parse_acceptance(data.get("acceptance"))
    method = _parse_method(_require(data, "method", "manifest"))
    fluorescent_dsdna = _parse_fluorescent_dsdna(
        _require(data, "fluorescent_dsdna", "manifest")
    )
    if mode is RunMode.HARDWARE and method.profile_kind is not ProfileKind.OPERATOR:
        raise ManifestError(
            "hardware mode requires method profile_kind='operator'; synthetic profiles "
            "are water-only"
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
        locus=locus,
        analysis_type=analysis_type,
        deck=deck,
        acceptance=acceptance,
        method=method,
        fluorescent_dsdna=fluorescent_dsdna,
        output_dir=output_dir,
        tip_column=tip_column,
        notes=str(data.get("notes", "")),
    )

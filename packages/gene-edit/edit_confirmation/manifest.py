"""
manifest.py - sparse input in, a full validated run plan out.

The product promise is "standardized from sparse input": an operator writes down the
few things that are specific to their run (which samples, in which wells, the locus
they are genotyping, and whether this is a dry simulation or the real thing) and the
package supplies everything else from pinned defaults - the deck, the reagent recipes,
the thermal programs, the QC cutoffs. This module is that expansion.

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
    EditType,
    LocusTarget,
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
    name = str(_require(raw, "name", "locus"))
    target_product_bp = int(_require(raw, "target_product_bp", "locus"))
    return LocusTarget(
        name=name,
        target_product_bp=target_product_bp,
        pcr1_anneal_c=(float(raw["pcr1_anneal_c"]) if "pcr1_anneal_c" in raw else None),
        primer_f=(str(raw["primer_f"]) if raw.get("primer_f") else None),
        primer_r=(str(raw["primer_r"]) if raw.get("primer_r") else None),
        edit_position_bp=(int(raw["edit_position_bp"]) if "edit_position_bp" in raw else None),
    )


def _parse_acceptance(raw: Any) -> AcceptanceCriteria:
    """Acceptance criteria: start from the pinned defaults, override only what is given.

    This is deliberate. The defaults ARE the standard; a manifest that overrides a
    cutoff is making an explicit, visible choice, and the report shows the value that
    was in force. An empty or absent block means "use the standard", which is what an
    operator at a new site should do until they have a reason not to.
    """
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

    edit_raw = data.get("edit", {})
    edit_type_raw = edit_raw.get("type", "unknown") if isinstance(edit_raw, dict) else "unknown"
    try:
        edit_type = EditType(edit_type_raw)
    except ValueError:
        valid = ", ".join(e.value for e in EditType)
        raise ManifestError(f"edit type {edit_type_raw!r} is not one of: {valid}")

    samples = _parse_samples(_require(data, "samples", "manifest"))
    locus = _parse_locus(_require(data, "locus", "manifest"))
    acceptance = _parse_acceptance(data.get("acceptance"))

    deck = DeckLayout.bio_validation_0()
    if data.get("deck") not in (None, "bio_validation_0"):
        raise ManifestError(
            f"deck {data.get('deck')!r} is not defined; only 'bio_validation_0' ships. "
            "Add a DeckLayout for a new deck before referencing it."
        )

    pcr2_cycles = int(data.get("pcr2_cycles", 8))
    if not (8 <= pcr2_cycles <= 12):
        raise ManifestError(
            f"pcr2_cycles={pcr2_cycles} is outside the protocol range 8 to 10 "
            "(with 1-2 more allowed if bands are faint); refusing to guess"
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
        edit_type=edit_type,
        deck=deck,
        acceptance=acceptance,
        output_dir=output_dir,
        pcr2_cycles=pcr2_cycles,
        tip_column=tip_column,
        notes=str(data.get("notes", "")),
    )

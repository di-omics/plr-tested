"""End-to-end tests: the flow, the gates that narrow it, and the ways it stops."""

import copy

import pytest

from sequencing_validation import build_run
from sequencing_validation.config import RunMode
from sequencing_validation.manifest import ManifestError
from sequencing_validation.orchestrator import RunStatus, run
from sequencing_validation.reporting.report import render_dossier
from sequencing_validation.simulation import POORLY_TUNED_DECK

BASE = {
    "run_id": "SEQ-TEST",
    "operator": "di",
    "mode": "simulation",
    "assay": {"type": "variant_detection"},
    "target": {"name": "target_region_01", "target_product_bp": 250},
    "method": {
        "profile_kind": "synthetic_water",
        "parameter_source": "test fixture; synthetic water only",
        "wgs_input_preparation_ul": 10,
        "wgs_reaction_mix_ul": 10,
        "wgs_odtc_profile": "wgs_prep",
        "pcr1_mastermix_ul": 10,
        "pcr2_mastermix_ul": 10,
        "pcr_reaction_volume_ul": 20,
        "post_pcr1_cleanup_ratio": 1,
        "post_pcr2_cleanup_ratio": 1,
        "supernatant_margin_ul": 0,
        "pcr1_anneal_c": 40,
        "pcr2_cycles": 2,
        "pcr1_odtc_profile": "pcr-enrichment-round1",
        "pcr2_odtc_profile": "pcr-enrichment-round2",
        "wgs_qc_dilution": 1,
        "pcr_qc_dilution": 1,
        "wgs_product_volume_ul": 20,
        "pcr_library_volume_ul": 20,
        "fluorescent_dsdna_excitation_nm": 400,
        "fluorescent_dsdna_emission_nm": 500,
        "fluorescent_dsdna_standards_ng_per_ml": [0, 1, 2, 3],
    },
    "acceptance": {
        "lh_cv_max_percent": 5,
        "lh_recovery_tolerance_percent": 20,
        "lh_qualified_volumes_ul": [10, 20, 50, 100],
        "curve_r2_min": 0.95,
        "wgs_prep_yield_min_ng": 50,
        "wgs_prep_uniformity_cv_max_percent": 50,
        "pcr_enrichment_conc_min_ng_per_ul": 1,
        "pcr_enrichment_conc_max_ng_per_ul": 100,
    },
    "samples": [
        {"id": "s1", "well": "A1"},
        {"id": "s2", "well": "B1"},
        {"id": "pos", "well": "C1", "type": "pos_ctrl"},
        {"id": "ntc", "well": "H1", "type": "ntc"},
    ],
}


def _cfg(**over):
    data = copy.deepcopy(BASE)
    data.update(over)
    return build_run(data)


def test_simulation_completes_and_drops_ntc_before_pcr_enrichment():
    out = run(_cfg(), timestamp="t")
    assert out.status is RunStatus.COMPLETED
    # the no-template well fails the post-WGS preparation yield gate and never reaches sequencing
    assert "ntc" not in out.final_active_sample_ids
    assert set(out.final_active_sample_ids) == {"s1", "s2", "pos"}
    # six stages ran to handoff
    assert [s.name for s in out.stages][-1] == "handoff"


def test_deterministic_and_gate_relative_simulation():
    a = run(_cfg(), timestamp="t")
    b = run(_cfg(), timestamp="t")
    assert a.to_dict()["stages"][2]["data"]["samples"] == \
        b.to_dict()["stages"][2]["data"]["samples"]

    scaled_acceptance = copy.deepcopy(BASE["acceptance"])
    scaled_acceptance["wgs_prep_yield_min_ng"] *= 2
    scaled_acceptance["pcr_enrichment_conc_min_ng_per_ul"] *= 2
    scaled_acceptance["pcr_enrichment_conc_max_ng_per_ul"] *= 2
    scaled = run(_cfg(acceptance=scaled_acceptance), timestamp="t")

    assert scaled.stages[2].data["samples"][0]["mass_ng"] > \
        a.stages[2].data["samples"][0]["mass_ng"]
    assert scaled.stages[4].data["samples"][0]["concentration_ng_per_ul"] > \
        a.stages[4].data["samples"][0]["concentration_ng_per_ul"]

    larger_product = copy.deepcopy(BASE["method"])
    larger_product["wgs_product_volume_ul"] *= 2
    volume_scaled = run(_cfg(method=larger_product), timestamp="t")
    base_wgs = a.stages[2].data["samples"][0]
    scaled_wgs = volume_scaled.stages[2].data["samples"][0]
    assert scaled_wgs["concentration_ng_per_ul"] < base_wgs["concentration_ng_per_ul"]
    assert scaled_wgs["mass_ng"] == pytest.approx(base_wgs["mass_ng"], rel=0.02)

    narrow_acceptance = copy.deepcopy(BASE["acceptance"])
    midpoint = narrow_acceptance["pcr_enrichment_conc_max_ng_per_ul"]
    half_width = midpoint / 50
    narrow_acceptance["pcr_enrichment_conc_min_ng_per_ul"] = midpoint - half_width
    narrow_acceptance["pcr_enrichment_conc_max_ng_per_ul"] = midpoint + half_width
    narrow = run(_cfg(acceptance=narrow_acceptance), timestamp="t")
    assert narrow.status is RunStatus.COMPLETED
    assert all(row["passed"] for row in narrow.stages[4].data["samples"])


def test_poor_deck_stops_at_gate_0():
    out = run(_cfg(run_id="SEQ-POOR"), timestamp="t", deck_quality=POORLY_TUNED_DECK)
    assert out.status is RunStatus.STOPPED
    assert len(out.stages) == 1
    assert out.stages[0].name == "lh_qc"


def test_hardware_without_calibration_is_blocked():
    method = copy.deepcopy(BASE["method"])
    method.update({
        "profile_kind": "operator",
        "parameter_source": "/secure/operator-method.json",
        "wgs_odtc_profile": "/secure/wgs-thermal.json",
        "pcr1_odtc_profile": "/secure/pcr1-thermal.json",
        "pcr2_odtc_profile": "/secure/pcr2-thermal.json",
    })
    out = run(_cfg(run_id="SEQ-HW", mode="hardware", method=method), timestamp="t")
    assert out.status is RunStatus.STOPPED
    assert len(out.guard_blocking) == 2   # working concentration + reader gain


def test_tip_column_reaches_resolved_commands():
    # A hardware run stops at Gate 0 provenance before dispensing, so unit-test the
    # adapter directly: the site-specific tip column must reach the resolved Pi command.
    from sequencing_validation.instruments.star import StarAdapter
    from sequencing_validation.config import ProfileKind
    star = StarAdapter(RunMode.HARDWARE, tip_column=3)
    star.add_mastermix(
        "PCR1",
        10,
        "p50",
        "01_pcr_enrichment_round1_mastermix_col1.py",
        ProfileKind.SYNTHETIC_WATER,
        "test fixture; synthetic water only",
    )
    assert star.run_card()
    assert any("--tip-col 3" in c for c in star.run_card())


def test_dossier_renders_without_error():
    out = run(_cfg(run_id="SEQ-DOSS"), timestamp="t")
    html = render_dossier(out)
    assert "<!doctype html>" in html
    assert "SEQ-DOSS" in html
    assert "Gate 0" in html


def test_manifest_rejects_bad_well():
    with pytest.raises(ManifestError):
        build_run({**BASE, "samples": [{"id": "x", "well": "Z9"}]})


def test_manifest_rejects_duplicate_well():
    with pytest.raises(ManifestError):
        build_run({**BASE, "samples": [
            {"id": "a", "well": "A1"}, {"id": "b", "well": "A1"}]})


def test_manifest_rejects_out_of_range_pcr2_cycles():
    method = copy.deepcopy(BASE["method"])
    method["pcr2_cycles"] = 0
    with pytest.raises(ManifestError):
        _cfg(method=method)


def test_manifest_requires_explicit_method_and_acceptance():
    missing_method = copy.deepcopy(BASE)
    missing_method.pop("method")
    with pytest.raises(ManifestError, match="method"):
        build_run(missing_method)

    missing_acceptance = copy.deepcopy(BASE)
    missing_acceptance.pop("acceptance")
    with pytest.raises(ManifestError, match="acceptance"):
        build_run(missing_acceptance)

    invalid_acceptance = copy.deepcopy(BASE["acceptance"])
    invalid_acceptance["wgs_prep_yield_min_ng"] = 0
    with pytest.raises(ManifestError, match="must be positive"):
        _cfg(acceptance=invalid_acceptance)

    invalid_acceptance = copy.deepcopy(BASE["acceptance"])
    invalid_acceptance["pcr_enrichment_conc_max_ng_per_ul"] = \
        invalid_acceptance["pcr_enrichment_conc_min_ng_per_ul"]
    with pytest.raises(ManifestError, match="less than maximum"):
        _cfg(acceptance=invalid_acceptance)


def test_hardware_rejects_public_synthetic_profile():
    with pytest.raises(ManifestError, match="water-only"):
        _cfg(mode="hardware")

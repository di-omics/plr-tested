"""End-to-end tests: the flow, the gates that narrow it, and the ways it stops."""

import copy
from dataclasses import asdict

import pytest

from assay_validation import build_run
from assay_validation.config import AcceptanceCriteria, RunMode
from assay_validation.manifest import ManifestError
from assay_validation.orchestrator import RunStatus, run
from assay_validation.reporting.report import render_dossier
from assay_validation.simulation import POORLY_TUNED_DECK

BASE = {
    "run_id": "SEQ-TEST",
    "operator": "di",
    "mode": "simulation",
    "analysis": {"type": "variant_calling"},
    "locus": {"name": "target_1", "pcr_product_bp": 250},
    "method": {
        "profile_kind": "synthetic_water",
        "parameter_source": "test fixture; synthetic water only",
        "wgs_stage_1_ul": 10,
        "wgs_stage_2_ul": 10,
        "wgs_odtc_profile": "synthetic-water-only-wgs.json",
        "pcr_stage_1_transfer_ul": 10,
        "pcr_stage_2_transfer_ul": 10,
        "pcr_reaction_volume_ul": 20,
        "post_pcr1_cleanup_ratio": 1,
        "post_pcr2_cleanup_ratio": 1,
        "supernatant_margin_ul": 0,
        "pcr1_anneal_c": 40,
        "pcr2_cycles": 2,
        "pcr1_odtc_profile": "synthetic-water-only-pcr1.json",
        "pcr2_odtc_profile": "synthetic-water-only-pcr2.json",
        "wgs_qc_dilution": 1,
        "pcr_qc_dilution": 1,
        "wgs_product_volume_ul": 20,
        "pcr_library_volume_ul": 20,
        "indexing_overhang_bp": 10,
        "pool_target_mass_ng": 1,
        "fragment_window_below_bp": 5,
        "fragment_window_above_bp": 5,
        "dimer_flag_below_bp": 5,
    },
    "fluorescent_dsdna": {
        "profile_label": "synthetic-water-only",
        "excitation_nm": 400,
        "emission_nm": 500,
        "standards_ng_per_ml": [0, 100, 200, 300],
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

    scaled_acceptance = asdict(AcceptanceCriteria())
    scaled_acceptance["wgs_prep_yield_min_ng"] *= 2
    scaled_acceptance["pcr_enrichment_conc_min_ng_per_ul"] *= 2
    scaled_acceptance["pcr_enrichment_conc_max_ng_per_ul"] *= 2
    scaled = run(_cfg(acceptance=scaled_acceptance), timestamp="t")

    assert (
        scaled.stages[2].data["samples"][0]["mass_ng"]
        > a.stages[2].data["samples"][0]["mass_ng"]
    )
    assert (
        scaled.stages[4].data["samples"][0]["concentration_ng_per_ul"]
        > a.stages[4].data["samples"][0]["concentration_ng_per_ul"]
    )

    larger_product = copy.deepcopy(BASE["method"])
    larger_product["wgs_product_volume_ul"] *= 2
    volume_scaled = run(_cfg(method=larger_product), timestamp="t")
    base_wgs = a.stages[2].data["samples"][0]
    scaled_wgs = volume_scaled.stages[2].data["samples"][0]
    assert scaled_wgs["concentration_ng_per_ul"] < base_wgs["concentration_ng_per_ul"]
    assert scaled_wgs["mass_ng"] == pytest.approx(base_wgs["mass_ng"], rel=0.02)

    narrow_acceptance = asdict(AcceptanceCriteria())
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
    operator_method = {
        **BASE["method"],
        "profile_kind": "operator",
        "parameter_source": "controlled local test profile",
        "wgs_odtc_profile": "/secure/wgs.json",
        "pcr1_odtc_profile": "/secure/pcr1.json",
        "pcr2_odtc_profile": "/secure/pcr2.json",
    }
    out = run(
        _cfg(run_id="SEQ-HW", mode="hardware", method=operator_method),
        timestamp="t",
    )
    assert out.status is RunStatus.STOPPED
    assert len(out.guard_blocking) == 2   # working concentration + reader gain


def test_hardware_manifest_rejects_synthetic_method():
    with pytest.raises(ManifestError, match="profile_kind='operator'"):
        _cfg(run_id="SEQ-HW-SYNTHETIC", mode="hardware")


def test_tip_column_reaches_resolved_commands():
    # A hardware run stops at Gate 0 provenance before dispensing, so unit-test the
    # adapter directly: the site-specific tip column must reach the resolved Pi command.
    from assay_validation.instruments.star import StarAdapter
    star = StarAdapter(RunMode.HARDWARE, tip_column=3)
    star.add_mastermix("PCR1", 10, "p50", "01_pcr_enrichment_round1_mastermix_col1.py")
    assert star.run_card()
    assert any("--tip-col 3" in c for c in star.run_card())


def test_odtc_hardware_command_uses_operator_profile():
    from assay_validation.instruments.odtc import OdtcAdapter
    odtc = OdtcAdapter(RunMode.HARDWARE)
    odtc.run_program("/secure/local method.json")
    assert odtc.run_card()
    assert any(
        "--operator-profile '/secure/local method.json'" in command
        for command in odtc.run_card()
    )
    assert all("--program" not in command for command in odtc.run_card())


def test_dossier_renders_without_error():
    out = run(_cfg(run_id="SEQ-DOSS"), timestamp="t")
    html = render_dossier(out)
    assert "<!doctype html>" in html
    assert "SEQ-DOSS" in html
    assert "Gate 0" in html
    assert "Stage 1 / stage 2" in html
    assert "None uL" not in html


def test_manifest_rejects_bad_well():
    with pytest.raises(ManifestError):
        build_run({**BASE, "samples": [{"id": "x", "well": "Z9"}]})


def test_manifest_rejects_duplicate_well():
    with pytest.raises(ManifestError):
        build_run({**BASE, "samples": [
            {"id": "a", "well": "A1"}, {"id": "b", "well": "A1"}]})


def test_manifest_rejects_out_of_range_pcr2_cycles():
    with pytest.raises(ManifestError):
        _cfg(method={**BASE["method"], "pcr2_cycles": 0})


def test_manifest_rejects_invalid_acceptance_ranges():
    invalid_acceptance = asdict(AcceptanceCriteria())
    invalid_acceptance["wgs_prep_yield_min_ng"] = 0
    with pytest.raises(ManifestError, match="must be positive"):
        _cfg(acceptance=invalid_acceptance)

    invalid_acceptance = asdict(AcceptanceCriteria())
    invalid_acceptance["pcr_enrichment_conc_max_ng_per_ul"] = \
        invalid_acceptance["pcr_enrichment_conc_min_ng_per_ul"]
    with pytest.raises(ManifestError, match="less than maximum"):
        _cfg(acceptance=invalid_acceptance)

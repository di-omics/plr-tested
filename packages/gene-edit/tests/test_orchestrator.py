"""End-to-end tests: the flow, the gates that narrow it, and the ways it stops."""

import copy

import pytest

from edit_confirmation import build_run
from edit_confirmation.config import RunMode
from edit_confirmation.manifest import ManifestError
from edit_confirmation.orchestrator import RunStatus, run
from edit_confirmation.reporting.report import render_dossier
from edit_confirmation.simulation import POORLY_TUNED_DECK

BASE = {
    "run_id": "EC-TEST",
    "operator": "di",
    "mode": "simulation",
    "edit": {"type": "crispr_indel"},
    "locus": {"name": "EMX1", "amplicon_bp": 250},
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


def test_simulation_completes_and_drops_ntc_before_ampseq():
    out = run(_cfg(), timestamp="t")
    assert out.status is RunStatus.COMPLETED
    # the no-template well fails the post-whole-genome amplification yield gate and never reaches sequencing
    assert "ntc" not in out.final_active_sample_ids
    assert set(out.final_active_sample_ids) == {"s1", "s2", "pos"}
    # six stages ran to handoff
    assert [s.name for s in out.stages][-1] == "handoff"


def test_deterministic_same_manifest_same_result():
    a = run(_cfg(), timestamp="t")
    b = run(_cfg(), timestamp="t")
    assert a.to_dict()["stages"][2]["data"]["samples"] == \
        b.to_dict()["stages"][2]["data"]["samples"]


def test_poor_deck_stops_at_gate_0():
    out = run(_cfg(run_id="EC-POOR"), timestamp="t", deck_quality=POORLY_TUNED_DECK)
    assert out.status is RunStatus.STOPPED
    assert len(out.stages) == 1
    assert out.stages[0].name == "lh_qc"


def test_hardware_without_calibration_is_blocked():
    out = run(_cfg(run_id="EC-HW", mode="hardware"), timestamp="t")
    assert out.status is RunStatus.STOPPED
    assert len(out.guard_blocking) == 2   # working concentration + reader gain


def test_tip_column_reaches_resolved_commands():
    # A hardware run stops at Gate 0 provenance before dispensing, so unit-test the
    # adapter directly: the site-specific tip column must reach the resolved Pi command.
    from edit_confirmation.instruments.star import StarAdapter
    star = StarAdapter(RunMode.HARDWARE, tip_column=3)
    star.add_mastermix("PCR1", 22.5, "p50", "01_ampseq_pcr1_mastermix_col1.py")
    assert star.run_card()
    assert any("--tip-col 3" in c for c in star.run_card())


def test_dossier_renders_without_error():
    out = run(_cfg(run_id="EC-DOSS"), timestamp="t")
    html = render_dossier(out)
    assert "<!doctype html>" in html
    assert "EC-DOSS" in html
    assert "Gate 0" in html


def test_manifest_rejects_bad_well():
    with pytest.raises(ManifestError):
        build_run({**BASE, "samples": [{"id": "x", "well": "Z9"}]})


def test_manifest_rejects_duplicate_well():
    with pytest.raises(ManifestError):
        build_run({**BASE, "samples": [
            {"id": "a", "well": "A1"}, {"id": "b", "well": "A1"}]})


def test_manifest_rejects_out_of_range_pcr2_cycles():
    with pytest.raises(ManifestError):
        _cfg(pcr2_cycles=20)

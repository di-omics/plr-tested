"""Integration tests: the full flow, the gates stopping it, and the manifest guardrails."""

import pytest

from elispot.config import RunMode
from elispot.instruments.base import AwaitingData
from elispot.instruments.imager import ImagerAdapter
from elispot.manifest import ManifestError, build_run
from elispot.orchestrator import RunStatus, run
from elispot.simulation import (
    DEAD_CELLS_PLATE,
    HIGH_BACKGROUND_PLATE,
    POOR_WASHER,
    WELL_TUNED_WASHER,
)


def _manifest(mode="simulation"):
    return {
        "run_id": "T1", "operator": "tester", "mode": mode,
        "site": {"name": "test", "cells_per_well": 250000},
        "wells": [
            {"well": "A1", "role": "neg_ctrl", "antigen": "medium"},
            {"well": "B1", "role": "neg_ctrl", "antigen": "medium"},
            {"well": "C1", "role": "neg_ctrl", "antigen": "medium"},
            {"well": "D1", "role": "pos_ctrl", "antigen": "PHA"},
            {"well": "E1", "role": "pos_ctrl", "antigen": "PHA"},
            {"well": "F1", "role": "pos_ctrl", "antigen": "PHA"},
            {"well": "A2", "role": "test", "antigen": "CEF"},        # responder in sim
            {"well": "B2", "role": "test", "antigen": "CEF"},
            {"well": "C2", "role": "test", "antigen": "CEF"},
            {"well": "A3", "role": "test", "antigen": "CMV_pp65"},   # non-responder in sim
            {"well": "B3", "role": "test", "antigen": "CMV_pp65"},
            {"well": "C3", "role": "test", "antigen": "CMV_pp65"},
        ],
    }


def _run(**kw):
    return run(build_run(_manifest()), timestamp="test", **kw)


def _responses(outcome):
    handoff = [s for s in outcome.stages if s.name == "handoff"][0]
    return {r["antigen"]: r for r in handoff.data["responses"]}


def test_full_run_completes_and_calls_responses():
    out = _run()
    assert out.status is RunStatus.COMPLETED
    resp = _responses(out)
    assert resp["CEF"]["positive"] is True
    assert resp["CMV_pp65"]["positive"] is False


def test_run_is_deterministic():
    a = _responses(_run())
    b = _responses(_run())
    assert a["CEF"]["net_sfu"] == b["CEF"]["net_sfu"]


def test_poor_washer_stops_at_gate0_before_the_plate():
    out = run(build_run(_manifest()), timestamp="t", washer_quality=POOR_WASHER)
    assert out.status is RunStatus.STOPPED
    assert out.stages[0].name == "readiness"
    assert out.stages[0].status.value == "stopped"
    # nothing past Gate 0 ran
    assert len(out.stages) == 1


def test_high_background_voids_the_plate_at_gate2():
    out = run(build_run(_manifest()), timestamp="t", biology=HIGH_BACKGROUND_PLATE)
    assert out.status is RunStatus.STOPPED
    readout = [s for s in out.stages if s.name == "readout"][0]
    assert readout.status.value == "stopped"
    assert "background" in readout.message


def test_dead_positive_control_voids_the_plate_at_gate2():
    out = run(build_run(_manifest()), timestamp="t", biology=DEAD_CELLS_PLATE)
    assert out.status is RunStatus.STOPPED
    readout = [s for s in out.stages if s.name == "readout"][0]
    assert readout.status.value == "stopped"
    assert "positive-control" in readout.message


def test_hardware_run_blocks_on_provenance_before_any_instrument():
    out = run(build_run(_manifest(mode="hardware")), timestamp="t")
    assert out.status is RunStatus.STOPPED
    assert out.stages[0].name == "readiness"
    # the membrane clearance and reader calibration are named as blocking
    blocking = " ".join(out.guard_blocking)
    assert "aspiration_clearance" in blocking


def test_completed_run_emits_recommendations_and_csv():
    out = _run()
    handoff = [s for s in out.stages if s.name == "handoff"][0]
    assert handoff.data["recommendations"]           # at least the no-change recommendation
    assert "antigen" in handoff.data["results_csv"]   # header present


def test_manifest_requires_negative_control():
    m = _manifest()
    m["wells"] = [w for w in m["wells"] if w["role"] != "neg_ctrl"]
    with pytest.raises(ManifestError):
        build_run(m)


def test_manifest_requires_positive_control():
    m = _manifest()
    m["wells"] = [w for w in m["wells"] if w["role"] != "pos_ctrl"]
    with pytest.raises(ManifestError):
        build_run(m)


def test_manifest_rejects_duplicate_well():
    m = _manifest()
    m["wells"].append({"well": "A1", "role": "test", "antigen": "CEF"})
    with pytest.raises(ManifestError):
        build_run(m)


def test_manifest_rejects_bad_well_address():
    m = _manifest()
    m["wells"][0]["well"] = "Z9"
    with pytest.raises(ManifestError):
        build_run(m)


def test_manifest_rejects_nonpositive_cell_count():
    m = _manifest()
    m["wells"][6]["cells"] = 0   # a test well with zero cells is nonsensical, not a run
    with pytest.raises(ManifestError):
        build_run(m)


def test_imager_awaits_data_in_hardware_without_a_counts_file():
    imager = ImagerAdapter(RunMode.HARDWARE)
    with pytest.raises(AwaitingData):
        imager.count("R", "plate", {"A1": 10}, saturation_sfu=600)

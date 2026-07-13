"""Tests for the gate machinery, the provenance guard, and the membrane constraints."""

import pytest

from immunoassay.gates import (
    Comparison,
    Criterion,
    Decision,
    SampleVerdict,
    check,
    evaluate_per_sample,
    evaluate_run_level,
)
from immunoassay.membrane import default_constraints
from immunoassay.provenance import (
    Origin,
    ProvenanceError,
    RunGuard,
    calibrate,
    todo,
    transcribed,
    tunable,
)
from immunoassay.reagents.elispot_kit import for_cytokine


def _cv_crit(bound=5.0):
    return Criterion("cv", "dispense CV", Comparison.MAX, bound, unit="%", source="test")


def test_criterion_max_min_range():
    assert _cv_crit(5.0).check(4.9) is True
    assert _cv_crit(5.0).check(5.1) is False
    minc = Criterion("y", "yield", Comparison.MIN, 100.0, source="test")
    assert minc.check(120) is True and minc.check(80) is False
    rng = Criterion("c", "conc", Comparison.RANGE, (2.0, 60.0), source="test")
    assert rng.check(30) is True and rng.check(1) is False and rng.check(61) is False


def test_evaluate_run_level_all_pass_proceeds():
    res = evaluate_run_level("g", [(_cv_crit(), 3.0), (_cv_crit(), 4.0)])
    assert res.decision is Decision.PROCEED
    assert res.passed is True


def test_evaluate_run_level_any_fail_stops():
    res = evaluate_run_level("g", [(_cv_crit(), 3.0), (_cv_crit(), 9.0)])
    assert res.decision is Decision.STOP
    assert res.stopped is True


def test_per_sample_subset_and_stop():
    v = [SampleVerdict("A1", True), SampleVerdict("B1", False), SampleVerdict("C1", True)]
    res = evaluate_per_sample("g", v)
    assert res.decision is Decision.PROCEED_SUBSET
    assert res.passing_sample_ids() == ["A1", "C1"]
    assert res.dropped_sample_ids() == ["B1"]

    allfail = [SampleVerdict("A1", False), SampleVerdict("B1", False)]
    assert evaluate_per_sample("g", allfail).decision is Decision.STOP


def test_per_sample_run_level_failure_forces_stop():
    v = [SampleVerdict("A1", True)]
    bad_run = [check(_cv_crit(), 99.0)]
    res = evaluate_per_sample("g", v, run_outcomes=bad_run)
    assert res.decision is Decision.STOP


def test_sourced_requires_a_source():
    with pytest.raises(ValueError):
        transcribed(5.0, "")


def test_guard_blocks_on_calibrate_and_todo():
    guard = RunGuard()
    guard.add(
        transcribed(3.0, "kit"),
        tunable(100.0, "engineering default"),
        calibrate(None, "measure it"),
        todo("unknown"),
    )
    blocking = guard.blocking()
    assert len(blocking) == 2
    with pytest.raises(ProvenanceError):
        guard.assert_ready_for_hardware()


def test_guard_passes_when_everything_resolved():
    guard = RunGuard()
    guard.add(transcribed(3.0, "kit"), tunable(100.0, "default"))
    guard.assert_ready_for_hardware()   # does not raise
    assert guard.summary()[Origin.CALIBRATE.value] == 0


def test_membrane_clearance_blocks_until_taught():
    untaught = default_constraints(None)
    assert untaught.aspiration_clearance_mm.blocks_hardware is True
    taught = default_constraints(1.2)
    assert taught.aspiration_clearance_mm.blocks_hardware is False
    assert taught.aspiration_clearance_mm.value == 1.2


def test_kit_guard_values_are_the_todos_and_calibrates():
    kit = for_cytokine("IFN-gamma")
    names = {v.name for v in kit.guard_values()}
    # kit concentrations are TODO, the substrate endpoint is CALIBRATE
    assert "coat_antibody_concentration" in names
    assert "detection_antibody_concentration" in names
    assert "substrate_development_endpoint" in names


def test_precoated_kit_drops_the_coat_step():
    assert for_cytokine(precoated=True).step("coat") is None
    assert for_cytokine(precoated=False).step("coat") is not None

"""Tests for the gate decisions and the provenance guard."""

import pytest

from edit_confirmation.gates import (
    Comparison,
    Criterion,
    Decision,
    SampleVerdict,
    check,
    evaluate_per_sample,
    evaluate_run_level,
)
from edit_confirmation.provenance import (
    Origin,
    ProvenanceError,
    RunGuard,
    calibrate,
    todo,
    transcribed,
    tunable,
)


def _cv_crit(bound=5.0):
    return Criterion("cv", "dispense CV", Comparison.MAX, bound, "%", "test")


def test_run_level_stop_on_any_fail():
    good = evaluate_run_level("g", [(_cv_crit(), 3.0), (_cv_crit(), 4.9)])
    assert good.decision is Decision.PROCEED
    bad = evaluate_run_level("g", [(_cv_crit(), 3.0), (_cv_crit(), 6.1)])
    assert bad.decision is Decision.STOP
    assert bad.stopped


def test_range_criterion():
    c = Criterion("c", "conc", Comparison.RANGE, (2.0, 60.0), "ng/uL", "test")
    assert c.check(18.0) is True
    assert c.check(1.0) is False
    assert c.check(61.0) is False


def test_per_sample_subset_and_stop():
    crit = Criterion("y", "yield", Comparison.MIN, 100.0, "ng", "test")
    verdicts = [
        SampleVerdict("a", True, [check(crit, 300.0)]),
        SampleVerdict("b", True, [check(crit, 250.0)]),
        SampleVerdict("c", False, [check(crit, 1.0)]),
    ]
    res = evaluate_per_sample("g", verdicts)
    assert res.decision is Decision.PROCEED_SUBSET
    assert res.passing_sample_ids() == ["a", "b"]
    assert res.dropped_sample_ids() == ["c"]

    all_fail = [SampleVerdict("x", False, [check(crit, 1.0)])]
    assert evaluate_per_sample("g", all_fail).decision is Decision.STOP


def test_per_sample_stops_on_run_level_failure():
    crit = Criterion("y", "yield", Comparison.MIN, 100.0, "ng", "test")
    curve = Criterion("r2", "curve", Comparison.MIN, 0.98, "", "test")
    verdicts = [SampleVerdict("a", True, [check(crit, 300.0)])]
    res = evaluate_per_sample("g", verdicts, run_outcomes=[check(curve, 0.5)])
    assert res.decision is Decision.STOP


def test_provenance_guard_blocks_calibrate_and_todo():
    guard = RunGuard()
    guard.add(
        transcribed(22.5, "script 01", "uL", "mm"),
        tunable(105.0, "standard Q5 lid", "C", "lid"),
        calibrate(None, "measure on reader", "uM", "working_conc"),
        todo("confirm catalog", name="kit"),
    )
    with pytest.raises(ProvenanceError):
        guard.assert_ready_for_hardware()
    assert guard.summary()["transcribed"] == 1
    assert len(guard.blocking()) == 2


def test_sourced_requires_a_source():
    with pytest.raises(ValueError):
        transcribed(1.0, "  ")

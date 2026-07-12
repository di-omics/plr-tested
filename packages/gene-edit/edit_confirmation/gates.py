"""
gates.py - QC checkpoints as first-class objects.

A gate is the thing that stands between two stages and decides whether the run goes
on. It is not a print statement buried in a protocol; it is an object with named
acceptance criteria, a pass/fail on each, and one of three decisions:

  PROCEED         everything passed, continue with all samples.
  PROCEED_SUBSET  some samples passed and some did not, continue with the ones that
                  did, and record which were dropped and why.
  STOP            a run-level criterion failed (the deck is not qualified, the
                  standard curve did not come out straight). No sample is safe to
                  continue, so nothing does.

Every cutoff a gate turns on comes from the acceptance-criteria config, in one place,
so an auditor reads the rubric without reading the code. That is the point of pulling
gates out into their own module: the definition of "correct, correctly executed
science" for this assay is a data file, and the gates enforce it the same way in
every lab.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple


class Comparison(str, Enum):
    MAX = "max"        # measured must be <= bound (e.g. CV <= 5%)
    MIN = "min"        # measured must be >= bound (e.g. yield >= 1 ng)
    RANGE = "range"    # bound is (lo, hi); measured must be within, inclusive


class Decision(str, Enum):
    PROCEED = "proceed"
    PROCEED_SUBSET = "proceed_subset"
    STOP = "stop"


@dataclass(frozen=True)
class Criterion:
    """One acceptance rule. `source` records why the bound is what it is."""

    key: str
    label: str
    comparison: Comparison
    bound: object          # float for MAX/MIN, (lo, hi) tuple for RANGE
    unit: str = ""
    source: str = ""

    def check(self, measured: float) -> bool:
        if self.comparison is Comparison.MAX:
            return measured <= float(self.bound)
        if self.comparison is Comparison.MIN:
            return measured >= float(self.bound)
        if self.comparison is Comparison.RANGE:
            lo, hi = self.bound  # type: ignore[misc]
            return lo <= measured <= hi
        raise ValueError(f"unknown comparison {self.comparison}")

    def bound_label(self) -> str:
        u = f" {self.unit}" if self.unit else ""
        if self.comparison is Comparison.MAX:
            return f"<= {self.bound}{u}"
        if self.comparison is Comparison.MIN:
            return f">= {self.bound}{u}"
        lo, hi = self.bound  # type: ignore[misc]
        return f"{lo} to {hi}{u}"


@dataclass
class Outcome:
    """The result of checking one criterion against one measured value."""

    criterion: Criterion
    measured: float
    passed: bool

    def to_dict(self) -> dict:
        return {
            "key": self.criterion.key,
            "label": self.criterion.label,
            "requirement": self.criterion.bound_label(),
            "measured": round(self.measured, 4),
            "unit": self.criterion.unit,
            "passed": self.passed,
            "source": self.criterion.source,
        }


@dataclass
class SampleVerdict:
    """Per-sample pass/fail at a gate, with the outcomes that decided it."""

    sample_id: str
    passed: bool
    outcomes: List[Outcome] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "sample_id": self.sample_id,
            "passed": self.passed,
            "note": self.note,
            "outcomes": [o.to_dict() for o in self.outcomes],
        }


@dataclass
class GateResult:
    """What a gate decided, and everything it decided it from."""

    gate: str
    decision: Decision
    run_outcomes: List[Outcome] = field(default_factory=list)     # run-level criteria
    sample_verdicts: List[SampleVerdict] = field(default_factory=list)
    message: str = ""

    @property
    def passed(self) -> bool:
        return self.decision in (Decision.PROCEED, Decision.PROCEED_SUBSET)

    @property
    def stopped(self) -> bool:
        return self.decision is Decision.STOP

    def passing_sample_ids(self) -> List[str]:
        return [v.sample_id for v in self.sample_verdicts if v.passed]

    def dropped_sample_ids(self) -> List[str]:
        return [v.sample_id for v in self.sample_verdicts if not v.passed]

    def to_dict(self) -> dict:
        return {
            "gate": self.gate,
            "decision": self.decision.value,
            "message": self.message,
            "run_outcomes": [o.to_dict() for o in self.run_outcomes],
            "sample_verdicts": [v.to_dict() for v in self.sample_verdicts],
            "passing": self.passing_sample_ids(),
            "dropped": self.dropped_sample_ids(),
        }


def check(criterion: Criterion, measured: float) -> Outcome:
    return Outcome(criterion=criterion, measured=measured, passed=criterion.check(measured))


def evaluate_run_level(gate: str, pairs: List[Tuple[Criterion, float]],
                       message_pass: str = "", message_fail: str = "") -> GateResult:
    """A gate with only run-level criteria: pass all, or STOP.

    Used by the liquid-handling qualification (the deck is qualified or it is not) and
    by a standard-curve quality check (the curve is straight or it is not).
    """
    outcomes = [check(c, m) for c, m in pairs]
    all_pass = all(o.passed for o in outcomes)
    if all_pass:
        return GateResult(gate=gate, decision=Decision.PROCEED, run_outcomes=outcomes,
                          message=message_pass or "all run-level criteria passed")
    failed = [o.criterion.label for o in outcomes if not o.passed]
    return GateResult(gate=gate, decision=Decision.STOP, run_outcomes=outcomes,
                      message=message_fail or f"run stopped: {', '.join(failed)} failed")


def evaluate_per_sample(gate: str, verdicts: List[SampleVerdict],
                        run_outcomes: Optional[List[Outcome]] = None,
                        require_at_least_one: bool = True) -> GateResult:
    """A gate that decides sample by sample.

    If a run-level criterion (passed in run_outcomes) failed, the whole gate STOPs
    regardless of samples. Otherwise: all samples pass -> PROCEED; some pass ->
    PROCEED_SUBSET; none pass -> STOP (nothing to carry forward).
    """
    run_outcomes = run_outcomes or []
    if any(not o.passed for o in run_outcomes):
        failed = [o.criterion.label for o in run_outcomes if not o.passed]
        return GateResult(gate=gate, decision=Decision.STOP, run_outcomes=run_outcomes,
                          sample_verdicts=verdicts,
                          message=f"run stopped: {', '.join(failed)} failed")

    n_pass = sum(1 for v in verdicts if v.passed)
    n_total = len(verdicts)
    if n_total == 0:
        return GateResult(gate=gate, decision=Decision.STOP, run_outcomes=run_outcomes,
                          message="no samples reached this gate")
    if n_pass == 0 and require_at_least_one:
        return GateResult(gate=gate, decision=Decision.STOP, run_outcomes=run_outcomes,
                          sample_verdicts=verdicts,
                          message="every sample failed this gate; nothing to carry forward")
    if n_pass == n_total:
        return GateResult(gate=gate, decision=Decision.PROCEED, run_outcomes=run_outcomes,
                          sample_verdicts=verdicts,
                          message=f"all {n_total} samples passed")
    return GateResult(gate=gate, decision=Decision.PROCEED_SUBSET, run_outcomes=run_outcomes,
                      sample_verdicts=verdicts,
                      message=f"{n_pass} of {n_total} samples passed; "
                              f"continuing with the {n_pass} that did")

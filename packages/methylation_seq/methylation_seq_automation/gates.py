"""Generic run-level and per-library acceptance gates."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from .config import MetricRule, RunConfig, SampleType
from .protocol import qualified_volumes


class Decision(str, Enum):
    PROCEED = "proceed"
    PROCEED_SUBSET = "proceed_subset"
    STOP = "stop"


@dataclass(frozen=True)
class Outcome:
    key: str
    label: str
    requirement: str
    measured: Optional[float]
    unit: str
    passed: bool
    source: str

    def to_dict(self) -> dict:
        return {
            "key": self.key, "label": self.label, "requirement": self.requirement,
            "measured": self.measured, "unit": self.unit, "passed": self.passed,
            "source": self.source,
        }


@dataclass
class SampleVerdict:
    sample_id: str
    passed: bool
    outcomes: List[Outcome]

    def to_dict(self) -> dict:
        return {
            "sample_id": self.sample_id, "passed": self.passed,
            "outcomes": [item.to_dict() for item in self.outcomes],
        }


@dataclass
class GateResult:
    gate: str
    decision: Decision
    message: str
    run_outcomes: List[Outcome] = field(default_factory=list)
    sample_verdicts: List[SampleVerdict] = field(default_factory=list)

    @property
    def stopped(self) -> bool:
        return self.decision is Decision.STOP

    @property
    def passing_sample_ids(self) -> List[str]:
        return [item.sample_id for item in self.sample_verdicts if item.passed]

    @property
    def dropped_sample_ids(self) -> List[str]:
        return [item.sample_id for item in self.sample_verdicts if not item.passed]

    def to_dict(self) -> dict:
        return {
            "gate": self.gate, "decision": self.decision.value, "message": self.message,
            "run_outcomes": [item.to_dict() for item in self.run_outcomes],
            "sample_verdicts": [item.to_dict() for item in self.sample_verdicts],
            "passing": self.passing_sample_ids, "dropped": self.dropped_sample_ids,
        }


def _outcome(rule: MetricRule, value: Any) -> Outcome:
    measured = float(value) if value is not None else None
    passed = measured is not None
    parts = []
    if rule.minimum is not None:
        parts.append(f">= {rule.minimum:g}")
        passed = passed and measured >= rule.minimum
    if rule.maximum is not None:
        parts.append(f"<= {rule.maximum:g}")
        passed = passed and measured <= rule.maximum
    return Outcome(
        rule.metric, rule.label, " and ".join(parts), measured, rule.unit, passed,
        "selected method profile acceptance rule",
    )


def _volume_metric(metrics: Dict[str, Any], volume: float) -> Any:
    for key in (str(volume), f"{volume:g}", f"{volume:.1f}"):
        if key in metrics:
            return metrics[key]
    return None


def evaluate_liquid_handling(config: RunConfig, metrics: Dict[str, Any]) -> GateResult:
    observed = metrics.get("liquid_handling", {}).get("cv_percent", {})
    outcomes = []
    for volume in qualified_volumes(config):
        rule = MetricRule(
            metric=f"lh_cv_{volume:g}ul",
            label=f"dispense CV at {volume:g} uL",
            unit="%",
            maximum=config.acceptance.lh_cv_max_percent,
        )
        outcomes.append(_outcome(rule, _volume_metric(observed, volume)))
    passed = bool(outcomes) and all(item.passed for item in outcomes)
    return GateResult(
        "gate_0_liquid_handling",
        Decision.PROCEED if passed else Decision.STOP,
        "all profile volumes qualified" if passed else "required profile volume qualification is missing or failed",
        run_outcomes=outcomes,
    )


def evaluate_library_qc(config: RunConfig, metrics: Dict[str, Any]) -> GateResult:
    observed_samples = metrics.get("samples", {})
    blanks: List[Outcome] = []
    verdicts: List[SampleVerdict] = []
    for sample in config.samples:
        observed = observed_samples.get(sample.id, {})
        rules = (
            config.acceptance.blank_rules
            if sample.sample_type is SampleType.PROCESS_BLANK
            else config.acceptance.sample_rules
        )
        outcomes = [_outcome(rule, observed.get(rule.metric)) for rule in rules]
        if sample.sample_type is SampleType.PROCESS_BLANK:
            blanks.extend(outcomes)
        else:
            verdicts.append(SampleVerdict(sample.id, bool(outcomes) and all(item.passed for item in outcomes), outcomes))
    if any(not item.passed for item in blanks):
        decision, message = Decision.STOP, "process blank failed the selected profile rules"
    else:
        passing = [item for item in verdicts if item.passed]
        if not passing:
            decision, message = Decision.STOP, "no sample passed the selected profile rules"
        elif len(passing) < len(verdicts):
            decision, message = Decision.PROCEED_SUBSET, "continue only with profile-qualified libraries"
        else:
            decision, message = Decision.PROCEED, "all non-blank libraries passed selected profile rules"
    return GateResult(
        "gate_1_operator_qc", decision, message,
        run_outcomes=blanks, sample_verdicts=verdicts,
    )

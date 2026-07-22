"""Run-level and per-library acceptance gates."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from .config import RunConfig, SampleType
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
            "key": self.key,
            "label": self.label,
            "requirement": self.requirement,
            "measured": self.measured,
            "unit": self.unit,
            "passed": self.passed,
            "source": self.source,
        }


@dataclass
class SampleVerdict:
    sample_id: str
    passed: bool
    outcomes: List[Outcome]

    def to_dict(self) -> dict:
        return {
            "sample_id": self.sample_id,
            "passed": self.passed,
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
            "gate": self.gate,
            "decision": self.decision.value,
            "message": self.message,
            "run_outcomes": [item.to_dict() for item in self.run_outcomes],
            "sample_verdicts": [item.to_dict() for item in self.sample_verdicts],
            "passing": self.passing_sample_ids,
            "dropped": self.dropped_sample_ids,
        }


def _max_outcome(key: str, label: str, value: Any, bound: float, unit: str, source: str) -> Outcome:
    measured = float(value) if value is not None else None
    return Outcome(key, label, f"<= {bound:g}", measured, unit,
                   measured is not None and measured <= bound, source)


def _min_outcome(key: str, label: str, value: Any, bound: float, unit: str, source: str) -> Outcome:
    measured = float(value) if value is not None else None
    return Outcome(key, label, f">= {bound:g}", measured, unit,
                   measured is not None and measured >= bound, source)


def _range_outcome(key: str, label: str, value: Any, low: float, high: float,
                   unit: str, source: str) -> Outcome:
    measured = float(value) if value is not None else None
    return Outcome(key, label, f"{low:g}-{high:g}", measured, unit,
                   measured is not None and low <= measured <= high, source)


def _volume_metric(metrics: Dict[str, Any], volume: float) -> Any:
    for key in (str(volume), f"{volume:g}", f"{volume:.1f}"):
        if key in metrics:
            return metrics[key]
    return None


def evaluate_liquid_handling(config: RunConfig, metrics: Dict[str, Any]) -> GateResult:
    cv_metrics = metrics.get("liquid_handling", {}).get("cv_percent", {})
    outcomes = []
    for volume in qualified_volumes(config):
        outcomes.append(_max_outcome(
            f"lh_cv_{volume:g}ul",
            f"dispense CV at {volume:g} uL",
            _volume_metric(cv_metrics, volume),
            config.acceptance.lh_cv_max_percent,
            "%",
            "site qualification gate; tune each protocol-relevant volume before sample use",
        ))
    passed = all(item.passed for item in outcomes)
    return GateResult(
        gate="gate_0_liquid_handling",
        decision=Decision.PROCEED if passed else Decision.STOP,
        message=("all protocol volumes qualified" if passed else
                 "deck qualification failed or a required volume was not measured"),
        run_outcomes=outcomes,
    )


def evaluate_library_qc(config: RunConfig, metrics: Dict[str, Any]) -> GateResult:
    sample_metrics = metrics.get("samples", {})
    blank_outcomes: List[Outcome] = []
    verdicts: List[SampleVerdict] = []
    criteria = config.acceptance

    for sample in config.samples:
        observed = sample_metrics.get(sample.id, {})
        if sample.sample_type is SampleType.PROCESS_BLANK:
            blank_outcomes.append(_max_outcome(
                f"{sample.id}_blank_concentration",
                f"{sample.id} process-blank library concentration",
                observed.get("library_concentration_ng_ul"),
                criteria.process_blank_concentration_max_ng_ul,
                "ng/uL",
                "TUNABLE contamination sentinel; establish from site blank history",
            ))
            continue

        outcomes = [
            _min_outcome(
                "lambda_reads", "unmethylated lambda paired reads",
                observed.get("lambda_reads"), criteria.lambda_reads_min, "reads",
                "M7634 v3.0 3.1.1 minimum coverage for an accurate conversion estimate",
            ),
            _min_outcome(
                "puc19_reads", "CpG-methylated pUC19 paired reads",
                observed.get("puc19_reads"), criteria.puc19_reads_min, "reads",
                "M7634 v3.0 3.1.1 minimum coverage for an accurate protection estimate",
            ),
            _min_outcome(
                "lambda_conversion", "lambda cytosine conversion",
                observed.get("lambda_conversion_percent"), criteria.lambda_conversion_min_percent, "%",
                "TUNABLE run gate; current di-omics EM-seq QC default",
            ),
            _min_outcome(
                "puc19_protection", "pUC19 CpG protection",
                observed.get("puc19_protection_percent"), criteria.puc19_protection_min_percent, "%",
                "TUNABLE run gate; current di-omics EM-seq QC default",
            ),
            _range_outcome(
                "library_mean_bp", "mean library fragment size",
                observed.get("library_mean_bp"), criteria.library_mean_bp_min,
                criteria.library_mean_bp_max, "bp",
                "TUNABLE expected range from current EM-seq automation validation plan",
            ),
            _min_outcome(
                "library_concentration", "final library concentration",
                observed.get("library_concentration_ng_ul"),
                criteria.library_concentration_min_ng_ul, "ng/uL",
                "TUNABLE sequencing handoff floor; verify for the local platform",
            ),
        ]
        verdicts.append(SampleVerdict(sample.id, all(item.passed for item in outcomes), outcomes))

    if any(not item.passed for item in blank_outcomes):
        decision = Decision.STOP
        message = "process blank failed; stop the run and investigate contamination"
    else:
        passing = [item for item in verdicts if item.passed]
        if not passing:
            decision = Decision.STOP
            message = "no sample passed conversion, protection, size, and yield QC"
        elif len(passing) < len(verdicts):
            decision = Decision.PROCEED_SUBSET
            message = "continue only with libraries that passed every QC criterion"
        else:
            decision = Decision.PROCEED
            message = "all non-blank libraries passed final QC"
    return GateResult(
        gate="gate_1_library_and_conversion_qc",
        decision=decision,
        message=message,
        run_outcomes=blank_outcomes,
        sample_verdicts=verdicts,
    )


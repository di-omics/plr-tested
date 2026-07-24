"""Typed, inert configuration for a generic methylation-sequencing run card."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class RunMode(str, Enum):
    SIMULATION = "simulation"
    HARDWARE = "hardware"


class ProfileKind(str, Enum):
    SYNTHETIC_WATER = "synthetic_water"
    OPERATOR = "operator"


class SampleType(str, Enum):
    SAMPLE = "sample"
    POSITIVE_CONTROL = "positive_control"
    PROCESS_BLANK = "process_blank"


class InputTier(str, Enum):
    """Compatibility label retained for existing report consumers."""

    OPERATOR = "operator-configured"


@dataclass(frozen=True)
class Sample:
    id: str
    well: str
    input_ng: float = 0.0
    udi: str = "operator-configured"
    control_dilution: str = "operator-configured"
    sample_type: SampleType = SampleType.SAMPLE
    notes: str = ""

    @property
    def input_tier(self) -> Optional[InputTier]:
        return None if self.sample_type is SampleType.PROCESS_BLANK else InputTier.OPERATOR


@dataclass(frozen=True)
class DeckPosition:
    rail: int
    pos: int
    role: str


@dataclass(frozen=True)
class DeckLayout:
    name: str
    positions: Dict[str, DeckPosition]

    @staticmethod
    def validation() -> "DeckLayout":
        return DeckLayout(
            name="validation_methylation_seq_column1",
            positions={
                "p10_tips": DeckPosition(48, 0, "p10 filter tips"),
                "p50_tips": DeckPosition(48, 1, "p50 filter tips"),
                "p300_tips": DeckPosition(48, 2, "p300 filter tips"),
                "work_plate": DeckPosition(35, 0, "moving methylation-sequencing work plate"),
                "reagent_source": DeckPosition(35, 1, "operator-configured stage source"),
                "magnet": DeckPosition(35, 2, "magnetic-cleanup position"),
                "reservoir": DeckPosition(35, 3, "operator-configured cleanup reservoir"),
                "odtc": DeckPosition(20, 1, "ODTC nest"),
            },
        )


@dataclass(frozen=True)
class MetricRule:
    metric: str
    label: str
    unit: str = ""
    minimum: Optional[float] = None
    maximum: Optional[float] = None


@dataclass
class AcceptanceCriteria:
    lh_cv_max_percent: float = 5.0
    sample_rules: List[MetricRule] = field(default_factory=list)
    blank_rules: List[MetricRule] = field(default_factory=list)


@dataclass
class RunConfig:
    run_id: str
    operator: str
    mode: RunMode
    samples: List[Sample]
    profile_kind: ProfileKind
    method: Dict[str, Any]
    method_profile_path: Optional[str]
    deck: DeckLayout
    acceptance: AcceptanceCriteria = field(default_factory=AcceptanceCriteria)
    output_dir: str = "runs"
    notes: str = ""

    # Compatibility fields retained without biological defaults.
    input_tier: InputTier = InputTier.OPERATOR
    fragmentation_minutes: float = 0.0
    pcr_cycles: int = 0
    reaction_batch_size: int = 0
    denaturation: str = "operator-configured"

    @property
    def active_samples(self) -> List[Sample]:
        return [s for s in self.samples if s.sample_type is not SampleType.PROCESS_BLANK]

    @property
    def low_input(self) -> bool:
        return False

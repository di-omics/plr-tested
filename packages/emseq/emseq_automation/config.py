"""Typed, inert configuration for one EM-seq v2 run.

The current hardware implementation is deliberately scoped to one eight-well column on
the Bio Validation 0 deck.  Keeping that limitation in the schema prevents a manifest
from promising throughput that the underlying STAR scripts do not implement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class RunMode(str, Enum):
    SIMULATION = "simulation"
    HARDWARE = "hardware"


class SampleType(str, Enum):
    SAMPLE = "sample"
    POSITIVE_CONTROL = "positive_control"
    PROCESS_BLANK = "process_blank"


class InputTier(str, Enum):
    LOW = "low"       # <= 10 ng: carrier DNA + diluted T4-BGT route
    HIGH = "high"     # > 10 ng: no carrier + undiluted T4-BGT route


@dataclass(frozen=True)
class Sample:
    id: str
    well: str
    input_ng: float
    udi: str
    control_dilution: str
    sample_type: SampleType = SampleType.SAMPLE
    notes: str = ""

    @property
    def input_tier(self) -> Optional[InputTier]:
        if self.sample_type is SampleType.PROCESS_BLANK:
            return None
        return InputTier.LOW if self.input_ng <= 10.0 else InputTier.HIGH


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
    def bio_validation_0() -> "DeckLayout":
        return DeckLayout(
            name="bio_validation_0_emseq_column1",
            positions={
                "p10_tips": DeckPosition(48, 0, "p10 filter tips"),
                "p50_tips": DeckPosition(48, 1, "p50 filter tips"),
                "p300_tips": DeckPosition(48, 2, "p300 filter tips"),
                "work_plate": DeckPosition(35, 0, "moving EM-seq work plate"),
                "reagent_source": DeckPosition(35, 1, "swap-source reagent plate"),
                "magnet": DeckPosition(35, 2, "SPRI magnet"),
                "reservoir": DeckPosition(35, 3, "beads, ethanol, elution, waste"),
                "odtc": DeckPosition(20, 1, "Inheco ODTC nest"),
            },
        )


@dataclass
class AcceptanceCriteria:
    """The run rubric. Protocol minima are identified separately from tunable gates."""

    lh_cv_max_percent: float = 5.0
    lambda_reads_min: int = 5000
    puc19_reads_min: int = 500
    lambda_conversion_min_percent: float = 99.5
    puc19_protection_min_percent: float = 95.0
    library_mean_bp_min: float = 420.0
    library_mean_bp_max: float = 620.0
    library_concentration_min_ng_ul: float = 2.0
    process_blank_concentration_max_ng_ul: float = 1.0


@dataclass
class RunConfig:
    run_id: str
    operator: str
    mode: RunMode
    samples: List[Sample]
    input_tier: InputTier
    shear_minutes: float
    pcr_cycles: int
    kit_size: int
    denaturation: str
    deck: DeckLayout
    acceptance: AcceptanceCriteria = field(default_factory=AcceptanceCriteria)
    output_dir: str = "runs"
    notes: str = ""

    @property
    def active_samples(self) -> List[Sample]:
        return [s for s in self.samples if s.sample_type is not SampleType.PROCESS_BLANK]

    @property
    def low_input(self) -> bool:
        return self.input_tier is InputTier.LOW


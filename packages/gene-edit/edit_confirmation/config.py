"""
config.py - the typed run plan the whole package agrees on.

A run is described by a small manifest (see manifest.py and configs/example_run.yaml).
This module is the in-memory form of that manifest after defaults are filled in and
everything is validated: samples with wells, the locus being genotyped, the deck the
robot will use, the acceptance criteria the gates will enforce, and whether this is a
simulation or a hardware run.

Nothing here reaches for an instrument. It is data. The stages and instrument adapters
take a RunConfig and act on it; keeping the plan inert makes it trivial to print,
diff, and archive, which is most of what "reproducible across sites" comes down to.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from .gates import Comparison, Criterion


class RunMode(str, Enum):
    SIMULATION = "simulation"   # no instrument touched; synthetic reads, full flow
    HARDWARE = "hardware"       # drives the real STAR / ODTC / Tecan


class EditType(str, Enum):
    CRISPR_INDEL = "crispr_indel"   # NHEJ knockout; confirm by indel at cut site
    CRISPR_HDR = "crispr_hdr"       # knock-in; confirm the intended edit
    BASE_EDIT = "base_edit"         # confirm the base conversion
    PRIME_EDIT = "prime_edit"       # confirm the programmed edit
    UNKNOWN = "unknown"             # genotype the locus, call whatever is there


class SampleType(str, Enum):
    TEST = "test"                   # an edited sample under confirmation
    POSITIVE_CONTROL = "pos_ctrl"   # known-edited, should confirm
    NEGATIVE_CONTROL = "neg_ctrl"   # unedited/wild-type, should be reference
    NO_TEMPLATE = "ntc"             # no template; watches for contamination


_WELL_RE = re.compile(r"^[A-H](?:[1-9]|1[0-2])$")


@dataclass
class Sample:
    id: str
    well: str
    sample_type: SampleType = SampleType.TEST
    notes: str = ""

    def __post_init__(self) -> None:
        if not _WELL_RE.match(self.well):
            raise ValueError(
                f"sample {self.id!r} has well {self.well!r}, "
                "which is not an A1..H12 96-well address"
            )


@dataclass
class LocusTarget:
    """The region being genotyped to confirm the edit.

    Only what the automation needs is required. Primer sequences and the exact edit
    coordinate matter for the sequencing analysis, not for driving the robot, so they
    are optional here and flow through to the sequencing handoff when provided.
    """

    name: str
    amplicon_bp: int
    pcr1_anneal_c: Optional[float] = None   # override the protocol's ~67 C default
    primer_f: Optional[str] = None
    primer_r: Optional[str] = None
    edit_position_bp: Optional[int] = None  # position of the expected edit in the amplicon

    def __post_init__(self) -> None:
        if self.amplicon_bp <= 0:
            raise ValueError(f"locus {self.name!r} has non-positive amplicon_bp")


@dataclass
class DeckPosition:
    rail: int
    pos: int
    role: str


@dataclass
class DeckLayout:
    """Named positions on the STAR deck. Defaults to the Bio Validation 0 rail35-48."""

    name: str
    positions: Dict[str, DeckPosition] = field(default_factory=dict)

    def get(self, role: str) -> DeckPosition:
        if role not in self.positions:
            raise KeyError(f"deck {self.name!r} has no position for role {role!r}")
        return self.positions[role]

    @staticmethod
    def bio_validation_0() -> "DeckLayout":
        # Transcribed from hamilton-star/README.md, "Bio Validation 0 / rail35-48".
        return DeckLayout(
            name="bio_validation_0",
            positions={
                "p10_tips": DeckPosition(48, 0, "p10 filter tips"),
                "p50_tips": DeckPosition(48, 1, "p50 filter tips"),
                "p300_tips": DeckPosition(48, 2, "p300 filter tips"),
                "work_plate": DeckPosition(35, 0, "destination / work plate"),
                "source_plate": DeckPosition(35, 1, "source / reagent plate"),
                "mag_plate": DeckPosition(35, 2, "magnet / cleanup plate"),
                "reservoir": DeckPosition(35, 3, "trough / reservoir"),
            },
        )


@dataclass
class AcceptanceCriteria:
    """All QC cutoffs for a run, in one auditable object.

    Loaded from configs/acceptance_criteria.yaml (see manifest.py). Held as plain
    numbers here plus the Criterion objects the gates consume, so the same file drives
    both the human-readable rubric and the machine enforcement.
    """

    # Gate 0: liquid-handling qualification (Rhodamine B).
    lh_cv_max_percent: float = 5.0
    lh_recovery_tolerance_percent: float = 10.0
    lh_qualified_volumes_ul: List[float] = field(
        default_factory=lambda: [2.0, 3.0, 5.0, 10.0, 20.0, 22.5, 50.0, 100.0, 200.0]
    )

    # Standard-curve quality (shared by PicoGreen reads).
    curve_r2_min: float = 0.98

    # Gate 1: post-whole-genome amplification yield and uniformity.
    pta_yield_min_ng: float = 100.0        # TUNABLE, see acceptance_criteria.yaml
    pta_uniformity_cv_max_percent: float = 30.0

    # Gate 2: post-targeted-PCR library concentration window (for even pooling / TapeStation).
    targeted_pcr_conc_min_ng_per_ul: float = 2.0
    targeted_pcr_conc_max_ng_per_ul: float = 60.0

    def lh_cv_criterion(self, volume_ul: float) -> Criterion:
        return Criterion(
            key=f"lh_cv_{volume_ul}ul",
            label=f"dispense CV at {volume_ul} uL",
            comparison=Comparison.MAX,
            bound=self.lh_cv_max_percent,
            unit="%",
            source="operator-set liquid-handling qualification cutoff (Rhodamine B CV)",
        )

    def curve_criterion(self, which: str) -> Criterion:
        return Criterion(
            key=f"curve_r2_{which}",
            label=f"{which} standard curve R-squared",
            comparison=Comparison.MIN,
            bound=self.curve_r2_min,
            unit="",
            source="standard-curve linearity floor; below this the assay is re-run",
        )

    def pta_yield_criterion(self) -> Criterion:
        return Criterion(
            key="pta_yield",
            label="post-PTA dsDNA yield per well",
            comparison=Comparison.MIN,
            bound=self.pta_yield_min_ng,
            unit="ng",
            source="TUNABLE: set from the whole-genome sequencing yield seen on your samples; verify",
        )

    def targeted_pcr_conc_criterion(self) -> Criterion:
        return Criterion(
            key="targeted_pcr_conc",
            label="post-targeted-PCR library concentration",
            comparison=Comparison.RANGE,
            bound=(self.targeted_pcr_conc_min_ng_per_ul, self.targeted_pcr_conc_max_ng_per_ul),
            unit="ng/uL",
            source="TUNABLE: loading window for TapeStation and the sequencer; verify",
        )


@dataclass
class RunConfig:
    run_id: str
    operator: str
    mode: RunMode
    samples: List[Sample]
    locus: LocusTarget
    edit_type: EditType
    deck: DeckLayout
    acceptance: AcceptanceCriteria
    output_dir: str = "runs"
    pcr2_cycles: int = 8                 # protocol range 8 to 10; default 8
    tip_column: int = 1                  # site-specific: which tip-rack column to start from
    notes: str = ""

    def sample_by_id(self, sample_id: str) -> Sample:
        for s in self.samples:
            if s.id == sample_id:
                return s
        raise KeyError(f"no sample {sample_id!r} in run {self.run_id!r}")

    def test_samples(self) -> List[Sample]:
        return [s for s in self.samples if s.sample_type is SampleType.TEST]

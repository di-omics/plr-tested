"""
config.py - the typed run plan the whole package agrees on.

A run is described by a small manifest (see manifest.py and configs/example_run.yaml).
This module is the in-memory form of that manifest after everything is validated:
samples with wells, explicit operator method parameters, the deck the robot will use,
the acceptance criteria the gates will enforce, and whether this is a simulation or a
hardware run. Biological recipe values have no package defaults.

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


class ProfileKind(str, Enum):
    SYNTHETIC_WATER = "synthetic_water"
    OPERATOR = "operator"


class AnalysisType(str, Enum):
    VARIANT_CALLING = "variant_calling"
    TARGET_CONFIRMATION = "target_confirmation"
    SEQUENCE_VALIDATION = "sequence_validation"
    TARGETED_SEQUENCE = "targeted_sequence"
    UNKNOWN = "unknown"


class SampleType(str, Enum):
    TEST = "test"                   # sample under validation
    POSITIVE_CONTROL = "pos_ctrl"   # known-positive control
    NEGATIVE_CONTROL = "neg_ctrl"   # reference control
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
    """The region being analyzed by the sequencing assay.

    Only what the automation needs is required. Primer sequences and an optional target
    coordinate matter for the sequencing analysis, not for driving the robot, so they
    are optional here and flow through to the sequencing handoff when provided.
    """

    name: str
    pcr_product_bp: int
    primer_f: Optional[str] = None
    primer_r: Optional[str] = None
    target_position_bp: Optional[int] = None  # optional target position in the PCR product

    def __post_init__(self) -> None:
        if self.pcr_product_bp <= 0:
            raise ValueError(f"locus {self.name!r} has non-positive pcr_product_bp")


@dataclass
class DeckPosition:
    rail: int
    pos: int
    role: str


@dataclass
class DeckLayout:
    """Named positions on the STAR deck. Defaults to the Validation rail35-48."""

    name: str
    positions: Dict[str, DeckPosition] = field(default_factory=dict)

    def get(self, role: str) -> DeckPosition:
        if role not in self.positions:
            raise KeyError(f"deck {self.name!r} has no position for role {role!r}")
        return self.positions[role]

    @staticmethod
    def validation() -> "DeckLayout":
        # Transcribed from hamilton-star/README.md, "Validation / rail35-48".
        return DeckLayout(
            name="validation",
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
        default_factory=lambda: [1.0, 10.0, 100.0]
    )

    # Standard-curve quality (shared by fluorescent dsDNA assay reads).
    curve_r2_min: float = 0.98

    # Gate 1: post-whole-genome sequencing preparation yield and uniformity.
    wgs_prep_yield_min_ng: float = 100.0        # TUNABLE, see acceptance_criteria.yaml
    wgs_prep_uniformity_cv_max_percent: float = 30.0

    # Gate 2: post-PCR-enrichment library concentration window.
    pcr_enrichment_conc_min_ng_per_ul: float = 2.0
    pcr_enrichment_conc_max_ng_per_ul: float = 60.0

    def __post_init__(self) -> None:
        if not self.lh_qualified_volumes_ul:
            raise ValueError("lh_qualified_volumes_ul must not be empty")
        if any(volume <= 0 for volume in self.lh_qualified_volumes_ul):
            raise ValueError("lh_qualified_volumes_ul values must be positive")
        if self.wgs_prep_yield_min_ng <= 0:
            raise ValueError("wgs_prep_yield_min_ng must be positive")
        if self.pcr_enrichment_conc_min_ng_per_ul < 0:
            raise ValueError(
                "pcr_enrichment concentration minimum cannot be negative"
            )
        if (
            self.pcr_enrichment_conc_min_ng_per_ul
            >= self.pcr_enrichment_conc_max_ng_per_ul
        ):
            raise ValueError(
                "pcr_enrichment concentration minimum must be less than maximum"
            )

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

    def wgs_prep_yield_criterion(self) -> Criterion:
        return Criterion(
            key="wgs_prep_yield",
            label="post-WGS preparation dsDNA yield per well",
            comparison=Comparison.MIN,
            bound=self.wgs_prep_yield_min_ng,
            unit="ng",
            source="TUNABLE: set from the whole-genome sequencing yield seen on your samples; verify",
        )

    def pcr_enrichment_conc_criterion(self) -> Criterion:
        return Criterion(
            key="pcr_enrichment_conc",
            label="post-PCR-enrichment library concentration",
            comparison=Comparison.RANGE,
            bound=(self.pcr_enrichment_conc_min_ng_per_ul, self.pcr_enrichment_conc_max_ng_per_ul),
            unit="ng/uL",
            source="TUNABLE: loading window for fragment analyzer and the sequencer; verify",
        )


@dataclass(frozen=True)
class MethodParameters:
    """Required wet-method and thermal handoff values for one run."""

    profile_kind: ProfileKind
    parameter_source: str
    wgs_stage_1_ul: float
    wgs_stage_2_ul: float
    wgs_odtc_profile: str
    pcr_stage_1_transfer_ul: float
    pcr_stage_2_transfer_ul: float
    pcr_reaction_volume_ul: float
    post_pcr1_cleanup_ratio: float
    post_pcr2_cleanup_ratio: float
    supernatant_margin_ul: float
    pcr1_anneal_c: float
    pcr2_cycles: int
    pcr1_odtc_profile: str
    pcr2_odtc_profile: str
    wgs_qc_dilution: float
    pcr_qc_dilution: float
    wgs_product_volume_ul: float
    pcr_library_volume_ul: float
    indexing_overhang_bp: int
    pool_target_mass_ng: float
    fragment_window_below_bp: int
    fragment_window_above_bp: int
    dimer_flag_below_bp: int

    def __post_init__(self) -> None:
        if not self.parameter_source.strip():
            raise ValueError("method parameter_source cannot be empty")
        positive = {
            "wgs_stage_1_ul": self.wgs_stage_1_ul,
            "wgs_stage_2_ul": self.wgs_stage_2_ul,
            "pcr_stage_1_transfer_ul": self.pcr_stage_1_transfer_ul,
            "pcr_stage_2_transfer_ul": self.pcr_stage_2_transfer_ul,
            "pcr_reaction_volume_ul": self.pcr_reaction_volume_ul,
            "post_pcr1_cleanup_ratio": self.post_pcr1_cleanup_ratio,
            "post_pcr2_cleanup_ratio": self.post_pcr2_cleanup_ratio,
            "pcr1_anneal_c": self.pcr1_anneal_c,
            "wgs_qc_dilution": self.wgs_qc_dilution,
            "pcr_qc_dilution": self.pcr_qc_dilution,
            "wgs_product_volume_ul": self.wgs_product_volume_ul,
            "pcr_library_volume_ul": self.pcr_library_volume_ul,
            "pool_target_mass_ng": self.pool_target_mass_ng,
        }
        for name, value in positive.items():
            if value <= 0:
                raise ValueError(f"method {name} must be positive")
        if self.supernatant_margin_ul < 0:
            raise ValueError("method supernatant_margin_ul cannot be negative")
        if self.pcr2_cycles < 1:
            raise ValueError("method pcr2_cycles must be a positive integer")
        positive_ints = {
            "indexing_overhang_bp": self.indexing_overhang_bp,
            "dimer_flag_below_bp": self.dimer_flag_below_bp,
        }
        for name, value in positive_ints.items():
            if value < 1:
                raise ValueError(f"method {name} must be a positive integer")
        nonnegative_ints = {
            "fragment_window_below_bp": self.fragment_window_below_bp,
            "fragment_window_above_bp": self.fragment_window_above_bp,
        }
        for name, value in nonnegative_ints.items():
            if value < 0:
                raise ValueError(f"method {name} cannot be negative")
        for name in ("wgs_odtc_profile", "pcr1_odtc_profile", "pcr2_odtc_profile"):
            if not getattr(self, name).strip():
                raise ValueError(f"method {name} cannot be empty")


@dataclass(frozen=True)
class FluorescentDsDNAProfile:
    """Operator-supplied reader settings and standard concentrations."""

    profile_label: str
    excitation_nm: float
    emission_nm: float
    standards_ng_per_ml: List[float]

    def __post_init__(self) -> None:
        if not self.profile_label.strip():
            raise ValueError("fluorescent dsDNA profile_label must be non-empty")
        if self.excitation_nm <= 0 or self.emission_nm <= 0:
            raise ValueError("fluorescent dsDNA wavelengths must be positive")
        if len(self.standards_ng_per_ml) < 2:
            raise ValueError("fluorescent dsDNA standards require at least two values")
        if any(value < 0 for value in self.standards_ng_per_ml):
            raise ValueError("fluorescent dsDNA standards cannot contain negative values")
        if sorted(self.standards_ng_per_ml) != self.standards_ng_per_ml:
            raise ValueError("fluorescent dsDNA standards must be sorted")


@dataclass
class RunConfig:
    run_id: str
    operator: str
    mode: RunMode
    samples: List[Sample]
    locus: LocusTarget
    analysis_type: AnalysisType
    deck: DeckLayout
    acceptance: AcceptanceCriteria
    method: MethodParameters
    fluorescent_dsdna: FluorescentDsDNAProfile
    output_dir: str = "runs"
    tip_column: int = 1                  # site-specific: which tip-rack column to start from
    notes: str = ""

    def sample_by_id(self, sample_id: str) -> Sample:
        for s in self.samples:
            if s.id == sample_id:
                return s
        raise KeyError(f"no sample {sample_id!r} in run {self.run_id!r}")

    def test_samples(self) -> List[Sample]:
        return [s for s in self.samples if s.sample_type is SampleType.TEST]

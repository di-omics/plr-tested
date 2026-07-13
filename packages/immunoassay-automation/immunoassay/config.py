"""
config.py - the typed run plan the whole package agrees on.

A run is described by a small manifest (see manifest.py and configs/example_run.yaml).
This module is the in-memory form of that manifest after defaults are filled in and
everything is validated: the plate layout (which well holds which antigen, and which
wells are controls), the acceptance criteria the gates will enforce, the site profile
that captures the few things that are specific to the local washer and imager, and
whether this is a simulation or a hardware run.

Nothing here reaches for an instrument. It is data. The stages and instrument adapters
take a RunConfig and act on it; keeping the plan inert makes it trivial to print, diff,
and archive, which is most of what "reproducible across sites" comes down to.

ELISpot is a plate-layout assay: the science lives in which wells are the negative
control, which are the mitogen positive control, and which replicate group belongs to
which antigen. So the plate layout is a first-class part of the plan, not an afterthought.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from .gates import Comparison, Criterion


class RunMode(str, Enum):
    SIMULATION = "simulation"   # no instrument touched; synthetic reads, full flow
    HARDWARE = "hardware"       # drives the real washer / liquid handler / imager


class WellRole(str, Enum):
    TEST = "test"                   # cells + a test antigen; the measurement
    POSITIVE_CONTROL = "pos_ctrl"   # cells + mitogen (PHA / anti-CD3); assay-validity check
    NEGATIVE_CONTROL = "neg_ctrl"   # cells + medium only; the background the test is read against
    BLANK = "blank"                 # no cells; watches for non-specific development / reagent spots


class AntigenKind(str, Enum):
    PEPTIDE_POOL = "peptide_pool"   # the usual test stimulus (e.g. a CEF or neoantigen pool)
    PROTEIN = "protein"             # whole-protein / lysate stimulus
    MITOGEN = "mitogen"             # PHA, anti-CD3; the positive control stimulus
    MEDIUM = "medium"               # medium only; the negative control "antigen"


_WELL_RE = re.compile(r"^[A-H](?:[1-9]|1[0-2])$")


@dataclass
class Antigen:
    """A stimulus used somewhere on the plate.

    `name` is what the response call reports against; `kind` decides how a well that uses
    it is scored (a MITOGEN well is a validity control, a MEDIUM well is the background).
    """

    name: str
    kind: AntigenKind = AntigenKind.PEPTIDE_POOL
    notes: str = ""


@dataclass
class Well:
    """One well of the PVDF plate: an address, a role, and the antigen it holds.

    cells_per_well overrides the run default for this well (a titration well, say); left
    None it inherits the site profile's cells_per_well. The role is what the gate reads:
    TEST wells are grouped by antigen and scored against the NEGATIVE_CONTROL group.
    """

    address: str
    role: WellRole = WellRole.TEST
    antigen: str = ""
    cells_per_well: Optional[int] = None
    notes: str = ""

    def __post_init__(self) -> None:
        if not _WELL_RE.match(self.address):
            raise ValueError(
                f"well {self.address!r} is not an A1..H12 96-well address"
            )
        if self.role in (WellRole.TEST, WellRole.POSITIVE_CONTROL, WellRole.NEGATIVE_CONTROL):
            if not self.antigen:
                raise ValueError(
                    f"well {self.address} has role {self.role.value} but no antigen; "
                    "a cell-containing well must name its stimulus (use 'medium' for neg ctrl)"
                )
        if self.cells_per_well is not None and self.cells_per_well <= 0:
            raise ValueError(
                f"well {self.address} has cells_per_well {self.cells_per_well}; "
                "a per-well cell count must be positive (omit it to use the site default)"
            )


@dataclass
class PlateLayout:
    """The 96-well PVDF plate as a list of populated wells.

    Not every address needs to be listed; an unlisted address is an empty well. The
    helpers below are what the readout gate uses to find its control groups and to group
    test replicates by antigen.
    """

    wells: List[Well] = field(default_factory=list)

    def by_role(self, role: WellRole) -> List[Well]:
        return [w for w in self.wells if w.role is role]

    def negative_wells(self) -> List[Well]:
        return self.by_role(WellRole.NEGATIVE_CONTROL)

    def positive_wells(self) -> List[Well]:
        return self.by_role(WellRole.POSITIVE_CONTROL)

    def blank_wells(self) -> List[Well]:
        return self.by_role(WellRole.BLANK)

    def test_groups(self) -> Dict[str, List[Well]]:
        """TEST wells grouped by antigen name, in first-seen order."""
        groups: Dict[str, List[Well]] = {}
        for w in self.wells:
            if w.role is WellRole.TEST:
                groups.setdefault(w.antigen, []).append(w)
        return groups

    def addresses(self) -> List[str]:
        return [w.address for w in self.wells]


@dataclass
class SiteProfile:
    """The handful of things that are specific to the site running this plate.

    This is the drift-control surface. Two labs running the same manifest differ here and
    nowhere else: their local washer aspirates to a slightly different residual, their
    plate lot wets out at a slightly different membrane height, their imager sits at a
    different background offset, and their cell prep lands a different count per well.
    Pinning these per site, and qualifying them at Gate 0, is what lets the same protocol
    execute the same way in Boston and at a partner bench.

    aspiration_height_mm is deliberately left None by default: it must be taught against
    the physical plate lot (a probe that rides too low scratches the membrane and prints
    false spots), so a hardware run stays blocked until it is measured. See membrane.py.
    """

    name: str = "default"
    cells_per_well: int = 250_000          # site-specific: the local PBMC prep density
    wash_cycles: int = 5                   # washer program: cycles per wash step
    wash_volume_ul: float = 200.0          # washer program: volume per cycle
    soak_seconds: float = 0.0              # optional soak between aspirate and dispense
    aspiration_height_mm: Optional[float] = None   # taught per plate lot; None blocks hardware
    imager_background_offset_sfu: float = 0.0       # site imager threshold offset, added to reads


@dataclass
class AcceptanceCriteria:
    """All QC cutoffs for a run, in one auditable object.

    Loaded from configs/acceptance_criteria.yaml (see manifest.py). Held as plain numbers
    here plus the Criterion objects the gates consume, so the same file drives both the
    human-readable rubric and the machine enforcement.
    """

    # Gate 0: liquid-handling / washer qualification (Rhodamine B).
    lh_cv_max_percent: float = 5.0
    lh_qualified_volumes_ul: List[float] = field(
        default_factory=lambda: [15.0, 50.0, 100.0, 150.0, 200.0]
    )
    # Aspiration completeness: the washer must draw a well down to near-dry, uniformly.
    # A well left wet carries reagent into the next step and prints as background.
    residual_volume_max_ul: float = 10.0

    # Gate 1: plate preparation. The membrane must wet out uniformly before it is coated.
    prewet_cv_max_percent: float = 8.0

    # Gate 2: readout validity and response calling.
    neg_ctrl_background_max_sfu: float = 25.0     # mean background per negative-control well
    pos_ctrl_min_sfu: float = 100.0               # positive control must fire, or the plate is void
    replicate_cv_max_percent: float = 30.0        # spread across replicate wells of a group
    saturation_sfu: float = 600.0                 # at/above this a well is TNTC, not quantitative
    # Response call (the "is this real" rule): a TEST antigen is positive if its mean net
    # spots clear both a floor and a fold-over-background. This is the conservative
    # empirical rule; the distribution-free resampling method (Moodie 2010) is the
    # gold-standard alternative and needs well-level replicate counts, noted in qc_math.
    response_min_net_sfu: float = 10.0
    response_min_stimulation_index: float = 2.0
    # How the "is this real" call is made: "empirical" (net + fold, no dependency) or the
    # distribution-free resampling methods "dfr2x" (permutation significance + the 2x fold,
    # the Moodie 2010 recommended default) or "dfr" (significance alone). dfr_alpha is the
    # permutation-test significance cutoff.
    response_method: str = "empirical"
    dfr_alpha: float = 0.05

    # Reporting normalization.
    report_per_cells: int = 1_000_000             # SFU normalized to this many input cells

    def lh_cv_criterion(self, volume_ul: float) -> Criterion:
        return Criterion(
            key=f"lh_cv_{volume_ul}ul",
            label=f"dispense CV at {volume_ul} uL",
            comparison=Comparison.MAX,
            bound=self.lh_cv_max_percent,
            unit="%",
            source="operator-set liquid-handling qualification cutoff (Rhodamine B CV)",
        )

    def residual_criterion(self) -> Criterion:
        return Criterion(
            key="aspiration_residual",
            label="residual volume after aspiration",
            comparison=Comparison.MAX,
            bound=self.residual_volume_max_ul,
            unit="uL",
            source="incomplete aspiration carries reagent forward and prints as background",
        )

    def prewet_cv_criterion(self) -> Criterion:
        return Criterion(
            key="prewet_cv",
            label="membrane pre-wet uniformity CV",
            comparison=Comparison.MAX,
            bound=self.prewet_cv_max_percent,
            unit="%",
            source="a membrane that wets out unevenly coats and develops unevenly",
        )

    def neg_ctrl_criterion(self) -> Criterion:
        return Criterion(
            key="neg_ctrl_background",
            label="negative-control background (mean SFU/well)",
            comparison=Comparison.MAX,
            bound=self.neg_ctrl_background_max_sfu,
            unit="SFU",
            source="TUNABLE: high background voids the plate; set from your assay and verify",
        )

    def pos_ctrl_criterion(self) -> Criterion:
        return Criterion(
            key="pos_ctrl_response",
            label="positive-control response (mean SFU/well)",
            comparison=Comparison.MIN,
            bound=self.pos_ctrl_min_sfu,
            unit="SFU",
            source="TUNABLE: a mitogen well that does not fire means dead cells or a broken "
                   "detection chain; the whole plate is void; set from your assay and verify",
        )

    def replicate_cv_criterion(self, group: str) -> Criterion:
        return Criterion(
            key=f"replicate_cv_{group}",
            label=f"replicate CV ({group})",
            comparison=Comparison.MAX,
            bound=self.replicate_cv_max_percent,
            unit="%",
            source="spread across replicate wells; over the cutoff the mean is not trustworthy",
        )


@dataclass
class RunConfig:
    run_id: str
    operator: str
    mode: RunMode
    plate: PlateLayout
    antigens: List[Antigen]
    acceptance: AcceptanceCriteria
    site: SiteProfile
    cytokine: str = "IFN-gamma"          # the analyte; sets the capture/detection antibody pair
    precoated_plate: bool = False        # True skips the on-deck coat step (kit ships coated)
    output_dir: str = "runs"
    notes: str = ""

    def antigen_by_name(self, name: str) -> Optional[Antigen]:
        for a in self.antigens:
            if a.name == name:
                return a
        return None

    def cells_for(self, well: Well) -> int:
        return well.cells_per_well if well.cells_per_well is not None else self.site.cells_per_well

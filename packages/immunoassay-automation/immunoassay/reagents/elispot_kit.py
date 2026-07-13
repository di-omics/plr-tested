"""
elispot_kit.py - the ELISpot reagent chain, step by step, with provenance on every value.

The structure of an IFN-gamma (or other single-cytokine) ELISpot is standard and is
transcribed here as a sequence of steps: activate and coat the membrane, block, add cells
and stimulus, incubate, wash the cells off, add the biotinylated detection antibody, wash,
add the streptavidin-enzyme conjugate, wash, develop with substrate, stop, and dry. That
sequence is not invented; it is the published PVDF-ELISpot workflow (e.g. Mabtech and CTL
ImmunoSpot kits follow it step for step).

What this module refuses to invent is the numbers. Antibody and conjugate concentrations
are set by the specific kit on the bench and are marked TODO: they must be transcribed from
that kit's datasheet, and until they are, a hardware run is blocked. Per-well volumes and
incubation times are TUNABLE engineering defaults with a rationale, safe to simulate and to
be confirmed against the kit. The substrate development endpoint is CALIBRATE: it is
time-critical and lot-dependent, set by watching the first plate develop, then pinned.

The cytokine is configurable (IFN-gamma by default) because the mechanics are identical
across single-analyte ELISpot; only the antibody pair changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from ..provenance import Sourced, calibrate, todo, transcribed, tunable


@dataclass(frozen=True)
class Step:
    """One reagent step: what goes in, how much, how long, and where each value came from."""

    key: str
    title: str
    reagent: Sourced           # what the reagent is
    volume_ul: Sourced         # per-well volume
    incubation: Sourced        # time + condition, as a labelled value
    concentration: Optional[Sourced] = None   # None where a fixed reagent has no set conc
    note: str = ""

    def sourced_values(self) -> List[Sourced]:
        vals = [self.reagent, self.volume_ul, self.incubation]
        if self.concentration is not None:
            vals.append(self.concentration)
        return vals


def _time(value: str, rationale: str, name: str) -> Sourced:
    return tunable(value, rationale, name=name)


@dataclass
class ElispotKit:
    """The ordered reagent chain for a single-cytokine ELISpot.

    Built with `for_cytokine(...)`. `precoated` drops the on-deck coat step for kits that
    ship a coated plate. guard_values() returns the values a hardware run must resolve
    first: the kit-defined concentrations (TODO until transcribed) and the substrate
    endpoint (CALIBRATE until set on the first plate).
    """

    cytokine: str
    steps: List[Step] = field(default_factory=list)

    def guard_values(self) -> List[Sourced]:
        out: List[Sourced] = []
        for s in self.steps:
            out.extend(v for v in s.sourced_values() if v.blocks_hardware)
        return out

    def step(self, key: str) -> Optional[Step]:
        for s in self.steps:
            if s.key == key:
                return s
        return None


def for_cytokine(cytokine: str = "IFN-gamma", precoated: bool = False) -> ElispotKit:
    """Assemble the reagent chain for a single-cytokine ELISpot.

    Volumes and times are TUNABLE defaults in the range the published workflow uses, each
    with its rationale; concentrations that belong to the kit are TODO so a hardware run is
    blocked until they are transcribed; the substrate endpoint is CALIBRATE.
    """
    steps: List[Step] = []

    if not precoated:
        steps.append(Step(
            key="coat",
            title="Coat capture antibody",
            reagent=transcribed(
                f"capture anti-{cytokine} monoclonal antibody in sterile PBS",
                "the capture antibody is the first layer of a sandwich ELISpot; identity is "
                "set by the kit (e.g. a validated capture clone for this cytokine)",
                name="coat_antibody",
            ),
            concentration=todo(
                "transcribe the coating concentration from your kit datasheet (commonly a "
                "few to ~15 ug/mL in PBS); do not guess it",
                unit="ug/mL", name="coat_antibody_concentration",
            ),
            volume_ul=tunable(
                100.0, "a per-well coating volume that covers the membrane; confirm vs kit",
                unit="uL", name="coat_volume",
            ),
            incubation=_time(
                "overnight at 4 C", "cold overnight coating is the standard for even capture-"
                "antibody binding to PVDF; confirm vs kit", name="coat_incubation",
            ),
            note="skipped when the kit ships a pre-coated plate (precoated_plate: true)",
        ))

    steps.append(Step(
        key="block",
        title="Block",
        reagent=tunable(
            "cell culture medium with serum (e.g. RPMI-1640 + 10% FCS), sterile",
            "blocking the coated membrane with the same serum-containing medium the cells "
            "arrive in prevents non-specific binding and conditions the surface; confirm the "
            "blocking reagent vs kit",
            name="block_reagent",
        ),
        volume_ul=tunable(
            150.0, "a per-well block volume that fully covers the membrane; confirm vs kit",
            unit="uL", name="block_volume",
        ),
        incubation=_time(
            "30 to 60 min at room temperature", "a short RT block is sufficient; confirm vs kit",
            name="block_incubation",
        ),
    ))

    steps.append(Step(
        key="stimulate",
        title="Add cells and stimulus, incubate",
        reagent=transcribed(
            "PBMC (or effector cells) plus the well's antigen / stimulus, in medium",
            "the biological step: secreted cytokine is captured locally on the membrane as a "
            "spot; the stimulus is per well and comes from the plate layout",
            name="cells_and_stimulus",
        ),
        volume_ul=tunable(
            100.0, "cell suspension volume per well at the site's plating density; the density "
                   "itself is the SiteProfile's cells_per_well", unit="uL", name="stimulate_volume",
        ),
        incubation=_time(
            "18 to 48 h at 37 C, 5% CO2, undisturbed", "spot formation needs an undisturbed "
            "incubation; moving or vibrating the plate smears spots. Duration is antigen-"
            "dependent (IFN-gamma commonly ~18 to 24 h); confirm vs your assay",
            name="stimulate_incubation",
        ),
        note="off-instrument incubation; the plate must not be disturbed",
    ))

    steps.append(Step(
        key="detect",
        title="Detection antibody (biotinylated)",
        reagent=transcribed(
            f"biotinylated detection anti-{cytokine} monoclonal antibody",
            "the second sandwich layer; a biotinylated detection clone paired to the capture "
            "clone, identity set by the kit",
            name="detection_antibody",
        ),
        concentration=todo(
            "transcribe the detection-antibody working concentration from your kit datasheet "
            "(commonly ~1 ug/mL in PBS with a low % serum); do not guess it",
            unit="ug/mL", name="detection_antibody_concentration",
        ),
        volume_ul=tunable(
            100.0, "per-well detection volume; confirm vs kit", unit="uL", name="detect_volume",
        ),
        incubation=_time(
            "1 to 2 h at room temperature", "standard RT detection incubation; confirm vs kit",
            name="detect_incubation",
        ),
    ))

    steps.append(Step(
        key="conjugate",
        title="Streptavidin-enzyme conjugate",
        reagent=transcribed(
            "streptavidin conjugated to alkaline phosphatase (ALP) or HRP, per the kit",
            "binds the biotinylated detection antibody; the enzyme turns substrate into an "
            "insoluble spot. ALP with BCIP/NBT and HRP with AEC/TMB are the two standard pairs",
            name="conjugate_reagent",
        ),
        concentration=todo(
            "transcribe the streptavidin-enzyme working dilution from your kit datasheet; do "
            "not guess it",
            unit="dilution", name="conjugate_dilution",
        ),
        volume_ul=tunable(
            100.0, "per-well conjugate volume; confirm vs kit", unit="uL", name="conjugate_volume",
        ),
        incubation=_time(
            "1 h at room temperature", "standard RT conjugate incubation; confirm vs kit",
            name="conjugate_incubation",
        ),
    ))

    steps.append(Step(
        key="develop",
        title="Develop with substrate, then stop",
        reagent=transcribed(
            "enzyme substrate matched to the conjugate (BCIP/NBT for ALP, AEC or TMB for HRP)",
            "the substrate precipitates at the enzyme site to form a visible spot; it must "
            "match the conjugate enzyme",
            name="substrate_reagent",
        ),
        volume_ul=tunable(
            100.0, "per-well substrate volume; confirm vs kit", unit="uL", name="substrate_volume",
        ),
        incubation=calibrate(
            None, "the development endpoint is time-critical and lot-dependent: develop until "
                  "spots are distinct but before background rises, then stop by rinsing "
                  "thoroughly with water. Set the time by watching the first plate (commonly a "
                  "few to ~15 min) and pin it for the batch; over-development merges spots and "
                  "raises background",
            unit="s", name="substrate_development_endpoint",
        ),
        note="stop by flooding both sides of the membrane with deionized water; then dry in the dark",
    ))

    return ElispotKit(cytokine=cytokine, steps=steps)

"""SPRI cleanup volume arithmetic.

Ratios, input volumes, and removal margins are supplied by the run's explicit
method block. This module performs arithmetic only; it contains no assay defaults.
"""

from __future__ import annotations

from dataclasses import dataclass

@dataclass(frozen=True)
class SpriPlan:
    stage: str
    ratio: float
    input_volume_ul: float
    bead_volume_ul: float
    supernatant_volume_ul: float

    def as_text(self) -> str:
        return (
            f"{self.stage}: {self.ratio:g}X of {self.input_volume_ul:g} uL "
            f"-> {self.bead_volume_ul:g} uL beads, "
            f"remove {self.supernatant_volume_ul:g} uL supernatant"
        )


def plan(
    stage: str,
    ratio: float,
    input_volume_ul: float,
    supernatant_margin_ul: float,
) -> SpriPlan:
    """Derive bead and removal volumes from explicit operator parameters."""
    bead_volume = round(ratio * input_volume_ul, 1)
    supernatant = round(input_volume_ul + bead_volume + supernatant_margin_ul, 1)
    return SpriPlan(
        stage=stage,
        ratio=ratio,
        input_volume_ul=input_volume_ul,
        bead_volume_ul=bead_volume,
        supernatant_volume_ul=supernatant,
    )


def post_pcr1_plan(
    ratio: float,
    input_volume_ul: float,
    supernatant_margin_ul: float,
) -> SpriPlan:
    return plan(
        "post-PCR1 cleanup",
        ratio,
        input_volume_ul,
        supernatant_margin_ul,
    )


def post_pcr2_plan(
    ratio: float,
    input_volume_ul: float,
    supernatant_margin_ul: float,
) -> SpriPlan:
    return plan(
        "post-PCR2 cleanup",
        ratio,
        input_volume_ul,
        supernatant_margin_ul,
    )

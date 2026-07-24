"""
spri.py - the two SPRI bead cleanups in the PCR enrichment flow, as ratios.

The PCR enrichment flow cleans up twice: an anti-dimer clean after PCR1 and a final clean
after PCR2. Both are SPRI (solid-phase reversible immobilization) bead cleans; the only
thing that changes between them is the bead-to-sample ratio, which sets the size cutoff.
A lower ratio keeps only larger fragments (drops primer dimers and adapter dimers); a
higher ratio keeps more.

Ratio, input volume, and supernatant margin are required operator parameters. This
module only performs the arithmetic and carries no biological defaults.
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


def plan(stage: str, ratio: float, input_volume_ul: float,
         supernatant_margin_ul: float) -> SpriPlan:
    """Derive bead and supernatant volumes from a ratio, matching the repo module."""
    bead_volume = round(ratio * input_volume_ul, 1)
    supernatant = round(input_volume_ul + bead_volume + supernatant_margin_ul, 1)
    return SpriPlan(
        stage=stage,
        ratio=ratio,
        input_volume_ul=input_volume_ul,
        bead_volume_ul=bead_volume,
        supernatant_volume_ul=supernatant,
    )

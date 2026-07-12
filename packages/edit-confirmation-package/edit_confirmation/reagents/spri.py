"""
spri.py - the two SPRI bead cleanups in the amplicon-seq flow, as ratios.

The amplicon-seq flow cleans up twice: an anti-dimer clean after PCR1 and a final clean
after PCR2. Both are SPRI (solid-phase reversible immobilization) bead cleans; the only
thing that changes between them is the bead-to-sample ratio, which sets the size cutoff.
A lower ratio keeps only larger fragments (drops primer dimers and adapter dimers); a
higher ratio keeps more.

These ratios are transcribed from the repo's own bead-clean module
(hamilton-star/starlab_live/ampseq_bead_clean_ratio_col1.py), which is the validated
liquid-handling implementation. The bead volume is derived from the ratio and the input
volume, the same way that module derives it, and the derived volumes carry a "verify
against the physical protocol" flag because a cleanup that removes the wrong size range
silently ruins a library.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..provenance import Sourced, transcribed, tunable


# The two presets, from ampseq_bead_clean_ratio_col1.py.
POST_PCR1_RATIO = transcribed(
    0.90, "ampseq_bead_clean_ratio_col1.py, --preset anti-dimer: 0.90X of 25 uL PCR1",
    unit="X", name="post_pcr1_spri_ratio",
)
POST_PCR2_RATIO = transcribed(
    0.65, "ampseq_bead_clean_ratio_col1.py, --preset final: 0.65X of 25 uL PCR2",
    unit="X", name="post_pcr2_spri_ratio",
)

# Reaction input volume both cleans start from.
PCR_REACTION_VOLUME_UL = transcribed(
    25.0, "Amplicon-seq Library Prep, PCR1/PCR2 total reaction volume 25 uL",
    unit="uL", name="pcr_reaction_volume",
)

# The extra volume pulled when removing supernatant, to take all liquid off the beads.
SUPERNATANT_MARGIN_UL = tunable(
    10.0, "ampseq_bead_clean_ratio_col1.py SUPERNATANT_MARGIN_UL; ensures all liquid is "
          "removed above the pellet",
    unit="uL", name="supernatant_margin",
)


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
         supernatant_margin_ul: float = float(SUPERNATANT_MARGIN_UL.value)) -> SpriPlan:
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


def post_pcr1_plan() -> SpriPlan:
    return plan("post-PCR1 anti-dimer", float(POST_PCR1_RATIO.value),
                float(PCR_REACTION_VOLUME_UL.value))


def post_pcr2_plan() -> SpriPlan:
    return plan("post-PCR2 final", float(POST_PCR2_RATIO.value),
                float(PCR_REACTION_VOLUME_UL.value))

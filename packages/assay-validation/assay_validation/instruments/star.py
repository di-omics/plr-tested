"""
instruments/star.py - the Hamilton STAR adapter.

Records each liquid-handling action and, in hardware mode, resolves it to the validated
Pi script that actually performs it. It does not re-implement any pipetting geometry;
the tuned motions live in hamilton-star/ and this adapter points at them. In simulation
mode a dispense returns the (physically unobservable) delivered volumes it modeled, so
the qualification stage can turn them into a plate read; those are simulated values and
are flagged as such on the ActionRecord.
"""

from __future__ import annotations

from typing import List, Optional

from ..config import RunMode
from ..reagents.spri import SpriPlan
from ..simulation import DeckQuality, WELL_TUNED_DECK, simulate_dispensed_volumes
from .base import ActionRecord, Adapter

# Working directory for the resolved commands: the STAR scripts run from hamilton-star/
# via its run_on_pi.sh. Paths below are relative to that directory.
_STAR_DIR = "hamilton-star"


class StarAdapter(Adapter):
    instrument = "Hamilton STAR"

    def __init__(self, mode: RunMode, deck: DeckQuality = WELL_TUNED_DECK,
                 sink: "List[ActionRecord]" = None, tip_column: int = 1):
        super().__init__(mode, sink=sink)
        self.deck = deck
        self.tip_column = tip_column

    def _tipcol(self) -> str:
        return f" --tip-col {self.tip_column}"

    def qualify_dispense(self, run_id: str, volume_ul: float, n_replicates: int,
                         tip: str) -> Optional[List[float]]:
        """Dispense one qualified volume into n replicate wells for Gate 0.

        Returns the modeled delivered volumes in simulation, None in hardware. The motion
        is parameterized from the repo's Rhodamine test; the resolved command names it.
        """
        cmd = (
            f"cd {_STAR_DIR} && ./run_on_pi.sh "
            f"starlab_live/96wp_rhodamine_b_test_p1000_p50.py{self._tipcol()} "
            f"# parameterize: volume={volume_ul} uL, tip={tip}, replicates={n_replicates}"
        )
        rec = self._record(
            "qualify_dispense",
            {"volume_ul": volume_ul, "n_replicates": n_replicates, "tip": tip,
             "tip_column": self.tip_column},
            resolved_command=cmd,
            note="Gate 0 Rhodamine dispense; top up to the common read volume before reading",
        )
        if self.mode is RunMode.SIMULATION:
            return simulate_dispensed_volumes(run_id, volume_ul, n_replicates, self.deck)
        return None

    def run_wgs_prep_liquid_handling(self, stage_1_ul: float, stage_2_ul: float) -> None:
        """Whole-genome sequencing preparation liquid handling and thermal handoff.

        Maps to the validated whole-genome sequencing preparation e2e runner. The thermal amplification itself is the
        ODTC's job (a separate action); this is only the deck work up to the handoff.
        """
        cmd = (
            f"cd {_STAR_DIR}/protocols/validation/wgs_prep && "
            f"./run_wgs_prep_REAL_DISCARD_TIPS_e2e.sh{self._tipcol()}"
        )
        self._record(
            "run_wgs_prep_liquid_handling",
            {
                "stage_1_ul": stage_1_ul,
                "stage_2_ul": stage_2_ul,
                "tip_column": self.tip_column,
            },
            resolved_command=cmd,
            note=(
                "whole-genome sequencing preparation: execute operator-approved "
                f"stage transfers ({stage_1_ul} uL, {stage_2_ul} uL)"
            ),
        )

    def add_mastermix(self, stage: str, volume_ul: float, tip: str,
                      script: str) -> None:
        """Add a PCR master mix from the source column to the work column.

        `script` is the validated PCR enrichment master-mix script this maps to (01 for PCR1,
        03 for PCR2), so the run card runs the code that was dry-validated on the deck.
        """
        cmd = (f"cd {_STAR_DIR} && ./run_on_pi.sh "
               f"protocols/validation/pcr_enrichment/{script}{self._tipcol()}")
        self._record(
            "add_mastermix",
            {"stage": stage, "volume_ul": volume_ul, "tip": tip, "script": script,
             "tip_column": self.tip_column},
            resolved_command=cmd,
            note=f"{stage}: {volume_ul} uL master mix, source col1 -> work col1",
        )

    def add_reagent(self, label: str, volume_ul: float, tip: str,
                    script: str) -> None:
        """A generic reagent add (whole-genome sequencing preparation lysis / reaction / neutralization)."""
        cmd = (f"cd {_STAR_DIR} && ./run_on_pi.sh "
               f"protocols/validation/wgs_prep/{script}{self._tipcol()}")
        self._record(
            "add_reagent",
            {"label": label, "volume_ul": volume_ul, "tip": tip, "script": script,
             "tip_column": self.tip_column},
            resolved_command=cmd,
            note=f"{label}: {volume_ul} uL",
        )

    def spri_clean(self, spri: SpriPlan) -> None:
        preset = "anti-dimer" if "PCR1" in spri.stage else "final"
        cmd = (
            f"cd {_STAR_DIR} && ./run_on_pi.sh "
            f"starlab_live/pcr_enrichment_bead_clean_ratio_col1.py --preset {preset}{self._tipcol()}"
        )
        self._record(
            "spri_clean",
            {
                "stage": spri.stage,
                "ratio": spri.ratio,
                "bead_volume_ul": spri.bead_volume_ul,
                "supernatant_volume_ul": spri.supernatant_volume_ul,
                "tip_column": self.tip_column,
            },
            resolved_command=cmd,
            note=spri.as_text(),
        )

    def iswap_move(self, from_role: str, to_role: str) -> None:
        """Plate handoff with the iSWAP (deck <-> thermal cycler)."""
        self._record(
            "iswap_move",
            {"from": from_role, "to": to_role},
            resolved_command=(
                f"cd {_STAR_DIR} && ./run_on_pi.sh "
                f"# iSWAP {from_role} -> {to_role}; geometry per starlab_live/ handoff legs"
            ),
            note=f"iSWAP {from_role} -> {to_role} (geometry not yet tuned on hardware)",
        )

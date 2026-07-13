"""
instruments/washer.py - the plate washer/dispenser (Agilent BioTek EL406 or equivalent).

The washer is the instrument that makes ELISpot reproducible. The assay's dominant variance
is the wash: too gentle and cells and debris stay behind and print as background, too harsh
and the wash lifts the capture-antibody layer off the membrane. A programmed washer runs the
same cycles, the same volume, and the same probe height every time, which is exactly the
site-to-site drift a manual wash cannot control. The EL406 is a good fit because it is a
combined washer and bulk dispenser: it can both run the washes and dispense the qualification
ladder and bulk buffers, so one instrument owns the fluidics the wash depends on.

This adapter does three things:
  - qualify_dispense / qualify_residual: the Gate 0 reads. Dispense precision (via the
    Rhodamine ladder, dispensed by the EL406's own manifold) and aspiration completeness
    (residual volume left in a well) are what "the washer is fit to run this plate" means,
    measured, not assumed.
  - wash: a programmed wash step (cycles, volume, soak, and - the ELISpot-critical part -
    the aspiration probe height above the membrane). The height is a membrane-safety value
    carried from the SiteProfile / membrane.py, not a default the washer picks.

In hardware mode each action resolves to the Pi command that would run it against a
PyLabRobot washer backend. That backend and its validated scripts are not in this repo yet;
the command shape is the plan for when they are (see the package README status).
"""

from __future__ import annotations

from typing import List, Optional

from ..config import RunMode
from ..simulation import (
    WELL_TUNED_WASHER,
    WasherQuality,
    simulate_dispensed_volumes,
    simulate_residual_volumes,
)
from .base import Adapter

# Where the resolved commands would run. This integration does not exist in the repo yet;
# the path is the intended home, consistent with the repo's instrument-integrations/ layout.
_WASHER_DIR = "instrument-integrations/biotek-el406"


class WasherAdapter(Adapter):
    instrument = "BioTek EL406 washer/dispenser"

    def __init__(self, mode: RunMode, quality: WasherQuality = WELL_TUNED_WASHER,
                 sink=None):
        super().__init__(mode, sink=sink)
        self.quality = quality

    def qualify_dispense(self, run_id: str, volume_ul: float, n_replicates: int
                         ) -> Optional[List[float]]:
        """Dispense one qualified volume into n replicate wells for Gate 0.

        Returns the modeled delivered volumes in simulation, None in hardware (the plate
        reader supplies the signals there). The Rhodamine method reads dispense CV.
        """
        cmd = (
            f"cd {_WASHER_DIR} && ./run_on_pi.sh dispense_ladder.py "
            f"# NOT YET BUILT: dispense {volume_ul} uL x {n_replicates} replicate wells, "
            f"Rhodamine B, side-wall low-flow"
        )
        self._record(
            "qualify_dispense",
            {"volume_ul": volume_ul, "n_replicates": n_replicates},
            resolved_command=cmd,
            note="Gate 0 dispense precision; top up to the common read volume before reading",
        )
        if self.mode is RunMode.SIMULATION:
            return simulate_dispensed_volumes(run_id, volume_ul, n_replicates, self.quality)
        return None

    def qualify_residual(self, run_id: str, n_wells: int) -> Optional[List[float]]:
        """Measure the volume left in each well after one aspiration cycle (Gate 0).

        Returns modeled residuals in simulation, None in hardware (measured gravimetrically
        or by a dye read on the instrument). A high or uneven residual is what carries
        reagent forward into the next step and prints as background.
        """
        cmd = (
            f"cd {_WASHER_DIR} && ./run_on_pi.sh residual_check.py "
            f"# NOT YET BUILT: aspirate {n_wells} filled wells, measure residual volume"
        )
        self._record(
            "qualify_residual",
            {"n_wells": n_wells},
            resolved_command=cmd,
            note="Gate 0 aspiration completeness",
        )
        if self.mode is RunMode.SIMULATION:
            return simulate_residual_volumes(run_id, n_wells, self.quality)
        return None

    def wash(self, step_label: str, cycles: int, volume_ul: float, soak_s: float,
             aspiration_height_mm: Optional[float]) -> None:
        """A programmed wash step. aspiration_height_mm is the membrane-safety clearance.

        The height comes from the SiteProfile (taught per plate lot); passing it explicitly,
        rather than letting the washer default, is the point - a probe that rides too low
        scratches the membrane. In hardware a None height must have been caught by the
        run guard before this is reached.
        """
        height = "site-taught" if aspiration_height_mm is not None else "NOT SET"
        cmd = (
            f"cd {_WASHER_DIR} && ./run_on_pi.sh wash_program.py "
            f"# NOT YET BUILT: '{step_label}' {cycles}x {volume_ul} uL, soak {soak_s}s, "
            f"aspiration height {aspiration_height_mm} mm ({height}), side-wall dispense"
        )
        self._record(
            "wash",
            {"step": step_label, "cycles": cycles, "volume_ul": volume_ul, "soak_s": soak_s,
             "aspiration_height_mm": aspiration_height_mm},
            resolved_command=cmd,
            note=f"{step_label}: {cycles} cycles x {volume_ul} uL",
        )

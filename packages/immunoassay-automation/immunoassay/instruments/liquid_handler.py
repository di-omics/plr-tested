"""
instruments/liquid_handler.py - the reagent and cell adds (Opentrons Flex by default).

The washer owns the wash; the liquid handler owns everything that goes IN: the coating
antibody, the block, the cells-plus-stimulus, the detection antibody, the conjugate, and the
substrate. The default is an Opentrons Flex - it has the deck, the pipetting range, and the
gentle low-flow control an ELISpot's small precise adds want, and it pairs cleanly with the
EL406 doing the fluidics. The cheaper OT-2 is a drop-in for a lower-throughput line, and a
lab that already runs a Hamilton STAR (as this repo does) can use that instead. The adapter
is deliberately backend-named so the resolved command records which one a site is on, but the
plan - what goes where, in what volume, down the side wall at capped flow - is identical.

The membrane rule from membrane.py rides on every add: reagents go down the side wall at a
capped flow rate, never a center jet at the membrane. That is passed through on each action
so the record shows it, and so a real backend can enforce it.

Like the washer, the hardware commands target integrations that are not in this repo yet;
the STAR path is the exception, since its liquid handling is validated here (hamilton-star/),
and a STAR-based ELISpot would reuse those motions.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from ..config import RunMode
from .base import Adapter


class Backend(str, Enum):
    OT2 = "opentrons_ot2"
    FLEX = "opentrons_flex"
    STAR = "hamilton_star"


_DIRS = {
    Backend.OT2: "instrument-integrations/opentrons",
    Backend.FLEX: "instrument-integrations/opentrons",
    Backend.STAR: "hamilton-star",   # validated liquid handling already lives here
}


class LiquidHandlerAdapter(Adapter):
    instrument = "liquid handler"

    def __init__(self, mode: RunMode, backend: Backend = Backend.FLEX, sink=None):
        super().__init__(mode, sink=sink)
        self.backend = backend
        self.instrument = f"liquid handler ({backend.value})"

    def _cmd(self, script: str, detail: str) -> str:
        d = _DIRS[self.backend]
        built = " " if self.backend is Backend.STAR else " # NOT YET BUILT: "
        return f"cd {d} && ./run_on_pi.sh {script}{built}{detail}"

    def dispense_reagent(self, step_key: str, title: str, volume_ul: float,
                         dispense_mode: str) -> None:
        """A reagent add (coat, block, detection, conjugate, substrate)."""
        cmd = self._cmd(
            f"elispot_add_{step_key}.py",
            f"{title}: {volume_ul} uL/well, {dispense_mode}",
        )
        self._record(
            "dispense_reagent",
            {"step": step_key, "volume_ul": volume_ul, "dispense_mode": dispense_mode,
             "backend": self.backend.value},
            resolved_command=cmd,
            note=f"{title}: {volume_ul} uL/well ({dispense_mode})",
        )

    def add_cells(self, volume_ul: float, cells_per_well: int, dispense_mode: str) -> None:
        """Plate the cell suspension plus each well's stimulus.

        The stimulus identity is per well (the plate layout); this records the mechanical
        add. Cells go in gently down the side wall so they settle evenly on the membrane.
        """
        cmd = self._cmd(
            "elispot_plate_cells.py",
            f"plate {cells_per_well} cells/well in {volume_ul} uL, {dispense_mode}",
        )
        self._record(
            "add_cells",
            {"volume_ul": volume_ul, "cells_per_well": cells_per_well,
             "dispense_mode": dispense_mode, "backend": self.backend.value},
            resolved_command=cmd,
            note=f"{cells_per_well} cells/well in {volume_ul} uL, then undisturbed incubation",
        )

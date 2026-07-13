"""
stages/stimulation.py - plate the cells and their stimuli, then hand off to the incubator.

This is the biological step, and it is the one the automation frames rather than owns. The
liquid handler plates each well's cells and stimulus - test antigens, the mitogen positive
control, medium-only negative control, no-cell blanks - down the side wall so the cells
settle evenly on the membrane. Then the plate goes to a 37 C / 5% CO2 incubator, undisturbed,
for the spot-forming incubation. There is no gate here: nothing measurable has happened yet,
and the one hard rule (do not disturb the plate - vibration smears spots) is a scheduling
constraint on the run, recorded so an operator and a scheduler both see it.

The stage also freezes the plate layout into the record: which well holds which antigen at
which role, and how many cells. That map is what the readout gate reads its controls from and
what the dossier prints, so it is captured here once.
"""

from __future__ import annotations

from ..config import WellRole
from ..reagents.elispot_kit import for_cytokine
from ..membrane import default_constraints
from .base import Stage, StageContext, StageResult, StageStatus


class Stimulation(Stage):
    name = "stimulation"
    title = "Cell plating and stimulation"

    def run(self, ctx: StageContext) -> StageResult:
        mark = ctx.action_mark()
        cfg = ctx.config
        kit = for_cytokine(cfg.cytokine, precoated=cfg.precoated_plate)
        stim = kit.step("stimulate")
        dispense_mode = str(default_constraints().dispense_mode.value)

        # One cell-plating action per distinct cell density on the plate (usually just one).
        densities = sorted({cfg.cells_for(w) for w in cfg.plate.wells
                            if w.role is not WellRole.BLANK})
        for density in densities:
            ctx.lh.add_cells(float(stim.volume_ul.value), density, dispense_mode)

        layout = []
        for w in cfg.plate.wells:
            layout.append({
                "well": w.address,
                "role": w.role.value,
                "antigen": w.antigen or "(none)",
                "cells": (0 if w.role is WellRole.BLANK else cfg.cells_for(w)),
            })

        groups = cfg.plate.test_groups()
        n_neg = len(cfg.plate.negative_wells())
        n_pos = len(cfg.plate.positive_wells())

        message = (
            f"plated {len(cfg.plate.wells)} wells: {len(groups)} test antigen(s), "
            f"{n_pos} positive-control and {n_neg} negative-control well(s); "
            f"incubate {stim.incubation.value}"
        )
        return StageResult(
            name=self.name,
            title=self.title,
            status=StageStatus.COMPLETED,
            message=message,
            data={
                "incubation": str(stim.incubation.value),
                "stimulate_volume_ul": float(stim.volume_ul.value),
                "densities": densities,
                "n_antigens": len(groups),
                "n_pos_ctrl_wells": n_pos,
                "n_neg_ctrl_wells": n_neg,
                "layout": layout,
                "do_not_disturb": "plate must not be moved or vibrated during incubation",
            },
            actions=ctx.actions_since(mark),
        )

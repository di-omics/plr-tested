"""
stages/develop.py - the wash-heavy core: wash off the cells, detect, develop, stop, dry.

This is the span where automation earns its place. After the incubation the plate goes
through: wash off the cells, add biotinylated detection antibody, wash, add streptavidin-
enzyme conjugate, wash, add substrate, watch it develop, stop by flooding with water, dry.
Every one of those washes is a place a manual run drifts, and the cell-wash in particular is
the one that decides background - too gentle leaves debris, too harsh lifts the capture layer.
Running it as a programmed washer step, at the qualified probe height, is the whole reason the
line exists.

There is no gate inside develop; the gate is the readout that follows. What this stage does is
execute the reagent chain from detection through drying in order, at the membrane-safe dispense
mode, and record each step and each wash so the dossier shows exactly how the plate was
handled. The substrate development endpoint is the CALIBRATE value from the kit - a timed
window set by watching the first plate; the record carries it so a stop time is never implicit.
"""

from __future__ import annotations

from ..membrane import default_constraints
from ..reagents.elispot_kit import for_cytokine
from .base import Stage, StageContext, StageResult, StageStatus


class Develop(Stage):
    name = "develop"
    title = "Wash, detect, develop, stop, dry"

    def run(self, ctx: StageContext) -> StageResult:
        mark = ctx.action_mark()
        cfg = ctx.config
        site = cfg.site
        membrane = default_constraints(site.aspiration_height_mm)
        dispense_mode = str(membrane.dispense_mode.value)
        kit = for_cytokine(cfg.cytokine, precoated=cfg.precoated_plate)

        def wash(label: str) -> None:
            ctx.washer.wash(label, site.wash_cycles, site.wash_volume_ul,
                            site.soak_seconds, site.aspiration_height_mm)

        steps_run = []

        # Wash off the cells - the background-determining wash.
        wash("wash off cells")
        steps_run.append("wash off cells")

        # Detection antibody, wash.
        detect = kit.step("detect")
        ctx.lh.dispense_reagent("detect", detect.title, float(detect.volume_ul.value), dispense_mode)
        wash("post-detection wash")
        steps_run.append(detect.title)

        # Conjugate, wash.
        conj = kit.step("conjugate")
        ctx.lh.dispense_reagent("conjugate", conj.title, float(conj.volume_ul.value), dispense_mode)
        wash("post-conjugate wash")
        steps_run.append(conj.title)

        # Substrate, develop to the calibrated endpoint, stop, dry.
        dev = kit.step("develop")
        ctx.lh.dispense_reagent("develop", dev.title, float(dev.volume_ul.value), dispense_mode)
        steps_run.append(dev.title)

        endpoint = dev.incubation  # CALIBRATE Sourced value: the development stop time
        message = (
            f"developed plate through {len(steps_run)} reagent steps at "
            f"{site.wash_cycles}x wash cycles; development endpoint: {endpoint.as_label()} "
            f"[{endpoint.origin.value}]"
        )
        return StageResult(
            name=self.name,
            title=self.title,
            status=StageStatus.COMPLETED,
            message=message,
            data={
                "steps": steps_run,
                "wash_cycles": site.wash_cycles,
                "wash_volume_ul": site.wash_volume_ul,
                "aspiration_height_mm": site.aspiration_height_mm,
                "dispense_mode": dispense_mode,
                "development_endpoint": endpoint.as_label(),
                "development_endpoint_origin": endpoint.origin.value,
                "stop_and_dry": "flood both membrane faces with deionized water, then dry in the dark",
            },
            actions=ctx.actions_since(mark),
        )

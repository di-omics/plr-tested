"""
stages/readout.py - Gate 2: count the spots, validate the plate, call the responses.

This is where the assay becomes a result, and where the science gate lives. The imager counts
spot-forming units per well; then two things happen, in this order, because the order is the
logic:

  1. Plate validity (run-level, STOP on failure). The mitogen positive control must fire above
     its floor - a positive control that does not fire means the cells were dead or the
     detection chain broke, and NO well on the plate can be trusted, so the plate is void. And
     the negative-control background must sit under its ceiling - global high background (a
     bad wash, over-development) voids the plate the same way. Either failing stops the run:
     there is nothing worth reporting off an invalid plate.

  2. Response calling (per antigen, PROCEED_SUBSET on failure). For a valid plate, each test
     antigen group is scored against the negative-control background by the configured method
     (acceptance.response_method): the empirical net-plus-fold rule, or the distribution-free
     resampling permutation test (dfr2x / dfr). Its replicate CV decides whether the mean is
     trustworthy. A group whose replicates scatter past the CV cutoff is
     dropped from the summary (its mean cannot be relied on); a group at or above saturation is
     kept but flagged TNTC, a qualitative positive that is not quantitative.

The response calls are the loop-closing output: they, and the background and positive-control
levels behind them, are what the handoff turns into recommendations for the next run.
"""

from __future__ import annotations

from typing import Dict, List

from ..config import WellRole
from ..gates import SampleVerdict, check, evaluate_per_sample
from ..qc_math import (
    call_response,
    call_response_dfr,
    cv_percent_or_none,
    mean,
    normalize_per_cells,
)
from ..simulation import GOOD_PLATE, PlateBiology, simulate_well_sfu
from .base import Stage, StageContext, StageResult, StageStatus


class Readout(Stage):
    name = "readout"
    title = "Gate 2 - readout, plate validity, and response calls"

    def __init__(self, biology: PlateBiology = GOOD_PLATE):
        # biology is a simulation knob only (GOOD_PLATE / HIGH_BACKGROUND_PLATE /
        # DEAD_CELLS_PLATE). It has no effect on a hardware run, where the imager supplies
        # the counts.
        self.biology = biology

    def run(self, ctx: StageContext) -> StageResult:
        mark = ctx.action_mark()
        cfg = ctx.config
        acc = cfg.acceptance

        # Model the truth (simulation only), then count on the imager.
        truth: Dict[str, int] = {}
        for w in cfg.plate.wells:
            truth[w.address] = simulate_well_sfu(cfg.run_id, w, cfg.cells_for(w), self.biology)
        counts = ctx.imager.count(
            cfg.run_id, "elispot_plate", truth,
            saturation_sfu=acc.saturation_sfu,
            background_offset_sfu=cfg.site.imager_background_offset_sfu,
        )

        by_addr = {w.address: w for w in cfg.plate.wells}
        neg_counts = [counts[w.address] for w in cfg.plate.negative_wells()]
        pos_counts = [counts[w.address] for w in cfg.plate.positive_wells()]
        blank_counts = [counts[w.address] for w in cfg.plate.blank_wells()]
        bg_mean = mean(neg_counts) if neg_counts else 0.0
        pos_mean = mean(pos_counts) if pos_counts else 0.0

        # 1. Plate validity, run-level.
        pos_crit = acc.pos_ctrl_criterion()
        neg_crit = acc.neg_ctrl_criterion()
        run_outcomes = [check(pos_crit, pos_mean), check(neg_crit, bg_mean)]

        # 2. Per-antigen scoring and per-well QC verdicts.
        groups = cfg.plate.test_groups()
        response_rows: List[dict] = []
        verdicts: List[SampleVerdict] = []

        for antigen, wells in groups.items():
            gcounts = [counts[w.address] for w in wells]
            cells = cfg.cells_for(wells[0])
            if acc.response_method in ("dfr2x", "dfr"):
                call = call_response_dfr(
                    antigen, gcounts, neg_counts,
                    alpha=acc.dfr_alpha,
                    saturation_sfu=acc.saturation_sfu,
                    require_fold_2x=(acc.response_method == "dfr2x"),
                    min_stimulation_index=acc.response_min_stimulation_index,
                )
            else:
                call = call_response(
                    antigen, gcounts, neg_counts,
                    min_net_sfu=acc.response_min_net_sfu,
                    min_stimulation_index=acc.response_min_stimulation_index,
                    saturation_sfu=acc.saturation_sfu,
                )
            rep_cv = cv_percent_or_none(gcounts)
            cv_crit = acc.replicate_cv_criterion(antigen)
            cv_ok = rep_cv is None or cv_crit.check(rep_cv)

            row = call.to_dict()
            row.update({
                "n_wells": len(wells),
                "wells": [w.address for w in wells],
                "replicate_cv_percent": (None if rep_cv is None else round(rep_cv, 2)),
                "replicate_cv_ok": cv_ok,
                "cells_per_well": cells,
                "net_per_million": round(
                    normalize_per_cells(call.net, cells, acc.report_per_cells), 1),
                "report_per_cells": acc.report_per_cells,
            })
            response_rows.append(row)

            note = ("" if cv_ok else
                    f"replicate CV {rep_cv:.1f}% over {acc.replicate_cv_max_percent}%; mean not trusted")
            for w in wells:
                outs = [] if rep_cv is None else [check(cv_crit, rep_cv)]
                verdicts.append(SampleVerdict(sample_id=w.address, passed=cv_ok,
                                              outcomes=outs, note=note))

        # Controls and blanks are validity-checked at run level; they always carry forward.
        for w in cfg.plate.wells:
            if w.role in (WellRole.TEST,):
                continue
            verdicts.append(SampleVerdict(sample_id=w.address, passed=True,
                                          note=f"{w.role.value} (checked at run level)"))

        gate = evaluate_per_sample(self.title, verdicts, run_outcomes=run_outcomes)

        # Publish the response calls for the handoff to turn into recommendations.
        ctx.shared["response_calls"] = response_rows
        ctx.shared["background_mean_sfu"] = bg_mean
        ctx.shared["pos_ctrl_mean_sfu"] = pos_mean

        status = StageStatus.COMPLETED if gate.passed else StageStatus.STOPPED
        n_pos_antigens = sum(1 for r in response_rows if r["positive"])
        if gate.stopped:
            message = gate.message
        else:
            message = (
                f"plate valid (pos ctrl {pos_mean:.0f} SFU, background {bg_mean:.1f} SFU); "
                f"{n_pos_antigens} of {len(response_rows)} antigen(s) called positive"
            )

        return StageResult(
            name=self.name,
            title=self.title,
            status=status,
            message=message,
            gate=gate,
            data={
                "pos_ctrl_mean_sfu": round(pos_mean, 1),
                "pos_ctrl_floor_sfu": acc.pos_ctrl_min_sfu,
                "background_mean_sfu": round(bg_mean, 1),
                "background_ceiling_sfu": acc.neg_ctrl_background_max_sfu,
                "blank_mean_sfu": round(mean(blank_counts), 1) if blank_counts else None,
                "saturation_sfu": acc.saturation_sfu,
                "responses": response_rows,
                "well_counts": {a: counts[a] for a in sorted(counts)},
            },
            actions=ctx.actions_since(mark),
        )

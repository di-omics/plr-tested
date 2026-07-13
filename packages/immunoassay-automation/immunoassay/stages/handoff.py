"""
stages/handoff.py - the result, and the feed-forward into the next run.

The plate is valid and scored; this stage packages what came out. Two things:

  - The results: per antigen, the call (positive / negative / TNTC), the net spots over
    background, the stimulation index, and the count normalized to a common cell number so
    it compares across wells and sites. Emitted as a table in the dossier and as a CSV.

  - The recommendations: the loop-closing part the JD asks for. The readout's own numbers -
    background level, positive-control level, replicate scatter, saturation - imply what to
    change next time, and this stage states those as concrete, bounded parameter deltas (add
    wash cycles, drop the cell density, re-check aspiration), each tied to the number that
    triggered it. They are heuristics, labelled as such; the point is that returning data
    shapes the next design instead of sitting in a report.
"""

from __future__ import annotations

import csv
import io
from typing import List

from .base import Stage, StageContext, StageResult, StageStatus


def _recommendations(ctx: StageContext, responses: List[dict]) -> List[dict]:
    cfg = ctx.config
    acc = cfg.acceptance
    bg = ctx.shared.get("background_mean_sfu", 0.0)
    pos = ctx.shared.get("pos_ctrl_mean_sfu", 0.0)
    recs: List[dict] = []

    # Background rising toward the ceiling: tighten the wash before it voids a plate.
    if bg > 0.5 * acc.neg_ctrl_background_max_sfu:
        recs.append({
            "trigger": f"background {bg:.1f} SFU is over half the {acc.neg_ctrl_background_max_sfu:.0f} ceiling",
            "action": f"add 1 to 2 wash cycles (currently {cfg.site.wash_cycles}) and re-check "
                      f"the Gate 0 aspiration residual; the wash is the background lever",
        })

    # Positive control saturating: it fires but is off the top of the quantitative range.
    if pos >= acc.saturation_sfu:
        recs.append({
            "trigger": f"positive control {pos:.0f} SFU is at/above saturation {acc.saturation_sfu:.0f}",
            "action": f"titrate the cell density down from {cfg.site.cells_per_well} cells/well "
                      f"so the positive control lands inside the countable range",
        })

    # Any group whose replicates scattered: chase the mechanical cause.
    noisy = [r["antigen"] for r in responses if not r.get("replicate_cv_ok", True)]
    if noisy:
        recs.append({
            "trigger": f"replicate CV over cutoff for: {', '.join(noisy)}",
            "action": "re-check dispense and wash uniformity for those columns; the mean is "
                      "not trustworthy until the scatter is understood",
        })

    # Saturated test responders: real positives, but not quantitative.
    sat = [r["antigen"] for r in responses if r.get("saturated")]
    if sat:
        recs.append({
            "trigger": f"saturated (TNTC) test antigen(s): {', '.join(sat)}",
            "action": "re-run these at a lower cell density (or a dilution series) to bring the "
                      "count into the quantitative range",
        })

    if not recs:
        recs.append({
            "trigger": "background, positive control, replicate scatter, and saturation all in range",
            "action": "no parameter change indicated; carry the current site profile forward",
        })
    return recs


def _results_csv(responses: List[dict]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["antigen", "n_wells", "wells", "mean_sfu", "background_sfu", "net_sfu",
                "stimulation_index", "net_per_million", "method", "p_value", "positive",
                "saturated", "replicate_cv_percent", "replicate_cv_ok"])
    for r in responses:
        w.writerow([
            r["antigen"], r["n_wells"], " ".join(r["wells"]),
            r["test_mean_sfu"], r["background_mean_sfu"], r["net_sfu"],
            r["stimulation_index"], r["net_per_million"],
            r.get("method", "empirical"),
            ("" if r.get("p_value") is None else r["p_value"]),
            "yes" if r["positive"] else "no",
            "yes" if r["saturated"] else "no",
            ("" if r["replicate_cv_percent"] is None else r["replicate_cv_percent"]),
            "yes" if r["replicate_cv_ok"] else "no",
        ])
    return buf.getvalue()


class Handoff(Stage):
    name = "handoff"
    title = "Results and next-run recommendations"

    def run(self, ctx: StageContext) -> StageResult:
        mark = ctx.action_mark()
        responses = ctx.shared.get("response_calls", [])
        survivors = set(ctx.active_addresses)

        # A group counts as reported if at least one of its wells survived the readout gate.
        reported = [r for r in responses if any(a in survivors for a in r["wells"])]
        dropped = [r["antigen"] for r in responses if r not in reported]

        recs = _recommendations(ctx, responses)
        csv_text = _results_csv(reported)
        n_pos = sum(1 for r in reported if r["positive"])

        message = (
            f"reported {len(reported)} antigen(s): {n_pos} positive, "
            f"{len(reported) - n_pos} negative"
            + (f"; dropped {', '.join(dropped)} (untrustworthy)" if dropped else "")
        )
        return StageResult(
            name=self.name,
            title=self.title,
            status=StageStatus.COMPLETED,
            message=message,
            data={
                "responses": reported,
                "dropped_antigens": dropped,
                "recommendations": recs,
                "results_csv": csv_text,
                "n_positive": n_pos,
                "n_reported": len(reported),
            },
            actions=ctx.actions_since(mark),
        )

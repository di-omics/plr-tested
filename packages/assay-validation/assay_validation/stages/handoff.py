"""
stages/handoff.py - hand the libraries off to fragment analyzer and the sequencer.

The package drives liquid handling, thermal cycling, and plate reading; it does not run
a fragment analyzer or a sequencer. What it can do is produce the exact submission those
instruments need, from the run's own data, so the handoff is not a person retyping
numbers off a screen. Three artifacts:

  - a fragment analyzer submission: which wells, the expected final library size, and the
    measured concentration, plus the size window a clean library should fall in (a band
    at the primer-dimer size means the anti-dimer clean did not hold).
  - an equal-mass pooling plan: how much of each library to pool so the sequencer sees
    even coverage. This is computed from the Gate 2 concentrations, which is the
    returning data feeding forward into the next decision.
  - a sequencing sample sheet: one row per surviving library, carrying the locus,
    expected PCR product size, and requested analysis.

This stage runs on the survivors of Gate 2 only, so a dropped well never reaches a
flow cell.
"""

from __future__ import annotations

import csv
import io
from typing import Dict, List

from ..config import AnalysisType
from .base import Stage, StageContext, StageResult, StageStatus

# Requested downstream sequencing analysis.
_ANALYSIS_INTENT = {
    AnalysisType.VARIANT_CALLING: "call sequence variants and report the allele spectrum",
    AnalysisType.TARGET_CONFIRMATION: "confirm the requested target sequence",
    AnalysisType.SEQUENCE_VALIDATION: "validate base calls across the target region",
    AnalysisType.TARGETED_SEQUENCE: "report the targeted sequence and observed variants",
    AnalysisType.UNKNOWN: "report all variants against the supplied reference",
}


class Handoff(Stage):
    name = "handoff"
    title = "Handoff - fragment analyzer QC and sequencing"

    def run(self, ctx: StageContext) -> StageResult:
        mark = ctx.action_mark()
        samples = ctx.active_samples()
        locus = ctx.config.locus
        method = ctx.config.method
        quant: Dict[str, dict] = ctx.shared.get("quant_post_pcr_enrichment", {})

        final_bp = locus.pcr_product_bp + method.indexing_overhang_bp

        fragment_analysis_rows: List[dict] = []
        pooling_rows: List[dict] = []
        samplesheet_rows: List[dict] = []
        for s in samples:
            q = quant.get(s.id, {})
            conc = q.get("concentration_ng_per_ul")
            pool_ul = (round(method.pool_target_mass_ng / conc, 2)
                       if conc and conc > 0 else None)
            fragment_analysis_rows.append({
                "sample_id": s.id,
                "well": s.well,
                "expected_size_bp": final_bp,
                "concentration_ng_per_ul": conc,
                "pass_window_bp": (
                    f"{final_bp - method.fragment_window_below_bp} to "
                    f"{final_bp + method.fragment_window_above_bp}"
                ),
                "flag_dimer_below_bp": method.dimer_flag_below_bp,
            })
            pooling_rows.append({
                "sample_id": s.id,
                "well": s.well,
                "concentration_ng_per_ul": conc,
                "volume_to_pool_ul": pool_ul,
                "target_mass_ng": method.pool_target_mass_ng,
            })
            samplesheet_rows.append({
                "Sample_ID": s.id,
                "Sample_Well": s.well,
                "Sample_Type": s.sample_type.value,
                "Locus": locus.name,
                "PCR_product_bp": locus.pcr_product_bp,
                "Expected_Library_bp": final_bp,
                "I7_Index_ID": "TODO_assign_index",
                "I5_Index_ID": "TODO_assign_index",
                "Analysis_Intent": _ANALYSIS_INTENT.get(ctx.config.analysis_type,
                                                        _ANALYSIS_INTENT[AnalysisType.UNKNOWN]),
            })

        samplesheet_csv = _rows_to_csv(samplesheet_rows)

        return StageResult(
            name=self.name,
            title=self.title,
            status=StageStatus.COMPLETED,
            message=(f"{len(samples)} librar(ies) ready; expected final size {final_bp} bp; "
                     f"pool by equal mass ({method.pool_target_mass_ng} ng each)"),
            data={
                "n_libraries": len(samples),
                "expected_final_bp": final_bp,
                "analysis_type": ctx.config.analysis_type.value,
                "analysis_intent": _ANALYSIS_INTENT.get(ctx.config.analysis_type,
                                                        _ANALYSIS_INTENT[AnalysisType.UNKNOWN]),
                "fragment_analysis": fragment_analysis_rows,
                "pooling": pooling_rows,
                "samplesheet_rows": samplesheet_rows,
                "samplesheet_csv": samplesheet_csv,
            },
            actions=ctx.actions_since(mark),
        )


def _rows_to_csv(rows: List[dict]) -> str:
    if not rows:
        return ""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()

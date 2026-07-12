"""
stages/handoff.py - hand the libraries off to TapeStation and the sequencer.

The package drives liquid handling, thermal cycling, and plate reading; it does not run
a TapeStation or a sequencer. What it can do is produce the exact submission those
instruments need, from the run's own data, so the handoff is not a person retyping
numbers off a screen. Three artifacts:

  - a TapeStation submission: which wells, the expected final library size, and the
    measured concentration, plus the size window a clean library should fall in (a band
    at the primer-dimer size means the anti-dimer clean did not hold).
  - an equal-mass pooling plan: how much of each library to pool so the sequencer sees
    even coverage. This is computed from the Gate 2 concentrations, which is the
    returning data feeding forward into the next decision.
  - an Illumina sample sheet: one row per surviving library, carrying the locus, the
    expected amplicon size, and the edit the analysis is meant to confirm, so the
    downstream variant calling knows what it is looking for.

This stage runs on the survivors of Gate 2 only, so a dropped well never reaches a
flow cell.
"""

from __future__ import annotations

import csv
import io
from typing import Dict, List

from ..config import EditType
from ..provenance import tunable
from .base import Stage, StageContext, StageResult, StageStatus

# Length added to the PCR1 amplicon by the PCR2 indexing primers (adapters + indices).
INDEXING_OVERHANG_BP = tunable(
    120, "approximate length the Nextera-style indexing PCR adds to the amplicon "
         "(adapters + i5 + i7); confirm for your index kit",
    unit="bp", name="indexing_overhang_bp",
)
# Target mass per library in the pool, for even representation.
POOL_TARGET_MASS_NG = tunable(
    10.0, "target mass per library contributed to the pool for even coverage; verify "
          "against the sequencer's loading guidance",
    unit="ng", name="pool_target_mass_ng",
)

# What the sequencing analysis is meant to confirm, by edit type.
_ANALYSIS_INTENT = {
    EditType.CRISPR_INDEL: "call indels at the cut site; report editing efficiency and allele spectrum",
    EditType.CRISPR_HDR: "confirm the intended knock-in allele; quantify HDR vs NHEJ",
    EditType.BASE_EDIT: "confirm the target base conversion; report bystander edits",
    EditType.PRIME_EDIT: "confirm the programmed edit; report scaffold incorporation and indels",
    EditType.UNKNOWN: "genotype the locus and report all variants against reference",
}


class Handoff(Stage):
    name = "handoff"
    title = "Handoff - TapeStation QC and sequencing"

    def run(self, ctx: StageContext) -> StageResult:
        mark = ctx.action_mark()
        samples = ctx.active_samples()
        locus = ctx.config.locus
        quant: Dict[str, dict] = ctx.shared.get("quant_post_ampseq", {})

        final_bp = locus.amplicon_bp + int(INDEXING_OVERHANG_BP.value)
        dimer_ceiling_bp = int(INDEXING_OVERHANG_BP.value) + 20  # adapter-dimer scale

        tapestation_rows: List[dict] = []
        pooling_rows: List[dict] = []
        samplesheet_rows: List[dict] = []
        for s in samples:
            q = quant.get(s.id, {})
            conc = q.get("concentration_ng_per_ul")
            pool_ul = (round(float(POOL_TARGET_MASS_NG.value) / conc, 2)
                       if conc and conc > 0 else None)
            tapestation_rows.append({
                "sample_id": s.id,
                "well": s.well,
                "expected_size_bp": final_bp,
                "concentration_ng_per_ul": conc,
                "pass_window_bp": f"{final_bp - 40} to {final_bp + 60}",
                "flag_dimer_below_bp": dimer_ceiling_bp,
            })
            pooling_rows.append({
                "sample_id": s.id,
                "well": s.well,
                "concentration_ng_per_ul": conc,
                "volume_to_pool_ul": pool_ul,
                "target_mass_ng": float(POOL_TARGET_MASS_NG.value),
            })
            samplesheet_rows.append({
                "Sample_ID": s.id,
                "Sample_Well": s.well,
                "Sample_Type": s.sample_type.value,
                "Locus": locus.name,
                "Amplicon_bp": locus.amplicon_bp,
                "Expected_Library_bp": final_bp,
                "I7_Index_ID": "TODO_assign_index",
                "I5_Index_ID": "TODO_assign_index",
                "Analysis_Intent": _ANALYSIS_INTENT.get(ctx.config.edit_type,
                                                        _ANALYSIS_INTENT[EditType.UNKNOWN]),
            })

        samplesheet_csv = _rows_to_csv(samplesheet_rows)

        return StageResult(
            name=self.name,
            title=self.title,
            status=StageStatus.COMPLETED,
            message=(f"{len(samples)} librar(ies) ready; expected final size {final_bp} bp; "
                     f"pool by equal mass ({POOL_TARGET_MASS_NG.value} ng each)"),
            data={
                "n_libraries": len(samples),
                "expected_final_bp": final_bp,
                "edit_type": ctx.config.edit_type.value,
                "analysis_intent": _ANALYSIS_INTENT.get(ctx.config.edit_type,
                                                        _ANALYSIS_INTENT[EditType.UNKNOWN]),
                "tapestation": tapestation_rows,
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

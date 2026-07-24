"""
stages/qc_fluorescent_dsdna.py - the yield gates, at two checkpoints, from one stage.

The same fluorescent dsDNA assay quant runs after WGS preparation and after PCR enrichment; only the acceptance
criterion differs. So this is one stage parameterized by checkpoint:

  POST_WGS_PREP     per-well dsDNA yield must clear a floor, and the passing wells must be
               reasonably uniform (a run-level CV). A well that did not amplify does not
               go into a library. -> PROCEED_SUBSET on the wells that passed.
  Post-PCR enrichment: per-well library concentration must sit inside the loading window for
               even pooling and fragment analyzer. -> PROCEED_SUBSET on the wells in window.

The assay itself: an operator-selected reference dsDNA standard curve is read on the same plate, its linearity
is gated (a curve that did not come out straight fails the whole checkpoint), and each
sample is read off it. High-yield product is diluted into the curve's range before
reading, the way the real assay is run; the dilution factor is applied back to report
the neat concentration.

Measured concentrations are stashed on the context so the sequencing handoff can pool by
concentration later. That is the "returning data feeds forward" loop, in miniature.
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, List

from ..gates import Outcome, SampleVerdict, check, evaluate_per_sample
from ..qc_math import cv_percent
from ..reagents.fluorescent_dsdna import build_standard_curve, quantitate_well
from ..simulation import (
    FLUORESCENT_DSDNA_MODEL,
    det_rng,
    simulate_sample_concentration_ng_per_ml,
)
from .base import Stage, StageContext, StageResult, StageStatus


class Checkpoint(str, Enum):
    POST_WGS_PREP = "post_wgs_prep"
    POST_PCR_ENRICHMENT = "post_pcr_enrichment"


class FluorescentDsDNAQC(Stage):
    def __init__(self, checkpoint: Checkpoint):
        self.checkpoint = checkpoint
        if checkpoint is Checkpoint.POST_WGS_PREP:
            self.name = "qc_post_wgs_prep"
            self.title = "Gate 1 - post-WGS preparation dsDNA yield (fluorescent dsDNA assay)"
        else:
            self.name = "qc_post_pcr_enrichment"
            self.title = "Gate 2 - post-PCR enrichment library concentration (fluorescent dsDNA assay)"

    # -- assay ---------------------------------------------------------------

    def _read_standard_curve(self, ctx: StageContext):
        method = ctx.config.method
        concs: List[float] = list(
            method.fluorescent_dsdna_standards_ng_per_ml
        )
        rng = det_rng(ctx.config.run_id, self.checkpoint.value, "standards")
        truth: Dict[str, float] = {}
        keys = []
        for i, c in enumerate(concs):
            key = f"std_{i:02d}"
            keys.append(key)
            truth[key] = FLUORESCENT_DSDNA_MODEL.signal(c, rng)
        read = ctx.tecan.read(ctx.config.run_id, f"fluorescent_dsdna_standards_{self.checkpoint.value}",
                              truth,
                              method.fluorescent_dsdna_excitation_nm,
                              method.fluorescent_dsdna_emission_nm)
        signals = [read[k] for k in keys]
        return build_standard_curve(concs, signals)

    def _simulation_centers_ng_per_ml(self, ctx: StageContext):
        """Return bounded passing/failing ranges derived from this run's active gate."""
        acceptance = ctx.config.acceptance
        method = ctx.config.method
        if self.checkpoint is Checkpoint.POST_WGS_PREP:
            gate_boundary = (
                acceptance.wgs_prep_yield_min_ng
                / method.wgs_product_volume_ul
                * 1000.0
            )
            passing = gate_boundary * 2.0
            failing = gate_boundary / 2.0
            return (
                passing,
                failing,
                (passing - gate_boundary) / 2.0,
                (gate_boundary - failing) / 2.0,
            )

        lower = acceptance.pcr_enrichment_conc_min_ng_per_ul
        upper = acceptance.pcr_enrichment_conc_max_ng_per_ul
        passing = ((lower + upper) / 2.0) * 1000.0
        passing_half_width = ((upper - lower) / 4.0) * 1000.0
        if lower > 0:
            failing = (lower / 2.0) * 1000.0
            failing_half_width = ((lower - (lower / 2.0)) / 2.0) * 1000.0
        else:
            span = upper - lower
            failing = (upper + span) * 1000.0
            failing_half_width = (span / 2.0) * 1000.0
        return passing, failing, passing_half_width, failing_half_width

    def _sample_truth_signal(
        self,
        ctx: StageContext,
        sample,
        curve,
        passing_center_ng_per_ml: float,
        failing_center_ng_per_ml: float,
        passing_half_width_ng_per_ml: float,
        failing_half_width_ng_per_ml: float,
    ) -> float:
        if self.checkpoint is Checkpoint.POST_WGS_PREP:
            dilution = ctx.config.method.wgs_qc_dilution
        else:
            dilution = ctx.config.method.pcr_qc_dilution
        neat = simulate_sample_concentration_ng_per_ml(
            ctx.config.run_id,
            self.checkpoint.value,
            sample,
            passing_center_ng_per_ml,
            failing_center_ng_per_ml,
            passing_half_width_ng_per_ml,
            failing_half_width_ng_per_ml,
        )
        diluted = neat / dilution
        return max(0.0, curve.fit.predict(diluted))

    # -- run -----------------------------------------------------------------

    def run(self, ctx: StageContext) -> StageResult:
        mark = ctx.action_mark()

        curve = self._read_standard_curve(ctx)
        curve_crit = ctx.config.acceptance.curve_criterion(self.checkpoint.value)
        curve_outcome = check(curve_crit, curve.fit.r_squared)

        samples = ctx.active_samples()
        dilution = (
            ctx.config.method.wgs_qc_dilution
            if self.checkpoint is Checkpoint.POST_WGS_PREP
            else ctx.config.method.pcr_qc_dilution
        )
        assay_volume = (
            ctx.config.method.wgs_product_volume_ul
            if self.checkpoint is Checkpoint.POST_WGS_PREP
            else ctx.config.method.pcr_library_volume_ul
        )
        (
            passing_center,
            failing_center,
            passing_half_width,
            failing_half_width,
        ) = self._simulation_centers_ng_per_ml(ctx)

        # One read of all sample wells.
        truth = {
            s.well: self._sample_truth_signal(
                ctx,
                s,
                curve,
                passing_center,
                failing_center,
                passing_half_width,
                failing_half_width,
            )
            for s in samples
        }
        read = ctx.tecan.read(ctx.config.run_id, f"fluorescent_dsdna_samples_{self.checkpoint.value}",
                              truth,
                              ctx.config.method.fluorescent_dsdna_excitation_nm,
                              ctx.config.method.fluorescent_dsdna_emission_nm)

        verdicts: List[SampleVerdict] = []
        rows = []
        quant_store: Dict[str, dict] = {}
        for s in samples:
            wq = quantitate_well(curve, s.id, s.well, read[s.well], assay_volume,
                                 dilution_factor=dilution, blank=curve.signals[0])
            conc_ng_per_ul = wq.concentration_ng_per_ml / 1000.0

            if self.checkpoint is Checkpoint.POST_WGS_PREP:
                crit = ctx.config.acceptance.wgs_prep_yield_criterion()
                outcome = check(crit, wq.mass_ng)
            else:
                crit = ctx.config.acceptance.pcr_enrichment_conc_criterion()
                outcome = check(crit, conc_ng_per_ul)

            note = "" if wq.in_curve_range else "signal outside standard curve; re-read at a new dilution"
            verdicts.append(SampleVerdict(sample_id=s.id, passed=outcome.passed,
                                          outcomes=[outcome], note=note))
            row = {
                "sample_id": s.id,
                "well": s.well,
                "sample_type": s.sample_type.value,
                "concentration_ng_per_ul": round(conc_ng_per_ul, 3),
                "mass_ng": round(wq.mass_ng, 2),
                "in_curve_range": wq.in_curve_range,
                "passed": outcome.passed,
            }
            rows.append(row)
            quant_store[s.id] = row

        # POST_WGS_PREP only: uniformity across the passing wells is a run-level criterion.
        run_outcomes: List[Outcome] = [curve_outcome]
        uniformity_cv = None
        if self.checkpoint is Checkpoint.POST_WGS_PREP:
            passing_concs = [r["concentration_ng_per_ul"] for r in rows if r["passed"]]
            if len(passing_concs) >= 2:
                from ..gates import Comparison, Criterion
                uniformity_cv = cv_percent(passing_concs)
                uni_crit = Criterion(
                    key="wgs_prep_uniformity",
                    label="post-WGS preparation yield uniformity CV across passing wells",
                    comparison=Comparison.MAX,
                    bound=ctx.config.acceptance.wgs_prep_uniformity_cv_max_percent,
                    unit="%",
                    source="systematic amplification spread; above this the run is suspect",
                )
                run_outcomes.append(check(uni_crit, uniformity_cv))

        gate = evaluate_per_sample(self.title, verdicts, run_outcomes=run_outcomes)

        # Feed measured concentrations forward.
        ctx.shared[f"quant_{self.checkpoint.value}"] = quant_store

        status = StageStatus.COMPLETED if gate.passed else StageStatus.STOPPED
        return StageResult(
            name=self.name,
            title=self.title,
            status=status,
            message=gate.message,
            gate=gate,
            data={
                "checkpoint": self.checkpoint.value,
                "curve_r2": round(curve.fit.r_squared, 5),
                "curve_slope": round(curve.fit.slope, 4),
                "dilution_factor": dilution,
                "uniformity_cv_percent": (round(uniformity_cv, 2)
                                          if uniformity_cv is not None else None),
                "samples": rows,
            },
            actions=ctx.actions_since(mark),
        )

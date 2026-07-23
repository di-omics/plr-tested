"""
stages/qc_picogreen.py - the yield gates, at two checkpoints, from one stage.

The same PicoGreen quant runs after PTA and after targeted PCR; only the acceptance
criterion differs. So this is one stage parameterized by checkpoint:

  POST_PTA     per-well dsDNA yield must clear a floor, and the passing wells must be
               reasonably uniform (a run-level CV). A well that did not amplify does not
               go into a library. -> PROCEED_SUBSET on the wells that passed.
  POST_TARGETED_PCR  per-well library concentration must sit inside the loading window for
               even pooling and TapeStation. -> PROCEED_SUBSET on the wells in window.

The assay itself: a Lambda dsDNA standard curve is read on the same plate, its linearity
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
from ..provenance import Sourced, transcribed, tunable
from ..qc_math import cv_percent
from ..reagents.picogreen import (
    EM_NM,
    EX_NM,
    HIGH_RANGE_STANDARDS_NG_PER_ML,
    build_standard_curve,
    quantitate_well,
)
from ..simulation import (
    PICOGREEN_MODEL,
    det_rng,
    simulate_targeted_pcr_library_conc_ng_per_ml,
    simulate_pta_yield_conc_ng_per_ml,
)
from .base import Stage, StageContext, StageResult, StageStatus


class Checkpoint(str, Enum):
    POST_PTA = "post_pta"
    POST_TARGETED_PCR = "post_targeted_pcr"


# Assay dilutions: high-yield product read in the curve's range. Operator-set, verify.
PTA_ASSAY_DILUTION = tunable(
    50.0, "dilute PTA product ~50x into the PicoGreen high-range curve; verify per yield",
    unit="x", name="pta_assay_dilution",
)
TARGETED_PCR_ASSAY_DILUTION = tunable(
    40.0, "dilute the library ~40x into the PicoGreen high-range curve; verify",
    unit="x", name="targeted_pcr_assay_dilution",
)
# Volume the post-whole-genome amplification yield mass is computed over: the WGA reaction volume.
PTA_PRODUCT_VOLUME_UL = transcribed(
    12.0, "odtc_protocols.py VOL_UL_WGA (authorized WGS/WGA workflow source): 12 uL WGA reaction",
    unit="uL", name="pta_product_volume",
)
TARGETED_PCR_LIBRARY_VOLUME_UL = tunable(
    25.0, "nominal cleaned-library elution volume for mass reporting; verify",
    unit="uL", name="targeted_pcr_library_volume",
)


class PicoGreenQC(Stage):
    def __init__(self, checkpoint: Checkpoint):
        self.checkpoint = checkpoint
        if checkpoint is Checkpoint.POST_PTA:
            self.name = "qc_post_pta"
            self.title = "Gate 1 - post-PTA dsDNA yield (PicoGreen)"
        else:
            self.name = "qc_post_targeted_pcr"
            self.title = "Gate 2 - post-targeted-PCR library concentration (PicoGreen)"

    # -- assay ---------------------------------------------------------------

    def _read_standard_curve(self, ctx: StageContext):
        concs: List[float] = list(HIGH_RANGE_STANDARDS_NG_PER_ML.value)
        rng = det_rng(ctx.config.run_id, self.checkpoint.value, "standards")
        truth: Dict[str, float] = {}
        keys = []
        for i, c in enumerate(concs):
            key = f"std_{i:02d}"
            keys.append(key)
            truth[key] = PICOGREEN_MODEL.signal(c, rng)
        read = ctx.tecan.read(ctx.config.run_id, f"picogreen_standards_{self.checkpoint.value}",
                              truth, float(EX_NM.value), float(EM_NM.value))
        signals = [read[k] for k in keys]
        return build_standard_curve(concs, signals)

    def _sample_truth_signal(self, ctx: StageContext, well: str, sample) -> float:
        if self.checkpoint is Checkpoint.POST_PTA:
            neat = simulate_pta_yield_conc_ng_per_ml(ctx.config.run_id, sample)
            dilution = float(PTA_ASSAY_DILUTION.value)
        else:
            neat = simulate_targeted_pcr_library_conc_ng_per_ml(ctx.config.run_id, sample)
            dilution = float(TARGETED_PCR_ASSAY_DILUTION.value)
        diluted = neat / dilution
        rng = det_rng(ctx.config.run_id, self.checkpoint.value, "sample", well)
        return PICOGREEN_MODEL.signal(diluted, rng)

    # -- run -----------------------------------------------------------------

    def run(self, ctx: StageContext) -> StageResult:
        mark = ctx.action_mark()
        ctx.guard.add(PTA_ASSAY_DILUTION, TARGETED_PCR_ASSAY_DILUTION)

        curve = self._read_standard_curve(ctx)
        curve_crit = ctx.config.acceptance.curve_criterion(self.checkpoint.value)
        curve_outcome = check(curve_crit, curve.fit.r_squared)

        samples = ctx.active_samples()
        dilution = (float(PTA_ASSAY_DILUTION.value) if self.checkpoint is Checkpoint.POST_PTA
                    else float(TARGETED_PCR_ASSAY_DILUTION.value))
        assay_volume = (float(PTA_PRODUCT_VOLUME_UL.value) if self.checkpoint is Checkpoint.POST_PTA
                        else float(TARGETED_PCR_LIBRARY_VOLUME_UL.value))

        # One read of all sample wells.
        truth = {s.well: self._sample_truth_signal(ctx, s.well, s) for s in samples}
        read = ctx.tecan.read(ctx.config.run_id, f"picogreen_samples_{self.checkpoint.value}",
                              truth, float(EX_NM.value), float(EM_NM.value))

        verdicts: List[SampleVerdict] = []
        rows = []
        quant_store: Dict[str, dict] = {}
        for s in samples:
            wq = quantitate_well(curve, s.id, s.well, read[s.well], assay_volume,
                                 dilution_factor=dilution, blank=curve.signals[0])
            conc_ng_per_ul = wq.concentration_ng_per_ml / 1000.0

            if self.checkpoint is Checkpoint.POST_PTA:
                crit = ctx.config.acceptance.pta_yield_criterion()
                outcome = check(crit, wq.mass_ng)
            else:
                crit = ctx.config.acceptance.targeted_pcr_conc_criterion()
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

        # POST_PTA only: uniformity across the passing wells is a run-level criterion.
        run_outcomes: List[Outcome] = [curve_outcome]
        uniformity_cv = None
        if self.checkpoint is Checkpoint.POST_PTA:
            passing_concs = [r["concentration_ng_per_ul"] for r in rows if r["passed"]]
            if len(passing_concs) >= 2:
                from ..gates import Comparison, Criterion
                uniformity_cv = cv_percent(passing_concs)
                uni_crit = Criterion(
                    key="pta_uniformity",
                    label="post-PTA yield uniformity CV across passing wells",
                    comparison=Comparison.MAX,
                    bound=ctx.config.acceptance.pta_uniformity_cv_max_percent,
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

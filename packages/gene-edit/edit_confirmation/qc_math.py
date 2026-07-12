"""
qc_math.py - the statistics the QC gates are made of.

Pure standard library on purpose. This is the part of the package that has to be
correct in any lab with any Python, with nothing to install, so it does not import
numpy. Every function here is small enough to check by eye and is covered by
tests/test_qc_math.py.

What lives here:
  - descriptive stats with the sample (n-1) standard deviation, so a CV computed
    here matches a CV computed in Excel or R.
  - a plain ordinary-least-squares line fit with R-squared, for the PicoGreen and
    Rhodamine standard curves.
  - back-calculation of concentration from a standard curve.
  - the Rhodamine working-range helper: given a reader's usable signal window and a
    measured dye response, what dye concentration lands the volumes of interest inside
    that window.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# Descriptive statistics
# ---------------------------------------------------------------------------

def mean(xs: Sequence[float]) -> float:
    xs = list(xs)
    if not xs:
        raise ValueError("mean() of an empty sequence")
    return sum(xs) / len(xs)


def stdev_sample(xs: Sequence[float]) -> float:
    """Sample standard deviation (n-1 in the denominator).

    n-1, not n: a QC CV reported to an operator or an auditor is expected to match a
    spreadsheet's STDEV, which is the sample estimator. A single value has no defined
    spread, so this returns 0.0 for n < 2 rather than raising, because a one-replicate
    well should read as "no spread measured", not crash a run.
    """
    xs = list(xs)
    n = len(xs)
    if n < 2:
        return 0.0
    m = mean(xs)
    ss = sum((x - m) ** 2 for x in xs)
    return math.sqrt(ss / (n - 1))


def cv_percent(xs: Sequence[float]) -> float:
    """Coefficient of variation, as a percent: 100 * stdev / mean.

    This is the number the liquid-handling gate turns on. Defined only for a positive
    mean; a mean at or below zero (all-blank wells, say) has no meaningful CV and
    raises, because silently returning 0 or inf would let a dead read pass a gate.
    """
    xs = list(xs)
    m = mean(xs)
    if m <= 0:
        raise ValueError(
            f"CV is undefined for a non-positive mean ({m:.4g}); "
            "the wells read blank or negative, which is a failure, not a 0% CV."
        )
    return 100.0 * stdev_sample(xs) / m


def recovery_percent(measured_mean: float, expected: float) -> float:
    """Accuracy as percent of target: 100 * measured / expected."""
    if expected == 0:
        raise ValueError("recovery is undefined against an expected value of 0")
    return 100.0 * measured_mean / expected


# ---------------------------------------------------------------------------
# Linear fit (ordinary least squares) and back-calculation
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LineFit:
    slope: float
    intercept: float
    r_squared: float
    n: int

    def predict(self, x: float) -> float:
        return self.slope * x + self.intercept

    def inverse(self, y: float) -> float:
        """Solve y = slope*x + intercept for x. Used to read concentration off signal."""
        if self.slope == 0:
            raise ValueError("cannot invert a flat line (slope 0)")
        return (y - self.intercept) / self.slope


def linear_fit(xs: Sequence[float], ys: Sequence[float]) -> LineFit:
    """Ordinary least squares y = slope*x + intercept, plus R-squared.

    Used for the standard curves: x = known concentration of a standard, y = its
    fluorescence. R-squared is reported so a gate can reject a curve that did not come
    out straight (a common sign the assay was mispipetted) before any sample is read
    off it.
    """
    xs = list(xs)
    ys = list(ys)
    if len(xs) != len(ys):
        raise ValueError("linear_fit needs xs and ys of equal length")
    n = len(xs)
    if n < 2:
        raise ValueError("linear_fit needs at least 2 points")

    mx = mean(xs)
    my = mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    if sxx == 0:
        raise ValueError("all x values are identical; cannot fit a line")

    slope = sxy / sxx
    intercept = my - slope * mx

    syy = sum((y - my) ** 2 for y in ys)
    if syy == 0:
        r2 = 1.0 if sxy == 0 else 0.0
    else:
        r2 = (sxy ** 2) / (sxx * syy)
    return LineFit(slope=slope, intercept=intercept, r_squared=r2, n=n)


# ---------------------------------------------------------------------------
# PicoGreen quantitation
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class QuantResult:
    concentration: float   # in the standard curve's concentration unit, e.g. ng/mL
    signal: float          # the raw reading it was computed from
    in_curve_range: bool   # was the signal within the standards used to build the curve
    unit: str = "ng/mL"


def quantitate(fit: LineFit, sample_signal: float, blank: float = 0.0,
               curve_signal_min: Optional[float] = None,
               curve_signal_max: Optional[float] = None,
               unit: str = "ng/mL") -> QuantResult:
    """Read a concentration off a standard curve.

    blank is subtracted from the sample signal before back-calculation, matching how a
    PicoGreen curve is built (standards are blank-subtracted too). in_curve_range flags
    a sample brighter than the top standard or dimmer than the bottom one, which the
    gate treats as "re-read at a different dilution", not a trustworthy number.
    """
    net = sample_signal - blank
    conc = fit.inverse(net)
    in_range = True
    if curve_signal_min is not None and net < curve_signal_min:
        in_range = False
    if curve_signal_max is not None and net > curve_signal_max:
        in_range = False
    return QuantResult(concentration=conc, signal=sample_signal, in_curve_range=in_range, unit=unit)


def mass_ng(concentration_ng_per_ml: float, volume_ul: float) -> float:
    """Total dsDNA mass in a well: ng/mL * mL. volume in uL -> mL is /1000."""
    return concentration_ng_per_ml * (volume_ul / 1000.0)


# ---------------------------------------------------------------------------
# Rhodamine B working-range helper
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DyeRangePlan:
    working_concentration: float   # dye concentration to prepare, in stock's unit
    dilution_factor: float         # stock -> working
    predicted_top_signal: float    # predicted reading of the brightest test well
    predicted_bottom_signal: float # predicted reading of the dimmest test well
    within_reader_window: bool
    unit: str = "uM"


def rhodamine_working_concentration(
    reference_concentration: float,
    reference_signal_at_reference: float,
    smallest_test_volume_ul: float,
    largest_test_volume_ul: float,
    common_read_volume_ul: float,
    reader_signal_floor: float,
    reader_signal_ceiling: float,
    target_top_fraction: float = 0.75,
) -> DyeRangePlan:
    """Pick a Rhodamine B working concentration for a constant-fill CV read.

    The liquid-handling CV method here is constant-concentration / variable-volume:
    the robot dispenses the test volume of a fixed-concentration dye, the well is
    topped up to a common read volume with buffer, and fluorescence is proportional to
    the mass of dye delivered, hence to the dispensed volume. So the brightest well is
    the largest test volume and the dimmest is the smallest.

    Given a single calibration read (a known dye concentration produced a known signal
    at the common read volume when it filled the well), this scales linearly to the
    concentration whose largest-volume well lands at target_top_fraction of the reader
    ceiling, then predicts where the smallest-volume well falls. If that dimmest well
    would sit under the reader floor, within_reader_window is False and the caller must
    either split the range across two dye concentrations or use a more sensitive read.

    Everything here is a prediction from one calibration point, to be confirmed by the
    actual dilution-series read on the instrument. It is arithmetic, not a measurement.
    """
    if reference_signal_at_reference <= 0:
        raise ValueError("the calibration read must be a positive signal")
    if not (0 < target_top_fraction <= 1):
        raise ValueError("target_top_fraction must be in (0, 1]")
    if smallest_test_volume_ul <= 0 or largest_test_volume_ul <= 0:
        raise ValueError("test volumes must be positive")
    if largest_test_volume_ul > common_read_volume_ul:
        raise ValueError(
            "the largest test volume exceeds the common read volume; "
            "there is nothing to top up with"
        )

    # Signal per (uM of dye * fraction-of-read-volume-that-is-dye), from the calibration
    # point where the dye filled the whole read volume (fraction = 1).
    signal_per_uM_full = reference_signal_at_reference / reference_concentration

    # Largest test well: fraction of read volume that is dye.
    top_fill_fraction = largest_test_volume_ul / common_read_volume_ul
    bottom_fill_fraction = smallest_test_volume_ul / common_read_volume_ul

    target_top_signal = target_top_fraction * reader_signal_ceiling
    # target_top_signal = signal_per_uM_full * working_conc * top_fill_fraction
    working_conc = target_top_signal / (signal_per_uM_full * top_fill_fraction)

    predicted_top = signal_per_uM_full * working_conc * top_fill_fraction
    predicted_bottom = signal_per_uM_full * working_conc * bottom_fill_fraction
    within = predicted_bottom >= reader_signal_floor and predicted_top <= reader_signal_ceiling

    dilution = reference_concentration / working_conc if working_conc > 0 else float("inf")
    return DyeRangePlan(
        working_concentration=working_conc,
        dilution_factor=dilution,
        predicted_top_signal=predicted_top,
        predicted_bottom_signal=predicted_bottom,
        within_reader_window=within,
    )

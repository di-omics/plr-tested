"""
qc_math.py - the statistics the QC gates are made of.

Pure standard library on purpose. This is the part of the package that has to be correct
in any lab with any Python, with nothing to install, so it does not import numpy. Every
function here is small enough to check by eye and is covered by tests/test_qc_math.py.

Two halves:
  - shared descriptive stats and a plain OLS line fit, the same ones any assay's precision
    and linearity checks are built from (the Gate 0 Rhodamine read uses them).
  - the ELISpot readout math: net spots over background, stimulation index, the response
    call rule that decides whether an antigen well is a real positive, saturation, and
    normalization to a common cell count.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Sequence


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
    spread, so this returns 0.0 for n < 2 rather than raising.
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

    Defined only for a positive mean; a mean at or below zero has no meaningful CV and
    raises, because silently returning 0 or inf would let a dead read pass a gate. For an
    ELISpot replicate group whose spots are genuinely near zero (a clean negative control),
    callers use cv_percent_or_none so a low-count group is not forced through this.
    """
    xs = list(xs)
    m = mean(xs)
    if m <= 0:
        raise ValueError(
            f"CV is undefined for a non-positive mean ({m:.4g}); "
            "the wells read blank, which is a state to report, not a 0% CV."
        )
    return 100.0 * stdev_sample(xs) / m


def cv_percent_or_none(xs: Sequence[float], floor_mean: float = 1.0) -> Optional[float]:
    """CV, or None when the group's mean is too low for a CV to mean anything.

    A negative-control group averaging under `floor_mean` spots has no useful CV: a jump
    from 1 to 3 spots is a 100% CV that says nothing about pipetting. Returning None lets
    the readout gate skip the replicate-CV check for genuinely near-zero groups instead of
    failing them on noise. Test and positive-control groups sit well above the floor and
    get a real number.
    """
    xs = list(xs)
    if not xs:
        return None
    if mean(xs) < floor_mean:
        return None
    return cv_percent(xs)


# ---------------------------------------------------------------------------
# Linear fit (ordinary least squares)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LineFit:
    slope: float
    intercept: float
    r_squared: float
    n: int

    def predict(self, x: float) -> float:
        return self.slope * x + self.intercept


def linear_fit(xs: Sequence[float], ys: Sequence[float]) -> LineFit:
    """Ordinary least squares y = slope*x + intercept, plus R-squared.

    Used for the Gate 0 signal-vs-volume line (a precise-but-nonlinear deck passes CV and
    fails this) and available for a cell-titration linearity read if a site wants one.
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
# ELISpot readout
# ---------------------------------------------------------------------------

def net_spots(test_mean: float, background_mean: float) -> float:
    """Spots attributable to the antigen: test mean minus the negative-control mean.

    Clamped at zero. A test group below its background has a net of zero, not a negative
    number; a negative "response" is noise, and reporting it as such would be misleading.
    """
    return max(0.0, test_mean - background_mean)


def stimulation_index(test_mean: float, background_mean: float) -> float:
    """Fold response over background: test mean / negative-control mean.

    Undefined against a zero background; a background floored at a small positive number is
    the caller's job (an all-zero negative control is itself a plate-validity signal, not a
    denominator). Returns infinity for a positive test over a zero background so the caller
    can render it as ">= ceiling" rather than crash.
    """
    if background_mean <= 0:
        return float("inf") if test_mean > 0 else 0.0
    return test_mean / background_mean


@dataclass(frozen=True)
class ResponseCall:
    """Whether an antigen group is a real positive, and the numbers behind the call."""

    antigen: str
    test_mean: float
    background_mean: float
    net: float
    stimulation_index: float
    positive: bool
    saturated: bool
    reason: str

    def to_dict(self) -> dict:
        si = self.stimulation_index
        return {
            "antigen": self.antigen,
            "test_mean_sfu": round(self.test_mean, 1),
            "background_mean_sfu": round(self.background_mean, 1),
            "net_sfu": round(self.net, 1),
            "stimulation_index": ("inf" if si == float("inf") else round(si, 2)),
            "positive": self.positive,
            "saturated": self.saturated,
            "reason": self.reason,
        }


def call_response(antigen: str, test_counts: Sequence[float], background_counts: Sequence[float],
                  min_net_sfu: float, min_stimulation_index: float,
                  saturation_sfu: float) -> ResponseCall:
    """The "is this real" rule: an antigen is positive if it clears both a floor and a fold.

    Two conditions, both required (the conservative empirical rule): the mean net spots are
    at least `min_net_sfu`, AND the stimulation index is at least `min_stimulation_index`
    (the 2x rule). Requiring both keeps two failure modes out: a large fold over a tiny
    background (2 vs 1 spot is SI 2 but not a response), and a large absolute count that is
    only a small fold over an already-high background (a dirty well, not an antigen
    response). A group whose mean is at or above the saturation ceiling is flagged TNTC and
    not treated as a trustworthy quantitative positive.

    The distribution-free resampling method (Moodie et al., Cancer Immunol Immunother 2010)
    is the field's gold standard for low-frequency responses and uses the individual
    replicate counts, not just their mean; it is the intended upgrade path here and the
    replicate counts this function receives are what it would consume.
    """
    tmean = mean(test_counts) if test_counts else 0.0
    bmean = mean(background_counts) if background_counts else 0.0
    net = net_spots(tmean, bmean)
    si = stimulation_index(tmean, bmean)
    saturated = tmean >= saturation_sfu

    meets_net = net >= min_net_sfu
    meets_si = si >= min_stimulation_index
    positive = meets_net and meets_si and not saturated

    if saturated:
        reason = f"mean {tmean:.0f} SFU at/above saturation {saturation_sfu:.0f}; TNTC, not quantitative"
    elif positive:
        reason = f"net {net:.0f} SFU >= {min_net_sfu:.0f} and SI {si:.2f} >= {min_stimulation_index:.1f}"
    elif not meets_net and not meets_si:
        reason = f"net {net:.0f} SFU below {min_net_sfu:.0f} and SI {si:.2f} below {min_stimulation_index:.1f}"
    elif not meets_net:
        reason = f"net {net:.0f} SFU below floor {min_net_sfu:.0f}"
    else:
        reason = f"SI {si:.2f} below {min_stimulation_index:.1f} (net over a high background)"

    return ResponseCall(
        antigen=antigen, test_mean=tmean, background_mean=bmean, net=net,
        stimulation_index=si, positive=positive, saturated=saturated, reason=reason,
    )


def normalize_per_cells(sfu: float, cells_per_well: int, report_per_cells: int) -> float:
    """Spots scaled to a common input-cell count, e.g. SFU per 1e6 PBMC.

    Lets two wells plated at different densities, or two sites with different cell preps, be
    compared on one axis. Requires a positive cell count.
    """
    if cells_per_well <= 0:
        raise ValueError("cells_per_well must be positive to normalize")
    return sfu * (report_per_cells / cells_per_well)

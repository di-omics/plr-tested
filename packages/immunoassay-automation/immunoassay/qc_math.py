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

import itertools
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
    method: str = "empirical"          # "empirical" | "dfr2x" | "dfr"
    p_value: Optional[float] = None    # permutation p (DFR methods only)

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
            "method": self.method,
            "p_value": (None if self.p_value is None else round(self.p_value, 4)),
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


def permutation_greater_p(test_counts: Sequence[float],
                          background_counts: Sequence[float]) -> float:
    """One-sided distribution-free (permutation) p-value that test > background.

    The statistic is the difference in group means. The pooled well counts are re-split
    every possible way into a test-sized group and a background-sized group; the p-value is
    the fraction of those splits whose mean-difference is at least the observed one. This is
    an exact permutation test (no random sampling): with the small replicate counts an
    ELISpot actually has - triplicate is typical - the number of splits is tiny and can be
    enumerated in full, which also makes the result deterministic.

    A consequence worth stating plainly: with m test and n background wells the smallest
    p-value reachable is 1 / C(m+n, m). Triplicate against triplicate floors at 1/20 = 0.05,
    so a strong responder lands exactly at 0.05 and a marginal one cannot clear a stricter
    alpha - which is a real property of the design, not of this code, and the reason more
    replicate wells buy statistical power. Returns 1.0 if either group is empty.
    """
    test = list(test_counts)
    bg = list(background_counts)
    m, n = len(test), len(bg)
    if m == 0 or n == 0:
        return 1.0
    pooled = test + bg
    observed = mean(test) - mean(bg)

    total = 0
    at_least = 0
    for combo in itertools.combinations(range(m + n), m):
        chosen = [pooled[i] for i in combo]
        rest = [pooled[i] for i in range(m + n) if i not in set(combo)]
        stat = mean(chosen) - mean(rest)
        total += 1
        if stat >= observed - 1e-9:   # tolerance so the observed split counts itself
            at_least += 1
    return at_least / total


def call_response_dfr(antigen: str, test_counts: Sequence[float],
                      background_counts: Sequence[float], alpha: float,
                      saturation_sfu: float, require_fold_2x: bool = True,
                      min_stimulation_index: float = 2.0) -> ResponseCall:
    """Distribution-free resampling response call, in the spirit of Moodie et al. 2010.

    An antigen is positive if a one-sided permutation test shows its wells are significantly
    greater than the negative-control wells (p <= alpha) AND, for the DFR(2x) variant, its
    stimulation index is at least the fold cutoff. DFR(2x) - significance plus a two-fold
    floor - is the method's recommended default; passing require_fold_2x=False gives the
    plain DFR variant (significance alone). A group at or above saturation is flagged TNTC.

    This is a faithful distribution-free permutation test with the 2x rule layered on, which
    is the shape of the published method; the exact alpha and any multiplicity adjustment
    for the number of antigens on the plate are the operator's to confirm against the
    reference for their replicate design (see permutation_greater_p on the triplicate floor).
    It is deliberately not claimed to be bit-identical to the paper's implementation.
    """
    tmean = mean(test_counts) if test_counts else 0.0
    bmean = mean(background_counts) if background_counts else 0.0
    net = net_spots(tmean, bmean)
    si = stimulation_index(tmean, bmean)
    saturated = tmean >= saturation_sfu
    p = permutation_greater_p(test_counts, background_counts)

    significant = p <= alpha
    meets_fold = (si >= min_stimulation_index) if require_fold_2x else True
    positive = significant and meets_fold and not saturated
    method = "dfr2x" if require_fold_2x else "dfr"

    if saturated:
        reason = f"mean {tmean:.0f} SFU at/above saturation {saturation_sfu:.0f}; TNTC, not quantitative"
    elif positive:
        reason = f"permutation p {p:.3f} <= {alpha:.3f}" + (
            f" and SI {si:.2f} >= {min_stimulation_index:.1f}" if require_fold_2x else "")
    elif not significant:
        reason = f"permutation p {p:.3f} > {alpha:.3f} (not distinguishable from background)"
    else:
        reason = f"significant (p {p:.3f}) but SI {si:.2f} below {min_stimulation_index:.1f}"

    return ResponseCall(
        antigen=antigen, test_mean=tmean, background_mean=bmean, net=net,
        stimulation_index=si, positive=positive, saturated=saturated, reason=reason,
        method=method, p_value=p,
    )


def normalize_per_cells(sfu: float, cells_per_well: int, report_per_cells: int) -> float:
    """Spots scaled to a common input-cell count, e.g. SFU per 1e6 PBMC.

    Lets two wells plated at different densities, or two sites with different cell preps, be
    compared on one axis. Requires a positive cell count.
    """
    if cells_per_well <= 0:
        raise ValueError("cells_per_well must be positive to normalize")
    return sfu * (report_per_cells / cells_per_well)

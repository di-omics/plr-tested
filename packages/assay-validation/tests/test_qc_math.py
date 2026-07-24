"""Tests for the QC statistics. These are the numbers the gates turn on."""

import math

import pytest

from assay_validation.qc_math import (
    cv_percent,
    linear_fit,
    mass_ng,
    mean,
    quantitate,
    recovery_percent,
    rhodamine_working_concentration,
    stdev_sample,
)


def test_cv_matches_sample_stdev():
    xs = [100.0, 102.0, 98.0, 101.0, 99.0]
    assert mean(xs) == pytest.approx(100.0)
    # sample stdev of this set is sqrt(10/4) = 1.5811...
    assert stdev_sample(xs) == pytest.approx(1.5811388, rel=1e-6)
    assert cv_percent(xs) == pytest.approx(1.5811388, rel=1e-6)


def test_cv_single_value_is_zero_spread():
    assert stdev_sample([42.0]) == 0.0
    assert cv_percent([42.0]) == 0.0


def test_cv_rejects_nonpositive_mean():
    with pytest.raises(ValueError):
        cv_percent([0.0, 0.0, 0.0])


def test_linear_fit_perfect_line():
    xs = [0, 1, 2, 3, 4]
    ys = [1, 3, 5, 7, 9]      # y = 2x + 1
    fit = linear_fit(xs, ys)
    assert fit.slope == pytest.approx(2.0)
    assert fit.intercept == pytest.approx(1.0)
    assert fit.r_squared == pytest.approx(1.0)
    assert fit.inverse(9) == pytest.approx(4.0)


def test_quantitate_back_calculates_and_flags_range():
    xs = [0, 100, 200, 300]
    ys = [50, 550, 1050, 1550]     # blank 50, slope 5
    fit = linear_fit(xs, [y - 50 for y in ys])
    q = quantitate(fit, sample_signal=550, blank=50,
                   curve_signal_min=0, curve_signal_max=1500)
    assert q.concentration == pytest.approx(100.0)
    assert q.in_curve_range is True
    # brighter than the top standard -> out of range
    q2 = quantitate(fit, sample_signal=3000, blank=50, curve_signal_max=1500)
    assert q2.in_curve_range is False


def test_mass_and_recovery():
    assert mass_ng(1000.0, 10.0) == pytest.approx(10.0)   # 1000 ng/mL over 10 uL
    assert recovery_percent(95.0, 100.0) == pytest.approx(95.0)


def test_rhodamine_range_puts_top_well_near_target():
    plan = rhodamine_working_concentration(
        reference_concentration=1.0, reference_signal_at_reference=45000.0,
        smallest_test_volume_ul=2.0, largest_test_volume_ul=200.0,
        common_read_volume_ul=200.0,
        reader_signal_floor=200.0, reader_signal_ceiling=60000.0,
        target_top_fraction=0.75,
    )
    # largest well fills the read volume -> lands at 75% of ceiling
    assert plan.predicted_top_signal == pytest.approx(45000.0, rel=1e-6)
    assert plan.within_reader_window is True

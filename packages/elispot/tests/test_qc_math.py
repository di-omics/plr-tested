"""Tests for the QC math: shared stats and the ELISpot readout scoring."""

import math

import pytest

from elispot.qc_math import (
    call_response,
    cv_percent,
    cv_percent_or_none,
    linear_fit,
    mean,
    net_spots,
    normalize_per_cells,
    stdev_sample,
    stimulation_index,
)


def test_mean_and_sample_stdev_match_spreadsheet():
    xs = [10, 12, 14, 16, 18]
    assert mean(xs) == 14
    # sum of squared deviations is 40; sample variance is 40/(5-1) = 10, so stdev is sqrt(10)
    assert stdev_sample(xs) == pytest.approx(math.sqrt(10))


def test_stdev_of_single_value_is_zero_not_error():
    assert stdev_sample([42]) == 0.0


def test_cv_percent_matches_definition():
    xs = [100, 110, 90]
    assert cv_percent(xs) == pytest.approx(100 * stdev_sample(xs) / mean(xs))


def test_cv_percent_rejects_nonpositive_mean():
    with pytest.raises(ValueError):
        cv_percent([0, 0, 0])


def test_cv_or_none_returns_none_for_near_zero_group():
    # A clean negative control averaging under 1 spot has no meaningful CV.
    assert cv_percent_or_none([0, 1, 0], floor_mean=1.0) is None
    # A real group gets a real number.
    assert cv_percent_or_none([100, 110, 90]) is not None


def test_net_spots_clamped_at_zero():
    assert net_spots(50, 8) == 42
    assert net_spots(5, 8) == 0.0    # below background is not a negative response


def test_stimulation_index_and_zero_background():
    assert stimulation_index(80, 10) == 8.0
    assert stimulation_index(80, 0) == math.inf   # positive over zero background
    assert stimulation_index(0, 0) == 0.0


def test_linear_fit_recovers_a_line():
    fit = linear_fit([1, 2, 3, 4], [2, 4, 6, 8])
    assert fit.slope == pytest.approx(2.0)
    assert fit.intercept == pytest.approx(0.0)
    assert fit.r_squared == pytest.approx(1.0)


def test_response_positive_needs_both_net_and_fold():
    call = call_response("CEF", [150, 148, 146], [8, 7, 9],
                         min_net_sfu=10, min_stimulation_index=2, saturation_sfu=600)
    assert call.positive is True
    assert call.net == pytest.approx(148 - 8)


def test_response_negative_when_below_floor():
    call = call_response("mock", [12, 11, 13], [8, 7, 9],
                         min_net_sfu=10, min_stimulation_index=2, saturation_sfu=600)
    # net = 12 - 8 = 4, below the 10 floor
    assert call.positive is False
    assert "below" in call.reason


def test_response_negative_when_high_background_kills_fold():
    # Large absolute count but only ~1.3x over an already-high background: not a response.
    call = call_response("dirty", [130, 128, 132], [100, 98, 102],
                         min_net_sfu=10, min_stimulation_index=2, saturation_sfu=600)
    assert call.positive is False
    assert call.stimulation_index < 2


def test_response_saturated_is_flagged_not_quantitative():
    call = call_response("PHA-like", [650, 660, 640], [8, 7, 9],
                         min_net_sfu=10, min_stimulation_index=2, saturation_sfu=600)
    assert call.saturated is True
    assert call.positive is False   # a saturated group is not a trustworthy quantitative positive
    assert "TNTC" in call.reason


def test_normalize_per_cells():
    # 100 SFU at 250k cells normalizes to 400 per 1e6.
    assert normalize_per_cells(100, 250_000, 1_000_000) == pytest.approx(400.0)
    with pytest.raises(ValueError):
        normalize_per_cells(100, 0, 1_000_000)

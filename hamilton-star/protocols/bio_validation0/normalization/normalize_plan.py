"""Pure plate-normalization math: per-well concentration -> per-well water add.

No hardware, no I/O, so it is unit-testable on its own and is the part most worth
getting exactly right. This is the DILUTE-IN-PLACE model the operator asked for:
add water from a reservoir into each existing well so every well reaches ONE common
target concentration. No sample is moved, so the FINAL VOLUME differs per well
(a more-concentrated well takes more water and ends up fuller). This is distinct
from the transfer-to-a-fresh-plate model in di-omics/plr-epigenome
(tipseq_plr/protocols/normalization/plan.py), which fixes the final volume and
moves both sample and water.

Mass is conserved when you only add water:
    C_i * V0_i = Ct * (V0_i + water_i)
    water_i = V0_i * (C_i / Ct - 1) = V0_i * (C_i - Ct) / Ct
    final_volume_i = V0_i + water_i = V0_i * C_i / Ct   (grows with C_i)

Written 2026-07-16. NOT yet run on hardware. The STAR executor that consumes this
plan dispenses a DIFFERENT volume into every well, which no validated script on
this instrument has ever done (all validated transfers are one volume x N channels).
Treat the executor as unproven until a supervised dry run says otherwise.

UNIT DISCIPLINE (a real trap): the PicoGreen curve math in
packages/gene-edit/edit_confirmation/ works in ng/mL. This module works entirely
in ng/uL. Convert exactly once, at the boundary, with `ng_per_ml_to_ng_per_ul`.
Mixing the two is a silent 1000x error.

NEVER-INVENT RULE: target concentration, starting well volume, minimum transfer
volume, and well capacity are protocol values. They are carried as Sourced and a
hardware run must refuse to proceed while any is still `todo`/`calibrate`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Sequence


# ---------------------------------------------------------------------------
# Provenance: the never-invent rule, in code (lean form of the gene-edit one)
# ---------------------------------------------------------------------------

SOURCED = "sourced"        # transcribed from a protocol/insert, trustworthy
TUNABLE = "tunable"        # a defensible default, confirm before a run that matters
CALIBRATE = "calibrate"    # must be set from a calibration on THIS instrument
TODO = "todo"             # not yet known; blocks a hardware run

_BLOCKING = {CALIBRATE, TODO}


@dataclass(frozen=True)
class Sourced:
    value: float
    status: str
    note: str
    unit: str = ""

    def __post_init__(self):
        if self.status not in (SOURCED, TUNABLE, CALIBRATE, TODO):
            raise ValueError(f"unknown provenance status: {self.status}")

    @property
    def blocks_hardware(self) -> bool:
        return self.status in _BLOCKING


def sourced(v, note, unit=""):
    return Sourced(float(v), SOURCED, note, unit)


def tunable(v, note, unit=""):
    return Sourced(float(v), TUNABLE, note, unit)


def calibrate(v, note, unit=""):
    return Sourced(float(v), CALIBRATE, note, unit)


def todo(note, unit=""):
    # value is a placeholder that must not be trusted; it is never used on hardware
    # because blocks_hardware is True.
    return Sourced(float("nan"), TODO, note, unit)


# ---------------------------------------------------------------------------
# Standard curve (RFU -> concentration). Mirrors the tested OLS in
# packages/gene-edit/edit_confirmation/qc_math.py:linear_fit, kept here so this
# module is self-contained on the Pi (run_on_pi.sh only ships this tree).
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LineFit:
    slope: float
    intercept: float
    r_squared: float
    n: int

    def inverse(self, y: float) -> float:
        if self.slope == 0:
            raise ValueError("cannot invert a flat standard curve (slope 0)")
        return (y - self.intercept) / self.slope


def linear_fit(xs: Sequence[float], ys: Sequence[float]) -> LineFit:
    xs, ys = list(xs), list(ys)
    if len(xs) != len(ys):
        raise ValueError("linear_fit needs xs and ys of equal length")
    n = len(xs)
    if n < 2:
        raise ValueError("linear_fit needs at least 2 standards")
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    if sxx == 0:
        raise ValueError("all standard concentrations identical; cannot fit a line")
    slope = sxy / sxx
    intercept = my - slope * mx
    syy = sum((y - my) ** 2 for y in ys)
    r2 = 1.0 if syy == 0 and sxy == 0 else (sxy ** 2) / (sxx * syy) if syy else 0.0
    return LineFit(slope, intercept, r_squared=r2, n=n)


def ng_per_ml_to_ng_per_ul(x: float) -> float:
    """The one place the ng/mL curve output crosses into this module's ng/uL."""
    return x / 1000.0


@dataclass(frozen=True)
class WellConc:
    well: str
    rfu: float
    conc_ng_per_ul: float     # neat sample concentration, assay dilution multiplied back
    in_curve_range: bool


def concentrations_from_rfu(
    standard_conc_ng_per_ml: Sequence[float],
    standard_rfu: Sequence[float],
    sample_rfu_by_well: Dict[str, float],
    assay_dilution: float = 1.0,
    blank_rfu: Optional[float] = None,
) -> tuple:
    """Fit the PicoGreen curve and read every well's NEAT concentration in ng/uL.

    The curve is built blank-subtracted (blank = lowest standard if not given),
    matching how a PicoGreen curve is made. Sample RFU is blank-subtracted the same
    way, back-calculated to ng/mL, multiplied by the assay dilution, and converted
    to ng/uL. Returns (fit, {well: WellConc}).
    """
    blank = min(standard_rfu) if blank_rfu is None else blank_rfu
    net_std = [s - blank for s in standard_rfu]
    fit = linear_fit(standard_conc_ng_per_ml, net_std)
    lo, hi = min(net_std), max(net_std)
    out: Dict[str, WellConc] = {}
    for well, rfu in sample_rfu_by_well.items():
        net = rfu - blank
        conc_ng_per_ml = fit.inverse(net) * assay_dilution
        out[well] = WellConc(
            well=well,
            rfu=rfu,
            conc_ng_per_ul=ng_per_ml_to_ng_per_ul(conc_ng_per_ml),
            in_curve_range=(lo <= net <= hi),
        )
    return fit, out


# ---------------------------------------------------------------------------
# Config: every number here is a protocol value, carried as Sourced
# ---------------------------------------------------------------------------

@dataclass
class NormConfig:
    # The common concentration every well should reach (ng/uL). No repo default is
    # meaningful; the operator must set it. Ct must be <= a well's concentration for
    # that well to be reachable by dilution (below-target wells are carried neat).
    target: Sourced
    # Starting volume already in each well before water is added (uL). Uniform here;
    # per-well starts can be passed to build_plan.
    start_volume: Sourced
    # Smallest volume the chosen tip can dispense reliably on THIS instrument (uL).
    # A calibration value, not a guess: it decides which tiny water adds are clamped.
    min_transfer: Sourced
    # Useful volume of the destination well (uL). Diluting in place cannot exceed it.
    well_capacity: Sourced
    # Policy for a water add that is > 0 but below min_transfer.
    #   "clamp" -> dispense min_transfer (slightly over-dilutes, ends below target)
    #   "skip"  -> add nothing (leaves the well slightly above target)
    min_vol_policy: str = "clamp"

    def blocking(self) -> List[str]:
        """Reasons a hardware run must refuse: unpinned provenance OR bad values."""
        out = []
        for name in ("target", "start_volume", "min_transfer", "well_capacity"):
            s: Sourced = getattr(self, name)
            if s.blocks_hardware:
                out.append(f"{name}: {s.status} - {s.note}")
        # numeric sanity: a zero/negative target divides by itself; a capacity below
        # the start volume can never hold the diluted well.
        t, v0 = self.target.value, self.start_volume.value
        vmin, cap = self.min_transfer.value, self.well_capacity.value
        if math.isfinite(t) and t <= 0:
            out.append(f"target must be > 0, got {t}")
        if math.isfinite(v0) and v0 <= 0:
            out.append(f"start_volume must be > 0, got {v0}")
        if math.isfinite(vmin) and vmin <= 0:
            out.append(f"min_transfer must be > 0, got {vmin}")
        if math.isfinite(cap) and math.isfinite(v0) and cap < v0:
            out.append(f"well_capacity {cap} is below start_volume {v0}")
        if math.isfinite(vmin) and math.isfinite(cap) and vmin > cap:
            out.append(f"min_transfer {vmin} exceeds well_capacity {cap}")
        if self.min_vol_policy not in ("clamp", "skip"):
            out.append(f"min_vol_policy: unknown value {self.min_vol_policy!r}")
        return out


# ---------------------------------------------------------------------------
# The planner
# ---------------------------------------------------------------------------

# status values
OK = "ok"                          # hit target exactly
BELOW_TARGET = "below_target"      # conc <= target: cannot concentrate, carried neat
MIN_VOL_CLAMPED = "min_vol_clamped"  # water add rounded to min_transfer per policy
EXCEEDS_CAPACITY = "exceeds_capacity"  # target needs more volume than the well holds
EMPTY = "empty"                    # conc <= 0
INVALID = "invalid"                # conc is nan/inf: not a real reading, never touched

# All statuses whose well was left NOT at the target concentration.
OFF_TARGET_STATUSES = (BELOW_TARGET, MIN_VOL_CLAMPED, EXCEEDS_CAPACITY, EMPTY, INVALID)


@dataclass
class WellNorm:
    well: str
    conc_ng_per_ul: float     # measured neat concentration
    start_ul: float           # volume already in the well
    water_ul: float           # water to ADD (0 if carried neat)
    final_ul: float           # start + water
    final_ng_per_ul: float    # achieved concentration
    status: str


def _round(x: float, nd: int = 2) -> float:
    return round(x + 1e-9, nd)


def plan_well(well: str, conc: float, start_ul: float, cfg: NormConfig) -> WellNorm:
    target = cfg.target.value
    vmin = cfg.min_transfer.value
    cap = cfg.well_capacity.value

    # nan/inf concentration (or start): not a real reading. Never touch the well.
    # This must come FIRST: nan fails every < / <= comparison silently, so without
    # this guard a nan concentration would fall through to water = nan and be aspirated.
    if not math.isfinite(conc) or not math.isfinite(start_ul):
        return WellNorm(well, conc, start_ul, 0.0, start_ul, conc, INVALID)

    if conc <= 0:
        return WellNorm(well, _round(conc), _round(start_ul), 0.0, _round(start_ul), 0.0, EMPTY)

    # Cannot concentrate by adding water. Carry neat, flag under target.
    if conc <= target:
        return WellNorm(well, _round(conc), _round(start_ul), 0.0,
                        _round(start_ul), _round(conc), BELOW_TARGET)

    # Ideal water add and the volume it would produce.
    water = start_ul * (conc / target - 1.0)
    final = start_ul + water

    # Does not fit the well. Add as much as fits, report the (still-high) result.
    if final > cap:
        water = max(cap - start_ul, 0.0)
        final = start_ul + water
        achieved = conc * start_ul / final if final > 0 else conc
        return WellNorm(well, _round(conc), _round(start_ul), _round(water),
                        _round(final), _round(achieved, 4), EXCEEDS_CAPACITY)

    # Water add is real but below the reliable minimum.
    if water < vmin:
        if cfg.min_vol_policy == "skip":
            return WellNorm(well, _round(conc), _round(start_ul), 0.0,
                            _round(start_ul), _round(conc), MIN_VOL_CLAMPED)
        # "clamp": dispense the minimum; the well ends slightly below target.
        water = vmin
        final = start_ul + water
        achieved = conc * start_ul / final
        return WellNorm(well, _round(conc), _round(start_ul), _round(water),
                        _round(final), _round(achieved, 4), MIN_VOL_CLAMPED)

    return WellNorm(well, _round(conc), _round(start_ul), _round(water),
                    _round(final), _round(target), OK)


def build_plan(
    concs: Dict[str, float],
    cfg: NormConfig,
    start_volumes: Optional[Dict[str, float]] = None,
) -> List[WellNorm]:
    """concs: {well: ng/uL}. start_volumes overrides the uniform cfg.start_volume."""
    out = []
    for well, c in concs.items():
        v0 = (start_volumes or {}).get(well, cfg.start_volume.value)
        out.append(plan_well(well, c, v0, cfg))
    return out


def summarize(plan: List[WellNorm]) -> dict:
    counts: Dict[str, int] = {}
    for w in plan:
        counts[w.status] = counts.get(w.status, 0) + 1
    return {
        "wells": len(plan),
        "counts": counts,
        "total_water_ul": _round(sum(w.water_ul for w in plan), 1),
        "max_final_ul": _round(max((w.final_ul for w in plan), default=0.0), 1),
        "normalized_ok": counts.get(OK, 0),
        "flagged": len(plan) - counts.get(OK, 0),
        "detail": [asdict(w) for w in plan],
    }

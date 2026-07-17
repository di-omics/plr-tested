"""Unit tests for the dilute-in-place normalization planner. Pure, no hardware.

Run:  python3 test_normalize_plan.py    (prints PASS/FAIL, exits non-zero on any fail)
"""

from normalize_plan import (
    NormConfig, sourced, tunable, calibrate, todo,
    build_plan, plan_well, summarize,
    concentrations_from_rfu, linear_fit, ng_per_ml_to_ng_per_ul,
    OK, BELOW_TARGET, MIN_VOL_CLAMPED, EXCEEDS_CAPACITY, EMPTY,
)

FAILS = []


def check(name, cond, detail=""):
    if cond:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}   {detail}")
        FAILS.append(name)


def approx(a, b, tol=1e-6):
    return abs(a - b) <= tol


def cfg(target=2.0, start=20.0, vmin=1.0, cap=300.0, policy="clamp"):
    # a fully-pinned (ready) config: every value sourced, nothing blocks hardware
    return NormConfig(
        target=sourced(target, "test"),
        start_volume=sourced(start, "test"),
        min_transfer=sourced(vmin, "test"),
        well_capacity=sourced(cap, "test"),
        min_vol_policy=policy,
    )


print("=== water-add math (mass conservation) ===")
# 10 ng/uL in 20 uL -> target 2 ng/uL. water = 20*(10/2 - 1) = 80. final = 100. conc = 200/100 = 2.
w = plan_well("A1", 10.0, 20.0, cfg())
check("ok status", w.status == OK)
check("water = 80", approx(w.water_ul, 80.0), f"got {w.water_ul}")
check("final volume = 100", approx(w.final_ul, 100.0), f"got {w.final_ul}")
check("final conc = target", approx(w.final_ng_per_ul, 2.0), f"got {w.final_ng_per_ul}")
check("mass conserved", approx(w.conc_ng_per_ul * w.start_ul, w.final_ng_per_ul * w.final_ul, 1e-3))

print("=== higher concentration takes MORE water (volume differs) ===")
# both must fit the well: 4 -> final 40, 8 -> final 80, well cap 300
lo = plan_well("A1", 4.0, 20.0, cfg())
hi = plan_well("A2", 8.0, 20.0, cfg())
check("more concentrated well gets more water", hi.water_ul > lo.water_ul, f"{hi.water_ul} vs {lo.water_ul}")
check("both reach target", approx(lo.final_ng_per_ul, 2.0) and approx(hi.final_ng_per_ul, 2.0))
check("final volumes differ", not approx(lo.final_ul, hi.final_ul), f"{lo.final_ul} vs {hi.final_ul}")

print("=== below-target well: carried neat, flagged (operator's choice) ===")
b = plan_well("B1", 1.5, 20.0, cfg(target=2.0))
check("below_target status", b.status == BELOW_TARGET)
check("no water added", approx(b.water_ul, 0.0))
check("final volume unchanged", approx(b.final_ul, 20.0))
check("concentration unchanged (not fabricated to target)", approx(b.final_ng_per_ul, 1.5))

print("=== exactly at target: carried neat (conc <= target) ===")
e = plan_well("B2", 2.0, 20.0, cfg(target=2.0))
check("at-target treated as below_target, no water", e.status == BELOW_TARGET and approx(e.water_ul, 0.0))

print("=== empty / zero / negative concentration ===")
z = plan_well("C1", 0.0, 20.0, cfg())
check("empty status", z.status == EMPTY and approx(z.water_ul, 0.0))
neg = plan_well("C2", -3.0, 20.0, cfg())
check("negative treated as empty", neg.status == EMPTY)

print("=== min-transfer clamp policy ===")
# conc just above target: 2.05 in 20 -> water = 20*(2.05/2 -1) = 0.5, below vmin 1.0.
c_clamp = plan_well("D1", 2.05, 20.0, cfg(target=2.0, vmin=1.0, policy="clamp"))
check("clamp raises water to vmin", c_clamp.status == MIN_VOL_CLAMPED and approx(c_clamp.water_ul, 1.0),
      f"got {c_clamp.water_ul}")
check("clamp ends slightly BELOW target (over-diluted)", c_clamp.final_ng_per_ul < 2.0,
      f"got {c_clamp.final_ng_per_ul}")
c_skip = plan_well("D2", 2.05, 20.0, cfg(target=2.0, vmin=1.0, policy="skip"))
check("skip adds no water", c_skip.status == MIN_VOL_CLAMPED and approx(c_skip.water_ul, 0.0))
check("skip ends slightly ABOVE target", c_skip.final_ng_per_ul > 2.0, f"got {c_skip.final_ng_per_ul}")

print("=== exceeds well capacity ===")
# 200 ng/uL in 20 uL -> target 2 -> final would be 2000 uL, well holds 300.
x = plan_well("E1", 200.0, 20.0, cfg(target=2.0, cap=300.0))
check("exceeds_capacity status", x.status == EXCEEDS_CAPACITY)
check("water filled to capacity only", approx(x.final_ul, 300.0), f"got {x.final_ul}")
check("achieved conc still ABOVE target (honest, not faked)", x.final_ng_per_ul > 2.0,
      f"got {x.final_ng_per_ul}")
check("achieved = C*V0/cap", approx(x.final_ng_per_ul, 200.0 * 20.0 / 300.0, 1e-2))

print("=== per-well start volumes override uniform ===")
concs = {"A1": 10.0, "A2": 10.0}
plan = build_plan(concs, cfg(target=2.0, start=20.0), start_volumes={"A2": 40.0})
wa = {w.well: w for w in plan}
check("A1 uses uniform 20", approx(wa["A1"].start_ul, 20.0))
check("A2 uses override 40", approx(wa["A2"].start_ul, 40.0))
check("A2 (double start) needs double water", approx(wa["A2"].water_ul, 2 * wa["A1"].water_ul))

print("=== provenance blocks a hardware run until pinned ===")
blocked = NormConfig(
    target=todo("operator must set target ng/uL"),
    start_volume=tunable(20.0, "assumed 20 uL"),
    min_transfer=calibrate(1.0, "set from p50 low-volume calibration"),
    well_capacity=sourced(300.0, "CellTreat 350 Fb useful volume"),
)
b2 = blocked.blocking()
check("todo target blocks", any("target" in s for s in b2))
check("calibrate min_transfer blocks", any("min_transfer" in s for s in b2))
check("sourced well_capacity does NOT block", not any("well_capacity" in s for s in b2))
ok_cfg = cfg()
check("fully-sourced config does not block", ok_cfg.blocking() == [])

print("=== RFU -> ng/uL bridge (unit boundary + assay dilution) ===")
# curve: conc(ng/mL) -> rfu, slope 5, intercept 100 (blank). standards 0..1000.
stds = [0.0, 100.0, 500.0, 1000.0]
rfu = [100.0 + 5.0 * c for c in stds]   # blank 100
fit, wells = concentrations_from_rfu(
    standard_conc_ng_per_ml=stds,
    standard_rfu=rfu,
    sample_rfu_by_well={"A1": 100.0 + 5.0 * 200.0},  # 200 ng/mL raw
    assay_dilution=10.0,                              # sample was 1:10 into the assay
)
a1 = wells["A1"]
# 200 ng/mL raw * 10 dilution = 2000 ng/mL neat = 2.0 ng/uL.
check("curve fit slope recovered", approx(fit.slope, 5.0, 1e-6))
check("assay dilution multiplied back", approx(a1.conc_ng_per_ul, 2.0, 1e-6), f"got {a1.conc_ng_per_ul}")
check("ng/mL -> ng/uL is /1000", approx(ng_per_ml_to_ng_per_ul(2000.0), 2.0))
check("in curve range flag", a1.in_curve_range is True)

print("=== summarize ===")
# A1=10 (final 100, ok), A2=8 (final 80, ok), B1=1 (below), C1=0 (empty), E1=500 (overflow)
plan = build_plan({"A1": 10.0, "A2": 8.0, "B1": 1.0, "C1": 0.0, "E1": 500.0},
                  cfg(target=2.0, start=20.0, cap=300.0))
s = summarize(plan)
check("counts add up", sum(s["counts"].values()) == 5)
check("two normalized ok", s["counts"].get(OK, 0) == 2, f"got {s['counts']}")
check("one below_target", s["counts"].get(BELOW_TARGET, 0) == 1)
check("one empty", s["counts"].get(EMPTY, 0) == 1)
check("one exceeds_capacity", s["counts"].get(EXCEEDS_CAPACITY, 0) == 1)
check("total water is positive", s["total_water_ul"] > 0)

print("=== non-finite concentration is INVALID, never touched (review finding) ===")
from normalize_plan import INVALID, OFF_TARGET_STATUSES
inf = plan_well("F1", float("inf"), 20.0, cfg())
nan = plan_well("F2", float("nan"), 20.0, cfg())
check("inf -> invalid, no water", inf.status == INVALID and inf.water_ul == 0.0)
check("nan -> invalid, no water", nan.status == INVALID and nan.water_ul == 0.0)
check("nan start volume -> invalid", plan_well("F3", 10.0, float("nan"), cfg()).status == INVALID)
check("invalid is off-target", INVALID in OFF_TARGET_STATUSES)

print("=== config value validation blocks bad numbers (review finding) ===")
from normalize_plan import NormConfig
bad_target = NormConfig(target=sourced(0.0, "x"), start_volume=sourced(20.0, "x"),
                        min_transfer=sourced(1.0, "x"), well_capacity=sourced(300.0, "x"))
check("target 0 blocks", any("target must be > 0" in s for s in bad_target.blocking()))
bad_neg = NormConfig(target=sourced(-2.0, "x"), start_volume=sourced(20.0, "x"),
                     min_transfer=sourced(1.0, "x"), well_capacity=sourced(300.0, "x"))
check("negative target blocks", any("target must be > 0" in s for s in bad_neg.blocking()))
bad_cap = NormConfig(target=sourced(2.0, "x"), start_volume=sourced(50.0, "x"),
                     min_transfer=sourced(1.0, "x"), well_capacity=sourced(20.0, "x"))
check("capacity below start blocks", any("below start_volume" in s for s in bad_cap.blocking()))
check("good config still clean", cfg().blocking() == [])

print()
if FAILS:
    print(f"FAILED {len(FAILS)}: {FAILS}")
    raise SystemExit(1)
print("ALL PASS")

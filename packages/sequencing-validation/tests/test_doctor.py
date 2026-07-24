"""The doctor must be honest and must never crash the environment it runs in."""

from sequencing_validation.doctor import Status, format_report, run_doctor


def test_compute_tier_is_green_here():
    checks = run_doctor(hardware=False)
    # On any environment that can import the package and run Python 3.9+, the compute
    # tier has nothing MISSING - simulation needs no install.
    assert all(c.status is not Status.MISSING for c in checks)
    names = [c.name for c in checks]
    assert "simulation self-test" in names
    sim = next(c for c in checks if c.name == "simulation self-test")
    assert sim.status is Status.OK


def test_hardware_tier_lists_calibration_blockers():
    checks = run_doctor(hardware=True)
    cal = [c for c in checks if c.name.startswith("calibration:")]
    # working concentration and reader gain both block a hardware run until measured
    assert len(cal) == 2
    assert all(c.status is Status.MISSING for c in cal)


def test_report_renders_and_names_the_tier():
    assert "compute tier" in format_report(run_doctor(False), hardware=False)
    assert "hardware" in format_report(run_doctor(True), hardware=True)


def test_doctor_survives_and_returns_checks():
    # It catches everything internally; it should always return a non-empty list.
    assert run_doctor(hardware=True)

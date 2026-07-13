"""Tests for the doctor: the compute tier is green with nothing installed."""

from immunoassay.doctor import Status, run_doctor


def test_compute_tier_has_no_missing():
    checks = run_doctor(hardware=False)
    assert all(c.status is not Status.MISSING for c in checks)


def test_compute_tier_includes_a_passing_simulation_selftest():
    checks = {c.name: c for c in run_doctor(hardware=False)}
    assert checks["simulation self-test"].status is Status.OK
    assert "completed" in checks["simulation self-test"].detail


def test_hardware_tier_enumerates_the_blocking_calibrations():
    names = [c.name for c in run_doctor(hardware=True)]
    # the membrane clearance and the kit concentrations must be listed to resolve
    assert any("aspiration_clearance" in n for n in names)
    assert any("coat_antibody_concentration" in n for n in names)

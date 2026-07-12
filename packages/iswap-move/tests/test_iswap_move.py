"""Tests for the iSWAP lid-move package: geometry, safety validation, and run cards."""

import pytest

from iswap_move import (
    Direction,
    LidMove,
    Mode,
    Runner,
    Slot,
    Status,
    UnsafeMove,
    assert_safe,
    confirmed_de_lid,
    confirmed_lid_on,
    validate,
)
from iswap_move.core import CARRIER_MAX_POS, PICKUP_Z_OFFSET_MM, DROP_Z_OFFSET_MM
from iswap_move.runner import CONFIRM_PHRASE, move_command


def test_confirmed_recipe_matches_the_instrument():
    on = confirmed_lid_on()
    off = confirmed_de_lid()
    # rail35 pos4 (park) <-> pos0 (work), both directions
    assert on.src.key() == (35, 4) and on.dst.key() == (35, 0)
    assert off.src.key() == (35, 0) and off.dst.key() == (35, 4)
    # same offsets both ways
    assert on.pickup_z_offset_mm == off.pickup_z_offset_mm == float(PICKUP_Z_OFFSET_MM.value)
    assert on.drop_z_offset_mm == off.drop_z_offset_mm == float(DROP_Z_OFFSET_MM.value)
    assert on.direction is Direction.LID_ON and off.direction is Direction.DE_LID


def test_slot_position_bounds():
    with pytest.raises(ValueError):
        Slot(35, CARRIER_MAX_POS + 1)


def test_same_slot_is_rejected():
    bad = LidMove(Direction.LID_ON, Slot(35, 0), Slot(35, 0))
    assert validate(bad)
    with pytest.raises(UnsafeMove):
        assert_safe(bad)


def test_low_pickup_is_refused_but_overridable():
    low = LidMove(Direction.LID_ON, Slot(35, 4), Slot(35, 0), pickup_z_offset_mm=-14.0)
    # the rail27 lesson: a -14 mm pickup crashed the Z drive
    assert validate(low)
    assert not validate(low, allow_low_pickup=True)


def test_confirmed_move_passes_validation():
    assert validate(confirmed_lid_on()) == []
    assert validate(confirmed_de_lid()) == []


def test_hardware_runner_emits_arming_command():
    r = Runner(Mode.HARDWARE)
    a = r.lid_move(confirmed_lid_on())
    assert not a.refused
    assert a.resolved_command and CONFIRM_PHRASE in a.resolved_command
    assert "--src-rail 35 --src-pos 4 --dst-rail 35 --dst-pos 0" in a.resolved_command
    assert "--pickup-z-offset-mm 9.0" in a.resolved_command
    assert len(r.run_card()) == 1


def test_hardware_runner_refuses_unsafe_move_no_arming():
    r = Runner(Mode.HARDWARE)
    a = r.lid_move(LidMove(Direction.LID_ON, Slot(35, 0), Slot(35, 0)))
    assert a.refused
    assert a.resolved_command is None
    assert r.run_card() == []


def test_simulation_records_but_does_not_arm():
    r = Runner(Mode.SIMULATION)
    a = r.lid_move(confirmed_lid_on())
    assert a.resolved_command is None      # simulation never emits an arming command
    assert a.dry_command                    # but always shows the dry inspection command
    assert not a.refused


def test_cycle_is_two_moves():
    r = Runner(Mode.HARDWARE)
    for mv in (confirmed_lid_on(), confirmed_de_lid()):
        r.lid_move(mv)
    assert len(r.run_card()) == 2


def test_odtc_geometry_is_still_todo():
    from iswap_move.core import ODTC_LID_GEOMETRY
    assert ODTC_LID_GEOMETRY.status is Status.TODO
    assert ODTC_LID_GEOMETRY.blocks_hardware()

"""
core.py - iSWAP plate and lid moves on the Hamilton STAR, as data.

This package reduces a hardware-confirmed capability to a small, reusable, testable
form: moving a plate, and moving a plate LID (lid-on and de-lid), with the STAR's iSWAP
gripper. The geometry was tuned by hand on the instrument; here it is encoded once, with
where each number came from, so any protocol can ask for a lid move without re-teaching
the arm.

Every value carries a status:
  CONFIRMED  walked in on the instrument and observed to work. The lid recipe below is
             CONFIRMED (rail35 pos4 <-> pos0, pickup +9 / drop +18 mm, both directions).
  TUNABLE    a sensible default that is the operator's to adjust for their slot/labware.
  TODO       not tuned yet. A move that depends on a TODO value must not run for real.

The hard lessons from teaching it are encoded as validation, not comments:
  - A lid pickup driven too LOW crashes the Z drive into the plate ("drive locked");
    too HIGH cleanly misses ("plate not found"). The recipe prefers a hair high, and the
    validator refuses a pickup-z offset below the confirmed floor without an override.
  - The offsets are lid- and slot-specific, NOT global. Moving between other slots is a
    TODO until it is taught, and is flagged as such.
  - Source must hold a lid and dest must hold a plate; same-slot moves are rejected.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class Status(str, Enum):
    CONFIRMED = "confirmed"   # observed to work on the instrument
    TUNABLE = "tunable"       # a default, adjust per slot/labware
    TODO = "todo"             # not tuned yet; must not run for real


@dataclass(frozen=True)
class Sourced:
    """A value plus its status and where it came from."""
    value: object
    status: Status
    source: str
    unit: str = ""

    def blocks_hardware(self) -> bool:
        return self.status is Status.TODO


# ---------------------------------------------------------------------------
# The carrier and the confirmed recipe
# ---------------------------------------------------------------------------

# PLT_CAR_L5AC_A00 has five plate positions, 0..4 (test_iswap_lid_variable.py).
CARRIER = "PLT_CAR_L5AC_A00"
CARRIER_MIN_POS = 0
CARRIER_MAX_POS = 4

# The CONFIRMED lid recipe, from hamilton-star/starlab_live/test_iswap_lid_variable.py
# (walked in on the instrument, 2026-07-12; multiple clean successes, both directions).
LID_WORK_RAIL = Sourced(35, Status.CONFIRMED, "test_iswap_lid_variable.py: work slot", "rail")
LID_WORK_POS = Sourced(0, Status.CONFIRMED, "test_iswap_lid_variable.py: work plate pos0", "pos")
LID_PARK_RAIL = Sourced(35, Status.CONFIRMED, "test_iswap_lid_variable.py: lid park slot", "rail")
LID_PARK_POS = Sourced(4, Status.CONFIRMED, "test_iswap_lid_variable.py: lid park pos4", "pos")

PICKUP_Z_OFFSET_MM = Sourced(
    9.0, Status.CONFIRMED,
    "test_iswap_lid_variable.py: confirmed pickup-z offset on the instrument 2026-07-12", "mm")
DROP_Z_OFFSET_MM = Sourced(
    18.0, Status.CONFIRMED,
    "test_iswap_lid_variable.py: confirmed drop-z offset on the instrument 2026-07-12", "mm")
XY_OFFSET_MM = Sourced(
    0.0, Status.CONFIRMED,
    "test_iswap_lid_variable.py: x/y offsets left at 0 (move_lid computes them)", "mm")

# The move_lid API computes the grip from resource geometry; offset 0 is the truth and
# is only nudged in small steps. Encoded so a caller cannot silently drive the grip low.
PICKUP_Z_FLOOR_MM = Sourced(
    0.0, Status.CONFIRMED,
    "trust move_lid (offset 0); a NEGATIVE pickup-z offset risks a Z-drive crash into "
    "the plate. Below this floor requires an explicit override.", "mm")

# The plate/lid geometry INTO the ODTC itself is a different move and is NOT tuned.
ODTC_LID_GEOMETRY = Sourced(
    None, Status.TODO,
    "lidding a plate seated inside the ODTC is not taught; deck-to-deck lid moves are "
    "confirmed, the ODTC-internal geometry is not", "")


class Direction(str, Enum):
    LID_ON = "lid_on"     # move a lid FROM the park slot ONTO the work plate
    DE_LID = "de_lid"     # move the lid OFF the work plate BACK to the park slot


@dataclass(frozen=True)
class Slot:
    rail: int
    pos: int
    role: str = ""

    def __post_init__(self) -> None:
        if not (CARRIER_MIN_POS <= self.pos <= CARRIER_MAX_POS):
            raise ValueError(
                f"{CARRIER} position {self.pos} is out of range "
                f"{CARRIER_MIN_POS}..{CARRIER_MAX_POS}")

    def key(self) -> tuple:
        return (self.rail, self.pos)

    def label(self) -> str:
        r = f" ({self.role})" if self.role else ""
        return f"rail{self.rail} pos{self.pos}{r}"


@dataclass(frozen=True)
class LidMove:
    """One lid move: which direction, from where to where, at which offsets."""
    direction: Direction
    src: Slot
    dst: Slot
    pickup_z_offset_mm: float = float(PICKUP_Z_OFFSET_MM.value)
    drop_z_offset_mm: float = float(DROP_Z_OFFSET_MM.value)
    x_offset_mm: float = float(XY_OFFSET_MM.value)
    y_offset_mm: float = float(XY_OFFSET_MM.value)

    def describe(self) -> str:
        return (f"{self.direction.value}: {self.src.label()} -> {self.dst.label()} "
                f"(pickup z+{self.pickup_z_offset_mm}, drop z+{self.drop_z_offset_mm})")


def confirmed_lid_on() -> LidMove:
    """The CONFIRMED lid-on move: park slot -> work plate."""
    return LidMove(
        direction=Direction.LID_ON,
        src=Slot(int(LID_PARK_RAIL.value), int(LID_PARK_POS.value), "lid park"),
        dst=Slot(int(LID_WORK_RAIL.value), int(LID_WORK_POS.value), "work plate"),
    )


def confirmed_de_lid() -> LidMove:
    """The CONFIRMED de-lid move: work plate -> park slot (same offsets, reversed)."""
    return LidMove(
        direction=Direction.DE_LID,
        src=Slot(int(LID_WORK_RAIL.value), int(LID_WORK_POS.value), "work plate"),
        dst=Slot(int(LID_PARK_RAIL.value), int(LID_PARK_POS.value), "lid park"),
    )


# ---------------------------------------------------------------------------
# Validation: the safety lessons, as checks
# ---------------------------------------------------------------------------

class UnsafeMove(ValueError):
    """A move that violates a rule learned on the instrument."""


def validate(move: LidMove, allow_low_pickup: bool = False) -> List[str]:
    """Return a list of problems with a move. Empty means it is safe to run.

    Raises nothing; the caller decides. The runner treats a non-empty list from a
    hardware run as a refusal.
    """
    problems: List[str] = []
    if move.src.key() == move.dst.key():
        problems.append("source and dest are the same slot; nothing to move")
    floor = float(PICKUP_Z_FLOOR_MM.value)
    if move.pickup_z_offset_mm < floor and not allow_low_pickup:
        problems.append(
            f"pickup-z offset {move.pickup_z_offset_mm} mm is below the floor {floor} mm; "
            "a low pickup risks a Z-drive crash into the plate. Prefer too-high; pass "
            "allow_low_pickup=True only if you are deliberately walking it in and watching.")
    return problems


def assert_safe(move: LidMove, allow_low_pickup: bool = False) -> None:
    problems = validate(move, allow_low_pickup=allow_low_pickup)
    if problems:
        raise UnsafeMove("; ".join(problems))

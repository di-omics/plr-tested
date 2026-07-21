"""Pure sample-count planning for the validated one-column dry envelope.

This module is deliberately inert. It imports no hardware libraries and has no
I/O. The current hardened component runners actuate all eight channels over
column 1, so a plan always contains A1:H1. If fewer than eight biological
samples are entered, the remaining channel positions are explicit blanks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple


ROWS: Tuple[str, ...] = tuple("ABCDEFGH")
CHANNEL_COUNT = 8
MIN_SAMPLE_COUNT = 1
MAX_VALIDATED_SAMPLE_COUNT = 8
ACTUATED_COLUMN = 1


class SampleCountError(ValueError):
    """An input cannot be represented by the released planning envelope."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class RunPlan:
    sample_count: int
    sample_wells: Tuple[str, ...]
    blank_wells: Tuple[str, ...]

    @property
    def actuated_wells(self) -> Tuple[str, ...]:
        return self.sample_wells + self.blank_wells

    def to_dict(self) -> Dict[str, object]:
        return {
            "sample_count": self.sample_count,
            "column_count": 1,
            "actuated_columns": [ACTUATED_COLUMN],
            "robot_reaction_count": CHANNEL_COUNT,
            "sample_wells": list(self.sample_wells),
            "blank_wells": list(self.blank_wells),
            "actuated_wells": list(self.actuated_wells),
            "unused_positions": len(self.blank_wells),
            "mode": "dry_planning_only",
            "notes": [
                "Sample count is biological samples only; no NTC or control wells are added.",
                "The robot plan actuates all eight wells A1:H1.",
                "Blank wells are intentional channel positions, not extra samples.",
                "Dry only: empty sacrificial labware and returned tips.",
                "No HHS heating or shaking and no ODTC command or heating.",
            ],
        }


def plan_samples(sample_count: int) -> RunPlan:
    """Return the only currently supported plan, or fail closed.

    Booleans and numeric-looking strings are rejected rather than coerced. The
    API contract is an integer sample count, which keeps malformed browser or
    scripted requests from silently selecting a different run plan.
    """

    if isinstance(sample_count, bool) or not isinstance(sample_count, int):
        raise SampleCountError(
            "invalid_type",
            "sample_count must be a JSON integer from 1 through 8",
        )
    if sample_count < MIN_SAMPLE_COUNT:
        raise SampleCountError(
            "below_minimum",
            "sample_count must be at least 1",
        )
    if sample_count > MAX_VALIDATED_SAMPLE_COUNT:
        raise SampleCountError(
            "no_validated_multicolumn_build",
            "sample_count above 8 is blocked until a combined multi-column build is validated",
        )

    wells = tuple(f"{row}{ACTUATED_COLUMN}" for row in ROWS)
    return RunPlan(
        sample_count=sample_count,
        sample_wells=wells[:sample_count],
        blank_wells=wells[sample_count:],
    )

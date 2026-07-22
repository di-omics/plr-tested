"""Pure EM-seq v2 sample-count planning for one 96-well plate.

This module is deliberately inert. It imports no hardware libraries and has no
I/O. Samples fill the plate in eight-channel column order: A1:H1, then A2:H2,
through A12:H12. The final partial column is padded with explicit blank channel
positions. Planning up to 96 wells does not expand the current physical runner,
which remains limited to the separately validated one-column dry envelope.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple


ROWS: Tuple[str, ...] = tuple("ABCDEFGH")
CHANNEL_COUNT = 8
PLATE_COLUMN_COUNT = 12
PLATE_WELL_COUNT = CHANNEL_COUNT * PLATE_COLUMN_COUNT
MIN_SAMPLE_COUNT = 1
MAX_PLANNABLE_SAMPLE_COUNT = PLATE_WELL_COUNT
MAX_HARDWARE_VALIDATED_SAMPLE_COUNT = 8
OBSERVED_DRY_RUNTIME_MINUTES = 67
DEFAULT_PCR_CYCLES = 8
DEFAULT_THERMAL_HOLD_MINUTES = 389


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
    def column_count(self) -> int:
        return (self.sample_count + CHANNEL_COUNT - 1) // CHANNEL_COUNT

    @property
    def actuated_columns(self) -> Tuple[int, ...]:
        return tuple(range(1, self.column_count + 1))

    @property
    def actuated_wells(self) -> Tuple[str, ...]:
        return self.sample_wells + self.blank_wells

    @property
    def current_runner_eligible(self) -> bool:
        return self.sample_count <= MAX_HARDWARE_VALIDATED_SAMPLE_COUNT

    def to_dict(self) -> Dict[str, object]:
        sample_set = set(self.sample_wells)
        blank_set = set(self.blank_wells)
        plate_layout = []
        for row in ROWS:
            for column in range(1, PLATE_COLUMN_COUNT + 1):
                well = f"{row}{column}"
                if well in sample_set:
                    state = "sample"
                elif well in blank_set:
                    state = "blank"
                else:
                    state = "unused"
                plate_layout.append({"well": well, "state": state})

        if self.current_runner_eligible:
            runner_message = (
                "This plan fits the physically dry-validated A1:H1 runner envelope. "
                "The planner still cannot start hardware, and wet/ODTC execution remains blocked."
            )
        else:
            runner_message = (
                "Layout proposal only: this plan exceeds the physically dry-validated "
                "A1:H1 runner. Multi-column tip, source, cleanup, and motion logic must "
                "be implemented and bench-validated before physical execution."
            )

        return {
            "sample_count": self.sample_count,
            "column_count": self.column_count,
            "actuated_columns": list(self.actuated_columns),
            "robot_reaction_count": len(self.actuated_wells),
            "sample_wells": list(self.sample_wells),
            "blank_wells": list(self.blank_wells),
            "actuated_wells": list(self.actuated_wells),
            "unused_positions": len(self.blank_wells),
            "unused_plate_wells": PLATE_WELL_COUNT - len(self.actuated_wells),
            "plate_layout": plate_layout,
            "current_runner": {
                "eligible": self.current_runner_eligible,
                "sample_count_max": MAX_HARDWARE_VALIDATED_SAMPLE_COUNT,
                "column_count_max": 1,
                "message": runner_message,
            },
            "runtime": {
                "observed_physical_dry_minutes": OBSERVED_DRY_RUNTIME_MINUTES,
                "observed_physical_dry_label": "about 1 h 7 min",
                "observed_scope": "one A1:H1 column, empty deck, no ODTC heat",
                "default_thermal_hold_minutes": DEFAULT_THERMAL_HOLD_MINUTES,
                "default_thermal_hold_label": "about 6 h 29 min",
                "default_pcr_cycles": DEFAULT_PCR_CYCLES,
                "multi_column_estimate_available": False,
                "note": (
                    "Thermal holds exclude ramps, cooling, reagent swaps, seal/spin, "
                    "cleanup waits, and QC. Multi-column runtime is not estimated because "
                    "the 9-96 sample runner has not been implemented."
                ),
            },
            "mode": "dry_planning_only",
            "notes": [
                "Sample count is library positions only; no hidden process-blank well is added.",
                "Lambda and pUC19 conversion controls are spike-ins within each sample, not extra wells.",
                "Plate layout fills complete eight-channel columns from A1:H1 through A12:H12.",
                "The final partial column is padded with intentional blank channel positions.",
                runner_message,
                "Dry only: empty sacrificial labware and returned tips.",
                "The validated rehearsal printed ODTC notes but did not run ODTC heating.",
            ],
        }


def plan_samples(sample_count: int) -> RunPlan:
    """Return a one-plate layout, or fail closed.

    Booleans and numeric-looking strings are rejected rather than coerced. The
    API contract is an integer sample count, which keeps malformed browser or
    scripted requests from silently selecting a different run plan.
    """

    if isinstance(sample_count, bool) or not isinstance(sample_count, int):
        raise SampleCountError(
            "invalid_type",
            "sample_count must be a JSON integer from 1 through 96",
        )
    if sample_count < MIN_SAMPLE_COUNT:
        raise SampleCountError(
            "below_minimum",
            "sample_count must be at least 1",
        )
    if sample_count > MAX_PLANNABLE_SAMPLE_COUNT:
        raise SampleCountError(
            "above_plate_capacity",
            "sample_count cannot exceed the 96 wells on one plate",
        )

    column_count = (sample_count + CHANNEL_COUNT - 1) // CHANNEL_COUNT
    wells = tuple(
        f"{row}{column}"
        for column in range(1, column_count + 1)
        for row in ROWS
    )
    return RunPlan(
        sample_count=sample_count,
        sample_wells=wells[:sample_count],
        blank_wells=wells[sample_count:],
    )

"""
runner.py - turn a lid move into either a recorded plan or a hardware run card.

Same split as the rest of the di-omics packages: in simulation the runner records what
it would do and returns success, so a flow can be exercised with no instrument; in
hardware mode it resolves the move to the exact validated Pi command and refuses to emit
an arming command for a move that fails validation.

It does not drive the STAR itself. The tuned motion lives in
hamilton-star/starlab_live/test_iswap_lid_variable.py, walked in on the instrument; this
runner points at it with the confirmed arguments. The package plans and gates; the
validated script executes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from .core import Direction, LidMove, UnsafeMove, validate

_STAR_DIR = "hamilton-star"
_LID_SCRIPT = "starlab_live/test_iswap_lid_variable.py"
CONFIRM_PHRASE = "RUN_LID_MOVE"


class Mode(str, Enum):
    SIMULATION = "simulation"
    HARDWARE = "hardware"


@dataclass
class Action:
    action: str
    params: dict
    mode: Mode
    resolved_command: Optional[str] = None   # hardware only
    dry_command: str = ""                     # the --mode deck (no motion) form
    note: str = ""
    problems: List[str] = field(default_factory=list)

    @property
    def refused(self) -> bool:
        return bool(self.problems)

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "params": self.params,
            "mode": self.mode.value,
            "resolved_command": self.resolved_command,
            "dry_command": self.dry_command,
            "note": self.note,
            "problems": self.problems,
        }


def _base_args(move: LidMove) -> str:
    return (f"--src-rail {move.src.rail} --src-pos {move.src.pos} "
            f"--dst-rail {move.dst.rail} --dst-pos {move.dst.pos} "
            f"--pickup-z-offset-mm {move.pickup_z_offset_mm} "
            f"--drop-z-offset-mm {move.drop_z_offset_mm}")


def dry_command(move: LidMove) -> str:
    """The coordinate-print-only command: assigns the deck, prints, does NOT move."""
    return (f"cd {_STAR_DIR} && ./run_on_pi.sh {_LID_SCRIPT} "
            f"--mode deck {_base_args(move)}")


def move_command(move: LidMove) -> str:
    """The arming command that actually moves the iSWAP. A person must be watching."""
    return (f"cd {_STAR_DIR} && ./run_on_pi.sh {_LID_SCRIPT} "
            f"--mode move {_base_args(move)} --confirm {CONFIRM_PHRASE}")


class Runner:
    """Records lid moves; in hardware mode resolves them to run-card commands."""

    def __init__(self, mode: Mode = Mode.SIMULATION):
        self.mode = mode
        self.actions: List[Action] = []

    def lid_move(self, move: LidMove, allow_low_pickup: bool = False) -> Action:
        problems = validate(move, allow_low_pickup=allow_low_pickup)
        dry = dry_command(move)
        resolved = None
        note = move.describe()
        if self.mode is Mode.HARDWARE:
            if problems:
                note = "REFUSED (see problems); run the dry command to inspect coordinates"
            else:
                resolved = move_command(move)
        rec = Action(
            action=move.direction.value,
            params={
                "src": move.src.label(), "dst": move.dst.label(),
                "pickup_z_offset_mm": move.pickup_z_offset_mm,
                "drop_z_offset_mm": move.drop_z_offset_mm,
            },
            mode=self.mode,
            resolved_command=resolved,
            dry_command=dry,
            note=note,
            problems=problems,
        )
        self.actions.append(rec)
        return rec

    def run_card(self) -> List[str]:
        """The ordered arming commands for this session (hardware, validated moves only)."""
        return [a.resolved_command for a in self.actions if a.resolved_command]

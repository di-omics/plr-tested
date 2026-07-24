"""
instruments/base.py - the seam between the package and the bench.

Every stage speaks to instruments through an adapter, and every adapter records what it
did as an ActionRecord before doing it. In simulation mode the record is the whole
story and the adapter also returns synthetic readings. In hardware mode the record
carries the resolved command - the exact validated Pi script and arguments that must
run - so a hardware run of this package is a run card an operator or a scheduler
executes on starpi, not a second, unvalidated copy of the liquid-handling code.

This split is deliberate. The validated way to drive the STAR, the ODTC, and the Tecan
already lives in this repo (hamilton-star/, instrument-integrations/), tuned by hand
against the physical deck. This package does not reimplement that. It plans the run,
enforces the gates, and in hardware mode points at those scripts; it never pretends to
have driven an instrument it cannot reach.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..config import RunMode


@dataclass
class ActionRecord:
    instrument: str
    action: str
    params: Dict[str, Any] = field(default_factory=dict)
    mode: RunMode = RunMode.SIMULATION
    resolved_command: Optional[str] = None   # hardware: the Pi command to run
    simulated: bool = True
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "instrument": self.instrument,
            "action": self.action,
            "params": self.params,
            "mode": self.mode.value,
            "resolved_command": self.resolved_command,
            "simulated": self.simulated,
            "note": self.note,
        }


class AwaitingData(RuntimeError):
    """A hardware read has no measured data yet.

    Raised when a hardware run reaches a plate read and no results file was supplied.
    The run card has been emitted; the operator runs the read on the Pi and re-runs
    this package with the results file. This is how a remote/asynchronous run resumes.
    """


class Adapter:
    """Common bookkeeping for the three instrument adapters.

    Every action is appended both to the adapter's own list and, if given, to a shared
    chronological sink so a stage can slice exactly the actions that happened during it,
    in the order they happened, across all three instruments.
    """

    instrument = "instrument"

    def __init__(self, mode: RunMode, sink: Optional[List[ActionRecord]] = None):
        self.mode = mode
        self.actions: List[ActionRecord] = []
        self._sink = sink

    def _record(self, action: str, params: Dict[str, Any],
                resolved_command: Optional[str] = None, note: str = "") -> ActionRecord:
        rec = ActionRecord(
            instrument=self.instrument,
            action=action,
            params=params,
            mode=self.mode,
            resolved_command=resolved_command if self.mode is RunMode.HARDWARE else None,
            simulated=(self.mode is RunMode.SIMULATION),
            note=note,
        )
        self.actions.append(rec)
        if self._sink is not None:
            self._sink.append(rec)
        return rec

    def run_card(self) -> List[str]:
        """The ordered list of hardware commands this adapter resolved (hardware mode)."""
        return [r.resolved_command for r in self.actions if r.resolved_command]

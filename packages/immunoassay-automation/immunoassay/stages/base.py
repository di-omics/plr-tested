"""
stages/base.py - what a stage is, and the context it runs in.

A stage is one span of the flow between two gates: qualify the instrument, prepare the
plate, add cells, develop, read out, hand off. Each takes a StageContext - the shared run
config, the three instrument adapters, the set of wells still in play, and the growing
record - and returns a StageResult that says whether the run continues, continues with a
subset of wells, or stops, plus everything the report needs.

The context carries the alive-well set because a gate can prune it. A saturated well or a
replicate group that fails its CV at the readout gate does not enter the response summary;
the orchestrator narrows context.active_addresses from the gate's verdict, and the handoff
sees only the survivors. That narrowing, recorded, is the audit trail.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from ..config import RunConfig, Well
from ..gates import GateResult
from ..instruments.base import ActionRecord
from ..instruments.imager import ImagerAdapter
from ..instruments.liquid_handler import LiquidHandlerAdapter
from ..instruments.washer import WasherAdapter
from ..provenance import RunGuard


class StageStatus(str, Enum):
    COMPLETED = "completed"
    STOPPED = "stopped"           # a gate stopped the run
    AWAITING_DATA = "awaiting"    # a hardware read needs data before continuing


@dataclass
class StageContext:
    config: RunConfig
    washer: WasherAdapter
    lh: LiquidHandlerAdapter
    imager: ImagerAdapter
    guard: RunGuard
    action_log: List[ActionRecord] = field(default_factory=list)   # shared, chronological
    active_addresses: List[str] = field(default_factory=list)
    shared: Dict[str, Any] = field(default_factory=dict)   # cross-stage carry

    def active_wells(self) -> List[Well]:
        by_addr = {w.address: w for w in self.config.plate.wells}
        return [by_addr[a] for a in self.active_addresses if a in by_addr]

    def action_mark(self) -> int:
        return len(self.action_log)

    def actions_since(self, mark: int) -> List[ActionRecord]:
        return self.action_log[mark:]


@dataclass
class StageResult:
    name: str
    status: StageStatus
    title: str = ""
    message: str = ""
    gate: Optional[GateResult] = None
    data: Dict[str, Any] = field(default_factory=dict)
    actions: List[ActionRecord] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status is StageStatus.COMPLETED

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "title": self.title,
            "status": self.status.value,
            "message": self.message,
            "gate": self.gate.to_dict() if self.gate else None,
            "data": self.data,
            "actions": [a.to_dict() for a in self.actions],
        }


class Stage:
    """Base class. A concrete stage sets `name`/`title` and implements run()."""

    name = "stage"
    title = "Stage"

    def run(self, ctx: StageContext) -> StageResult:  # pragma: no cover - interface
        raise NotImplementedError

"""
stages/base.py - what a stage is, and the context it runs in.

A stage is one span of the flow between two gates: qualify the deck, run PTA, quant the
PTA product, build the library, quant the library, hand off. Each takes a StageContext -
the shared run config, the three instrument adapters, the set of samples still alive,
and the growing record - and returns a StageResult that says whether the run continues,
continues with a subset, or stops, plus everything the report needs.

The context carries the alive-sample set because gates prune it. A sample that fails the
post-PTA yield gate does not reach the library prep; the orchestrator narrows
context.active_sample_ids from each gate's verdict, and every later stage sees only the
survivors. That narrowing, recorded at each step, is the audit trail.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from ..config import RunConfig, Sample
from ..gates import GateResult
from ..instruments.base import ActionRecord
from ..instruments.odtc import OdtcAdapter
from ..instruments.star import StarAdapter
from ..instruments.tecan import TecanAdapter
from ..provenance import RunGuard


class StageStatus(str, Enum):
    COMPLETED = "completed"
    STOPPED = "stopped"          # a gate stopped the run
    AWAITING_DATA = "awaiting"    # a hardware read needs data before continuing


@dataclass
class StageContext:
    config: RunConfig
    star: StarAdapter
    odtc: OdtcAdapter
    tecan: TecanAdapter
    guard: RunGuard
    action_log: List[ActionRecord] = field(default_factory=list)   # shared, chronological
    active_sample_ids: List[str] = field(default_factory=list)
    shared: Dict[str, Any] = field(default_factory=dict)   # cross-stage carry (e.g. concs)

    def active_samples(self) -> List[Sample]:
        by_id = {s.id: s for s in self.config.samples}
        return [by_id[sid] for sid in self.active_sample_ids if sid in by_id]

    def action_mark(self) -> int:
        """Current length of the shared action log; slice from here at stage end."""
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

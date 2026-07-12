"""
orchestrator.py - run the stages, enforce the gates, assemble the dossier.

This is the backbone the JD calls distributed automation: the thing that sequences a
protocol the same way in any lab and controls what happens between the steps. It builds
the three instrument adapters, threads a shared action log and a provenance guard
through every stage, and runs the fixed sequence:

  Gate 0 lh_qc -> PTA -> Gate 1 post-PTA -> ampseq -> Gate 2 post-ampseq -> handoff

After each stage it reads the gate's decision and acts on it, which is the whole reason
gates are objects and not print statements:
  - STOP: the run ends here; no later stage runs, no reagent past this point is spent.
  - PROCEED_SUBSET: the active sample set narrows to the wells that passed, and every
    later stage sees only those.
  - PROCEED: everything continues.

A hardware read with no data yet raises AwaitingData; the run pauses with a run card for
the operator and can be resumed with the captured data. A value that was never pinned
down raises ProvenanceError before any instrument moves. Both end the run cleanly with a
dossier that says exactly why.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from .config import RunConfig, RunMode
from .gates import Decision
from .instruments.base import ActionRecord, AwaitingData
from .instruments.odtc import OdtcAdapter
from .instruments.star import StarAdapter
from .instruments.tecan import TecanAdapter
from .provenance import ProvenanceError, RunGuard
from .simulation import POORLY_TUNED_DECK, WELL_TUNED_DECK
from .stages.ampseq import AmpliconSeq
from .stages.base import Stage, StageContext, StageResult, StageStatus
from .stages.handoff import Handoff
from .stages.lh_qc import LiquidHandlingQC
from .stages.pta import PTA
from .stages.qc_picogreen import Checkpoint, PicoGreenQC


class RunStatus(str, Enum):
    COMPLETED = "completed"
    STOPPED = "stopped"
    AWAITING_DATA = "awaiting_data"


@dataclass
class RunOutcome:
    config: RunConfig
    status: RunStatus
    stages: List[StageResult] = field(default_factory=list)
    final_active_sample_ids: List[str] = field(default_factory=list)
    guard_summary: dict = field(default_factory=dict)
    guard_blocking: List[str] = field(default_factory=list)
    message: str = ""
    timestamp: str = ""

    def to_dict(self) -> dict:
        return {
            "run_id": self.config.run_id,
            "operator": self.config.operator,
            "mode": self.config.mode.value,
            "timestamp": self.timestamp,
            "status": self.status.value,
            "message": self.message,
            "locus": {
                "name": self.config.locus.name,
                "amplicon_bp": self.config.locus.amplicon_bp,
            },
            "edit_type": self.config.edit_type.value,
            "final_active_sample_ids": self.final_active_sample_ids,
            "guard_summary": self.guard_summary,
            "guard_blocking": self.guard_blocking,
            "stages": [s.to_dict() for s in self.stages],
        }


def build_stages(config: RunConfig) -> List[Stage]:
    """The fixed sequence for edit confirmation."""
    return [
        LiquidHandlingQC(),
        PTA(),
        PicoGreenQC(Checkpoint.POST_PTA),
        AmpliconSeq(),
        PicoGreenQC(Checkpoint.POST_AMPSEQ),
        Handoff(),
    ]


def run(config: RunConfig, timestamp: str = "", deck_quality=None) -> RunOutcome:
    """Execute the run and return its outcome.

    deck_quality is a simulation knob only: pass simulation.POORLY_TUNED_DECK to see
    Gate 0 stop the run before any sample is touched. It has no effect on a hardware run.
    """
    action_log: List[ActionRecord] = []
    deck = deck_quality if deck_quality is not None else WELL_TUNED_DECK
    star = StarAdapter(config.mode, deck=deck, sink=action_log, tip_column=config.tip_column)
    odtc = OdtcAdapter(config.mode, sink=action_log)
    tecan = TecanAdapter(config.mode, sink=action_log)
    guard = RunGuard()

    ctx = StageContext(
        config=config, star=star, odtc=odtc, tecan=tecan, guard=guard,
        action_log=action_log,
        active_sample_ids=[s.id for s in config.samples],
    )

    results: List[StageResult] = []
    status = RunStatus.COMPLETED
    message = "run completed through handoff"

    for stage in build_stages(config):
        try:
            result = stage.run(ctx)
        except AwaitingData as exc:
            results.append(StageResult(
                name=stage.name, title=stage.title, status=StageStatus.AWAITING_DATA,
                message=str(exc), actions=list(action_log),
            ))
            status = RunStatus.AWAITING_DATA
            message = f"paused at {stage.title}: awaiting instrument data"
            break
        except ProvenanceError as exc:
            results.append(StageResult(
                name=stage.name, title=stage.title, status=StageStatus.STOPPED,
                message=str(exc),
            ))
            status = RunStatus.STOPPED
            message = f"stopped at {stage.title}: values not pinned down"
            break

        results.append(result)

        if result.gate and result.gate.decision is Decision.PROCEED_SUBSET:
            ctx.active_sample_ids = result.gate.passing_sample_ids()

        if result.status is StageStatus.STOPPED:
            status = RunStatus.STOPPED
            message = f"stopped at {stage.title}: {result.message}"
            break

    return RunOutcome(
        config=config,
        status=status,
        stages=results,
        final_active_sample_ids=list(ctx.active_sample_ids),
        guard_summary=guard.summary(),
        guard_blocking=[str(v) for v in guard.blocking()],
        message=message,
        timestamp=timestamp,
    )

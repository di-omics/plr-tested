"""
orchestrator.py - run the stages, enforce the gates, assemble the dossier.

This is the backbone the JD calls distributed automation: the thing that sequences the
protocol the same way in any lab and controls what happens between the steps. It builds the
three instrument adapters, threads a shared action log and a provenance guard through every
stage, and runs the fixed sequence:

  Gate 0 readiness -> plate prep (Gate 1) -> stimulation -> develop -> Gate 2 readout -> handoff

After each stage it reads the gate's decision and acts on it, which is the whole reason gates
are objects and not print statements:
  - STOP: the run ends here; no later stage runs, no reagent past this point is spent.
  - PROCEED_SUBSET: the active well set narrows to the wells that passed, and the handoff sees
    only those.
  - PROCEED: everything continues.

A hardware read with no data yet raises AwaitingData; the run pauses with a run card for the
operator and resumes with the captured counts. A value that was never pinned down raises
ProvenanceError before any instrument moves. Both end the run cleanly with a dossier that says
exactly why.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from .config import RunConfig
from .gates import Decision
from .instruments.base import ActionRecord, AwaitingData
from .instruments.imager import ImagerAdapter
from .instruments.liquid_handler import Backend, LiquidHandlerAdapter
from .instruments.washer import WasherAdapter
from .provenance import ProvenanceError, RunGuard
from .simulation import GOOD_PLATE, WELL_TUNED_WASHER, PlateBiology, WasherQuality
from .stages.base import Stage, StageContext, StageResult, StageStatus
from .stages.develop import Develop
from .stages.handoff import Handoff
from .stages.plate_prep import PlatePrep
from .stages.readiness import Readiness
from .stages.readout import Readout
from .stages.stimulation import Stimulation


class RunStatus(str, Enum):
    COMPLETED = "completed"
    STOPPED = "stopped"
    AWAITING_DATA = "awaiting_data"


@dataclass
class RunOutcome:
    config: RunConfig
    status: RunStatus
    stages: List[StageResult] = field(default_factory=list)
    final_active_addresses: List[str] = field(default_factory=list)
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
            "cytokine": self.config.cytokine,
            "site": self.config.site.name,
            "final_active_addresses": self.final_active_addresses,
            "guard_summary": self.guard_summary,
            "guard_blocking": self.guard_blocking,
            "stages": [s.to_dict() for s in self.stages],
        }


def build_stages(biology: PlateBiology) -> List[Stage]:
    """The fixed ELISpot sequence. biology is a simulation-only knob for the readout."""
    return [
        Readiness(),
        PlatePrep(),
        Stimulation(),
        Develop(),
        Readout(biology=biology),
        Handoff(),
    ]


def run(config: RunConfig, timestamp: str = "",
        washer_quality: WasherQuality = WELL_TUNED_WASHER,
        biology: PlateBiology = GOOD_PLATE,
        lh_backend: Backend = Backend.FLEX) -> RunOutcome:
    """Execute the run and return its outcome.

    washer_quality and biology are simulation knobs only (pass POOR_WASHER to see Gate 0
    stop, HIGH_BACKGROUND_PLATE or DEAD_CELLS_PLATE to see Gate 2 void the plate). They have
    no effect on a hardware run, where the instruments supply the reads.
    """
    action_log: List[ActionRecord] = []
    washer = WasherAdapter(config.mode, quality=washer_quality, sink=action_log)
    lh = LiquidHandlerAdapter(config.mode, backend=lh_backend, sink=action_log)
    imager = ImagerAdapter(config.mode, sink=action_log)
    guard = RunGuard()

    ctx = StageContext(
        config=config, washer=washer, lh=lh, imager=imager, guard=guard,
        action_log=action_log,
        active_addresses=[w.address for w in config.plate.wells],
    )

    results: List[StageResult] = []
    status = RunStatus.COMPLETED
    message = "run completed through handoff"

    for stage in build_stages(biology):
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
            ctx.active_addresses = result.gate.passing_sample_ids()

        if result.status is StageStatus.STOPPED:
            status = RunStatus.STOPPED
            message = f"stopped at {stage.title}: {result.message}"
            break

    return RunOutcome(
        config=config,
        status=status,
        stages=results,
        final_active_addresses=list(ctx.active_addresses),
        guard_summary=guard.summary(),
        guard_blocking=[str(v) for v in guard.blocking()],
        message=message,
        timestamp=timestamp,
    )

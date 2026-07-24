"""Simulation-first orchestration and honest live-run blocking."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from .config import RunConfig, RunMode
from .gates import Decision, GateResult, evaluate_library_qc, evaluate_liquid_handling
from .protocol import ProtocolStep, build_protocol
from .provenance import (
    HardwareNotReady,
    Sourced,
    assert_hardware_ready,
    blocking,
    protocol_values,
)
from .simulation import simulate_metrics


class RunStatus(str, Enum):
    COMPLETED = "completed"
    STOPPED = "stopped"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class ActionRecord:
    step_number: int
    name: str
    operation: str
    simulated: bool
    executed: bool
    command: Optional[str]
    note: str

    def to_dict(self) -> dict:
        return {
            "step_number": self.step_number,
            "name": self.name,
            "operation": self.operation,
            "simulated": self.simulated,
            "executed": self.executed,
            "command": self.command,
            "note": self.note,
        }


@dataclass
class RunOutcome:
    config: RunConfig
    status: RunStatus
    message: str
    timestamp: str
    protocol: List[ProtocolStep]
    provenance: List[Sourced]
    actions: List[ActionRecord] = field(default_factory=list)
    gates: List[GateResult] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)
    final_sample_ids: List[str] = field(default_factory=list)

    @property
    def hardware_blockers(self) -> List[Sourced]:
        return blocking(self.provenance)

    def to_dict(self) -> dict:
        return {
            "run_id": self.config.run_id,
            "operator": self.config.operator,
            "mode": self.config.mode.value,
            "timestamp": self.timestamp,
            "status": self.status.value,
            "message": self.message,
            "profile_kind": self.config.profile_kind.value,
            "method_name": self.config.method.get("method_name"),
            "reaction_batch_size": self.config.reaction_batch_size,
            "samples": [
                {
                    "id": sample.id,
                    "well": sample.well,
                    "type": sample.sample_type.value,
                    "input_ng": sample.input_ng,
                    "udi": sample.udi,
                    "control_dilution": sample.control_dilution,
                }
                for sample in self.config.samples
            ],
            "final_sample_ids": self.final_sample_ids,
            "hardware_blockers": [item.to_dict() for item in self.hardware_blockers],
            "provenance": [item.to_dict() for item in self.provenance],
            "gates": [item.to_dict() for item in self.gates],
            "actions": [item.to_dict() for item in self.actions],
            "protocol": [item.to_dict() for item in self.protocol],
            "metrics": self.metrics,
        }


def _records(steps: List[ProtocolStep], mode: RunMode, executed: bool) -> List[ActionRecord]:
    return [
        ActionRecord(
            step_number=step.number,
            name=step.name,
            operation=step.operation,
            simulated=(mode is RunMode.SIMULATION),
            executed=executed,
            command=(step.simulation_command if mode is RunMode.SIMULATION
                     else step.candidate_hardware_command),
            note=step.note,
        )
        for step in steps
    ]


def run(config: RunConfig, metrics: Optional[Dict[str, Any]] = None,
        timestamp: str = "", poor_deck: bool = False,
        failing_sample: Optional[str] = None) -> RunOutcome:
    steps = build_protocol(config)
    provenance = protocol_values(config)

    if config.mode is RunMode.HARDWARE:
        try:
            assert_hardware_ready(provenance)
        except HardwareNotReady as exc:
            return RunOutcome(
                config=config,
                status=RunStatus.BLOCKED,
                message=str(exc),
                timestamp=timestamp,
                protocol=steps,
                provenance=provenance,
                actions=_records(steps, config.mode, executed=False),
                final_sample_ids=[],
            )
        # Defensive: there is intentionally no subprocess executor in this product layer.
        return RunOutcome(
            config=config,
            status=RunStatus.BLOCKED,
            message="hardware guard cleared, but this package emits run cards only; execute under the Pi safety workflow",
            timestamp=timestamp,
            protocol=steps,
            provenance=provenance,
            actions=_records(steps, config.mode, executed=False),
        )

    observed = metrics if metrics is not None else simulate_metrics(
        config, poor_deck=poor_deck, failing_sample=failing_sample
    )
    gate0 = evaluate_liquid_handling(config, observed)
    if gate0.stopped:
        return RunOutcome(
            config=config,
            status=RunStatus.STOPPED,
            message=f"stopped before sample processing: {gate0.message}",
            timestamp=timestamp,
            protocol=steps,
            provenance=provenance,
            gates=[gate0],
            metrics=observed,
            final_sample_ids=[],
        )

    actions = _records(steps, config.mode, executed=True)
    gate1 = evaluate_library_qc(config, observed)
    if gate1.decision is Decision.STOP:
        status = RunStatus.STOPPED
        final_ids: List[str] = []
        message = gate1.message
    else:
        status = RunStatus.COMPLETED
        final_ids = gate1.passing_sample_ids
        message = ("simulation completed; candidate libraries passed the QC handoff" if
                   gate1.decision is Decision.PROCEED else
                   "simulation completed with a QC-qualified subset")
    return RunOutcome(
        config=config,
        status=status,
        message=message,
        timestamp=timestamp,
        protocol=steps,
        provenance=provenance,
        actions=actions,
        gates=[gate0, gate1],
        metrics=observed,
        final_sample_ids=final_ids,
    )

"""Generic methylation-sequencing run-card choreography.

The public package contains stage order and supervised handoffs only. Biological
reagent identities, compositions, volumes, thermal settings, and QC thresholds
come from an external operator profile.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .config import RunConfig


@dataclass(frozen=True)
class ProtocolStep:
    number: int
    name: str
    operation: str
    reaction_before_ul: Optional[float]
    reaction_after_ul: Optional[float]
    components_ul: Dict[str, float] = field(default_factory=dict)
    source: str = "operator method profile"
    note: str = ""
    simulation_command: Optional[str] = None
    candidate_hardware_command: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "number": self.number,
            "name": self.name,
            "operation": self.operation,
            "reaction_before_ul": self.reaction_before_ul,
            "reaction_after_ul": self.reaction_after_ul,
            "components_ul": self.components_ul,
            "source": self.source,
            "note": self.note,
            "simulation_command": self.simulation_command,
            "candidate_hardware_command": self.candidate_hardware_command,
        }


def _star_add(stage: int) -> str:
    return (
        "cd hamilton-star && ./run_on_pi.sh "
        "starlab_live/methylation_seq/methylation_seq_reagent_adds.py "
        f"--mode stage-{stage} --dry --return-tips"
    )


def _cleanup(stage: int) -> str:
    return (
        "cd hamilton-star && ./run_on_pi.sh "
        "starlab_live/methylation_seq/methylation_seq_cleanup.py "
        f"--cleanup cleanup-{stage} --mode all --dry --return-tips"
    )


def _odtc(stage: int) -> str:
    return (
        "cd instrument-integrations && ./run_on_pi.sh "
        "odtc/05_odtc_run_protocol.py "
        f"--program methylation-seq-stage-{stage} --dry"
    )


def build_protocol(config: RunConfig) -> List[ProtocolStep]:
    source = (
        "public synthetic water-only profile"
        if config.method.get("water_only")
        else "external operator method profile"
    )
    rows = [
        ("Operator setup", "operator", None),
        ("Reagent stage 1", "STAR reagent add", _star_add(1)),
        ("Thermal handoff 1", "ODTC", _odtc(1)),
        ("Reagent stage 2", "STAR reagent add", _star_add(2)),
        ("Thermal handoff 2", "ODTC", _odtc(2)),
        ("Reagent stage 3", "STAR reagent add", _star_add(3)),
        ("Reagent stage 4", "STAR reagent add", _star_add(4)),
        ("Thermal handoff 3", "ODTC", _odtc(3)),
        ("Cleanup 1", "STAR cleanup + operator transfer", _cleanup(1)),
        ("Reagent stage 5", "STAR reagent add", _star_add(5)),
        ("Reagent stage 6", "STAR reagent add", _star_add(6)),
        ("Thermal handoff 4", "ODTC", _odtc(4)),
        ("Reagent stage 7", "STAR reagent add", _star_add(7)),
        ("Thermal handoff 5", "ODTC", _odtc(5)),
        ("Cleanup 2", "STAR cleanup + operator transfer", _cleanup(2)),
        ("Reagent stage 8", "STAR reagent add", _star_add(8)),
        ("Thermal handoff 6", "ODTC", _odtc(6)),
        ("Reagent stage 9", "STAR reagent add", _star_add(9)),
        ("Thermal handoff 7", "ODTC", _odtc(7)),
        ("Reagent stage 10", "STAR per-well reagent add", _star_add(10)),
        ("Reagent stage 11", "STAR reagent add", _star_add(11)),
        ("Thermal handoff 8", "ODTC", _odtc(8)),
        ("Cleanup 3", "STAR cleanup + operator transfer", _cleanup(3)),
        ("Operator QC handoff", "operator/instrument handoff", None),
    ]
    note = (
        "Water only; do not load samples or biological reagents."
        if config.method.get("water_only")
        else "Execute only under the approved operator method and site safety workflow."
    )
    return [
        ProtocolStep(
            number=index,
            name=name,
            operation=operation,
            reaction_before_ul=None,
            reaction_after_ul=None,
            source=source,
            note=note,
            simulation_command=command,
            candidate_hardware_command=None,
        )
        for index, (name, operation, command) in enumerate(rows, start=1)
    ]


def qualified_volumes(config: RunConfig) -> List[float]:
    """Volumes that the selected profile requires for site qualification."""
    return sorted({float(value) for value in config.method.get("qualified_volumes_ul", [])})

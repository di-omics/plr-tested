"""
provenance.py - every number in this package carries where it came from.

The house rule across di-omics protocol code is: source every reagent, volume,
temperature, time, and catalog number from the protocol, and mark anything that is
not pinned down. This module makes that rule mechanical instead of a habit. A value
is not a bare float; it is a Sourced value with an origin, so a reviewer (or the
orchestrator, before a real run) can ask "where did this come from" and get an
answer for every single one.

Four origins, in decreasing order of trust:

  TRANSCRIBED  copied from a cited document. Carries the citation. The only origin
               a real sample run should depend on without a second thought.
  TUNABLE      an engineering default the protocol does not pin down. Carries a
               rationale. Safe to run, but it is a choice, not a transcription, and
               it is allowed to be overridden per run.
  CALIBRATE    must be measured on THIS instrument before it is trusted (a plate
               reader gain, a working dye concentration for a given reader's linear
               range). Blocks a hardware run until a measured value replaces it.
  TODO         not known yet. Blocks a hardware run, full stop.

`RunGuard.assert_ready_for_hardware()` walks a set of Sourced values and refuses to
proceed if any CALIBRATE or TODO survives, which is the automated form of "we never
make things up."
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, List, Optional


class Origin(str, Enum):
    TRANSCRIBED = "transcribed"   # from a cited document
    TUNABLE = "tunable"           # engineering default, protocol does not pin it
    CALIBRATE = "calibrate"       # must be measured on this instrument first
    TODO = "todo"                 # unknown, blocks a real run


# Origins that must not survive into a live hardware run.
_BLOCKING = (Origin.CALIBRATE, Origin.TODO)


@dataclass(frozen=True)
class Sourced:
    """A value plus where it came from.

    value      the number (or string, or list) itself.
    origin     one of Origin.
    source     for TRANSCRIBED: the citation. For TUNABLE: the rationale. For
               CALIBRATE/TODO: what has to happen before it is trusted.
    unit       optional unit string, ascii only ("uL", "C", "s", "ng/mL", "nm").
    name       optional short label, used in reports and guard messages.
    """

    value: Any
    origin: Origin
    source: str
    unit: str = ""
    name: str = ""

    def __post_init__(self) -> None:
        if not self.source or not self.source.strip():
            raise ValueError(
                f"Sourced value {self.name or self.value!r} has no source. "
                "Every value must say where it came from; that is the whole point."
            )

    @property
    def blocks_hardware(self) -> bool:
        return self.origin in _BLOCKING

    def as_label(self) -> str:
        u = f" {self.unit}" if self.unit else ""
        return f"{self.value}{u}"

    def __str__(self) -> str:
        return f"{self.name or 'value'}={self.as_label()} [{self.origin.value}: {self.source}]"


def transcribed(value: Any, source: str, unit: str = "", name: str = "") -> Sourced:
    """A value copied from a cited document. `source` is the citation."""
    return Sourced(value=value, origin=Origin.TRANSCRIBED, source=source, unit=unit, name=name)


def tunable(value: Any, rationale: str, unit: str = "", name: str = "") -> Sourced:
    """An engineering default the protocol does not pin down. `rationale` is why."""
    return Sourced(value=value, origin=Origin.TUNABLE, source=rationale, unit=unit, name=name)


def calibrate(placeholder: Any, how: str, unit: str = "", name: str = "") -> Sourced:
    """A value that must be measured on this instrument first. `how` says how."""
    return Sourced(value=placeholder, origin=Origin.CALIBRATE, source=how, unit=unit, name=name)


def todo(how: str, unit: str = "", name: str = "") -> Sourced:
    """A value that is not known yet. `how` says what has to happen to know it."""
    return Sourced(value=None, origin=Origin.TODO, source=how, unit=unit, name=name)


@dataclass
class RunGuard:
    """Collects Sourced values and rules on whether a hardware run may proceed."""

    values: List[Sourced] = field(default_factory=list)

    def add(self, *vals: Sourced) -> None:
        for v in vals:
            if not isinstance(v, Sourced):
                raise TypeError(f"RunGuard only tracks Sourced values, got {type(v)}")
            self.values.append(v)

    def blocking(self) -> List[Sourced]:
        return [v for v in self.values if v.blocks_hardware]

    def assert_ready_for_hardware(self) -> None:
        """Raise if any tracked value still has an unresolved origin.

        Simulation runs skip this on purpose: the point of a simulation is to exercise
        the flow before the calibration values exist. A hardware run calls this first.
        """
        offenders = self.blocking()
        if offenders:
            lines = [f"  - {v}" for v in offenders]
            raise ProvenanceError(
                "Refusing to start a hardware run: "
                f"{len(offenders)} value(s) are not pinned down yet.\n"
                + "\n".join(lines)
                + "\nResolve each (measure it, or transcribe it from the protocol) "
                "or run in simulation mode."
            )

    def summary(self) -> dict:
        counts = {o.value: 0 for o in Origin}
        for v in self.values:
            counts[v.origin.value] += 1
        return counts


class ProvenanceError(RuntimeError):
    """A value that should have been pinned down was not."""

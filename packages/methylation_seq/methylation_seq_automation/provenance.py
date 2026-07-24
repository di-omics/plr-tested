"""Selected-profile provenance and the mechanical live-hardware guard."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, List

from .config import ProfileKind, RunConfig


class Origin(str, Enum):
    OPERATOR = "operator"
    SYNTHETIC = "synthetic"
    CALIBRATE = "calibrate"
    TODO = "todo"


@dataclass(frozen=True)
class Sourced:
    name: str
    value: Any
    unit: str
    origin: Origin
    source: str

    @property
    def blocks_hardware(self) -> bool:
        return self.origin in (Origin.SYNTHETIC, Origin.CALIBRATE, Origin.TODO)

    def to_dict(self) -> dict:
        return {
            "name": self.name, "value": self.value, "unit": self.unit,
            "origin": self.origin.value, "source": self.source,
            "blocks_hardware": self.blocks_hardware,
        }

    def __str__(self) -> str:
        value = "unresolved" if self.value is None else f"{self.value} {self.unit}".strip()
        return f"{self.name}: {value} [{self.origin.value}] {self.source}"


class HardwareNotReady(RuntimeError):
    pass


def protocol_values(config: RunConfig) -> List[Sourced]:
    values = [
        Sourced(
            "method profile",
            config.method.get("method_name"),
            "",
            Origin.SYNTHETIC if config.profile_kind is ProfileKind.SYNTHETIC_WATER else Origin.OPERATOR,
            "public water-only profile" if config.profile_kind is ProfileKind.SYNTHETIC_WATER else "external operator profile",
        ),
        Sourced(
            "site liquid-handling qualification",
            None,
            "",
            Origin.CALIBRATE,
            "qualify every operator-profile volume on the destination instrument",
        ),
        Sourced(
            "supervised hardware execution",
            None,
            "",
            Origin.TODO,
            "the package emits reviewed run cards and does not execute hardware",
        ),
    ]
    return values


def blocking(values: Iterable[Sourced]) -> List[Sourced]:
    return [value for value in values if value.blocks_hardware]


def assert_hardware_ready(values: Iterable[Sourced]) -> None:
    offenders = blocking(values)
    if offenders:
        details = "\n".join(f"  - {item}" for item in offenders)
        raise HardwareNotReady(
            "Live methylation-sequencing execution is blocked until the selected "
            "operator profile and site qualifications are approved:\n" + details
        )

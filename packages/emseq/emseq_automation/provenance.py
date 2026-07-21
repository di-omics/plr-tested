"""Sourced values and the mechanical live-hardware readiness guard."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, List

from .config import RunConfig


class Origin(str, Enum):
    TRANSCRIBED = "transcribed"
    TUNABLE = "tunable"
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
        return self.origin in (Origin.CALIBRATE, Origin.TODO)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "value": self.value,
            "unit": self.unit,
            "origin": self.origin.value,
            "source": self.source,
            "blocks_hardware": self.blocks_hardware,
        }

    def __str__(self) -> str:
        value = "unresolved" if self.value is None else f"{self.value} {self.unit}".strip()
        return f"{self.name}: {value} [{self.origin.value}] {self.source}"


class HardwareNotReady(RuntimeError):
    pass


def protocol_values(config: RunConfig) -> List[Sourced]:
    manual = "NEB #M7634 v3.0 (3/26), Section 3, UltraShear coupled with EM-seq v2"
    values = [
        Sourced("input range", "0.1-200", "ng", Origin.TRANSCRIBED, manual),
        Sourced("UltraShear time", config.shear_minutes, "min at 37 C", Origin.TUNABLE,
                "M7634 3.1.6 permits 25-35 min; manifest records the selected value"),
        Sourced("PCR cycles", config.pcr_cycles, "cycles", Origin.TUNABLE,
                "M7634 3.9.3 is input-dependent (4-14); manifest records the selected value"),
        Sourced("high-volume dispense geometry", None, "", Origin.CALIBRATE,
                "tune EM-seq 31 and 45 uL additions into already-full wells on the STAR"),
        Sourced("on-deck 10x mixing", None, "", Origin.TODO,
                "implement and dye-test the mixing required after reagent additions"),
        Sourced("SPRI timing and clear-eluate transfer", None, "", Origin.TODO,
                "automate 5 min incubations, air-dry windows, and transfer into a fresh column"),
        Sourced("ODTC child location", None, "", Origin.CALIBRATE,
                "ODTC_CHILD_LOCATION_IS_MEASURED is false; measure and confirm the nest coordinate"),
        Sourced("EM-seq ODTC programs", None, "", Origin.CALIBRATE,
                "run all eight emseq-* programs on the physical ODTC and record setpoint holds"),
        Sourced("ligation lid-off translation", 50, "C", Origin.CALIBRATE,
                "the backend cannot disable the lid; validate the current 50 C substitute"),
        Sourced("post-denaturation cooling", 4, "C block hold", Origin.CALIBRATE,
                "validate ODTC block cooling against the manual's immediate ice-block cool"),
    ]
    if config.low_input:
        values.append(Sourced("low-input carrier DNA addition", None, "", Origin.TODO,
                              "add and validate the 1 uL carrier step after 27 uL elution"))
    return values


def blocking(values: Iterable[Sourced]) -> List[Sourced]:
    return [value for value in values if value.blocks_hardware]


def assert_hardware_ready(values: Iterable[Sourced]) -> None:
    offenders = blocking(values)
    if offenders:
        details = "\n".join(f"  - {item}" for item in offenders)
        raise HardwareNotReady(
            "Live EM-seq execution is blocked: the implementation is written/simulated, "
            "not hardware-validated. Resolve these items first:\n" + details
        )


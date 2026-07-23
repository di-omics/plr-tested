"""
instruments/odtc.py - the Inheco ODTC (on-deck thermal cycler) adapter.

Records each thermal program and, in hardware mode, resolves it to the ODTC run script.
The thermal truth - the temperatures, times, and cycle counts - lives in
instrument-integrations/odtc/odtc_protocols.py, transcribed from authorized WGS/WGA workflow source and the
targeted PCR protocol and validated on the instrument. This adapter references those
programs by name; it does not restate their contents, so there is one source of thermal
truth, not two that can drift.

Two on-instrument findings carried over as notes on the relevant programs:
  - A cycling method needs a PreMethod pre-warm first; run_cycling_method() supplies it
    and 05_odtc_run_protocol.py uses that. This adapter's resolved command uses it too.
  - targeted-pcr-round1's 98 C denaturation grazes the ODTC's 99 C ceiling on the ramp-in and
    logs ~3 out-of-spec warnings per cycle. The run completes and holds tightly; the
    warning is documented, not silenced, because 98 C is the protocol value.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from ..config import RunMode
from .base import Adapter

_ODTC_DIR = "instrument-integrations"


@dataclass(frozen=True)
class ProgramRef:
    name: str
    source: str
    approx_minutes: Optional[float] = None
    note: str = ""


# The programs this package uses, referenced by the odtc_protocols.py registry name.
# Values here are citations and run-time estimates, not the thermal profiles themselves.
KNOWN_PROGRAMS: Dict[str, ProgramRef] = {
    "wga": ProgramRef(
        "wga", "odtc_protocols.py WGA (authorized WGS/WGA workflow source Table 1); lid 70 C, 12 uL",
        approx_minutes=156.0, note="whole-genome sequencing DNA amplification; ~2.6 h hold",
    ),
    "targeted-pcr-round1": ProgramRef(
        "targeted-pcr-round1", "odtc_protocols.py targeted-pcr-round1 (Targeted PCR Library Preparation PCR1)",
        approx_minutes=37.0,
        note="30 cycles; 98 C denat grazes the 99 C ceiling (documented warnings)",
    ),
    "targeted-pcr-round2": ProgramRef(
        "targeted-pcr-round2", "odtc_protocols.py targeted-pcr-round2 (Targeted PCR Library Preparation PCR2)",
        approx_minutes=14.0, note="8 cycles by default (protocol range 8 to 10)",
    ),
}


class OdtcAdapter(Adapter):
    instrument = "Inheco ODTC"

    def run_program(self, program: str, anneal_c: Optional[float] = None,
                    num_cycles: Optional[int] = None) -> ProgramRef:
        """Run a named thermal program. Validates the name against the known registry."""
        if program not in KNOWN_PROGRAMS:
            known = ", ".join(sorted(KNOWN_PROGRAMS))
            raise ValueError(
                f"unknown ODTC program {program!r}; odtc_protocols.py defines: {known}"
            )
        ref = KNOWN_PROGRAMS[program]
        args = f"--program {program} --ip $ODTC_IP --confirm i-am-watching"
        if anneal_c is not None:
            args += f"  # anneal_c override {anneal_c} C requires a custom program call"
        if num_cycles is not None:
            args += f"  # num_cycles override {num_cycles}"
        cmd = f"cd {_ODTC_DIR} && ./run_on_pi.sh odtc/05_odtc_run_protocol.py {args}"
        self._record(
            "run_program",
            {"program": program, "anneal_c": anneal_c, "num_cycles": num_cycles,
             "source": ref.source, "approx_minutes": ref.approx_minutes},
            resolved_command=cmd,
            note=ref.note,
        )
        return ref

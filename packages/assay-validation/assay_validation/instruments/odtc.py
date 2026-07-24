"""
instruments/odtc.py - the Inheco ODTC (on-deck thermal cycler) adapter.

Records each operator-supplied thermal profile and, in hardware mode, resolves it to
the ODTC runner. Temperatures, times, cycle counts, lid settings, and reaction volume
live only in the operator-owned JSON profile.

Two on-instrument findings carried over as notes on the relevant programs:
  - A cycling method needs a PreMethod pre-warm first; run_cycling_method() supplies it
    and 05_odtc_run_protocol.py uses that. This adapter's resolved command uses it too.
"""

from __future__ import annotations

from dataclasses import dataclass
import shlex
from typing import Optional

from ..config import RunMode
from .base import Adapter

_ODTC_DIR = "instrument-integrations"


@dataclass(frozen=True)
class ProgramRef:
    name: str
    source: str
    approx_minutes: Optional[float] = None
    note: str = ""


class OdtcAdapter(Adapter):
    instrument = "Inheco ODTC"

    def run_program(self, profile: str) -> ProgramRef:
        """Run one operator-owned JSON method profile."""
        ref = ProgramRef(
            name=profile,
            source="operator-owned ODTC JSON method profile",
            note="biological method values are not stored in the public package",
        )
        args = (
            f"--operator-profile {shlex.quote(profile)} --ip $ODTC_IP "
            "--confirm i-am-watching"
        )
        cmd = f"cd {_ODTC_DIR} && ./run_on_pi.sh odtc/05_odtc_run_protocol.py {args}"
        self._record(
            "run_program",
            {"operator_profile": profile, "source": ref.source},
            resolved_command=cmd,
            note=ref.note,
        )
        return ref

"""Inheco ODTC adapter for explicit method profiles.

Public generic registry names are short synthetic water-only hardware exercises.
Biological thermal values are supplied in an operator-owned JSON profile outside
this repository and passed to ``05_odtc_run_protocol.py`` at run time.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..config import ProfileKind, RunMode
from .base import Adapter

_ODTC_DIR = "instrument-integrations"
_PUBLIC_WATER_PROGRAMS = {
    "wgs_prep",
    "pcr-enrichment-round1",
    "pcr-enrichment-round2",
}


@dataclass(frozen=True)
class ProgramRef:
    name: str
    source: str
    approx_minutes: Optional[float] = None
    note: str = ""


class OdtcAdapter(Adapter):
    instrument = "Inheco ODTC"

    def run_profile(self, profile: str, profile_kind: ProfileKind) -> ProgramRef:
        """Record a synthetic registry program or operator-owned JSON profile."""
        if profile_kind is ProfileKind.SYNTHETIC_WATER:
            if profile not in _PUBLIC_WATER_PROGRAMS:
                known = ", ".join(sorted(_PUBLIC_WATER_PROGRAMS))
                raise ValueError(
                    f"synthetic ODTC profile {profile!r} is not registered; use: {known}"
                )
            ref = ProgramRef(
                name=profile,
                source="public synthetic water-only ODTC registry",
                approx_minutes=3.0,
                note="water-only motion profile; do not load samples or reagents",
            )
            args = f"--program {profile} --water-only"
        else:
            profile_path = Path(profile).expanduser()
            ref = ProgramRef(
                name=profile_path.stem or "operator-method",
                source=f"operator-owned ODTC profile: {profile_path}",
                note="biological values supplied by the operator at run time",
            )
            args = f"--operator-profile {shlex.quote(str(profile_path))}"

        command = (
            f"cd {_ODTC_DIR} && ./run_on_pi.sh odtc/05_odtc_run_protocol.py "
            f"{args} --ip $ODTC_IP --confirm i-am-watching"
        )
        self._record(
            "run_profile",
            {
                "profile": profile,
                "profile_kind": profile_kind.value,
                "source": ref.source,
                "approx_minutes": ref.approx_minutes,
            },
            resolved_command=command,
            note=ref.note,
        )
        return ref

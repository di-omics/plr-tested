"""
instruments/tecan.py - the Tecan Infinite 200 PRO adapter.

The QC endpoint. It reads a plate; it does not move liquid or heat. In simulation it
returns per-well signals by adding a small reader noise to the physical signal the stage
modeled, so the dominant variance in a Gate 0 read is the dispense, not the reader - the
CV gate reflects the STAR, which is the whole point. In hardware mode it resolves to a
read command and either loads a results file the operator captured on the Pi or raises
AwaitingData, which is how a remote run pauses for the read and resumes with the data.

Nothing here has been run on a reader yet (see instrument-integrations/tecan-infinite/).
The USB identity, the wavelength ranges, and the read-script names are from that
integration; the reader-quirk workarounds that a live run will surface belong there,
not here.
"""

from __future__ import annotations

import json
import os
from typing import Dict, Optional

from ..config import RunMode
from ..simulation import det_rng
from .base import Adapter, AwaitingData

_TECAN_DIR = "instrument-integrations"

# Reader measurement noise. Small on purpose: the reader should not be the thing a
# liquid-handling CV gate measures.
_READER_NOISE_CV_PERCENT = 0.5


class TecanAdapter(Adapter):
    instrument = "Tecan Infinite 200 PRO"

    def read(self, run_id: str, read_label: str, well_signals_truth: Dict[str, float],
             ex_nm: float, em_nm: float, gain: Optional[float] = None,
             results_file: Optional[str] = None) -> Dict[str, float]:
        """Read fluorescence for a set of wells.

        well_signals_truth is the modeled physical signal per well (simulation only);
        the reader adds noise on top. In hardware mode the truth is unknown and unused;
        a results_file (JSON: {well: signal}) supplies the measured values, or the read
        pauses.
        """
        wells = sorted(well_signals_truth) if well_signals_truth else []
        cmd = (
            f"cd {_TECAN_DIR} && ./run_on_pi.sh tecan-infinite/04_tecan_read_absorbance.py "
            f"# fluorescence read '{read_label}': ex {ex_nm} nm, em {em_nm} nm, "
            f"gain {'locked' if gain else 'autoscale-once'}; wells {wells or 'all'}"
        )
        rec = self._record(
            "read",
            {"read_label": read_label, "ex_nm": ex_nm, "em_nm": em_nm, "gain": gain,
             "n_wells": len(wells)},
            resolved_command=cmd,
            note=f"Tecan {read_label} read",
        )

        if self.mode is RunMode.SIMULATION:
            out = {}
            rng = det_rng(run_id, "tecan_read", read_label)
            for well in wells:
                truth = well_signals_truth[well]
                sigma = (_READER_NOISE_CV_PERCENT / 100.0) * max(truth, 1.0)
                out[well] = max(0.0, rng.gauss(truth, sigma))
            return out

        # Hardware: use captured data if present, else emit the run card and pause.
        if results_file and os.path.exists(results_file):
            data = json.loads(open(results_file, "r", encoding="utf-8").read())
            rec.note += f" (loaded from {results_file})"
            return {str(k): float(v) for k, v in data.items()}
        raise AwaitingData(
            f"Read '{read_label}' has no data. Run this on the Pi:\n  {cmd}\n"
            f"then re-run with the captured results file (JSON: {{well: signal}})."
        )

"""
instruments/imager.py - the spot-counting imager (Cytation / CTL ImmunoSpot / Mabtech IRIS).

The readout. It images the dried membrane and returns a spot-forming-unit (SFU) count per
well; it moves no liquid. In simulation it returns the modeled per-well counts the readout
stage computed, plus a small counting noise, so the flow can run end to end. In hardware it
resolves to a count command and either loads a counts file the operator captured or raises
AwaitingData - which is how a plate that develops overnight at a partner site pauses the run
and resumes, asynchronously, once the imager has counted it.

Counting is not neutral: spot size/intensity gates, a saturation ceiling (too-numerous-to-
count wells), and background subtraction are all imager-software settings, and they are a
real site-drift source. This adapter records the settings it was told to use so two sites'
counts are comparable; the settings themselves are site profile / acceptance values, not
invented here. No imager has been run from this package yet (see the README status).
"""

from __future__ import annotations

import json
import os
from typing import Dict, Optional

from ..config import RunMode
from ..simulation import det_rng
from .base import Adapter, AwaitingData

_IMAGER_DIR = "instrument-integrations/imager"

# Counting noise: small, because the count itself is the measurement, not the imager's jitter.
_COUNT_NOISE_CV_PERCENT = 3.0


class ImagerAdapter(Adapter):
    instrument = "spot imager"

    def count(self, run_id: str, plate_label: str, well_sfu_truth: Dict[str, int],
              saturation_sfu: float, background_offset_sfu: float = 0.0,
              counts_file: Optional[str] = None) -> Dict[str, int]:
        """Count spots for a set of wells.

        well_sfu_truth is the modeled count per well (simulation only); the imager adds a
        small counting noise and the site background offset. In hardware the truth is
        unused; a counts_file (JSON: {well: sfu}) supplies the measured counts, or the read
        pauses with a run card.
        """
        wells = sorted(well_sfu_truth) if well_sfu_truth else []
        cmd = (
            f"cd {_IMAGER_DIR} && ./run_on_pi.sh count_plate.py "
            f"# NOT YET BUILT: count '{plate_label}', saturation ceiling {saturation_sfu} SFU, "
            f"background offset {background_offset_sfu} SFU; wells {wells or 'all'}"
        )
        rec = self._record(
            "count",
            {"plate_label": plate_label, "saturation_sfu": saturation_sfu,
             "background_offset_sfu": background_offset_sfu, "n_wells": len(wells)},
            resolved_command=cmd,
            note=f"imager count '{plate_label}'",
        )

        if self.mode is RunMode.SIMULATION:
            out: Dict[str, int] = {}
            rng = det_rng(run_id, "imager_count", plate_label)
            for well in wells:
                truth = well_sfu_truth[well]
                sigma = (_COUNT_NOISE_CV_PERCENT / 100.0) * max(truth, 1.0)
                counted = rng.gauss(truth, sigma) + background_offset_sfu
                out[well] = max(0, round(counted))
            return out

        # Hardware: use captured counts if present, else emit the run card and pause.
        if counts_file and os.path.exists(counts_file):
            data = json.loads(open(counts_file, "r", encoding="utf-8").read())
            rec.note += f" (loaded from {counts_file})"
            return {str(k): int(v) for k, v in data.items()}
        raise AwaitingData(
            f"Count '{plate_label}' has no data. Run this on the Pi:\n  {cmd}\n"
            f"then re-run with the captured counts file (JSON: {{well: sfu}})."
        )

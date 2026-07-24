"""
simulation.py - every made-up number in the package lives here, on purpose.

The house rule is that we do not invent values. Simulation is the one place invented
values are not only allowed but required: to exercise the whole flow - dispense, QC
read, gate, stop-or-continue, report - before a single sample or a single instrument
exists. Quarantining the synthetic models in one file named simulation.py keeps the
rule honest. If a number in a report is not traceable to a protocol or a measurement,
it came from here, and every simulated ActionRecord and reading is flagged simulated so
it can never be mistaken for data.

Two more properties matter:
  - Deterministic. The pseudo-randomness is seeded from the run id and a label, via a
    hash, so the same manifest simulates to the same numbers every time. Tests depend on
    this, and so does anyone trying to reproduce a demo.
  - Plausible, not flattering. The simulated deck is good but not perfect: its dispense
    CV rises at low volume, so a qualification that includes 2 uL can actually be tight
    or actually fail depending on the modeled quality, which is the point of having a
    gate at all.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from typing import List

from .config import Sample, SampleType


def det_rng(*parts: object) -> random.Random:
    """A deterministic RNG seeded from the string form of its arguments.

    Python's built-in hash() is salted per process, so it is not reproducible across
    runs; sha256 of the joined parts is. Same inputs -> same stream, every time.
    """
    key = "|".join(str(p) for p in parts).encode("utf-8")
    seed = int.from_bytes(hashlib.sha256(key).digest()[:8], "big")
    return random.Random(seed)


# ---------------------------------------------------------------------------
# Simulated liquid handler precision
# ---------------------------------------------------------------------------

@dataclass
class DeckQuality:
    """A model of a STAR's dispense precision as a function of volume.

    true_cv(V) = floor_cv + low_volume_term / V, capped. A well-tuned deck has a low
    floor and a small low-volume term; a poorly tuned one fails the small volumes first,
    which is exactly where single-cell WGS preparation lives, so the model puts the stress there.
    """

    floor_cv_percent: float = 1.5
    low_volume_coeff: float = 4.0     # percent-uL; adds low_volume_coeff/V percent
    cap_cv_percent: float = 25.0

    def true_cv_percent(self, volume_ul: float) -> float:
        cv = self.floor_cv_percent + self.low_volume_coeff / max(volume_ul, 0.5)
        return min(cv, self.cap_cv_percent)


# A deck good enough to pass at and above a few uL, tight across PCR enrichment/WGS preparation
# volumes actually sit. Swap for a worse one to demonstrate a Gate 0 stop.
WELL_TUNED_DECK = DeckQuality(floor_cv_percent=1.5, low_volume_coeff=4.0)
POORLY_TUNED_DECK = DeckQuality(floor_cv_percent=3.0, low_volume_coeff=12.0)


def simulate_dispensed_volumes(run_id: str, volume_ul: float, n_replicates: int,
                               deck: DeckQuality) -> List[float]:
    """N replicate delivered volumes for a target, drawn around the model's true CV."""
    rng = det_rng(run_id, "dispense", volume_ul, n_replicates)
    cv = deck.true_cv_percent(volume_ul) / 100.0
    sigma = cv * volume_ul
    return [max(0.0, rng.gauss(volume_ul, sigma)) for _ in range(n_replicates)]


# Simulated reader window and Rhodamine response, in arbitrary fluorescence units. The
# working concentration and gain that produce these are exactly what a real Gate 0
# calibration read has to establish on the instrument (CALIBRATE in rhodamine_b.py); the
# simulation just picks self-consistent values so the flow can run end to end.
SIM_READER_FLOOR = 200.0
SIM_READER_CEILING = 60000.0
SIM_WORKING_CONC_UM = 1.0
SIM_SIGNAL_PER_UM_FULL = 45000.0     # a 1 uM full-fill well reads ~75% of ceiling


def rhodamine_signal(delivered_volume_ul: float, working_conc_um: float,
                     common_read_volume_ul: float, signal_per_um_full: float,
                     reader_floor: float) -> float:
    """Fluorescence of a topped-up Rhodamine well.

    Signal is proportional to dye mass over read volume, i.e. to delivered volume, plus a
    small reader floor. This is the same linear model rhodamine_working_concentration
    uses to plan the concentration, so a simulated read is consistent with the plan.
    """
    fill_fraction = delivered_volume_ul / common_read_volume_ul
    return reader_floor + signal_per_um_full * working_conc_um * fill_fraction


# ---------------------------------------------------------------------------
# Simulated fluorescent dsDNA assay reads
# ---------------------------------------------------------------------------

@dataclass
class FluorescentDsDNAAssayModel:
    """A linear fluorescent dsDNA assay response: signal = blank + slope * concentration(ng/mL)."""

    blank: float = 50.0
    slope: float = 5.0     # signal per ng/mL

    def signal(self, concentration_ng_per_ml: float, rng: random.Random,
               noise_cv_percent: float = 2.0) -> float:
        clean = self.blank + self.slope * concentration_ng_per_ml
        sigma = (noise_cv_percent / 100.0) * clean
        return max(0.0, rng.gauss(clean, sigma))


FLUORESCENT_DSDNA_MODEL = FluorescentDsDNAAssayModel()


def simulate_sample_concentration_ng_per_ml(
    run_id: str,
    checkpoint: str,
    sample: Sample,
    passing_center_ng_per_ml: float,
    failing_center_ng_per_ml: float,
    passing_half_width_ng_per_ml: float,
    failing_half_width_ng_per_ml: float,
) -> float:
    """Generate a deterministic concentration around caller-supplied gate-relative centers.

    The QC stage derives the centers and bounded half-widths from the active operator
    method and acceptance criteria. Keeping the helper gate-agnostic prevents
    simulation.py from embedding an assay-specific yield scale or loading window.
    """
    if sample.sample_type is SampleType.NO_TEMPLATE:
        center = failing_center_ng_per_ml
        half_width = failing_half_width_ng_per_ml
    else:
        center = passing_center_ng_per_ml
        half_width = passing_half_width_ng_per_ml
    if center < 0 or half_width < 0 or half_width > center:
        raise ValueError(
            "simulated concentration centers and bounded half-widths must be nonnegative"
        )
    rng = det_rng(run_id, checkpoint, sample.id, sample.well)
    return rng.uniform(center - half_width, center + half_width)

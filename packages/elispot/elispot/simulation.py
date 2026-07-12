"""
simulation.py - every made-up number in the package lives here, on purpose.

The house rule is that we do not invent values. Simulation is the one place invented values
are not only allowed but required: to exercise the whole flow - dispense, wash, develop,
count, gate, stop-or-continue, report - before a single cell or a single instrument exists.
Quarantining the synthetic models in one file named simulation.py keeps the rule honest. If
a number in a report is not traceable to a protocol or a measurement, it came from here, and
every simulated action and reading is flagged simulated so it can never be mistaken for data.

Two properties matter:
  - Deterministic. The pseudo-randomness is seeded from the run id and a label via a hash,
    so the same manifest simulates to the same numbers every time. Tests depend on this, and
    so does anyone reproducing a demo.
  - Plausible, not flattering. The default washer is good but not perfect; the default plate
    has real background; and only some antigens respond. The scenario knobs
    (HIGH_BACKGROUND_PLATE, DEAD_CELLS_PLATE, POOR_WASHER) exist so a demo can show a gate
    doing its job, which is the whole point of having gates.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from typing import List

from .config import Well, WellRole


def det_rng(*parts: object) -> random.Random:
    """A deterministic RNG seeded from the string form of its arguments.

    Python's built-in hash() is salted per process, so it is not reproducible across runs;
    sha256 of the joined parts is. Same inputs -> same stream, every time.
    """
    key = "|".join(str(p) for p in parts).encode("utf-8")
    seed = int.from_bytes(hashlib.sha256(key).digest()[:8], "big")
    return random.Random(seed)


# ---------------------------------------------------------------------------
# Gate 0: washer / liquid-handler precision
# ---------------------------------------------------------------------------

@dataclass
class WasherQuality:
    """A model of dispense precision and aspiration completeness as functions of volume.

    dispense CV rises at low volume (floor + coeff/V, capped), the same shape a real
    pipettor shows. residual is the volume left in a well after an aspiration cycle: a good
    washer draws a well down to a small, uniform residual; a poor one leaves more and less
    evenly, which is exactly what carries reagent forward and prints as background.
    """

    floor_cv_percent: float = 1.5
    low_volume_coeff: float = 4.0        # percent-uL; adds low_volume_coeff/V percent
    cap_cv_percent: float = 25.0
    residual_mean_ul: float = 4.0        # mean volume left after aspiration
    residual_cv_percent: float = 20.0    # spread of that residual across wells

    def true_cv_percent(self, volume_ul: float) -> float:
        cv = self.floor_cv_percent + self.low_volume_coeff / max(volume_ul, 0.5)
        return min(cv, self.cap_cv_percent)


WELL_TUNED_WASHER = WasherQuality()
POOR_WASHER = WasherQuality(
    floor_cv_percent=3.0, low_volume_coeff=12.0, residual_mean_ul=14.0, residual_cv_percent=45.0,
)


def simulate_dispensed_volumes(run_id: str, volume_ul: float, n_replicates: int,
                               washer: WasherQuality) -> List[float]:
    """N replicate delivered volumes for a target, drawn around the model's true CV."""
    rng = det_rng(run_id, "dispense", volume_ul, n_replicates)
    cv = washer.true_cv_percent(volume_ul) / 100.0
    sigma = cv * volume_ul
    return [max(0.0, rng.gauss(volume_ul, sigma)) for _ in range(n_replicates)]


def simulate_residual_volumes(run_id: str, n_wells: int, washer: WasherQuality) -> List[float]:
    """Volume left in each well after one aspiration cycle."""
    rng = det_rng(run_id, "residual", n_wells)
    sigma = (washer.residual_cv_percent / 100.0) * washer.residual_mean_ul
    return [max(0.0, rng.gauss(washer.residual_mean_ul, sigma)) for _ in range(n_wells)]


# Simulated reader window and Rhodamine response, in arbitrary fluorescence units. The
# working concentration and gain that produce these are exactly what a real Gate 0
# calibration read has to establish (CALIBRATE in rhodamine_b.py); the simulation just picks
# self-consistent values so the flow can run end to end.
SIM_READER_FLOOR = 200.0
SIM_READER_CEILING = 60000.0
SIM_WORKING_CONC_UM = 1.0
SIM_SIGNAL_PER_UM_FULL = 45000.0


def rhodamine_signal(delivered_volume_ul: float, working_conc_um: float,
                     common_read_volume_ul: float, signal_per_um_full: float,
                     reader_floor: float) -> float:
    """Fluorescence of a topped-up Rhodamine well: proportional to delivered volume."""
    fill_fraction = delivered_volume_ul / common_read_volume_ul
    return reader_floor + signal_per_um_full * working_conc_um * fill_fraction


# ---------------------------------------------------------------------------
# Gate 1: membrane pre-wet uniformity (a plate-lot property, not the instrument's)
# ---------------------------------------------------------------------------

@dataclass
class PlateLotQuality:
    """How evenly this plate lot's PVDF membrane wets out under the ethanol pre-wet."""

    wetout_cv_percent: float = 4.0


GOOD_PLATE_LOT = PlateLotQuality(wetout_cv_percent=4.0)
UNEVEN_PLATE_LOT = PlateLotQuality(wetout_cv_percent=12.0)


def simulate_prewet_wetout(run_id: str, n_wells: int, lot: PlateLotQuality) -> List[float]:
    """A per-well wet-out metric (arbitrary units around 1.0) whose CV is the uniformity."""
    rng = det_rng(run_id, "prewet", n_wells)
    sigma = lot.wetout_cv_percent / 100.0
    return [max(0.0, rng.gauss(1.0, sigma)) for _ in range(n_wells)]


# ---------------------------------------------------------------------------
# Gate 2: spot-forming units, by well role and antigen response
# ---------------------------------------------------------------------------

@dataclass
class PlateBiology:
    """The biological scenario the plate simulates.

    background_mean_sfu is the medium-only background that the negative control reads and
    the test wells sit on top of; pos_ctrl_center is where the mitogen well lands (near
    saturation on a live plate); pos_ctrl_alive False models dead cells or a broken
    detection chain, so the positive control fails and the plate is void.
    """

    background_mean_sfu: float = 8.0
    background_cv_percent: float = 35.0
    pos_ctrl_center_sfu: float = 520.0
    pos_ctrl_alive: bool = True
    responder_net_sfu: float = 140.0     # net spots a responding antigen adds over background
    reference_cells: int = 250_000       # response scales with cells relative to this


GOOD_PLATE = PlateBiology()
HIGH_BACKGROUND_PLATE = PlateBiology(background_mean_sfu=45.0, background_cv_percent=40.0)
DEAD_CELLS_PLATE = PlateBiology(pos_ctrl_alive=False)


def antigen_is_responder(antigen: str) -> bool:
    """A stable per-antigen responder flag, so a demo plate shows both a hit and a miss.

    Simulation only: on a real plate whether an antigen responds is the measurement, not a
    property we get to assign. Here it is a deterministic hash so the same antigen behaves
    the same way across runs.
    """
    h = int.from_bytes(hashlib.sha256(antigen.encode("utf-8")).digest()[:2], "big")
    return h % 2 == 0


def _background(run_id: str, well: str, bio: PlateBiology, rng: random.Random) -> float:
    sigma = (bio.background_cv_percent / 100.0) * bio.background_mean_sfu
    return max(0.0, rng.gauss(bio.background_mean_sfu, sigma))


def simulate_well_sfu(run_id: str, well: Well, cells_per_well: int, bio: PlateBiology) -> int:
    """Spot-forming units counted in one well, by role, as a non-negative integer.

    Spots are counts, so the return is rounded to an integer. The negative control reads
    background; the mitogen positive control reads near saturation on a live plate and near
    background on a dead one; a responding test antigen adds responder_net_sfu (scaled by
    cell number) on top of background, a non-responder adds almost nothing; a no-cell blank
    reads a few reagent specks.
    """
    rng = det_rng(run_id, "sfu", well.address, well.role.value, well.antigen)

    if well.role is WellRole.BLANK:
        return max(0, round(rng.gauss(2.0, 1.5)))

    bg = _background(run_id, well.address, bio, rng)

    if well.role is WellRole.NEGATIVE_CONTROL:
        return max(0, round(bg))

    if well.role is WellRole.POSITIVE_CONTROL:
        if not bio.pos_ctrl_alive:
            return max(0, round(bg))
        sigma = 0.12 * bio.pos_ctrl_center_sfu
        return max(0, round(rng.gauss(bio.pos_ctrl_center_sfu, sigma)))

    # TEST well.
    scale = cells_per_well / bio.reference_cells if bio.reference_cells else 1.0
    if antigen_is_responder(well.antigen):
        net = rng.gauss(bio.responder_net_sfu * scale, 0.18 * bio.responder_net_sfu * scale)
    else:
        net = rng.gauss(2.0, 1.5)
    return max(0, round(bg + max(0.0, net)))

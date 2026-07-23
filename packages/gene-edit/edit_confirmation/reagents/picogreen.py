"""
picogreen.py - dsDNA quantitation for the two yield gates.

The same assay runs at two checkpoints: after PTA (does each cell have enough amplified
genome to be worth sequencing) and after targeted PCR (is each library in the loading
window). Quant-iT PicoGreen is a dsDNA-selective fluorophore, so it reports
double-stranded yield and ignores the single-stranded and primer background that a
UV A260 would count, which is why it is the right quant for both an amplified genome
and a cleaned library.

The reader is the same Tecan Infinite 200 PRO used for Gate 0, in fluorescence mode at
a different wavelength pair. A standard curve of known dsDNA (Lambda) is read on the
same plate as the samples; qc_math.linear_fit turns it into a line and
qc_math.quantitate reads each sample's concentration off it. The curve's R-squared is
itself gated (a curve that did not come out straight means the assay was mispipetted,
and no sample read off it is trustworthy).

Assay wavelengths are the kit's and are cited. The exact kit catalog number, the
standard concentrations, and the sample dilution are the operator's to confirm against
the insert for their lot, so they are tunable/verify, not transcribed as gospel.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence

from ..provenance import Sourced, todo, transcribed, tunable
from ..qc_math import LineFit, QuantResult, linear_fit, mass_ng, quantitate


# Kit optics. 480/520 is the PicoGreen excitation/emission pair, cited.
EX_NM = transcribed(
    480, "Quant-iT PicoGreen dsDNA assay, excitation maximum (Thermo Fisher kit insert)",
    unit="nm", name="picogreen_ex",
)
EM_NM = transcribed(
    520, "Quant-iT PicoGreen dsDNA assay, emission maximum (Thermo Fisher kit insert)",
    unit="nm", name="picogreen_em",
)
KIT_CATALOG = todo(
    "confirm the kit catalog number and lot against the box before a real assay "
    "(Quant-iT PicoGreen dsDNA Reagent and Kit family)",
    name="picogreen_kit_catalog",
)

# A high-range standard series in ng/mL. The kit supports high (about 1 ng/mL to
# 1000 ng/mL) and low (about 25 pg/mL to 25 ng/mL) ranges; whole-genome amplification product and cleaned
# libraries sit in the high range after the standard sample dilution. These points are a
# sensible default series, to be confirmed against the insert.
HIGH_RANGE_STANDARDS_NG_PER_ML = tunable(
    [0.0, 1.0, 10.0, 100.0, 250.0, 500.0, 1000.0],
    "high-range Lambda DNA standard series (ng/mL); confirm against the kit insert",
    unit="ng/mL", name="high_range_standards",
)


@dataclass(frozen=True)
class StandardCurve:
    fit: LineFit
    concentrations: List[float]
    signals: List[float]
    unit: str = "ng/mL"

    @property
    def signal_min(self) -> float:
        return min(self.signals)

    @property
    def signal_max(self) -> float:
        return max(self.signals)


def build_standard_curve(concentrations: Sequence[float], signals: Sequence[float],
                         blank: Optional[float] = None, unit: str = "ng/mL") -> StandardCurve:
    """Fit a PicoGreen standard curve.

    If blank is None, the lowest-concentration standard's signal is used as the blank
    and subtracted from every standard, which is how a PicoGreen curve is built. The fit
    is then over blank-subtracted signals, so a sample read off it must also be
    blank-subtracted (quantitate() does this).
    """
    concentrations = list(concentrations)
    signals = list(signals)
    if blank is None:
        blank = min(signals)
    net = [s - blank for s in signals]
    fit = linear_fit(concentrations, net)
    return StandardCurve(fit=fit, concentrations=concentrations, signals=net, unit=unit)


@dataclass(frozen=True)
class WellQuant:
    sample_id: str
    well: str
    concentration_ng_per_ml: float
    mass_ng: float
    in_curve_range: bool
    dilution_factor: float


def quantitate_well(curve: StandardCurve, sample_id: str, well: str,
                    signal: float, assay_volume_ul: float,
                    dilution_factor: float = 1.0, blank: float = 0.0) -> WellQuant:
    """Read one well's dsDNA concentration and total mass off the curve.

    dilution_factor accounts for diluting the sample into the assay (whole-genome amplification product is
    routinely diluted before PicoGreen); the back-calculated concentration is multiplied
    back up. mass is computed at the sample's own assay volume before dilution scaling,
    so pass the volume of neat sample the mass should represent.
    """
    q: QuantResult = quantitate(
        curve.fit, signal, blank=blank,
        curve_signal_min=curve.signal_min, curve_signal_max=curve.signal_max,
        unit=curve.unit,
    )
    neat_conc = q.concentration * dilution_factor
    return WellQuant(
        sample_id=sample_id,
        well=well,
        concentration_ng_per_ml=neat_conc,
        mass_ng=mass_ng(neat_conc, assay_volume_ul),
        in_curve_range=q.in_curve_range,
        dilution_factor=dilution_factor,
    )

"""
fluorescent_dsdna.py - dsDNA quantitation for the two yield gates.

The same assay runs at two checkpoints: after WGS preparation (does each cell have enough amplified
genome to be worth sequencing) and after PCR enrichment (is each library in the loading
window). The fluorescent dsDNA assay is a dsDNA-selective fluorophore, so it reports
double-stranded yield and ignores the single-stranded and primer background that a
UV A260 would count, which is why it is the right quant for both an amplified genome
and a cleaned library.

The reader is the same Tecan Infinite 200 PRO used for Gate 0, in fluorescence mode at
a different wavelength pair. A standard curve of operator-selected reference dsDNA is read on the
same plate as the samples; qc_math.linear_fit turns it into a line and
qc_math.quantitate reads each sample's concentration off it. The curve's R-squared is
itself gated (a curve that did not come out straight means the assay was mispipetted,
and no sample read off it is trustworthy).

Assay wavelengths, standard concentrations, formulation, and sample dilution come
from the run's controlled operator profile. The public package supplies curve
fitting and quantitation only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence

from ..qc_math import LineFit, QuantResult, linear_fit, mass_ng, quantitate


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
    """Fit a fluorescent dsDNA assay standard curve.

    If blank is None, the lowest-concentration standard's signal is used as the blank
    and subtracted from every standard, which is how a fluorescent dsDNA assay curve is built. The fit
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

    dilution_factor accounts for diluting the sample into the assay (WGS preparation product is
    routinely diluted before fluorescent dsDNA assay); the back-calculated concentration is multiplied
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

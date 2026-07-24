"""
rhodamine_b.py - Rhodamine B, from the bottle to the plate reader's linear range.

Rhodamine B is the liquid-handling QC tracer for this package. The point is not to
measure a dye; it is to measure the STAR. If the robot dispenses a fixed-concentration
dye and the wells are all topped to a common read volume, then the fluorescence of a
well is proportional to the volume the robot delivered, and the CV of the fluorescence
across replicate wells IS the CV of the dispense at that volume. That is Gate 0: the
deck is not allowed to touch a sample until its dispense CV is under the cutoff across
the volumes the real protocol uses.

Method: constant concentration, variable volume, common read volume.
  1. Prepare a Rhodamine B working solution at a concentration that lands the read in
     the Tecan Infinite 200 PRO's linear window at the read geometry.
  2. The robot dispenses each qualified test volume into a column of replicate wells.
  3. Every well is topped to a common read volume with buffer, so path length and
     meniscus are constant and fluorescence tracks delivered volume, not fill height.
  4. Read top fluorescence, compute per-volume CV -> Gate 0.

What is a real fact and what has to be measured on the instrument is marked with the
provenance module. Excitation/emission maxima and the molar mass are chemistry and are
cited. The working concentration and the reader gain are NOT known until they are read
on this reader with this labware, so they are CALIBRATE and a hardware run refuses to
proceed until they are pinned. A qualified ratiometric dual-dye reference method,
which also gives accuracy without the top-up assumption, is noted below;
this built-in single-dye method measures precision, which is what the 5% CV gate is.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from ..provenance import Sourced, calibrate, transcribed, tunable
from ..qc_math import DyeRangePlan, rhodamine_working_concentration


# Chemistry. These are properties of the molecule, cited, not invented.
MW_G_PER_MOL = transcribed(
    479.02, "Rhodamine B, C28H31ClN2O3, molar mass (PubChem CID 6694)",
    unit="g/mol", name="rhodamine_b_molar_mass",
)
EX_MAX_NM = transcribed(
    554, "Rhodamine B absorption maximum in water (operator-verified QC reference)",
    unit="nm", name="rhodamine_b_ex_max",
)
EM_MAX_NM = transcribed(
    627, "Rhodamine B emission maximum in water (operator-verified QC reference)",
    unit="nm", name="rhodamine_b_em_max",
)

# Reader settings. Filter-based excitation/emission bands that bracket the maxima are a
# defensible default, but the exact bands and the gain depend on the reader's optics and
# the labware, so they are tunable/calibrate, not transcribed.
READ_EX_NM = tunable(
    535, "excitation band below the 554 nm max to limit bleed into the emission channel; "
         "confirm on the 200 PRO monochromator", unit="nm", name="read_ex",
)
READ_EM_NM = tunable(
    595, "emission band on the blue shoulder of the 627 nm max to keep the Stokes gap; "
         "confirm on the 200 PRO", unit="nm", name="read_em",
)
READ_GAIN = calibrate(
    None, "autoscale gain on the brightest qualification well (largest volume), once, "
          "then lock it for the whole plate", name="read_gain",
)

# Read geometry. The variable-volume method needs a fixed final read volume above the
# largest test volume. 200 uL is a standard flat-bottom 96-well read volume; confirm the
# labware's working range.
COMMON_READ_VOLUME_UL = tunable(
    200.0, "common final read volume; a flat-bottom 96-well plate reads well near 200 uL "
           "and it sits above the 200 uL top of the qualified ladder edge case", unit="uL",
    name="common_read_volume",
)

# Working concentration: NOT known until the calibration read. A single-dye Rhodamine B
# read for liquid handling is commonly run around 1 uM, but the value that lands THIS
# reader's window at THIS gain must be measured, so it is CALIBRATE.
WORKING_CONCENTRATION_UM = calibrate(
    None, "read a Rhodamine B dilution series on the 200 PRO and pick the concentration "
          "whose largest-volume well sits near 75% of the ceiling at the locked gain",
    unit="uM", name="working_concentration",
)

# The diluent for both the working solution and the top-up. Keeping them identical means
# the top-up adds no dye and no quenching mismatch.
DILUENT = tunable(
    "deionized water", "Rhodamine B is water soluble; water is the standard diluent for "
                       "a liquid-handling dye read and matches the top-up",
    name="diluent",
)


@dataclass(frozen=True)
class DilutionStep:
    """One C1V1 = C2V2 dilution: how much stock, how much diluent, to hit a target."""

    from_concentration: float
    to_concentration: float
    final_volume_ul: float
    stock_volume_ul: float
    diluent_volume_ul: float
    unit: str

    def as_text(self) -> str:
        return (
            f"{self.stock_volume_ul:.1f} uL of {self.from_concentration:g} {self.unit} stock "
            f"+ {self.diluent_volume_ul:.1f} uL diluent "
            f"-> {self.final_volume_ul:.1f} uL at {self.to_concentration:g} {self.unit}"
        )


def dilute(from_concentration: float, to_concentration: float,
           final_volume_ul: float, unit: str = "uM") -> DilutionStep:
    """C1V1 = C2V2. Volume of stock to take, and diluent to add, for a target."""
    if to_concentration <= 0 or from_concentration <= 0:
        raise ValueError("concentrations must be positive")
    if to_concentration > from_concentration:
        raise ValueError(
            f"cannot dilute {from_concentration}{unit} up to {to_concentration}{unit}; "
            "the target is more concentrated than the stock"
        )
    stock_v = final_volume_ul * to_concentration / from_concentration
    diluent_v = final_volume_ul - stock_v
    return DilutionStep(
        from_concentration=from_concentration,
        to_concentration=to_concentration,
        final_volume_ul=final_volume_ul,
        stock_volume_ul=round(stock_v, 2),
        diluent_volume_ul=round(diluent_v, 2),
        unit=unit,
    )


@dataclass
class RhodaminePrep:
    """The full prep and read plan for a Gate 0 qualification.

    stock_concentration is the one thing the operator supplies (what is in the bottle
    they diluted from); everything else is derived. Until the calibration read fixes the
    working concentration and gain, those stay unresolved and a hardware run is blocked
    by the RunGuard.
    """

    stock_concentration: Sourced
    working_concentration: Sourced = WORKING_CONCENTRATION_UM
    read_ex_nm: Sourced = READ_EX_NM
    read_em_nm: Sourced = READ_EM_NM
    read_gain: Sourced = READ_GAIN
    common_read_volume_ul: Sourced = COMMON_READ_VOLUME_UL
    diluent: Sourced = DILUENT

    def guard_values(self) -> List[Sourced]:
        """The values a hardware Gate 0 must have resolved before it runs."""
        return [self.working_concentration, self.read_gain]

    def dilution_to_working(self, working_conc: float, batch_volume_ul: float = 5000.0
                            ) -> DilutionStep:
        """Recipe to make the working solution once the calibration fixes its concentration."""
        return dilute(
            from_concentration=float(self.stock_concentration.value),
            to_concentration=working_conc,
            final_volume_ul=batch_volume_ul,
            unit=self.stock_concentration.unit or "uM",
        )

    def plan_range(self, qualified_volumes_ul: List[float],
                   reader_signal_floor: float, reader_signal_ceiling: float,
                   calibration_reference_concentration: float,
                   calibration_signal_at_reference: float) -> DyeRangePlan:
        """Predict the working concentration and where the volume ladder falls.

        This turns a single calibration read (a known concentration read at the common
        fill volume produced a known signal) into a predicted working concentration and
        the predicted signals of the smallest and largest qualified volumes. It is
        arithmetic to be confirmed by the actual dilution-series read, not a substitute
        for it.
        """
        return rhodamine_working_concentration(
            reference_concentration=calibration_reference_concentration,
            reference_signal_at_reference=calibration_signal_at_reference,
            smallest_test_volume_ul=min(qualified_volumes_ul),
            largest_test_volume_ul=max(qualified_volumes_ul),
            common_read_volume_ul=float(self.common_read_volume_ul.value),
            reader_signal_floor=reader_signal_floor,
            reader_signal_ceiling=reader_signal_ceiling,
        )


def default_prep(stock_concentration_um: float = 100.0) -> RhodaminePrep:
    """A prep starting from a 100 uM Rhodamine B stock.

    100 uM is a convenient intermediate stock to dilute a ~1 uM working solution from;
    it is the operator's to change, so it is tunable, not transcribed.
    """
    stock = tunable(
        stock_concentration_um,
        "operator-supplied Rhodamine B intermediate stock; dilute the working solution "
        "from this. Change it to match the bottle actually on the bench.",
        unit="uM", name="stock_concentration",
    )
    return RhodaminePrep(stock_concentration=stock)

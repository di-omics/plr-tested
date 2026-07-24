"""
rhodamine_b.py - Rhodamine B, the Gate 0 tracer that measures the machine, not a dye.

ELISpot's precision problem is the wash and reagent dispenses onto a delicate membrane: if
the washer or liquid handler is imprecise, the assay is imprecise no matter how good the
biology is. Rhodamine B is how Gate 0 qualifies the instrument before a single well is
coated. The point is not to measure a dye; it is to measure the dispense. If the instrument
dispenses a fixed-concentration dye and every well is topped to a common read volume, then
the fluorescence of a well is proportional to the volume delivered, and the CV of the
fluorescence across replicate wells IS the CV of the dispense at that volume.

Method: constant concentration, variable volume, common read volume.
  1. Prepare a Rhodamine B working solution at a concentration that lands the read in the
     plate reader's linear window at the read geometry.
  2. The instrument dispenses each qualified volume into a column of replicate wells.
  3. Every well is topped to a common read volume with buffer, so fluorescence tracks
     delivered volume, not fill height.
  4. Read fluorescence, compute per-volume CV -> Gate 0.

What is a real fact and what has to be measured on the instrument is marked with the
provenance module. Excitation/emission maxima and the molar mass are chemistry and are
cited. The working concentration and the reader gain are NOT known until they are read on
this reader with this labware, so they are CALIBRATE and a hardware run refuses to proceed
until they are pinned. For an ELISpot-only lab that owns a washer but no fluorescence
reader, the gravimetric alternative (dispense water, weigh) measures the same precision;
Rhodamine is the plate-reader form, kept here because the readout imager and many washers
sit next to one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from ..provenance import Sourced, calibrate, transcribed, tunable


# Chemistry. Properties of the molecule, cited, not invented.
MW_G_PER_MOL = transcribed(
    479.02, "Rhodamine B, C28H31ClN2O3, molar mass (PubChem CID 6694)",
    unit="g/mol", name="rhodamine_b_molar_mass",
)
EX_MAX_NM = transcribed(
    554, "Rhodamine B absorption maximum in water (supplier product data)",
    unit="nm", name="rhodamine_b_ex_max",
)
EM_MAX_NM = transcribed(
    627, "Rhodamine B emission maximum in water (supplier product data)",
    unit="nm", name="rhodamine_b_em_max",
)

# Reader settings. Bands that bracket the maxima are a defensible default, but the exact
# bands and the gain depend on the reader's optics and the labware, so they are
# tunable/calibrate, not transcribed.
READ_EX_NM = tunable(
    535, "excitation band below the 554 nm max to limit bleed into the emission channel; "
         "confirm on your reader", unit="nm", name="read_ex",
)
READ_EM_NM = tunable(
    595, "emission band on the blue shoulder of the 627 nm max to keep the Stokes gap; "
         "confirm on your reader", unit="nm", name="read_em",
)
READ_GAIN = calibrate(
    None, "autoscale gain on the brightest qualification well (largest volume), once, then "
          "lock it for the whole plate", name="read_gain",
)

# Read geometry. The variable-volume method needs a fixed final read volume at or above the
# largest test volume. 250 uL sits above the 200 uL top of the ELISpot wash-volume ladder.
COMMON_READ_VOLUME_UL = tunable(
    250.0, "common final read volume, above the 200 uL top of the qualified wash ladder so "
           "every well tops up to the same path length; confirm the labware working range",
    unit="uL", name="common_read_volume",
)

# Working concentration: NOT known until the calibration read. CALIBRATE.
WORKING_CONCENTRATION_UM = calibrate(
    None, "read a Rhodamine B dilution series on this reader and pick the concentration "
          "whose largest-volume well sits near 75% of the ceiling at the locked gain",
    unit="uM", name="working_concentration",
)

DILUENT = tunable(
    "deionized water", "Rhodamine B is water soluble; water matches the top-up so the "
                       "top-up adds no dye and no quenching mismatch",
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
    """The prep and read plan for a Gate 0 qualification.

    stock_concentration is the one thing the operator supplies (what is in the bottle they
    diluted from); everything else is derived. Until the calibration read fixes the working
    concentration and gain, those stay unresolved and a hardware run is blocked by the guard.
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


def default_prep(stock_concentration_um: float = 100.0) -> RhodaminePrep:
    """A prep starting from a 100 uM Rhodamine B stock (the operator's to change)."""
    stock = tunable(
        stock_concentration_um,
        "operator-supplied Rhodamine B intermediate stock; dilute the working solution from "
        "this. Change it to match the bottle actually on the bench.",
        unit="uM", name="stock_concentration",
    )
    return RhodaminePrep(stock_concentration=stock)

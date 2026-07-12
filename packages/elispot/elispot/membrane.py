"""
membrane.py - the PVDF membrane is why ELISpot is hard to automate, in one module.

Most of an ELISpot protocol automates cleanly: it is dispense, wash, incubate, wash,
develop. The catch is the surface. The assay is read off a PVDF membrane at the bottom of
each well, and a spot is a place where a single cell secreted cytokine onto that membrane.
Three things about the membrane decide whether an automated run produces data or garbage,
and none of them is a reagent volume - they are geometry and force. An engineer reading
this protocol like code should stop at each of them and ask "does this step survive a
robot", which is exactly what this module makes explicit.

  1. Probe clearance. A wash probe that rides too low scratches or pierces the membrane.
     A scratch develops as a line or a smear of false spots and there is no rescuing the
     well. The safe aspiration height sits a fixed clearance above the membrane, and it
     depends on the plate lot's membrane seating, so it must be taught on the physical
     plate, not guessed. It is CALIBRATE: a hardware run is blocked until it is measured.

  2. No jet onto the membrane. A dispense aimed straight down at full flow drives liquid
     into the membrane and lifts or damages the coated capture antibody. Reagents and wash
     buffer go down the side wall at a capped flow rate. This is a mode and a rate, marked
     TUNABLE with the reason, to be confirmed on the instrument.

  3. Never let it dry mid-assay, and never over-wash. Between the coat and the final
     development the membrane must stay wet; a membrane that dries traps background. But
     the cell-wash step also cannot be run harder "to be safe" - excess high-force wash
     lifts the capture layer. The number of wash cycles and the volume are therefore QC
     parameters (they live in the SiteProfile and are qualified at Gate 0), not free knobs.

This module holds those constraints as Sourced values and offers one guard,
`membrane_guard_values`, that the readiness stage adds to the run guard so a hardware run
refuses to start until the clearance is taught. It invents nothing: the ethanol pre-wet
activates PVDF and the side-wall low-flow rule are standard PVDF-ELISpot practice, and the
numeric clearance is explicitly left to be measured.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .provenance import Sourced, calibrate, transcribed, tunable


# The membrane material and why it needs activating. PVDF is hydrophobic; a brief low-
# percentage ethanol wet-out lets aqueous coating buffer reach the surface. This is
# standard practice for PVDF ELISpot plates (e.g. Millipore MSIP/MAIP, Mabtech guidance);
# the exact percentage and contact time are kit-specific and must not be exceeded, so the
# structure is cited and the numbers are tunable-with-caution, not invented catalog values.
MEMBRANE_MATERIAL = transcribed(
    "PVDF", "ELISpot capture membrane; hydrophobic, requires a brief alcohol pre-wet to "
            "activate before aqueous coating (standard PVDF-ELISpot practice)",
    name="membrane_material",
)
PREWET_ETHANOL_PERCENT = tunable(
    35.0, "low-percentage ethanol activates PVDF for aqueous coating; over-exposure or too "
          "high a percentage destroys the membrane. Source the exact percentage and contact "
          "time from your plate/kit instructions and do not exceed them.",
    unit="%", name="prewet_ethanol_percent",
)
PREWET_CONTACT_SECONDS = tunable(
    60.0, "keep the ethanol contact short and immediately follow with water/buffer washes; "
          "the membrane must not sit in ethanol. Confirm against your kit.",
    unit="s", name="prewet_contact_time",
)

# 1. Probe clearance above the membrane. THE value that must be taught on hardware.
ASPIRATION_CLEARANCE_MM = calibrate(
    None, "teach the wash/aspiration probe height on the physical plate lot: the tip must "
          "clear the membrane with margin at the aspiration point. A probe that rides too "
          "low scratches the membrane and prints false spots. Measure it, then pin it in the "
          "SiteProfile; do not carry a value across plate lots without re-checking.",
    unit="mm", name="aspiration_clearance",
)

# 2. Dispense mode and flow. A jet at the membrane damages the capture layer.
DISPENSE_MODE = tunable(
    "side_wall_low_flow", "dispense reagents and wash buffer down the well side wall at a "
                          "capped flow rate; never a center jet at the membrane. Confirm the "
                          "flow-rate cap on your washer/liquid handler.",
    name="dispense_mode",
)

# 3. Wet-out discipline. Between coat and development the membrane stays wet.
KEEP_WET_RULE = tunable(
    "no_dry_between_coat_and_develop",
    "the membrane must not dry between coating and final development; a dried membrane "
    "traps background. Schedule wash and reagent steps so no well sits empty.",
    name="keep_wet_rule",
)


@dataclass(frozen=True)
class MembraneConstraints:
    """The membrane-safety envelope for a run, assembled from the module defaults.

    site_clearance, if the SiteProfile has taught it, replaces the CALIBRATE placeholder so
    the guard passes for a hardware run. Everything else is a fixed part of the envelope.
    """

    material: Sourced = MEMBRANE_MATERIAL
    prewet_ethanol_percent: Sourced = PREWET_ETHANOL_PERCENT
    prewet_contact_seconds: Sourced = PREWET_CONTACT_SECONDS
    aspiration_clearance_mm: Sourced = ASPIRATION_CLEARANCE_MM
    dispense_mode: Sourced = DISPENSE_MODE
    keep_wet_rule: Sourced = KEEP_WET_RULE

    def with_site_clearance(self, clearance_mm: Optional[float]) -> "MembraneConstraints":
        """Return a copy whose clearance is the site-taught value, if one was given."""
        if clearance_mm is None:
            return self
        taught = tunable(
            clearance_mm,
            "taught on this site's plate lot and pinned in the SiteProfile; re-teach for a "
            "new plate lot",
            unit="mm", name="aspiration_clearance",
        )
        return MembraneConstraints(
            material=self.material,
            prewet_ethanol_percent=self.prewet_ethanol_percent,
            prewet_contact_seconds=self.prewet_contact_seconds,
            aspiration_clearance_mm=taught,
            dispense_mode=self.dispense_mode,
            keep_wet_rule=self.keep_wet_rule,
        )

    def guard_values(self) -> List[Sourced]:
        """The values a hardware run must have resolved before a probe enters a well."""
        return [self.aspiration_clearance_mm]


def default_constraints(site_clearance_mm: Optional[float] = None) -> MembraneConstraints:
    return MembraneConstraints().with_site_clearance(site_clearance_mm)

"""One source-of-truth run card for M7634 v3.0 Section 3.

The package references the existing STAR and ODTC implementations; it does not copy
their geometry or thermal XML.  Candidate live commands are included for review, but a
hardware run is blocked by provenance.py until those scripts are physically qualified.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .config import RunConfig


MANUAL = "NEB #M7634 v3.0 (3/26), Section 3"


@dataclass(frozen=True)
class ProtocolStep:
    number: int
    name: str
    operation: str
    reaction_before_ul: Optional[float]
    reaction_after_ul: Optional[float]
    components_ul: Dict[str, float] = field(default_factory=dict)
    source: str = MANUAL
    note: str = ""
    simulation_command: Optional[str] = None
    candidate_hardware_command: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "number": self.number,
            "name": self.name,
            "operation": self.operation,
            "reaction_before_ul": self.reaction_before_ul,
            "reaction_after_ul": self.reaction_after_ul,
            "components_ul": self.components_ul,
            "source": self.source,
            "note": self.note,
            "simulation_command": self.simulation_command,
            "candidate_hardware_command": self.candidate_hardware_command,
        }


def _star_add(mode: str) -> tuple:
    base = (
        "cd hamilton-star && ./run_on_pi.sh "
        f"starlab_live/emseq/emseq_reagent_adds.py --mode {mode}"
    )
    return base + " --dry --return-tips", base


def _cleanup(preset: str) -> tuple:
    base = (
        "cd hamilton-star && ./run_on_pi.sh starlab_live/emseq/emseq_cleanup.py "
        f"--cleanup {preset} --mode all"
    )
    return base + " --dry --return-tips", base


def _odtc(program: str) -> tuple:
    dry = (
        "cd instrument-integrations && ./run_on_pi.sh odtc/05_odtc_run_protocol.py "
        f"--program {program} --dry"
    )
    live = (
        "cd instrument-integrations && ./run_on_pi.sh odtc/05_odtc_run_protocol.py "
        f"--program {program} --ip $ODTC_IP --confirm i-am-watching"
    )
    return dry, live


def build_protocol(config: RunConfig) -> List[ProtocolStep]:
    steps: List[ProtocolStep] = []

    def add(name: str, operation: str, before: Optional[float], after: Optional[float],
            components: Optional[Dict[str, float]] = None, section: str = "",
            note: str = "", commands: tuple = (None, None)) -> None:
        steps.append(ProtocolStep(
            number=len(steps) + 1,
            name=name,
            operation=operation,
            reaction_before_ul=before,
            reaction_after_ul=after,
            components_ul=components or {},
            source=f"{MANUAL}, {section}" if section else MANUAL,
            note=note,
            simulation_command=commands[0],
            candidate_hardware_command=commands[1],
        ))

    add(
        "DNA + conversion-control preparation", "operator", None, 26.0,
        {"sample DNA in TE": 24.0, "unmethylated lambda control": 1.0,
         "CpG-methylated pUC19 control": 1.0}, "3.1.1",
        "Prepare off deck. Each sample's manifest records the input-specific control dilution.",
    )
    add("UltraShear master-mix addition", "STAR reagent add", 26.0, 44.0,
        {"UltraShear Reaction Buffer": 14.0, "UltraShear": 4.0}, "3.1.4",
        "UltraShear must be vortexed before use; set up on ice.", _star_add("shear-mm"))
    add("UltraShear fragmentation", "ODTC", 44.0, 44.0, section="3.1.6",
        note=f"37 C {config.shear_minutes:g} min; 65 C 15 min; 4 C hold; lid 75 C.",
        commands=_odtc("emseq-shear"))
    add("Coupled End Prep addition", "STAR reagent add", 44.0, 49.0,
        {"500 mM DTT from M7634": 2.0, "Ultra II End Prep Enzyme Mix": 3.0}, "3.2.1",
        "Do not add the EM-seq End Prep Reaction Buffer; use the green M7634 DTT.",
        _star_add("endprep-mm"))
    add("Coupled End Prep", "ODTC", 49.0, 49.0, section="3.2.3",
        note="20 C 15 min; 65 C 15 min; 4 C hold; lid >=75 C.",
        commands=_odtc("emseq-endprep"))
    add("EM-seq adaptor addition", "STAR reagent add", 49.0, 51.5,
        {"EM-seq Adaptor": 2.5}, "3.3.1",
        "Adaptor must contact sample before ligation mix; never premix it with all ligation reagents.",
        _star_add("adaptor"))
    add("Ligation mix addition", "STAR reagent add", 51.5, 82.5,
        {"Ligation Enhancer": 1.0, "Ultra II Ligation Master Mix": 30.0}, "3.3.1",
        "Master mix is viscous; the 31 uL high-volume dispense requires hardware tuning.",
        _star_add("ligation-mm"))
    add("Adaptor ligation", "ODTC", 82.5, 82.5, section="3.3.3",
        note="20 C 15 min; 4 C hold. Manual says lid off; current backend uses 50 C and is unvalidated.",
        commands=_odtc("emseq-ligation"))

    if config.low_input:
        cleanup_note = (
            "1.1X beads (93 uL), two 200 uL 80% ethanol washes, elute with 28 uL, "
            "transfer 27 uL, then add 1 uL carrier DNA (<=10 ng route)."
        )
        cleanup_components = {"Sample Purification Beads": 93.0, "ethanol wash x2": 400.0,
                              "Elution Buffer": 28.0, "Carrier DNA": 1.0}
    else:
        cleanup_note = (
            "1.1X beads (93 uL), two 200 uL 80% ethanol washes, elute with 29 uL, "
            "transfer 28 uL (>10 ng route)."
        )
        cleanup_components = {"Sample Purification Beads": 93.0, "ethanol wash x2": 400.0,
                              "Elution Buffer": 29.0}
    add("Post-ligation SPRI cleanup", "STAR cleanup + operator transfer", 82.5, 28.0,
        cleanup_components, "3.4", cleanup_note, _cleanup("post-ligation"))

    tet2_buffer_reconstitution = 100.0 if config.kit_size == 24 else 400.0
    t4_note = "1:10 diluted T4-BGT, prepared fresh" if config.low_input else "undiluted T4-BGT"
    add("TET2 protection mix addition", "STAR reagent add", 28.0, 45.0,
        {"reconstituted TET2 Reaction Buffer": 10.0, "UDP-Glucose": 1.0,
         "yellow DTT": 1.0, "T4-BGT": 1.0, "TET2": 4.0}, "3.5.1-3.5.3",
        f"Reconstitute supplement with {tet2_buffer_reconstitution:g} uL buffer for the "
        f"{config.kit_size}-reaction kit; use {t4_note}.", _star_add("tet2-mm"))
    add("Fresh diluted Fe(II) addition", "STAR reagent add", 45.0, 50.0,
        {"fresh 1:1250 diluted Fe(II)": 5.0}, "3.5.4",
        "Prepare 1 uL 500 mM Fe(II) + 1249 uL water; use immediately and discard.",
        _star_add("feii"))
    add("TET2 protection", "ODTC", 50.0, 50.0, section="3.5.5",
        note="37 C 60 min; 4 C hold; lid >=45 C.", commands=_odtc("emseq-tet2"))
    add("Stop-reagent addition", "STAR reagent add", 50.0, 51.0,
        {"Stop Reagent": 1.0}, "3.5.6", commands=_star_add("stop"))
    add("Stop incubation", "ODTC", 51.0, 51.0, section="3.5.7",
        note="37 C 30 min; 4 C hold; lid >=45 C.", commands=_odtc("emseq-tet2-stop"))
    add("Post-protection SPRI cleanup", "STAR cleanup + operator transfer", 51.0, 16.0,
        {"Sample Purification Beads": 50.0, "ethanol wash x2": 400.0,
         "Elution Buffer": 17.0}, "3.6",
        "1X cleanup; transfer 16 uL clear eluate. Even small bead carryover can impair deamination.",
        _cleanup("post-tet2"))
    add("Formamide addition", "STAR reagent add", 16.0, 20.0,
        {"Formamide": 4.0}, "3.7A.2", "Recommended denaturation route.",
        _star_add("formamide"))
    add("DNA denaturation", "ODTC", 20.0, 20.0, section="3.7A.1-3.7A.4",
        note="85 C 10 min; immediately cool ~2 min. ODTC 4 C block substitution is unvalidated.",
        commands=_odtc("emseq-denature"))
    add("APOBEC deamination mix addition", "STAR reagent add", 20.0, 40.0,
        {"nuclease-free water": 14.0, "Deamination Reaction Buffer": 4.0,
         "Recombinant Albumin": 1.0, "APOBEC": 1.0}, "3.8.1",
        commands=_star_add("deaminate-mm"))
    add("Cytosine deamination", "ODTC", 40.0, 40.0, section="3.8.3",
        note="37 C 3 h; 4 C hold; lid >=45 C. Continue directly to PCR without cleanup.",
        commands=_odtc("emseq-deaminate"))
    add("Unique dual-index primer addition", "STAR per-well reagent add", 40.0, 45.0,
        {"NEBNext LV UDI Primer Pair": 5.0}, "3.9.1",
        "Manifest validation guarantees one unique UDI per well.", _star_add("pcr-primer"))
    add("Q5U master-mix addition", "STAR reagent add", 45.0, 90.0,
        {"NEBNext Q5U Master Mix": 45.0}, "3.9.1",
        "Largest p50 addition; tune dispense height and 10x mixing on hardware.",
        _star_add("pcr-mm"))
    add("Library PCR", "ODTC", 90.0, 90.0, section="3.9.3",
        note=(f"98 C 30 s; {config.pcr_cycles} x (98 C 10 s, 62 C 30 s, 65 C 60 s); "
              "65 C 5 min; 4 C hold; lid 105 C."), commands=_odtc("emseq-pcr"))
    add("Post-PCR SPRI cleanup", "STAR cleanup + operator transfer", 90.0, 20.0,
        {"Sample Purification Beads": 72.0, "ethanol wash x2": 400.0,
         "Elution Buffer": 21.0}, "3.10",
        "0.8X cleanup; transfer 20 uL clear final library and avoid over-drying beads.",
        _cleanup("post-pcr"))
    add("Library and conversion QC", "operator/instrument handoff", 20.0, 20.0,
        section="3.11", note=(
            "TapeStation/Bioanalyzer size + concentration, then sequencing QC of lambda and "
            "pUC19 controls. The package evaluates supplied metrics against the run rubric."
        ))
    return steps


def qualified_volumes(config: RunConfig) -> List[float]:
    """Distinct liquid transfers that need a site-specific precision check."""
    values = {1.0, 2.5, 4.0, 5.0, 14.0, 17.0, 18.0, 20.0, 31.0, 45.0,
              50.0, 72.0, 93.0, 200.0}
    values.update({28.0, 27.0} if config.low_input else {29.0, 28.0})
    return sorted(values)


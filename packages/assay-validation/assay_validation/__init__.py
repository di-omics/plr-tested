"""
assay_validation - QC-gated WGS preparation + PCR enrichment for sequencing targets.

An explicit run manifest in; a qualified, gated, auditable run out. The public surface
is small on purpose:

    from assay_validation import load_run, run
    outcome = run(load_run("configs/example_run.yaml"))

See README.md for the flow and the gates.
"""

from .config import (
    AcceptanceCriteria,
    DeckLayout,
    AnalysisType,
    FluorescentDsDNAProfile,
    LocusTarget,
    MethodParameters,
    ProfileKind,
    RunConfig,
    RunMode,
    Sample,
    SampleType,
)
from .manifest import ManifestError, build_run, load_run
from .orchestrator import RunOutcome, RunStatus, run
from .version import __version__

__all__ = [
    "__version__",
    "load_run",
    "build_run",
    "run",
    "RunOutcome",
    "RunStatus",
    "RunConfig",
    "RunMode",
    "Sample",
    "SampleType",
    "LocusTarget",
    "AnalysisType",
    "ProfileKind",
    "DeckLayout",
    "AcceptanceCriteria",
    "MethodParameters",
    "FluorescentDsDNAProfile",
    "ManifestError",
]

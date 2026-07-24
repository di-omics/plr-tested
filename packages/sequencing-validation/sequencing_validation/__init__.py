"""
sequencing_validation - QC-gated WGS preparation and PCR enrichment for assay validation.

Sparse input (which samples, which target, simulation or hardware) in; a qualified,
gated, auditable run out. The public surface is small on purpose:

    from sequencing_validation import load_run, run
    outcome = run(load_run("configs/example_run.yaml"))

See README.md for the flow and the gates.
"""

from .config import (
    AcceptanceCriteria,
    DeckLayout,
    AssayType,
    AssayTarget,
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
    "ProfileKind",
    "MethodParameters",
    "Sample",
    "SampleType",
    "AssayTarget",
    "AssayType",
    "DeckLayout",
    "AcceptanceCriteria",
    "ManifestError",
]

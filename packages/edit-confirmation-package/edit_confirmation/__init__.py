"""
edit_confirmation - a QC-gated whole-genome amplification + targeted PCR package for confirming gene edits.

Sparse input (which samples, which locus, simulation or hardware) in; a qualified,
gated, auditable run out. The public surface is small on purpose:

    from edit_confirmation import load_run, run
    outcome = run(load_run("configs/example_run.yaml"))

See README.md for the flow and the gates.
"""

from .config import (
    AcceptanceCriteria,
    DeckLayout,
    EditType,
    LocusTarget,
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
    "EditType",
    "DeckLayout",
    "AcceptanceCriteria",
    "ManifestError",
]

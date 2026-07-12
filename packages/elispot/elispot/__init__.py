"""
elispot - a QC-gated ELISpot automation package.

Sparse input (which cytokine, which wells hold which antigen, simulation or hardware) in; a
qualified, gated, auditable run out, driven across a plate washer, a liquid handler, and a
spot imager from a Raspberry Pi through an agent harness. The public surface is small on
purpose:

    from elispot import load_run, run
    outcome = run(load_run("configs/example_run.yaml"))

See README.md for the flow and the gates.
"""

from .config import (
    AcceptanceCriteria,
    Antigen,
    AntigenKind,
    PlateLayout,
    RunConfig,
    RunMode,
    SiteProfile,
    Well,
    WellRole,
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
    "Well",
    "WellRole",
    "Antigen",
    "AntigenKind",
    "PlateLayout",
    "SiteProfile",
    "AcceptanceCriteria",
    "ManifestError",
]

#!/usr/bin/env python3
"""Launch the canonical local EM-seq bench planner from the STAR protocol folder.

This file is deliberately only a launcher. The planner implementation stays in
``packages/emseq-app`` so the Hamilton entrypoint, tests, and shareable package all
use one source of truth. Importing this launcher does not import PyLabRobot or connect
to an instrument.
"""

from __future__ import annotations

from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PLANNER_ROOT = REPOSITORY_ROOT / "packages" / "emseq-app"


def main() -> int:
    package_dir = PLANNER_ROOT / "emseq_app"
    if not package_dir.is_dir():
        raise SystemExit(
            "EM-seq bench planner package was not found at "
            f"{PLANNER_ROOT}. Keep packages/emseq-app beside hamilton-star."
        )

    sys.path.insert(0, str(PLANNER_ROOT))
    from emseq_app.server import main as planner_main

    return planner_main()


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env bash
# Run the whole assay-validateation flow in simulation and open the dossier.
# No instruments, no install required: pure standard-library Python.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== plan =="
python3 -m assay_validation plan configs/example_run.yaml

echo
echo "== run (simulation) =="
python3 -m assay_validation run configs/example_run.yaml --out runs

echo
echo "Dossier: runs/SEQ-2026-07-11-01/dossier.html"
echo "To see a Gate 0 stop:  python3 -m assay_validation run configs/example_run.yaml --poor-deck"
echo "To see the hardware provenance block:  python3 -m assay_validation run configs/example_run.yaml --hardware"

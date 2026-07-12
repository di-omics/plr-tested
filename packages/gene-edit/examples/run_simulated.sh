#!/usr/bin/env bash
# Run the whole edit-confirmation flow in simulation and open the dossier.
# No instruments, no install required: pure standard-library Python.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== plan =="
python3 -m edit_confirmation plan configs/example_run.yaml

echo
echo "== run (simulation) =="
python3 -m edit_confirmation run configs/example_run.yaml --out runs

echo
echo "Dossier: runs/EC-2026-07-11-embryo01/dossier.html"
echo "To see a Gate 0 stop:  python3 -m edit_confirmation run configs/example_run.yaml --poor-deck"
echo "To see the hardware provenance block:  python3 -m edit_confirmation run configs/example_run.yaml --hardware"

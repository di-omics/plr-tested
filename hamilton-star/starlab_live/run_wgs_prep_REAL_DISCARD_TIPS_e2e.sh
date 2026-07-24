#!/usr/bin/env bash
set -euo pipefail

cd ~/star-lab
source env/bin/activate

SCRIPT="00_wgs_prep_col1_swap_source_staged_discardtips_P10_sourceH00_dspH05_bo7.py"
INPUT_VOLUME_UL="$(python -c 'from operator_parameters import required_positive; print(required_positive("wgs.input_volume_ul"))')"
THERMAL_PROGRAM_ID="$(python -c 'from operator_parameters import required_text; print(required_text("wgs.thermal_programs.preparation"))')"

echo
echo "=== WGS preparation REAL E2E RUNNER: DISCARD TIPS ==="
echo "REAL mode: no --return-tips. Tips will be DISCARDED."
echo "Use only with real reagents/samples and fresh tip columns."
echo

echo "Checking STAR USB..."
lsusb | grep -i 08af

echo
echo "Checking no obvious STAR protocol process is already running..."
ps aux | grep -E "00_wgs_prep|pylabrobot" | grep -v grep || true

echo
read -p "Confirm deck clear + fresh p10 tips loaded. Press Enter for deck check..."

python "$SCRIPT" --mode deck

echo
echo "=== STEP 1: REAL LYSIS REAGENT MIX ADDITION ==="
echo "Deck:"
echo "  rail48 pos0 = p10 tips, column 1 fresh"
echo "  rail35 pos0 = destination/work plate, column 1 A-H contains $INPUT_VOLUME_UL uL operator-approved input"
echo "  rail35 pos1 = source plate/strip, column 1 A-H contains lysis reagent mix"
echo
echo "This step will run: python \$SCRIPT --mode lysis"
echo "Tips will be DISCARDED."
echo
read -p "Type RUN_REAL_WGS_PREP to run real lysis: " CONFIRM
if [[ "$CONFIRM" != "RUN_REAL_WGS_PREP" ]]; then
  echo "Aborted before lysis."
  exit 1
fi

python "$SCRIPT" --mode lysis

echo
echo "LYSIS STAR STEP COMPLETE."
echo "Now do real protocol handoff:"
echo "  seal/spin"
echo "  operator-approved stage 1 handoff"
echo "  spin"
echo "  place back on ice"
echo
read -p "After real lysis incubation/handoff is complete, press Enter..."

echo
echo "=== STEP 2: REAL WGS PREPARATION REACTION MIX ADDITION ==="
echo "Deck:"
echo "  rail48 pos0 = p10 tips, column 2 fresh"
echo "  rail35 pos1 = source plate/strip, column 1 A-H contains WGS preparation reaction mix"
echo "  rail35 pos0 = destination/work plate clear/no obstruction"
echo
echo "This step will run: python \$SCRIPT --mode reaction"
echo "Tips will be DISCARDED."
echo
read -p "Type RUN_REAL_REACTION to run real reaction: " CONFIRM
if [[ "$CONFIRM" != "RUN_REAL_REACTION" ]]; then
  echo "Aborted before reaction."
  exit 1
fi

python "$SCRIPT" --mode reaction

echo
echo "REACTION STAR STEP COMPLETE."
echo "Now do real protocol handoff:"
echo "  seal/spin"
echo "  operator-approved stage 2 handoff"
echo "  spin"
echo "  keep plate on ice"
echo
read -p "Press Enter for final WGS preparation thermocycler handoff..."

echo
echo "=== WGS preparation THERMOCYCLER HANDOFF ==="
echo "Load plate into thermocycler:"
echo "  run operator-approved program: $THERMAL_PROGRAM_ID"
echo
echo "WGS preparation real E2E handoff complete."

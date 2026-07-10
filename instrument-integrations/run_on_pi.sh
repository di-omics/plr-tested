#!/usr/bin/env bash
#
# Run an instrument-integrations script on the Pi, from this repo.
#
# Sibling of hamilton-star/run_on_pi.sh. Syncs the instrument-integrations/ tree to
# its own run directory on the Pi and executes the chosen script in the existing
# PyLabRobot venv. It never writes to the Pi's own ~/star-lab working directory, and
# it does not collide with the hamilton-star run directory.
#
# Usage:
#   ./run_on_pi.sh <script-path-relative-to-instrument-integrations> [args...]
#
# Examples:
#   ./run_on_pi.sh odtc/odtc_offline_checks.py
#   ODTC_IP=169.254.1.50 ./run_on_pi.sh odtc/01_odtc_probe_raw.py
#   ./run_on_pi.sh odtc/02_odtc_bringup.py --ip 169.254.1.50
#
# ODTC_IP is forwarded to the Pi if it is set in your environment. Lab addresses are
# not committed to this repo.
#
# Safety: these scripts drive real hardware.
#   - 01_odtc_probe_raw.py is read-only. Run it first, always.
#   - Anything that moves the door or heats the block demands --confirm i-am-watching.
#   - Never run unattended. A person watches the instrument.
#   - Only one process may drive a given instrument at a time.
#   - Long programs (wga is ~2.6 hours) should be launched detached on the Pi, so a
#     dropped SSH session cannot kill a run mid-cycle.

set -euo pipefail

PI="${PI:-starpi}"                          # ssh alias, see ~/.ssh/config
VENV="${VENV:-\$HOME/star-lab/env}"         # existing PyLabRobot venv on the Pi
REMOTE="${REMOTE:-plr-tested-ii-run}"       # dedicated run dir, not ~/star-lab

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ "$#" -lt 1 ]; then
  echo "usage: $0 <script-relative-to-instrument-integrations> [args...]" >&2
  exit 2
fi
SCRIPT="$1"; shift

if [ ! -f "$HERE/$SCRIPT" ]; then
  echo "error: $SCRIPT not found under $HERE" >&2
  exit 2
fi

echo "[run_on_pi] sync $HERE/ -> $PI:~/$REMOTE/"
rsync -a --delete \
  --exclude 'env' --exclude '.git' --exclude '__pycache__' --exclude '*.pyc' \
  -e ssh "$HERE/" "$PI:$REMOTE/"

# Scripts import odtc_compat as a sibling module, so run from the script's directory.
SCRIPT_DIR="$(dirname "$SCRIPT")"
SCRIPT_FILE="$(basename "$SCRIPT")"

echo "[run_on_pi] run $SCRIPT on $PI"
ssh "$PI" "source $VENV/bin/activate \
  && cd ~/$REMOTE/$SCRIPT_DIR \
  && ${ODTC_IP:+ODTC_IP='$ODTC_IP'} python '$SCRIPT_FILE' $*"

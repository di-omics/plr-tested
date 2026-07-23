#!/usr/bin/env bash
#
# Run a hamilton-star script on the Pi-controlled Hamilton STAR, from this repo.
#
# Dev lives here in plr-tested. This script syncs the hamilton-star/ tree to a
# dedicated run directory on the Pi and executes the chosen script in the
# existing PyLabRobot venv. It never writes to the Pi's own ~/star-lab working
# directory, so live work there is not clobbered.
#
# Usage:
#   ./run_on_pi.sh <script-path-relative-to-hamilton-star> [args...]
#
# Examples:
#   ./run_on_pi.sh starlab_live/test_star_no_autoload.py
#   ./run_on_pi.sh starlab_live/01_targeted_pcr_round1_mastermix_col1.py --mode deck
#
# Safety: these scripts move real hardware.
#   - Never run unattended. A person watches the deck, hand near the E-stop.
#   - Run --mode deck first where available: it assigns the deck, no motion.
#   - Only one process may drive the STAR at a time. Two clients racing for the
#     USB interface produce "USBError: [Errno 16] Resource busy".
#   - For long runs, launch detached on the Pi so that a dropped SSH session
#     cannot interrupt the arm mid-transfer.

set -euo pipefail

PI="${PI:-starpi}"                 # ssh alias, see ~/.ssh/config
VENV="${VENV:-\$HOME/star-lab/env}"   # existing PyLabRobot venv on the Pi
REMOTE="${REMOTE:-plr-tested-run}"    # dedicated run dir on the Pi (not ~/star-lab)

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ "$#" -lt 1 ]; then
  echo "usage: $0 <script-relative-to-hamilton-star> [args...]" >&2
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
  --exclude 'odtc_lib' \
  -e ssh "$HERE/" "$PI:$REMOTE/"

# The ODTC thermal programs live in the sibling instrument-integrations/ tree, which this
# script does not otherwise sync. Choreography that drives the cycler (see
# starlab_live/run_targeted_pcr_odtc_LIDDED_1col_full_thermocycle.py) needs them ON the Pi, so
# put them alongside as odtc_lib/. Additive: scripts that do not import them are unaffected,
# and the sync above excludes odtc_lib so --delete does not fight this.
ODTC_SRC="$(cd "$HERE/.." && pwd)/instrument-integrations/odtc"
if [ -d "$ODTC_SRC" ]; then
  echo "[run_on_pi] sync $ODTC_SRC/ -> $PI:~/$REMOTE/odtc_lib/"
  rsync -a --delete \
    --exclude '__pycache__' --exclude '*.pyc' \
    -e ssh "$ODTC_SRC/" "$PI:$REMOTE/odtc_lib/"
fi

# ODTC_IP is forwarded when set, so a choreography running --thermocycle can reach the
# cycler. Lab addresses are never committed; this passes through from your environment.
echo "[run_on_pi] run $SCRIPT on $PI"
ssh "$PI" "source $VENV/bin/activate && cd ~/$REMOTE && ${ODTC_IP:+ODTC_IP='$ODTC_IP'} python '$SCRIPT' $*"

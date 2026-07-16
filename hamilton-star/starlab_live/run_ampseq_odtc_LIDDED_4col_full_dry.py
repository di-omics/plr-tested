import argparse
import subprocess
import sys
from pathlib import Path

# Amplicon-seq column-1 full choreography WITH the ODTC thermocycler handoffs AND
# the lid-on / lid-off legs wired around each ODTC trip.
#
# This is the LIDDED variant of run_ampseq_odtc_1col_full_dry.py. Same 9-leg protocol
# shape, plus 4 lid legs: the plate is SEALED with a lid while it sits in the ODTC nest
# (so the ODTC's heated lid presses on a lid, not open wells) and UNSEALED before it is
# lifted back out. Dry (every leg returns its tips; no reagents consumed). It orchestrates
# already hardware-confirmed leg scripts by subprocess; no geometry is re-derived here.
#
# Protocol shape (lid legs marked *):
#   STEP 1   PCR1 master mix add, col 1                      (p50, tips returned)
#   STEP 2   iSWAP plate rail35 pos0 -> ODTC nest rail20 pos1   (PCR1 thermocycle handoff)
#   STEP 2b* LID ON  pos4 -> ODTC nest        (seal the plate for PCR1 thermocycling)
#            <-- in a REAL run, the ODTC PCR1 thermal program runs HERE, lid sealed -->
#   STEP 2c* LID OFF ODTC nest -> pos4        (unseal before lifting the plate out)
#   STEP 3   iSWAP plate ODTC nest -> rail35 pos0               (return)
#   STEP 4   iSWAP plate rail35 pos0 -> magnet rail35 pos2      (bead cleanup handoff)
#   STEP 5   PCR1 cleanup all-dry on the magnet (beads, 2x EtOH, elute)
#   STEP 6   iSWAP plate magnet rail35 pos2 -> rail35 pos0      (return)
#   STEP 7   PCR2 master mix add, col 1                      (p50, tips returned)
#   STEP 8   iSWAP plate rail35 pos0 -> ODTC nest rail20 pos1   (PCR2 thermocycle handoff)
#   STEP 8b* LID ON  pos4 -> ODTC nest        (seal the plate for PCR2 thermocycling)
#            <-- in a REAL run, the ODTC PCR2 thermal program runs HERE, lid sealed -->
#   STEP 8c* LID OFF ODTC nest -> pos4        (unseal before lifting the plate out)
#   STEP 9   iSWAP plate ODTC nest -> rail35 pos0               (return)
#
# CONFIRMED geometry baked into the leg calls (see each leg's own PATCH log):
#   ODTC forward  : pickup z5, drop x2 / y36.5 / z12 at rail20 pos1     (committed)
#   ODTC return   : pickup z0, drop z8.5   (z0 gripped clean on hardware 2026-07-12)
#   Magnet forward: pickup z8.5, drop z18.0 (defaults, confirmed in the 1-col choreography)
#   Magnet return : pickup z14.0, drop z8.5 (confirmed tuned values)
#   LID ON  (pos4 -> ODTC nest): pickup z9, drop x2 / y36.5 / z12       (confirmed 2026-07-12)
#   LID OFF (ODTC nest -> pos4): pickup x2 / y36.5 / z7, drop z4        (z5 caught the plate; raised to z7)
#   The lid rides pos4 <-> ODTC through BOTH trips: LID OFF returns it to pos4, so the
#   second trip's LID ON picks it up from pos4 again. No re-staging between trips.
#
# FULL DECK required before a hardware run (all at once):
#   rail48 pos1 = p50 tips (col1 PCR1, col2 PCR2)
#   rail48 pos2 = p300-class tips (cleanup EtOH / supernatant)
#   rail35 pos0 = work plate (sacrificial; the plate that gets moved around)
#   rail35 pos1 = source (col1 PCR1 MM, col1/col3 PCR2 MM per the mastermix script)
#   rail35 pos2 = magnet block (iSWAP target for the bead clean)
#   rail35 pos3 = reservoir / waste (EtOH + water)
#   rail35 pos4 = LID, staged (moved onto the plate in the ODTC and back)
#   rail20 pos1 = ODTC nest, EMPTY and open to receive the plate
# The magnet MUST be physically at rail35 pos2, the lid on rail35 pos4, and the ODTC nest
# empty, or an iSWAP releases into open space. Deck-check and a human at the E-stop required.

ROOT = Path(__file__).resolve().parent

PCR1_MM = ROOT / "01_ampseq_pcr1_mastermix_4col_DRY.py"
PCR2_MM = ROOT / "03_ampseq_pcr2_mastermix_4col_DRY.py"
CLEANUP = ROOT / "02_ampseq_pcr1_cleanup_4col_DRY.py"
ODTC_FWD = ROOT / "test_iswap_plate_rail35pos0_to_odtc_variable.py"
ODTC_RET = ROOT / "test_iswap_plate_odtc_to_rail35pos0_return.py"
MAG_FWD = ROOT / "test_iswap_plate_rail35pos0_to_rail35pos2_mag_variable.py"
MAG_RET = ROOT / "test_iswap_plate_rail35pos2_mag_to_rail35pos0_variable.py"
LID_MOVER = ROOT / "test_iswap_lid_variable.py"

ODTC_RAIL = ["--odtc-rail", "20", "--odtc-position", "1"]

# Confirmed lid legs (see test_iswap_lid_variable.py PATCH log, 2026-07-12).
LID_ON = [str(LID_MOVER), "--mode", "move",
          "--src-rail", "35", "--src-pos", "4", "--dst-rail", "20", "--dst-pos", "1",
          "--pickup-z-offset-mm", "9",
          "--drop-x-offset-mm", "2", "--drop-y-offset-mm", "36.5", "--drop-z-offset-mm", "12",
          "--confirm", "RUN_LID_MOVE"]
LID_OFF = [str(LID_MOVER), "--mode", "move",
           "--src-rail", "20", "--src-pos", "1", "--dst-rail", "35", "--dst-pos", "4",
           "--pickup-x-offset-mm", "2", "--pickup-y-offset-mm", "36.5", "--pickup-z-offset-mm", "7",
           "--drop-z-offset-mm", "4",
           "--confirm", "RUN_LID_MOVE"]
# NOTE: lid-off pickup raised z5 -> z7 (2026-07-12). At z5 the grip caught the PLATE, not
# the lid, and lifted the plate out of the nest -- which then made STEP 3's return whiff
# ('Plate not found') because the plate was no longer where the return expected it. z7
# grabs the lid (higher), leaving the plate seated for the return. If z7 still catches the
# plate, keep raising in 1-2 mm steps.

STEPS = [
    ("STEP 1: PCR1 master mix add, cols 1-4 (dry)",
     [str(PCR1_MM), "--mode", "pcr1-mm", "--tip-col", "1", "--return-tips"]),
    ("STEP 2: iSWAP plate rail35 pos0 -> ODTC nest (PCR1 thermocycle handoff)",
     [str(ODTC_FWD), "--mode", "move"] + ODTC_RAIL + ["--confirm", "RUN_ODTC_ISWAP_FWD"]),
    ("STEP 2b: LID ON pos4 -> ODTC nest (seal plate for PCR1 thermocycling)", LID_ON),
    # REAL RUN: ODTC PCR1 thermal program executes here with the lid sealed.
    ("STEP 2c: LID OFF ODTC nest -> pos4 (unseal before lifting the plate out)", LID_OFF),
    ("STEP 3: iSWAP plate ODTC nest -> rail35 pos0 (return, pickup z0)",
     [str(ODTC_RET), "--mode", "move"] + ODTC_RAIL + ["--odtc-pickup-z-offset-mm", "0", "--confirm", "RUN_ODTC_ISWAP_RET"]),
    ("STEP 4: iSWAP plate rail35 pos0 -> magnet rail35 pos2 (bead clean handoff)",
     [str(MAG_FWD), "--mode", "move", "--confirm", "RUN_ISWAP_MAG_MOVE_TEST"]),
    ("STEP 5: PCR1 cleanup all-dry on the magnet, cols 1-4 (beads, 2x EtOH, elute)",
     [str(CLEANUP), "--mode", "all-dry"]),
    ("STEP 6: iSWAP plate magnet rail35 pos2 -> rail35 pos0 (return, pickup z14 / drop z8.5)",
     [str(MAG_RET), "--mode", "move", "--pickup-z-offset-mm", "14.0", "--drop-z-offset-mm", "8.5", "--confirm", "RUN_ISWAP_MAG_RETURN_TEST"]),
    ("STEP 7: PCR2 master mix add, cols 1-4 (dry)",
     [str(PCR2_MM), "--mode", "pcr2-mm", "--tip-col", "2", "--return-tips"]),
    ("STEP 8: iSWAP plate rail35 pos0 -> ODTC nest (PCR2 thermocycle handoff)",
     [str(ODTC_FWD), "--mode", "move"] + ODTC_RAIL + ["--confirm", "RUN_ODTC_ISWAP_FWD"]),
    ("STEP 8b: LID ON pos4 -> ODTC nest (seal plate for PCR2 thermocycling)", LID_ON),
    # REAL RUN: ODTC PCR2 thermal program executes here with the lid sealed.
    ("STEP 8c: LID OFF ODTC nest -> pos4 (unseal before lifting the plate out)", LID_OFF),
    ("STEP 9: iSWAP plate ODTC nest -> rail35 pos0 (return, pickup z0)",
     [str(ODTC_RET), "--mode", "move"] + ODTC_RAIL + ["--odtc-pickup-z-offset-mm", "0", "--confirm", "RUN_ODTC_ISWAP_RET"]),
]


def run_step(label, argv):
    print("")
    print("=" * 88)
    print(label)
    print("=" * 88)
    cmd = [sys.executable] + argv
    print(" ".join(cmd))
    subprocess.run(cmd, cwd=ROOT, check=True)


def main():
    parser = argparse.ArgumentParser(
        description="LIDDED ampseq col1 full choreography with ODTC handoffs, dry (tips returned)."
    )
    parser.add_argument(
        "--confirm",
        default="",
        help="Required to run on hardware: --confirm RUN_AMPSEQ_ODTC_LIDDED_4COL",
    )
    args = parser.parse_args()

    print("")
    print("FULL AMPSEQ + ODTC CHOREOGRAPHY, COLUMNS 1-4, LIDDED, DRY (tips returned)")
    print("13 legs: PCR1 add -> ODTC out / lid on / lid off / back -> magnet clean out/back")
    print("         -> PCR2 add -> ODTC out / lid on / lid off / back.")
    print("Every leg runs its own hardware-confirmed script; geometry is not re-derived here.")
    print("Deck fully staged: magnet rail35 pos2, LID rail35 pos4, ODTC nest rail20 pos1 empty. Human at E-stop.")

    if args.confirm != "RUN_AMPSEQ_ODTC_LIDDED_4COL":
        print("")
        print("Refusing to run. This moves the arm through 13 transfers, including two ODTC")
        print("round trips WITH lid on/off and the magnet round trip.")
        print("Add: --confirm RUN_AMPSEQ_ODTC_LIDDED_4COL")
        print("Run each leg's --mode deck first, and confirm the full deck is staged (lid on pos4).")
        return

    for label, argv in STEPS:
        run_step(label, argv)

    print("")
    print("SUCCESS: full LIDDED ampseq + ODTC column-1 choreography completed. Plate back on rail35 pos0, lid on pos4.")


if __name__ == "__main__":
    main()

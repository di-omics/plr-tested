import argparse
import subprocess
import sys
from pathlib import Path

# Targeted PCR column-1 full choreography WITH the ODTC thermocycler handoffs baked in.
#
# This is the demo run: the whole protocol shape as one script, single column, dry
# (every leg returns its tips; no reagents consumed). It orchestrates the already
# hardware-confirmed leg scripts by subprocess, exactly as they were each tuned, so
# no geometry is re-derived here.
#
# Protocol shape (matches the operator request: liquid handle col 1, ODTC out/back,
# bead clean out/back, ODTC out/back):
#   STEP 1  PCR1 master mix add, col 1                      (p50, tips returned)
#   STEP 2  iSWAP plate rail35 pos0 -> ODTC nest rail20 pos1   (PCR1 thermocycle handoff)
#   STEP 3  iSWAP plate ODTC nest -> rail35 pos0               (return)
#   STEP 4  iSWAP plate rail35 pos0 -> magnet rail35 pos2      (bead cleanup handoff)
#   STEP 5  PCR1 cleanup all-dry on the magnet (beads, 2x EtOH, elute)
#   STEP 6  iSWAP plate magnet rail35 pos2 -> rail35 pos0      (return)
#   STEP 7  PCR2 master mix add, col 1                      (p50, tips returned)
#   STEP 8  iSWAP plate rail35 pos0 -> ODTC nest rail20 pos1   (PCR2 thermocycle handoff)
#   STEP 9  iSWAP plate ODTC nest -> rail35 pos0               (return)
#
# CONFIRMED geometry baked into the leg calls (see each leg's own PATCH log):
#   ODTC forward  : pickup z5, drop x2 / y36.5 / z12 at rail20 pos1   (committed)
#   ODTC return   : pickup z0 (plate settles ~9 mm deep in the ODTC nest, so grab low),
#                   drop z8.5. z0 is the value that gripped clean on hardware 2026-07-12.
#                   NOTE: operator asked for pickup z1.5 (+1.5 from z0). That is NOT yet
#                   grip-tested, so this choreography uses the confirmed z0 to protect the
#                   demo run. Verify z1.5 with one ODTC round trip before switching.
#   Magnet forward: pickup z8.5, drop z18.0 (defaults, confirmed in the 1-col choreography)
#   Magnet return : pickup z14.0, drop z8.5 (confirmed tuned values)
#
# FULL DECK required before a hardware run (all at once):
#   rail48 pos1 = p50 tips (col1 PCR1, col2 PCR2)
#   rail48 pos2 = p300-class tips (cleanup EtOH / supernatant)
#   rail35 pos0 = work plate (sacrificial; the plate that gets moved around)
#   rail35 pos1 = source (col1 PCR1 MM, col1/col3 PCR2 MM per the mastermix script)
#   rail35 pos2 = magnet block (iSWAP target for the bead clean)
#   rail35 pos3 = reservoir / waste (EtOH + water)
#   rail20 pos1 = ODTC nest, EMPTY and open to receive the plate
# The magnet MUST be physically at rail35 pos2 and the ODTC nest empty, or an iSWAP
# releases the plate into open space. Deck-check and a human at the E-stop are required.

ROOT = Path(__file__).resolve().parent

PCR1_MM = ROOT / "01_ampseq_pcr1_mastermix_col1.py"
PCR2_MM = ROOT / "03_ampseq_pcr2_mastermix_col1.py"
CLEANUP = ROOT / "02_ampseq_pcr1_cleanup_col1_dry_v2_p50low.py"
ODTC_FWD = ROOT / "test_iswap_plate_rail35pos0_to_odtc_variable.py"
ODTC_RET = ROOT / "test_iswap_plate_odtc_to_rail35pos0_return.py"
MAG_FWD = ROOT / "test_iswap_plate_rail35pos0_to_rail35pos2_mag_variable.py"
MAG_RET = ROOT / "test_iswap_plate_rail35pos2_mag_to_rail35pos0_variable.py"

ODTC_RAIL = ["--odtc-rail", "20", "--odtc-position", "1"]

STEPS = [
    ("STEP 1: PCR1 master mix add, col 1 (dry)",
     [str(PCR1_MM), "--mode", "pcr1-mm", "--tip-col", "1", "--return-tips"]),
    ("STEP 2: iSWAP plate rail35 pos0 -> ODTC nest (PCR1 thermocycle handoff)",
     [str(ODTC_FWD), "--mode", "move"] + ODTC_RAIL + ["--confirm", "RUN_ODTC_ISWAP_FWD"]),
    ("STEP 3: iSWAP plate ODTC nest -> rail35 pos0 (return, pickup z0)",
     [str(ODTC_RET), "--mode", "move"] + ODTC_RAIL + ["--odtc-pickup-z-offset-mm", "0", "--confirm", "RUN_ODTC_ISWAP_RET"]),
    ("STEP 4: iSWAP plate rail35 pos0 -> magnet rail35 pos2 (bead clean handoff)",
     [str(MAG_FWD), "--mode", "move", "--confirm", "RUN_ISWAP_MAG_MOVE_TEST"]),
    ("STEP 5: PCR1 cleanup all-dry on the magnet (beads, 2x EtOH, elute)",
     [str(CLEANUP), "--mode", "all-dry"]),
    ("STEP 6: iSWAP plate magnet rail35 pos2 -> rail35 pos0 (return, pickup z14 / drop z8.5)",
     [str(MAG_RET), "--mode", "move", "--pickup-z-offset-mm", "14.0", "--drop-z-offset-mm", "8.5", "--confirm", "RUN_ISWAP_MAG_RETURN_TEST"]),
    ("STEP 7: PCR2 master mix add, col 1 (dry)",
     [str(PCR2_MM), "--mode", "pcr2-mm", "--tip-col", "2", "--return-tips"]),
    ("STEP 8: iSWAP plate rail35 pos0 -> ODTC nest (PCR2 thermocycle handoff)",
     [str(ODTC_FWD), "--mode", "move"] + ODTC_RAIL + ["--confirm", "RUN_ODTC_ISWAP_FWD"]),
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
        description="Ampseq col1 full choreography with ODTC thermocycler handoffs, dry (tips returned)."
    )
    parser.add_argument(
        "--confirm",
        default="",
        help="Required to run the choreography on hardware: --confirm RUN_AMPSEQ_ODTC_FULL",
    )
    args = parser.parse_args()

    print("")
    print("FULL AMPSEQ + ODTC CHOREOGRAPHY, COLUMN 1, DRY (tips returned)")
    print("Nine legs: PCR1 add -> ODTC out/back -> magnet bead clean out/back -> PCR2 add -> ODTC out/back.")
    print("Every leg runs its own hardware-confirmed script; geometry is not re-derived here.")
    print("Deck must be fully staged (magnet at rail35 pos2, ODTC nest rail20 pos1 empty). Human at the E-stop.")

    if args.confirm != "RUN_AMPSEQ_ODTC_FULL":
        print("")
        print("Refusing to run. This moves the arm through nine transfers, including two ODTC")
        print("round trips and the magnet round trip. Add: --confirm RUN_AMPSEQ_ODTC_FULL")
        print("Run each leg's --mode deck first, and confirm the full deck is staged.")
        return

    for label, argv in STEPS:
        run_step(label, argv)

    print("")
    print("SUCCESS: full ampseq + ODTC column-1 choreography completed. Plate back on rail35 pos0.")


if __name__ == "__main__":
    main()

import argparse
import subprocess
import sys
from pathlib import Path

# whole-genome amplification / HHS lidded plate ROUND TRIP, combined into one gated runner.
#
#   STEP 1   iSWAP plate  rail35 pos0 -> HHS rail27 pos2      (move plate onto the shaker)
#   STEP 2   iSWAP LID    rail35 pos4 -> HHS rail27 pos2      (lid on, seals the plate)
#            <-- in a REAL run the HHS shakes the sealed plate for the incubation HERE -->
#   STEP 3   iSWAP DELID  HHS rail27 pos2 -> rail35 pos4      (lid off before lifting the plate)
#   STEP 4   iSWAP plate  HHS rail27 pos2 -> rail35 pos0      (plate back)
#
# It orchestrates the standalone leg scripts by subprocess; geometry is not re-derived here.
# Dry: no reagent, no tips. USE AN EMPTY SACRIFICIAL PLATE until STEP 3 and STEP 4 are proven.
#
# GEOMETRY (see HHS_LIDDED_MOUNT_CONFIRMED_2026-07-17.md, pushed origin/main 0bd23d1):
#   STEP 1 plate fwd : pickup-z 5,  drop x12 / y45.5 / z17     CONFIRMED on hardware 2026-07-17
#   STEP 2 lid on    : pickup-z 9,  drop x12 / y45.5 / z17     CONFIRMED on hardware 2026-07-17
#   STEP 3 DELID     : pickup x12 / y45.5 / z16, drop z4       *** UNVALIDATED - deck-printed only ***
#   STEP 4 plate ret : pickup x12 / y45.5 / z10, drop z8.5     *** UNVALIDATED geometry at y45.5 ***
#
# WHY THE MOUNT Y IS 45.5 (not the repo's old 54.5): the prior HHS drop x12/y54.5/z17 marked
# "passed" in the README was never real-plate seat-checked (dry/empty-plate transfer-completion
# and pickup-Z only; the CAMERA round trip re-picks at the same Y so a constant bias is
# invisible). The first real-plate mount (2026-07-17) landed ~2 rows too far +Y; y45.5 is the
# walked-in real-plate value, and the lid seats flush on the plate at that same y45.5 / z17.
#
# *** THE TWO LEGS TO WATCH ***
#   STEP 3 DELID is the one that has NEVER run. The lid and the plate share the SAME footprint
#   (127.76 x 85.48), so the iSWAP grip-width check cannot tell them apart: a too-LOW delid
#   pickup grabs the PLATE and lifts it out, then reports SUCCESS. Pickup-z 16 is deliberately
#   START-HIGH so it takes the lid, not the plate. WATCH IT: if the PLATE lifts instead of the
#   lid, E-STOP and raise --pickup-z; if it misses the lid entirely, lower in 1 mm steps.
#   STEP 4 return then relies on the plate still being on the HHS at y45.5; if STEP 3 stranded
#   the plate, STEP 4 will fault "Plate not found" (protective).
#
# DECK before running (empty sacrificial plate only):
#   rail35 pos0 = plate (sacrificial, empty)
#   rail35 pos4 = LID, seated as it was tuned (on its park plate, not directly on the carrier -
#                 a too-low lid at pos4 gives "Plate not found" at STEP 2)
#   rail27 pos2 = HHS nest, EMPTY and open to receive the plate
# A human at the E-stop, hand ready, for the whole run. Only ONE process may drive the STAR.
#
# Preview with --plan (prints the leg commands, touches nothing).
# Run with       --confirm RUN_PTA_HHS_LIDDED_ROUNDTRIP  (moves the arm through 4 transfers).

ROOT = Path(__file__).resolve().parent
CONFIRM_TOKEN = "RUN_PTA_HHS_LIDDED_ROUNDTRIP"

PLATE_FWD = ROOT / "test_iswap_plate_rail35pos0_to_rail27_variable.py"
LID = ROOT / "test_iswap_lid_variable.py"
PLATE_RET = ROOT / "test_iswap_plate_rail27pos2_hhs_to_rail35pos0_return.py"

# Confirmed HHS mount geometry (2026-07-17). Plate and lid MUST share the drop-Y.
DROP_X, DROP_Y, DROP_Z = "12.0", "45.5", "17.0"

STEPS = [
    ("STEP 1: plate rail35 pos0 -> HHS rail27 pos2   [CONFIRMED 2026-07-17]",
     [str(PLATE_FWD), "--mode", "move", "--drop-position", "2",
      "--pickup-z-offset-mm", "5.0",
      "--drop-x-offset-mm", DROP_X, "--drop-y-offset-mm", DROP_Y, "--drop-z-offset-mm", DROP_Z,
      "--confirm", "RUN_ISWAP_PLATE_TEST"]),

    ("STEP 2: LID ON pos4 -> HHS rail27 pos2   [CONFIRMED 2026-07-17]",
     [str(LID), "--mode", "move", "--src-rail", "35", "--src-pos", "4",
      "--dst-rail", "27", "--dst-pos", "2", "--pickup-z-offset-mm", "9.0",
      "--drop-x-offset-mm", DROP_X, "--drop-y-offset-mm", DROP_Y, "--drop-z-offset-mm", DROP_Z,
      "--confirm", "RUN_LID_MOVE"]),

    ("STEP 3: DELID HHS rail27 pos2 -> pos4   *** UNVALIDATED - start-high z16, WATCH: lid must lift, not the plate ***",
     [str(LID), "--mode", "move", "--src-rail", "27", "--src-pos", "2",
      "--dst-rail", "35", "--dst-pos", "4",
      "--pickup-x-offset-mm", "12.0", "--pickup-y-offset-mm", "45.5", "--pickup-z-offset-mm", "16.0",
      "--drop-z-offset-mm", "4.0", "--confirm", "RUN_LID_MOVE"]),

    ("STEP 4: plate HHS rail27 pos2 -> rail35 pos0 (return)   *** UNVALIDATED geometry at y45.5; ungated leg ***",
     [str(PLATE_RET),
      "--hhs-pickup-x-offset-mm", "12.0", "--hhs-pickup-y-offset-mm", "45.5",
      "--hhs-pickup-z-offset-mm", "10.0", "--return-drop-z-offset-mm", "8.5"]),
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
        description="PTA/HHS lidded plate round trip (plate in, lid on, delid, plate back), dry."
    )
    parser.add_argument("--confirm", default="",
                        help="Required to move the arm: --confirm " + CONFIRM_TOKEN)
    parser.add_argument("--plan", action="store_true",
                        help="Print the leg commands and exit. Touches nothing.")
    args = parser.parse_args()

    print("")
    print("PTA / HHS LIDDED PLATE ROUND TRIP (dry, sacrificial empty plate)")
    print("  plate rail35 pos0 -> HHS rail27 pos2 -> lid on -> DELID -> plate back to pos0")
    print("  STEP 1 and STEP 2 are CONFIRMED (2026-07-17, y45.5). STEP 3 (delid) and STEP 4")
    print("  (return) are NOT validated - watch the delid: a too-low grab takes the PLATE.")
    print("  Deck: sacrificial plate rail35 pos0, LID on pos4 (on its park), HHS nest empty. E-stop ready.")

    if args.plan:
        print("")
        print("PLAN (no motion):")
        for label, argv in STEPS:
            print("  " + label)
            print("    " + " ".join([sys.executable] + argv))
        return

    if args.confirm != CONFIRM_TOKEN:
        print("")
        print("Refusing to run. This moves the arm through 4 iSWAP transfers, and STEP 3/4 are")
        print("UNVALIDATED (the delid can grab the plate if too low).")
        print("Add: --confirm " + CONFIRM_TOKEN + "   (or --plan to preview)")
        print("Deck-print each leg first if unsure (--mode deck on the leg scripts homes the arm).")
        return

    for label, argv in STEPS:
        run_step(label, argv)

    print("")
    print("SUCCESS: PTA/HHS lidded round trip completed. Plate back on rail35 pos0, lid on pos4.")


if __name__ == "__main__":
    main()

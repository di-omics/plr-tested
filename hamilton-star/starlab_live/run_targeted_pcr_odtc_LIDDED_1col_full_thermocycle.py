import argparse
import os
import subprocess
import sys
from pathlib import Path

# Targeted PCR column-1 full choreography, LIDDED, with the two ODTC THERMAL PROGRAMS
# baked into the flow.
#
# Copied 2026-07-16 from run_targeted_pcr_odtc_LIDDED_1col_full_dry.py (tag
# targeted_pcr-lidded-inwellmix-2026-07-16, 13/13 clean twice). The parent marked the two
# points where the cycler should run with a comment:
#     "REAL RUN: ODTC PCR1 thermal program executes here with the lid sealed."
# This variant makes those two comments real, and nothing else.
#
# PATCH LOG
#   2026-07-16  Created from the validated 13-leg lidded choreography. Added two thermal
#               legs (STEP 2t PCR1, STEP 8t PCR2) between LID ON and LID OFF on each ODTC
#               trip, gated behind --thermocycle. No geometry changed. No leg script
#               changed. No parent file edited.
#   2026-07-16  Dry now CALLS the cycler instead of skipping it. The default dry leg does a
#               read-only GetStatus probe at STEP 2t / 8t, so a dry run proves the ODTC is
#               reachable and answering at the exact point in the flow where it will later
#               be asked to cycle. It cannot heat and cannot move the door. --no-odtc
#               restores the old skip-entirely behaviour (pure motion, no cycler at all).
#   2026-07-16  RUN ON HARDWARE, default mode: 15 steps, 22 SUCCESS, 0 failures. All 13
#               motion legs plus both ODTC calls; the cycler answered at 2t and 8t; deck
#               self-returned (plate rail35 pos0, lid pos4). This is the validated build.
#               A --thermocycle run was also started and reached STEP 2t cleanly before
#               being stopped in pre-warm on purpose, which is what settled the
#               Reset-with-plate-loaded question below. --thermocycle has NOT yet been run
#               to completion.
#
# THE POINT OF THIS FILE
#   Dry (default)       : 13 motion legs, and the ODTC is CALLED read-only at STEP 2t / 8t
#                         (GetStatus). Proves the whole chain reaches the cycler. No heat.
#   --no-odtc           : 13 motion legs, cycler never contacted. The validated parent.
#   --thermocycle       : the same 13 legs, and the plate actually thermocycles in the ODTC
#                         while the lid is sealed on it.
#
# WHY THE DRY CALL IS A RAW PROBE AND NOT THE PLR BRING-UP
#   At STEP 2t the plate is seated in the nest with a lid on it. 02_odtc_bringup.py (and
#   05's setup) send Reset + Initialize, and Initialize HOMES THE DOOR. Homing the door
#   with a plate and lid sitting in the nest is not something to do casually. The raw probe
#   (01_odtc_probe_raw.py) only ever sends read-only queries: it never sends Reset,
#   Initialize, OpenDoor, or ExecuteMethod. That is why the dry call uses it.
#
# ANSWERED ON HARDWARE 2026-07-16: Reset + Initialize with a plate loaded is BENIGN.
#   05_odtc_run_protocol.py calls setup(), which sends Reset + Initialize and therefore
#   homes the door. The worry was that it does this with the plate and lid already seated
#   in the nest. A --thermocycle run was started and reached STEP 2t: the choreography
#   found odtc_lib on the Pi, drove 05, uploaded targeted-pcr-round1, and began pre-warming, all
#   with the plate and lid in the nest, with zero failures. Nothing was disturbed. The run
#   was then stopped by operator choice during the lid pre-warm (block never left 25 C), so
#   the thermal programs themselves are still not run end to end inside this choreography.
#
# STILL OPEN: this choreography never CLOSES the ODTC door around the thermal leg. The
#   standalone targeted-pcr-round1 run on 2026-07-10 completed regardless of door state, but an
#   open door is not a thermally sound way to run a real PCR. Worth settling before
#   --thermocycle is pointed at real chemistry.
#
# THE THERMAL LEGS (from instrument-integrations/odtc, hardware-validated 2026-07-10)
#   PCR1: program `targeted-pcr-round1`  98/30s x1, (98/10s, 67/15s, 72/15s) x30, 72/60s, 10 C hold
#   PCR2: program `targeted-pcr-round2`  98/30s x1, (98/10s, 67/15s, 72/15s) x8,  72/60s,  4 C hold
#   Source: Targeted PCR Library Preparation (di-omics internal, 2026-05-28), PCR1/PCR2 tables.
#   targeted-pcr-round1 ran end to end on the physical ODTC 2026-07-10: 30/30 cycles, 36.6 min,
#   block held setpoints to a mean 0.27 C. targeted-pcr-round2 is the same shape, not yet run.
#   Wall clock with --thermocycle: roughly +37 min (PCR1) and +15 min (PCR2) on top of the
#   motion. The ODTC leg BLOCKS until the program completes; that is intended.
#
# WHERE THE ODTC CODE LIVES
#   instrument-integrations/odtc/ is a SIBLING tree to hamilton-star/. run_on_pi.sh only
#   rsyncs hamilton-star/, so the cycler code would not exist on the Pi. run_on_pi.sh now
#   also syncs that folder alongside as odtc_lib/ and forwards $ODTC_IP. This script looks
#   in both places (local checkout, and the Pi's odtc_lib/) and fails loudly if neither is
#   present AND --thermocycle was asked for.
#
# FAIL BEFORE YOU MOVE
#   With --thermocycle, this script pre-flights the cycler (address set, script present,
#   read-only GetStatus probe) BEFORE the first leg. Discovering the ODTC is unreachable
#   after 6 legs would strand a plate in the nest with the arm holding a lid.
#
# Protocol shape (lid legs marked *, thermal legs marked t):
#   STEP 1   PCR1 master mix add, col 1                      (p50, tips returned)
#   STEP 2   iSWAP plate rail35 pos0 -> ODTC nest rail20 pos1   (PCR1 thermocycle handoff)
#   STEP 2b* LID ON  pos4 -> ODTC nest        (seal the plate for PCR1 thermocycling)
#   STEP 2t  ODTC PCR1 THERMAL PROGRAM, lid sealed            (skipped unless --thermocycle)
#   STEP 2c* LID OFF ODTC nest -> pos4        (unseal before lifting the plate out)
#   STEP 3   iSWAP plate ODTC nest -> rail35 pos0               (return)
#   STEP 4   iSWAP plate rail35 pos0 -> magnet rail35 pos2      (bead cleanup handoff)
#   STEP 5   PCR1 cleanup all-dry on the magnet (beads, 2x EtOH, elute)
#   STEP 6   iSWAP plate magnet rail35 pos2 -> rail35 pos0      (return)
#   STEP 7   PCR2 master mix add, col 1                      (p50, tips returned)
#   STEP 8   iSWAP plate rail35 pos0 -> ODTC nest rail20 pos1   (PCR2 thermocycle handoff)
#   STEP 8b* LID ON  pos4 -> ODTC nest        (seal the plate for PCR2 thermocycling)
#   STEP 8t  ODTC PCR2 THERMAL PROGRAM, lid sealed            (skipped unless --thermocycle)
#   STEP 8c* LID OFF ODTC nest -> pos4        (unseal before lifting the plate out)
#   STEP 9   iSWAP plate ODTC nest -> rail35 pos0               (return)
#
# NOT WET-READY EVEN WITH --thermocycle. This flow returns its tips (--return-tips) and
# consumes no reagent. --thermocycle makes the CYCLER real, not the chemistry. A wet run
# additionally needs: fresh tips per column, the incubation times that are coded nowhere,
# and the operator to load actual master mix. See targeted_pcr_state_handoff.md.
#
# CONFIRMED geometry baked into the leg calls (see each leg's own PATCH log):
#   ODTC forward  : pickup z5, drop x2 / y36.5 / z12 at rail20 pos1     (committed)
#   ODTC return   : pickup z0, drop z8.5   (z0 gripped clean on hardware 2026-07-12)
#   Magnet forward: pickup z8.5, drop z18.0 (defaults, confirmed in the 1-col choreography)
#   Magnet return : pickup z14.0, drop z8.5 (confirmed tuned values)
#   LID ON  (pos4 -> ODTC nest): pickup z9, drop x2 / y36.5 / z12       (confirmed 2026-07-12)
#   LID OFF (ODTC nest -> pos4): pickup x2 / y36.5 / z7, drop z4        (z5 caught the plate; raised to z7)
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

PCR1_MM = ROOT / "01_targeted_pcr_round1_mastermix_col1.py"
PCR2_MM = ROOT / "03_targeted_pcr_round2_mastermix_col1.py"
CLEANUP = ROOT / "02_targeted_pcr_round1_cleanup_col1_dry_v2_p50low.py"
ODTC_FWD = ROOT / "test_iswap_plate_rail35pos0_to_odtc_variable.py"
ODTC_RET = ROOT / "test_iswap_plate_odtc_to_rail35pos0_return.py"
MAG_FWD = ROOT / "test_iswap_plate_rail35pos0_to_rail35pos2_mag_variable.py"
MAG_RET = ROOT / "test_iswap_plate_rail35pos2_mag_to_rail35pos0_variable.py"
LID_MOVER = ROOT / "test_iswap_lid_variable.py"

# The ODTC control code is a sibling tree, not part of hamilton-star. Look for it in the
# local checkout first, then where run_on_pi.sh drops it on the Pi.
ODTC_LIB_CANDIDATES = [
    ROOT.parent.parent / "instrument-integrations" / "odtc",  # local repo checkout
    ROOT.parent / "odtc_lib",                                 # synced onto the Pi
]

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


def find_odtc_lib():
    """Return the odtc/ directory that has the runner, or None."""
    for cand in ODTC_LIB_CANDIDATES:
        if (cand / "05_odtc_run_protocol.py").exists():
            return cand
    return None


def odtc_thermal_argv(odtc_lib, program, odtc_ip):
    """The real cycler invocation for one thermal leg. This heats."""
    argv = [str(odtc_lib / "05_odtc_run_protocol.py"),
            "--program", program,
            "--confirm", "i-am-watching"]
    if odtc_ip:
        argv += ["--ip", odtc_ip]
    return argv


def odtc_dry_call_argv(odtc_lib, odtc_ip):
    """A read-only touch of the cycler for a dry thermal leg.

    GetStatus only. The raw probe never sends Reset, Initialize, OpenDoor, or
    ExecuteMethod, so this cannot heat the block and cannot move the door out from under
    the plate that is sitting in the nest at this point in the flow.
    """
    argv = [str(odtc_lib / "01_odtc_probe_raw.py"),
            "--timeout", "8", "--commands", "GetStatus"]
    if odtc_ip:
        # Omitted rather than passed as None so --plan works with no address set; the
        # pre-flight hard-requires an address before anything actually runs.
        argv += ["--ip", odtc_ip]
    return argv


def build_steps(mode, odtc_lib, odtc_ip):
    """The 13 motion legs, with the two thermal legs woven in at the marked points.

    mode is one of:
      "call"  (default) read-only GetStatus at each thermal leg. Proves the cycler is
              reachable at that moment in the flow. No heat, no door motion.
      "skip"  thermal legs carry argv None: narrated, cycler never contacted.
      "cycle" the real thermal programs run. This heats.

    The 13 MOTION legs are byte-identical in every mode, and identical to the validated
    parent run_targeted_pcr_odtc_LIDDED_1col_full_dry.py.
    """
    def thermal(step, program, minutes):
        label = (f"{step}: ODTC {program} THERMAL PROGRAM, lid sealed "
                 f"(~{minutes} min, blocks until the cycler finishes)")
        if mode in ("cycle", "call") and odtc_lib is None:
            # Narrate rather than crash: preflight_odtc refuses before anything moves.
            return (label + "  [ODTC code NOT FOUND -- pre-flight will refuse]", None)
        if mode == "cycle":
            return (label, odtc_thermal_argv(odtc_lib, program, odtc_ip))
        if mode == "call":
            return (f"{step}: ODTC {program} leg -- DRY, calling the cycler read-only "
                    f"(GetStatus). No heat. Real run would cycle ~{minutes} min here.",
                    odtc_dry_call_argv(odtc_lib, odtc_ip))
        return (label + "  [--no-odtc: SKIPPED, cycler not contacted]", None)

    return [
        ("STEP 1: PCR1 master mix add, col 1 (dry)",
         [str(PCR1_MM), "--mode", "pcr1-mm", "--tip-col", "1", "--return-tips"]),
        ("STEP 2: iSWAP plate rail35 pos0 -> ODTC nest (PCR1 thermocycle handoff)",
         [str(ODTC_FWD), "--mode", "move"] + ODTC_RAIL + ["--confirm", "RUN_ODTC_ISWAP_FWD"]),
        ("STEP 2b: LID ON pos4 -> ODTC nest (seal plate for PCR1 thermocycling)", LID_ON),
        thermal("STEP 2t", "targeted-pcr-round1", 37),
        ("STEP 2c: LID OFF ODTC nest -> pos4 (unseal before lifting the plate out)", LID_OFF),
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
        ("STEP 8b: LID ON pos4 -> ODTC nest (seal plate for PCR2 thermocycling)", LID_ON),
        thermal("STEP 8t", "targeted-pcr-round2", 15),
        ("STEP 8c: LID OFF ODTC nest -> pos4 (unseal before lifting the plate out)", LID_OFF),
        ("STEP 9: iSWAP plate ODTC nest -> rail35 pos0 (return, pickup z0)",
         [str(ODTC_RET), "--mode", "move"] + ODTC_RAIL + ["--odtc-pickup-z-offset-mm", "0", "--confirm", "RUN_ODTC_ISWAP_RET"]),
    ]


def run_step(label, argv):
    print("")
    print("=" * 88)
    print(label)
    print("=" * 88)
    if argv is None:
        print("DRY: the ODTC thermal program is NOT run and the cycler is not contacted.")
        print("     Re-run with --thermocycle to make this leg execute for real.")
        return
    cmd = [sys.executable] + argv
    print(" ".join(cmd))
    subprocess.run(cmd, cwd=ROOT, check=True)


def preflight_odtc(odtc_lib, odtc_ip):
    """Prove the cycler is there BEFORE the arm moves. Raises SystemExit on failure.

    Stranding a plate in the nest because the ODTC was unreachable is the failure this
    exists to prevent: by STEP 2t the plate is in the cycler with a lid on it and the
    only way out is the rest of the choreography.
    """
    print("")
    print("--- ODTC pre-flight (read-only, before any motion) ---")
    if odtc_lib is None:
        raise SystemExit(
            "--thermocycle asked for, but the ODTC code was not found in any of:\n  "
            + "\n  ".join(str(c) for c in ODTC_LIB_CANDIDATES)
            + "\nOn the Pi, run_on_pi.sh syncs it as odtc_lib/. Update run_on_pi.sh or run"
              " from a checkout that has instrument-integrations/odtc."
        )
    if not odtc_ip:
        raise SystemExit(
            "--thermocycle asked for, but no ODTC address. Pass --odtc-ip or set ODTC_IP."
        )
    probe = odtc_lib / "01_odtc_probe_raw.py"
    if not probe.exists():
        raise SystemExit(f"ODTC probe not found at {probe}")
    result = subprocess.run(
        [sys.executable, str(probe), "--ip", odtc_ip, "--timeout", "8",
         "--commands", "GetStatus"],
        cwd=odtc_lib,
    )
    if result.returncode != 0:
        raise SystemExit(
            "ODTC did not answer the read-only probe. Refusing to start the choreography:"
            " a plate would be parked in an unreachable cycler. Fix the link first"
            " (the Pi's link-local address does not survive a reboot)."
        )
    print("ODTC pre-flight OK.")


def main():
    parser = argparse.ArgumentParser(
        description="LIDDED targeted_pcr col1 full choreography with ODTC handoffs and the two "
                    "ODTC thermal programs baked in (gated behind --thermocycle)."
    )
    parser.add_argument(
        "--confirm",
        default="",
        help="Required to run on hardware: --confirm RUN_TARGETED_PCR_ODTC_LIDDED_FULL",
    )
    parser.add_argument(
        "--thermocycle",
        action="store_true",
        help="Actually run the ODTC PCR1/PCR2 thermal programs at STEP 2t and STEP 8t. "
             "THIS HEATS. Default is a dry read-only call to the cycler instead.",
    )
    parser.add_argument(
        "--no-odtc",
        action="store_true",
        help="Do not contact the cycler at all: the thermal legs are narrated and skipped. "
             "This is the validated parent's behaviour (pure motion).",
    )
    parser.add_argument(
        "--odtc-ip",
        default=os.environ.get("ODTC_IP"),
        help="ODTC address, only needed with --thermocycle. Defaults to $ODTC_IP.",
    )
    parser.add_argument(
        "--plan",
        action="store_true",
        help="Print the step plan and exit. Touches nothing.",
    )
    args = parser.parse_args()

    if args.thermocycle and args.no_odtc:
        parser.error("--thermocycle and --no-odtc are contradictory. Pick one.")
    mode = "cycle" if args.thermocycle else ("skip" if args.no_odtc else "call")

    odtc_lib = find_odtc_lib()
    steps = build_steps(mode, odtc_lib, args.odtc_ip)

    banner = {"cycle": ", THERMOCYCLING LIVE (block heats)",
              "call": ", DRY (cycler called read-only, no heat)",
              "skip": ", DRY (cycler not contacted)"}[mode]
    print("")
    print("FULL TARGETED PCR + ODTC CHOREOGRAPHY, COLUMN 1, LIDDED" + banner)
    print("13 motion legs: PCR1 add -> ODTC out / lid on / [PCR1] / lid off / back")
    print("                -> magnet clean out/back -> PCR2 add")
    print("                -> ODTC out / lid on / [PCR2] / lid off / back.")
    print("Every leg runs its own hardware-confirmed script; geometry is not re-derived here.")
    print("")
    if mode == "cycle":
        print("THERMOCYCLE MODE: STEP 2t runs targeted-pcr-round1 (~37 min) and STEP 8t runs")
        print("targeted-pcr-round2 (~15 min) on the real cycler, each with the lid sealed on the")
        print("plate. Tips are still returned and no reagent is consumed: this makes the")
        print("CYCLER real, not the chemistry.")
        print(f"ODTC address: {args.odtc_ip or '<unset, will refuse>'}")
    elif mode == "call":
        print("DRY: the 13 motion legs run, and at STEP 2t / 8t the ODTC is CALLED")
        print("read-only (GetStatus) at the exact point it would otherwise cycle. This")
        print("proves the chain reaches the cycler. It cannot heat and cannot move the")
        print("door out from under the plate. Real cycling needs --thermocycle.")
        print(f"ODTC address: {args.odtc_ip or '<unset, will refuse>'}")
    else:
        print("DRY: the two thermal legs are narrated and skipped. The cycler is never")
        print("contacted. This is the validated 13-leg motion choreography.")
    print("Deck fully staged: magnet rail35 pos2, LID rail35 pos4, ODTC nest rail20 pos1 empty. Human at E-stop.")

    if args.plan:
        print("")
        print("--- PLAN (nothing executed) ---")
        for label, argv in steps:
            print("")
            print(label)
            if argv is None:
                print("    (skipped: --thermocycle not set)")
            else:
                print("    " + " ".join([Path(sys.executable).name] + argv))
        print("")
        print(f"{len(steps)} steps. ODTC code: {odtc_lib if odtc_lib else 'NOT FOUND'}")
        return

    if args.confirm != "RUN_TARGETED_PCR_ODTC_LIDDED_FULL":
        print("")
        print("Refusing to run. This moves the arm through 13 transfers, including two ODTC")
        print("round trips WITH lid on/off and the magnet round trip.")
        print("Add: --confirm RUN_TARGETED_PCR_ODTC_LIDDED_FULL")
        print("Run each leg's --mode deck first, and confirm the full deck is staged (lid on pos4).")
        print("Use --plan to see the step list without touching anything.")
        return

    # Any mode that touches the cycler is pre-flighted before the arm moves. Reaching
    # STEP 2t and finding the ODTC unreachable would leave a plate in the nest under a
    # sealed lid, mid-choreography.
    if mode in ("cycle", "call"):
        preflight_odtc(odtc_lib, args.odtc_ip)

    for label, argv in steps:
        run_step(label, argv)

    print("")
    if mode == "cycle":
        print("SUCCESS: full LIDDED targeted_pcr + ODTC column-1 choreography completed WITH both")
        print("thermal programs run on the cycler. Plate back on rail35 pos0, lid on pos4.")
        print("NOTE: the block holds its final temperature after a program (post_heating).")
    elif mode == "call":
        print("SUCCESS: full LIDDED targeted_pcr + ODTC column-1 choreography completed, DRY,")
        print("with the ODTC called read-only at both thermal legs. The cycler answered")
        print("at each point it would cycle. Nothing was heated. Plate back on rail35 pos0,")
        print("lid on pos4.")
    else:
        print("SUCCESS: full LIDDED targeted_pcr + ODTC column-1 choreography completed, DRY.")
        print("The cycler was not contacted. Plate back on rail35 pos0, lid on pos4.")


if __name__ == "__main__":
    main()

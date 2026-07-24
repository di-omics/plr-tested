import argparse
import subprocess
import sys
from pathlib import Path

# Generic methylation-sequencing column-1 choreography. Public reagent and
# cleanup legs are numbered stages, and public ODTC names are water-only motion
# checks. Exact biological methods stay in operator-owned profiles.
#
# The runner does not derive geometry. It reuses the scoped leg scripts and the
# confirmed iSWAP arguments below. The magnet must be at rail35 pos2, the ODTC
# nest must be empty, and a human must remain at the E-stop for hardware motion.
# Confirmed motion values: ODTC forward pickup z5/drop x2,y36.5,z12; ODTC return
# pickup z0/drop z8.5; magnet forward pickup z8.5/drop z18; magnet return pickup
# z14/drop z8.5. These hardware constants are intentionally preserved.

ROOT = Path(__file__).resolve().parent           # .../starlab_live/methylation_seq
STARLAB = ROOT.parent                            # .../starlab_live

REAGENTS = ROOT / "methylation_seq_reagent_adds.py"
CLEANUP = ROOT / "methylation_seq_cleanup.py"

ODTC_FWD = STARLAB / "test_iswap_plate_rail35pos0_to_odtc_variable.py"
ODTC_RET = STARLAB / "test_iswap_plate_odtc_to_rail35pos0_return.py"
MAG_FWD = STARLAB / "test_iswap_plate_rail35pos0_to_rail35pos2_mag_variable.py"
MAG_RET = STARLAB / "test_iswap_plate_rail35pos2_mag_to_rail35pos0_variable.py"

ODTC_RAIL = ["--odtc-rail", "20", "--odtc-position", "1"]

CONFIRM_PHRASE = "RUN_METHYLATION_SEQ_ODTC_FULL"
LABWARE_ACK = "CELLTREAT_229195_WORK_SOURCE"


def odtc_command(program: str) -> str:
    """The command the operator runs (detached, from the instrument-integrations tree)."""
    return (f"instrument-integrations/run_on_pi.sh odtc/05_odtc_run_protocol.py "
            f"--program {program} --ip $ODTC_IP --confirm i-am-watching")


def build_plan(sim_lh: bool):
    """Return the ordered list of legs. Each leg is one of:
        ("run",  label, argv)   subprocess a leg script
        ("note", label, text)   print an operator instruction, do not execute
    In --sim-lh, the reagent/cleanup legs get --dry (chatterbox) and the iSWAP legs
    downgrade to notes (they are hardware-only, no chatterbox equivalent).
    """
    lh_extra = ["--dry"] if sim_lh else []

    def reagent(mode, tip_col):
        argv = [str(REAGENTS), "--mode", mode, "--tip-col", str(tip_col), "--return-tips"] + lh_extra
        return ("run", f"reagent add: {mode} (tip col {tip_col})", argv)

    def cleanup(name):
        # This is a dry, no-reagent rehearsal, so return tips (methylation_seq_cleanup defaults to
        # discard for real reagent/ethanol runs). A real run drops the --return-tips.
        argv = [str(CLEANUP), "--cleanup", name, "--mode", "all", "--return-tips"] + lh_extra
        return ("run", f"SPRI cleanup: {name}", argv)

    def iswap(label, script, extra):
        argv = [str(script), "--mode", "move"] + extra
        if sim_lh:
            return ("note", f"iSWAP (hardware-only, skipped in --sim-lh): {label}",
                    "on hardware this runs: " + " ".join(["python"] + argv))
        return ("run", f"iSWAP move: {label}", argv)

    def odtc_out_back(program, leg_label):
        return [
            iswap(f"work rail35 pos0 -> ODTC nest ({leg_label})", ODTC_FWD,
                  ODTC_RAIL + ["--confirm", "RUN_ODTC_ISWAP_FWD"]),
            ("note", f"ODTC thermal: {program}",
             "run this detached on the Pi, wait for completion, then continue:\n      "
             + odtc_command(program)),
            iswap(f"ODTC nest -> work rail35 pos0 ({leg_label} return)", ODTC_RET,
                  ODTC_RAIL + ["--odtc-pickup-z-offset-mm", "0", "--confirm", "RUN_ODTC_ISWAP_RET"]),
        ]

    def magnet_out():
        return iswap("work rail35 pos0 -> magnet rail35 pos2", MAG_FWD,
                     ["--confirm", "RUN_ISWAP_MAG_MOVE_TEST"])

    def magnet_back():
        return iswap("magnet rail35 pos2 -> work rail35 pos0", MAG_RET,
                     ["--pickup-z-offset-mm", "14.0", "--drop-z-offset-mm", "8.5",
                      "--confirm", "RUN_ISWAP_MAG_RETURN_TEST"])

    plan = []
    plan.append(("note", "start",
                 "Use only a water-filled rehearsal plate with the public plan. "
                 "Biological setup belongs to the operator-approved local method."))

    plan.append(reagent("stage-1", 1))
    plan += odtc_out_back("methylation-seq-stage-1", "stage 1")
    plan.append(reagent("stage-2", 1))
    plan += odtc_out_back("methylation-seq-stage-2", "stage 2")
    plan.append(reagent("stage-3", 2))
    plan.append(reagent("stage-4", 2))
    plan += odtc_out_back("methylation-seq-stage-3", "stage 3")

    plan.append(magnet_out())
    plan.append(cleanup("cleanup-1"))
    plan.append(magnet_back())

    plan.append(reagent("stage-5", 3))
    plan.append(reagent("stage-6", 3))
    plan += odtc_out_back("methylation-seq-stage-4", "stage 4")
    plan.append(reagent("stage-7", 4))
    plan += odtc_out_back("methylation-seq-stage-5", "stage 5")

    plan.append(magnet_out())
    plan.append(cleanup("cleanup-2"))
    plan.append(magnet_back())

    plan.append(reagent("stage-8", 5))
    plan += odtc_out_back("methylation-seq-stage-6", "stage 6")
    plan.append(reagent("stage-9", 4))
    plan += odtc_out_back("methylation-seq-stage-7", "stage 7")
    plan.append(reagent("stage-10", 6))
    plan.append(reagent("stage-11", 5))
    plan += odtc_out_back("methylation-seq-stage-8", "stage 8")

    plan.append(magnet_out())
    plan.append(cleanup("cleanup-3"))
    plan.append(magnet_back())

    return plan


def build_deck_preflight():
    """Each distinct deck assignment the 36-leg rehearsal depends on, motion-free.

    The scoped scripts remain the source of geometry truth. Running each once in deck
    mode catches missing resources/imports on the Pi and prints the exact coordinates
    the following dry rehearsal will use without issuing a pipetting or iSWAP transfer
    after each script's normal STAR setup/initialization.
    """
    return [
        ("note", "physical deck checklist",
         "Stage the complete dry deck before continuing:\n"
         "  rail48 p0 (first slot) = p10 filter tips\n"
         "  rail48 p1 (second slot) = p50 filter tips\n"
         "  rail48 p2 (third slot) = p300 filter tips\n"
         "  rail35 p0 (first slot) = EMPTY CellTreat_96_wellplate_350ul_Fb sacrificial work plate\n"
         "  rail35 p1 (second slot) = EMPTY CellTreat_96_wellplate_350ul_Fb reagent-source plate\n"
         "  rail35 p2 (third slot) = magnetic rack/nest, empty and seated\n"
         "  rail35 p3 (fourth slot) = EMPTY/DRY 12-well reservoir\n"
         "  rail20 p1 (ODTC modeled target) = ODTC nest, empty, open, and clear\n"
         "Do not load samples or biological reagents."),
        ("run", "reagent-add deck assignment",
         [str(REAGENTS), "--mode", "deck"]),
        ("run", "SPRI cleanup deck assignment",
         [str(CLEANUP), "--cleanup", "cleanup-1", "--mode", "deck"]),
        ("run", "ODTC forward iSWAP coordinate print",
         [str(ODTC_FWD), "--mode", "deck"] + ODTC_RAIL),
        ("run", "ODTC return iSWAP coordinate print",
         [str(ODTC_RET), "--mode", "deck"] + ODTC_RAIL
         + ["--odtc-pickup-z-offset-mm", "0"]),
        ("run", "magnet forward iSWAP coordinate print",
         [str(MAG_FWD), "--mode", "deck"]),
        ("run", "magnet return iSWAP coordinate print",
         [str(MAG_RET), "--mode", "deck", "--pickup-z-offset-mm", "14.0",
          "--drop-z-offset-mm", "8.5"]),
    ]


def print_plan(plan):
    print("")
    print("methylation-sequencing workflow (fragmentation-coupled) full column-1 choreography plan")
    print("=" * 88)
    n = 0
    for kind, label, payload in plan:
        if kind == "run":
            n += 1
            print(f"[{n:>2}] {label}")
            print(f"     $ python {' '.join(str(p) for p in payload)}")
        else:
            print(f"  -  {label}")
            for line in str(payload).splitlines():
                print(f"     {line}")
    print("=" * 88)
    print(f"{n} executed legs, plus operator notes (ODTC thermal runs and the start condition).")


def run_step(kind, label, payload):
    print("")
    print("=" * 88)
    print(label)
    print("=" * 88)
    if kind == "note":
        print(payload)
        return
    cmd = [sys.executable] + payload
    print(" ".join(cmd))
    subprocess.run(cmd, cwd=ROOT, check=True)


def main():
    parser = argparse.ArgumentParser(
        description="methylation-sequencing workflow (fragmentation-coupled) column-1 full choreography with ODTC and SPRI handoffs, dry."
    )
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--print", dest="print_only", action="store_true",
                       help="Print the ordered plan and exit. No execution.")
    modes.add_argument("--deck", action="store_true",
                       help="Run every deck/coordinate view on the STAR. Setup/homing only; no protocol transfer.")
    modes.add_argument("--sim-lh", action="store_true",
                       help="Run liquid-handling legs on the chatterbox backend; iSWAP/ODTC legs become notes. Local, no hardware.")
    parser.add_argument("--confirm", default="",
                        help=f"Required to run the dry rehearsal on hardware: --confirm {CONFIRM_PHRASE}")
    parser.add_argument(
        "--labware-ack",
        default="",
        help=f"Required hardware labware acknowledgement: --labware-ack {LABWARE_ACK}",
    )
    args = parser.parse_args()

    plan = build_plan(sim_lh=args.sim_lh)

    if args.print_only:
        print_plan(plan)
        return

    if args.deck:
        print("")
        print("methylation-sequencing workflow FULL-DECK PREFLIGHT (REAL STAR BACKEND; SETUP/HOMING ONLY)")
        print("Each scoped script initializes the STAR, assigns its resources, prints coordinates,")
        print("and exits in --mode deck without pipetting or iSWAP transfer. Normal STAR setup/homing")
        print("can occur. Watch the console for any resource or geometry mismatch.")
        for kind, label, payload in build_deck_preflight():
            run_step(kind, label, payload)
        print("")
        print("SUCCESS: all methylation sequencing deck/coordinate views initialized without protocol transfer.")
        print(f"Next, with the staged dry deck and a human at the E-stop: --confirm {CONFIRM_PHRASE}")
        return

    print("")
    print("methylation-sequencing workflow FULL CHOREOGRAPHY, COLUMN 1, DRY")
    print("Reagent adds -> ODTC out/back (x8 programs) -> 3x magnet + SPRI cleanup out/back.")
    print("Every leg runs its own scoped script; geometry is not re-derived here.")
    print("STATUS: written, simulation-first, NOT yet run on hardware. Tune each leg before trusting it.")

    if args.sim_lh:
        print("\n--sim-lh: liquid-handling legs run on the chatterbox (no hardware); iSWAP and ODTC")
        print("legs are printed as notes only.")
    elif args.confirm != CONFIRM_PHRASE or args.labware_ack != LABWARE_ACK:
        print("")
        print("Refusing to run on hardware. This moves the arm through many transfers, eight ODTC")
        print("round trips, and three magnet round trips. Review the plan first with --print, run")
        print("each leg's --mode deck, stage both physical CellTreat 229195/229196 plates, then add:")
        print(f"  --confirm {CONFIRM_PHRASE} --labware-ack {LABWARE_ACK}")
        print("Or exercise the liquid-handling legs locally with --sim-lh.")
        return

    for kind, label, payload in plan:
        run_step(kind, label, payload)

    print("")
    print("SUCCESS: full methylation sequencing column-1 choreography completed. Plate back on rail35 pos0.")
    print("Complete the operator-approved final transfer off the magnet.")


if __name__ == "__main__":
    main()

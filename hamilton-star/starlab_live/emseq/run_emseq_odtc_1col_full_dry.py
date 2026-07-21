import argparse
import subprocess
import sys
from pathlib import Path

# EM-seq v2 (UltraShear-coupled) column-1 full choreography, with the ODTC thermocycler
# and SPRI cleanup handoffs in order. Single column, dry.
#
# STATUS: written, simulation-first. NOT yet run on hardware. See emseq/README.md.
#
# What this is
# ------------
# The whole UltraShear + EM-seq v2 shape as one ordered plan: reagent adds into column 1,
# ODTC out/back for each thermal program, and three magnet + SPRI cleanup out/backs. It is
# the same orchestration pattern as run_ampseq_odtc_1col_full_dry.py: each leg runs an
# already-scoped leg script by subprocess, and NO geometry is re-derived here. The iSWAP
# plate-move legs reuse the parent starlab_live/ move scripts with the SAME confirmed args
# the ampseq choreography used; the reagent and cleanup legs run the sibling emseq scripts.
#
# Two things this runner does NOT do, on purpose:
#   1. It does not run the ODTC thermal programs. Those live in the instrument-integrations
#      tree, synced to a different run dir on the Pi, and long thermal runs are launched
#      detached per this repo's safety rules. At each ODTC handoff the runner prints the
#      exact command to run there, then (in a dry plate-move rehearsal) does the return leg.
#      In a real run the operator pauses after the forward leg, runs the thermal detached,
#      waits for completion, then resumes with the return leg.
#   2. It does not consume reagents. Like the ampseq choreography, the dry rehearsal returns
#      tips and moves an empty/water plate to prove the plate flow and every handoff.
#
# Modes:
#   --print              print the ordered plan and exit. No execution. Review this first.
#   --deck               initialize the STAR for each distinct deck/geometry view and print
#                        all assignments. Normal STAR setup/homing can occur, but no
#                        pipetting or iSWAP transfer is issued after setup.
#   --sim-lh             run the liquid-handling legs on the chatterbox backend (--dry);
#                        iSWAP and ODTC legs become printed notes. Fully local, no hardware.
#   --confirm RUN_EMSEQ_ODTC_FULL
#                        run the dry rehearsal on hardware: real iSWAP motion, LH legs with
#                        tips returned and no reagents, ODTC thermal as operator notes.
#
# FULL DECK required before a hardware run (all at once):
#   rail48 pos0 = p10 tips        rail48 pos1 = p50 tips        rail48 pos2 = p300 tips
#   rail35 pos0 = work plate (the plate that gets moved around)
#   rail35 pos1 = reagent source (swap the reagent between reagent legs; see PREP lines)
#   rail35 pos2 = magnet block (iSWAP target for the three cleanups)
#   rail35 pos3 = 12-well reservoir (beads, 2x ethanol, elution buffer, waste)
#   rail20 pos1 = ODTC nest, EMPTY and open to receive the plate
# The magnet MUST be physically at rail35 pos2 and the ODTC nest empty, or an iSWAP releases
# the plate into open space. Deck-check every position and keep a human at the E-stop.
#
# Confirmed iSWAP geometry baked into the leg args (from run_ampseq_odtc_1col_full_dry.py,
# gripped clean on hardware 2026-07-12; NOT re-derived here):
#   ODTC forward : pickup z5, drop x2 / y36.5 / z12 at rail20 pos1
#   ODTC return  : pickup z0 (plate settles ~9 mm deep in the nest), drop z8.5
#   Magnet fwd   : pickup z8.5, drop z18.0 (defaults)
#   Magnet return: pickup z14.0, drop z8.5

ROOT = Path(__file__).resolve().parent           # .../starlab_live/emseq
STARLAB = ROOT.parent                            # .../starlab_live

REAGENTS = ROOT / "emseq_reagent_adds.py"
CLEANUP = ROOT / "emseq_cleanup.py"

ODTC_FWD = STARLAB / "test_iswap_plate_rail35pos0_to_odtc_variable.py"
ODTC_RET = STARLAB / "test_iswap_plate_odtc_to_rail35pos0_return.py"
MAG_FWD = STARLAB / "test_iswap_plate_rail35pos0_to_rail35pos2_mag_variable.py"
MAG_RET = STARLAB / "test_iswap_plate_rail35pos2_mag_to_rail35pos0_variable.py"

ODTC_RAIL = ["--odtc-rail", "20", "--odtc-position", "1"]

CONFIRM_PHRASE = "RUN_EMSEQ_ODTC_FULL"


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
        # This is a dry, no-reagent rehearsal, so return tips (emseq_cleanup defaults to
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
                 "work plate at rail35 pos0 col 1 holds 26 uL combined gDNA + control DNA "
                 "(off-deck prep; water for a dry rehearsal)."))

    # Fragmentation
    plan.append(reagent("shear-mm", 1))
    plan += odtc_out_back("emseq-shear", "shear")

    # End Prep
    plan.append(reagent("endprep-mm", 1))
    plan += odtc_out_back("emseq-endprep", "end prep")

    # Adaptor ligation (adaptor added before ligation mix)
    plan.append(reagent("adaptor", 2))
    plan.append(reagent("ligation-mm", 2))
    plan += odtc_out_back("emseq-ligation", "ligation")

    # Cleanup 1 (1.1X)
    plan.append(magnet_out())
    plan.append(cleanup("post-ligation"))
    plan.append(magnet_back())

    # TET2 protection (Fe(II) initiates), then stop incubation
    plan.append(reagent("tet2-mm", 3))
    plan.append(reagent("feii", 3))
    plan += odtc_out_back("emseq-tet2", "TET2 oxidation")
    plan.append(reagent("stop", 4))
    plan += odtc_out_back("emseq-tet2-stop", "stop incubation")

    # Cleanup 2 (1.0X)
    plan.append(magnet_out())
    plan.append(cleanup("post-tet2"))
    plan.append(magnet_back())

    # Denaturation
    plan.append(reagent("formamide", 5))
    plan += odtc_out_back("emseq-denature", "denaturation")

    # Deamination
    plan.append(reagent("deaminate-mm", 4))
    plan += odtc_out_back("emseq-deaminate", "deamination")

    # Library PCR (per-well index primer, then Q5U master mix)
    plan.append(reagent("pcr-primer", 6))
    plan.append(reagent("pcr-mm", 5))
    plan += odtc_out_back("emseq-pcr", "library PCR")

    # Cleanup 3 (0.8X)
    plan.append(magnet_out())
    plan.append(cleanup("post-pcr"))
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
         "  rail48 pos0 = p10 filter tips\n"
         "  rail48 pos1 = p50 filter tips\n"
         "  rail48 pos2 = p300 filter tips\n"
         "  rail35 pos0 = EMPTY sacrificial 96-well work plate\n"
         "  rail35 pos1 = EMPTY reagent-source 96-well plate/strip\n"
         "  rail35 pos2 = magnetic rack/nest, empty and seated\n"
         "  rail35 pos3 = EMPTY/DRY 12-well reservoir\n"
         "  rail20 pos1 = ODTC nest, empty, open, and clear\n"
         "Do not load samples, reagents, beads, ethanol, or formamide."),
        ("run", "reagent-add deck assignment",
         [str(REAGENTS), "--mode", "deck"]),
        ("run", "SPRI cleanup deck assignment",
         [str(CLEANUP), "--cleanup", "post-ligation", "--mode", "deck"]),
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
    print("EM-seq v2 (UltraShear-coupled) full column-1 choreography plan")
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
        description="EM-seq v2 (UltraShear-coupled) column-1 full choreography with ODTC and SPRI handoffs, dry."
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
    args = parser.parse_args()

    plan = build_plan(sim_lh=args.sim_lh)

    if args.print_only:
        print_plan(plan)
        return

    if args.deck:
        print("")
        print("EM-seq v2 FULL-DECK PREFLIGHT (REAL STAR BACKEND; SETUP/HOMING ONLY)")
        print("Each scoped script initializes the STAR, assigns its resources, prints coordinates,")
        print("and exits in --mode deck without pipetting or iSWAP transfer. Normal STAR setup/homing")
        print("can occur. Watch the console for any resource or geometry mismatch.")
        for kind, label, payload in build_deck_preflight():
            run_step(kind, label, payload)
        print("")
        print("SUCCESS: all EM-seq deck/coordinate views initialized without protocol transfer.")
        print(f"Next, with the staged dry deck and a human at the E-stop: --confirm {CONFIRM_PHRASE}")
        return

    print("")
    print("EM-seq v2 FULL CHOREOGRAPHY, COLUMN 1, DRY")
    print("Reagent adds -> ODTC out/back (x8 programs) -> 3x magnet + SPRI cleanup out/back.")
    print("Every leg runs its own scoped script; geometry is not re-derived here.")
    print("STATUS: written, simulation-first, NOT yet run on hardware. Tune each leg before trusting it.")

    if args.sim_lh:
        print("\n--sim-lh: liquid-handling legs run on the chatterbox (no hardware); iSWAP and ODTC")
        print("legs are printed as notes only.")
    elif args.confirm != CONFIRM_PHRASE:
        print("")
        print("Refusing to run on hardware. This moves the arm through many transfers, eight ODTC")
        print("round trips, and three magnet round trips. Review the plan first with --print, run")
        print(f"each leg's --mode deck, stage the full deck, then add: --confirm {CONFIRM_PHRASE}")
        print("Or exercise the liquid-handling legs locally with --sim-lh.")
        return

    for kind, label, payload in plan:
        run_step(kind, label, payload)

    print("")
    print("SUCCESS: full EM-seq column-1 choreography completed. Plate back on rail35 pos0.")
    print("Final library eluate (20 uL, post-pcr cleanup) is on the beads; transfer off the magnet.")


if __name__ == "__main__":
    main()

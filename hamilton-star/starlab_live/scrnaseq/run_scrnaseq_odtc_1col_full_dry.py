import argparse
import subprocess
import sys
from pathlib import Path

# NEBNext Single Cell / Low Input RNA library prep (scRNA-seq) column-1 full choreography,
# with the ODTC thermocycler and SPRI cleanup handoffs in order. Single column, dry.
#
# STATUS: written, simulation-first. NOT yet run on hardware. See scrnaseq/README.md.
#
# What this is
# ------------
# The whole E6420 Section 1 shape as one ordered plan: reagent adds into column 1, ODTC
# out/back for each thermal program, and three magnet + SPRI cleanup out/backs (the first is
# the two-round cDNA cleanup). Same orchestration pattern as run_emseq_odtc_1col_full_dry.py:
# each leg runs an already-scoped leg script by subprocess, and NO geometry is re-derived here.
# The iSWAP plate-move legs reuse the parent starlab_live/ move scripts with the SAME confirmed
# args the targeted PCR and EM-seq choreographies used; the reagent and cleanup legs run the sibling
# scrnaseq scripts.
#
# As in the emseq runner, this does NOT run the ODTC thermal programs (they live in the
# instrument-integrations tree, synced to a different run dir on the Pi, and long runs launch
# detached). At each ODTC handoff the runner prints the exact command to run there. In a real
# run the operator pauses after the forward leg, runs the thermal detached, waits, then resumes
# with the return leg. The dry rehearsal returns tips and moves an empty/water plate.
#
# Modes:
#   --print              print the ordered plan and exit. No execution.
#   --sim-lh             run the liquid-handling legs on the chatterbox backend (--dry);
#                        iSWAP and ODTC legs become printed notes. Fully local, no hardware.
#   --confirm RUN_SCRNASEQ_ODTC_FULL
#                        run the dry rehearsal on hardware: real iSWAP motion, LH legs with
#                        tips returned and no reagents, ODTC thermal as operator notes.
#
# FULL DECK required before a hardware run (all at once):
#   rail48 pos0 = p10 tips        rail48 pos1 = p50 tips        rail48 pos2 = p300 tips
#   rail35 pos0 = work plate (the plate that gets moved around; starts with cells lysed in
#                5 uL 1X Cell Lysis Buffer, sorted off-deck)
#   rail35 pos1 = reagent source (swap the reagent between reagent legs; see PREP lines)
#   rail35 pos2 = magnet block (iSWAP target for the three cleanups)
#   rail35 pos3 = 12-well reservoir (beads, ethanol, 0.1X TE, reconstitution buffer, 1X TE, waste)
#   rail20 pos1 = ODTC nest, EMPTY and open to receive the plate
# Note: the post-cdna cleanup discards 16 tip-columns, more than one p300 rack; plan a tip
# replenishment for a real wet run. The magnet MUST be at rail35 pos2 and the ODTC nest empty,
# or an iSWAP releases the plate into open space. Deck-check every position, human at the E-stop.
#
# Confirmed iSWAP geometry baked into the leg args (from run_targeted_pcr_odtc_1col_full_dry.py,
# gripped clean on hardware 2026-07-12; NOT re-derived here):
#   ODTC forward : pickup z5, drop x2 / y36.5 / z12 at rail20 pos1
#   ODTC return  : pickup z0, drop z8.5
#   Magnet fwd   : pickup z8.5, drop z18.0 (defaults)
#   Magnet return: pickup z14.0, drop z8.5

ROOT = Path(__file__).resolve().parent           # .../starlab_live/scrnaseq
STARLAB = ROOT.parent                            # .../starlab_live

REAGENTS = ROOT / "scrnaseq_reagent_adds.py"
CLEANUP = ROOT / "scrnaseq_cleanup.py"

ODTC_FWD = STARLAB / "test_iswap_plate_rail35pos0_to_odtc_variable.py"
ODTC_RET = STARLAB / "test_iswap_plate_odtc_to_rail35pos0_return.py"
MAG_FWD = STARLAB / "test_iswap_plate_rail35pos0_to_rail35pos2_mag_variable.py"
MAG_RET = STARLAB / "test_iswap_plate_rail35pos2_mag_to_rail35pos0_variable.py"

ODTC_RAIL = ["--odtc-rail", "20", "--odtc-position", "1"]

CONFIRM_PHRASE = "RUN_SCRNASEQ_ODTC_FULL"


def odtc_command(program: str) -> str:
    return (f"instrument-integrations/run_on_pi.sh odtc/05_odtc_run_protocol.py "
            f"--program {program} --ip $ODTC_IP --confirm i-am-watching")


def build_plan(sim_lh: bool):
    lh_extra = ["--dry"] if sim_lh else []

    def reagent(mode, tip_col):
        argv = [str(REAGENTS), "--mode", mode, "--tip-col", str(tip_col), "--return-tips"] + lh_extra
        return ("run", f"reagent add: {mode} (tip col {tip_col})", argv)

    def cleanup(name):
        # dry, no-reagent rehearsal: return tips (scrnaseq_cleanup defaults to discard for real runs).
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
                 "work plate at rail35 pos0 col 1 holds 5 uL of cells lysed in cold 1X Cell Lysis "
                 "Buffer (sorted off-deck; water for a dry rehearsal)."))

    # cDNA synthesis
    plan.append(reagent("primer-mix", 1))
    plan += odtc_out_back("sc-anneal", "primer anneal")
    plan.append(reagent("rt-mix", 1))
    plan += odtc_out_back("sc-rt", "reverse transcription")
    plan.append(reagent("cdna-pcr-mix", 2))
    plan += odtc_out_back("sc-cdna-pcr", "cDNA amplification")

    # cDNA cleanup (0.6X double, with reconstitution re-bind)
    plan.append(magnet_out())
    plan.append(cleanup("post-cdna"))
    plan.append(magnet_back())
    plan.append(("note", "quantify + normalize cDNA (off-deck checkpoint)",
                 "The post-cdna cleanup keeps 30 uL. Quantify the cleaned cDNA (Bioanalyzer HS, "
                 "E6420 Section 1.7; typical 1-20 ng) and normalize to 26 uL before fragmentation. "
                 "Use the yield to pick the sc-lib-pcr cycle count (default 8 for 1-20 ng cDNA)."))

    # Fragmentation / end prep
    plan.append(reagent("fs-mix", 3))
    plan += odtc_out_back("sc-fs", "fragmentation / end prep")

    # Adaptor ligation + USER
    plan.append(reagent("adaptor", 2))
    plan.append(reagent("ligation-mm", 4))
    plan += odtc_out_back("sc-ligation", "adaptor ligation")
    plan.append(reagent("user-enzyme", 3))
    plan += odtc_out_back("sc-user", "USER excision")

    # Cleanup 2 (0.8X)
    plan.append(magnet_out())
    plan.append(cleanup("post-ligation"))
    plan.append(magnet_back())

    # Library enrichment PCR (per-well index, then Q5 master mix)
    plan.append(reagent("pcr-primer", 5))
    plan.append(reagent("pcr-mm", 6))
    plan += odtc_out_back("sc-lib-pcr", "library PCR")

    # Cleanup 3 (0.9X)
    plan.append(magnet_out())
    plan.append(cleanup("post-pcr"))
    plan.append(magnet_back())

    return plan


def print_plan(plan):
    print("")
    print("scRNA-seq (E6420) full column-1 choreography plan")
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
        description="scRNA-seq (E6420) column-1 full choreography with ODTC and SPRI handoffs, dry."
    )
    parser.add_argument("--print", dest="print_only", action="store_true",
                        help="Print the ordered plan and exit. No execution.")
    parser.add_argument("--sim-lh", action="store_true",
                        help="Run liquid-handling legs on the chatterbox; iSWAP/ODTC legs become notes. Local, no hardware.")
    parser.add_argument("--confirm", default="",
                        help=f"Required to run the dry rehearsal on hardware: --confirm {CONFIRM_PHRASE}")
    args = parser.parse_args()

    plan = build_plan(sim_lh=args.sim_lh)

    if args.print_only:
        print_plan(plan)
        return

    print("")
    print("scRNA-seq FULL CHOREOGRAPHY, COLUMN 1, DRY")
    print("Reagent adds -> ODTC out/back (x7 programs) -> 3x magnet + SPRI cleanup out/back")
    print("(the first cleanup is the two-round cDNA cleanup).")
    print("Every leg runs its own scoped script; geometry is not re-derived here.")
    print("STATUS: written, simulation-first, NOT yet run on hardware. Tune each leg before trusting it.")

    if args.sim_lh:
        print("\n--sim-lh: liquid-handling legs run on the chatterbox (no hardware); iSWAP and ODTC")
        print("legs are printed as notes only.")
    elif args.confirm != CONFIRM_PHRASE:
        print("")
        print("Refusing to run on hardware. This moves the arm through many transfers, seven ODTC")
        print("round trips, and three magnet round trips. Review the plan first with --print, run")
        print(f"each leg's --mode deck, stage the full deck, then add: --confirm {CONFIRM_PHRASE}")
        print("Or exercise the liquid-handling legs locally with --sim-lh.")
        return

    for kind, label, payload in plan:
        run_step(kind, label, payload)

    print("")
    print("SUCCESS: full scRNA-seq column-1 choreography completed. Plate back on rail35 pos0.")
    print("Final library eluate (30 uL, post-pcr cleanup) is on the beads; transfer off the magnet.")


if __name__ == "__main__":
    main()

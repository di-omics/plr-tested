import argparse
import subprocess
import sys
from pathlib import Path

# TIP-seq column-1 full choreography (the T7 linear-amplification + library back half), with the
# ODTC thermocycler and SPRI cleanup handoffs in order. Single column, dry.
#
# STATUS: written, simulation-first. NOT yet run on hardware. See tipseq/README.md.
#
# What this is
# ------------
# The automatable TIP-seq back half as one ordered plan: reagent adds into column 1, ODTC out/back
# for each thermal program, and four magnet + SPRI cleanup out/backs. Same orchestration pattern as
# the emseq/scrnaseq runners: each leg runs an already-scoped leg script by subprocess, and NO
# geometry is re-derived here. The iSWAP plate-move legs reuse the parent starlab_live/ move scripts
# with the SAME confirmed args the targeted PCR and EM-seq choreographies used.
#
# The CUT&Tag front end (conA beads, antibody, pA-Tn5 tagmentation) and, for single cell / sciTIP,
# FACS sorting are OFF-DECK; the plate enters here holding 8 uL of SPRI-purified tagmented gDNA +
# retained beads. As in the other runners, this does NOT run the ODTC programs (they live in the
# instrument-integrations tree); at each ODTC handoff it prints the exact command. Note tip-ivt is
# a 16-19 h overnight hold - run it detached on the Pi.
#
# Modes:
#   --print              print the ordered plan and exit. No execution.
#   --sim-lh             run the liquid-handling legs on the chatterbox backend (--dry);
#                        iSWAP and ODTC legs become printed notes. Fully local, no hardware.
#   --confirm RUN_TIPSEQ_ODTC_FULL
#                        run the dry rehearsal on hardware: real iSWAP motion, LH legs with tips
#                        returned and no reagents, ODTC thermal as operator notes.
#
# FULL DECK required before a hardware run (all at once):
#   rail48 pos0 = p10 tips        rail48 pos1 = p50 tips        rail48 pos2 = p300 tips
#   rail35 pos0 = work plate (starts with 8 uL tagmented gDNA + retained SPRI beads, off-deck)
#   rail35 pos1 = reagent source (swap the reagent between reagent legs; see PREP lines)
#   rail35 pos2 = magnet block (iSWAP target for the four cleanups)
#   rail35 pos3 = 12-well reservoir (fresh beads, ethanol, RNase-free water, SPRI binding buffer,
#                nuclease-free water, 10 mM Tris, waste)
#   rail20 pos1 = ODTC nest, EMPTY and open to receive the plate
# The magnet MUST be at rail35 pos2 and the ODTC nest empty. Deck-check every position, human at
# the E-stop. tip-ivt ties up the ODTC overnight.
#
# Confirmed iSWAP geometry baked into the leg args (from run_targeted_pcr_odtc_1col_full_dry.py,
# gripped clean on hardware 2026-07-12; NOT re-derived here):
#   ODTC forward : pickup z5, drop x2 / y36.5 / z12 at rail20 pos1
#   ODTC return  : pickup z0, drop z8.5
#   Magnet fwd   : pickup z8.5, drop z18.0 (defaults)
#   Magnet return: pickup z14.0, drop z8.5

ROOT = Path(__file__).resolve().parent           # .../starlab_live/tipseq
STARLAB = ROOT.parent                            # .../starlab_live

REAGENTS = ROOT / "tipseq_reagent_adds.py"
CLEANUP = ROOT / "tipseq_cleanup.py"

ODTC_FWD = STARLAB / "test_iswap_plate_rail35pos0_to_odtc_variable.py"
ODTC_RET = STARLAB / "test_iswap_plate_odtc_to_rail35pos0_return.py"
MAG_FWD = STARLAB / "test_iswap_plate_rail35pos0_to_rail35pos2_mag_variable.py"
MAG_RET = STARLAB / "test_iswap_plate_rail35pos2_mag_to_rail35pos0_variable.py"

ODTC_RAIL = ["--odtc-rail", "20", "--odtc-position", "1"]

CONFIRM_PHRASE = "RUN_TIPSEQ_ODTC_FULL"


def odtc_command(program: str) -> str:
    return (f"instrument-integrations/run_on_pi.sh odtc/05_odtc_run_protocol.py "
            f"--program {program} --ip $ODTC_IP --confirm i-am-watching")


def build_plan(sim_lh: bool):
    lh_extra = ["--dry"] if sim_lh else []

    def reagent(mode, tip_col):
        argv = [str(REAGENTS), "--mode", mode, "--tip-col", str(tip_col), "--return-tips"] + lh_extra
        return ("run", f"reagent add: {mode} (tip col {tip_col})", argv)

    def cleanup(name):
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
                 "work plate at rail35 pos0 col 1 holds 8 uL of SPRI-purified tagmented gDNA + "
                 "retained SPRI beads (CUT&Tag + pA-Tn5 tagmentation done off-deck; water for a dry "
                 "rehearsal)."))

    # Gap fill + T7 IVT linear amplification
    plan.append(reagent("gapfill-mix", 1))
    plan += odtc_out_back("tip-gapfill", "gap fill")
    plan.append(reagent("ivt-mix", 1))
    plan += odtc_out_back("tip-ivt", "T7 IVT (overnight)")

    # RNA cleanup (2.0X reactivation)
    plan.append(magnet_out())
    plan.append(cleanup("post-ivt"))
    plan.append(magnet_back())

    # First-strand RT + RNase H
    plan.append(reagent("hexamer", 2))
    plan += odtc_out_back("tip-rt-anneal", "hexamer anneal")
    plan.append(reagent("rt-mix", 2))
    plan += odtc_out_back("tip-rt", "reverse transcription")
    plan.append(reagent("rnaseh", 3))
    plan += odtc_out_back("tip-rnaseh", "RNase H")

    # Second-strand synthesis
    plan.append(reagent("sss-oligo", 4))
    plan += odtc_out_back("tip-ss-anneal", "second-strand anneal")
    plan.append(reagent("ss-taq", 3))
    plan += odtc_out_back("tip-ss", "second-strand synthesis")

    # cDNA cleanup (2.0X reactivation)
    plan.append(magnet_out())
    plan.append(cleanup("post-ss"))
    plan.append(magnet_back())

    # cDNA fragmentation (Tn5 ME-B), then operator GuHCl stop
    plan.append(reagent("tn5-mix", 5))
    plan += odtc_out_back("tip-tag", "cDNA fragmentation")
    plan.append(("note", "GuHCl stop (off-deck)",
                 "Add GuHCl to 4 M final and vortex to degrade Tn5 before the DNA cleanup (volume is "
                 "stock-dependent; not a robot leg)."))

    # DNA cleanup (2.0X reactivation, transfer off beads)
    plan.append(magnet_out())
    plan.append(cleanup("post-tag"))
    plan.append(magnet_back())
    plan.append(("note", "transfer off beads (off-deck)",
                 "Move the 16 uL eluate to a fresh column, leaving the SPRI beads behind, before PCR."))

    # Indexing PCR
    plan.append(reagent("pcr-mix", 4))
    plan += odtc_out_back("tip-pcr", "indexing PCR")

    # Final library cleanup (0.85X left-side size select)
    plan.append(magnet_out())
    plan.append(cleanup("post-pcr"))
    plan.append(magnet_back())

    return plan


def print_plan(plan):
    print("")
    print("TIP-seq full column-1 choreography plan (linear-amp + library back half)")
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
    print(f"{n} executed legs, plus operator notes (ODTC thermal runs, GuHCl stop, off-beads transfer).")


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
        description="TIP-seq column-1 full choreography with ODTC and SPRI handoffs, dry."
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
    print("TIP-seq FULL CHOREOGRAPHY, COLUMN 1, DRY (linear-amp + library back half)")
    print("Reagent adds -> ODTC out/back (x9 programs) -> 4x magnet + SPRI cleanup out/back.")
    print("Every leg runs its own scoped script; geometry is not re-derived here.")
    print("STATUS: written, simulation-first, NOT yet run on hardware. Tune each leg before trusting it.")

    if args.sim_lh:
        print("\n--sim-lh: liquid-handling legs run on the chatterbox (no hardware); iSWAP and ODTC")
        print("legs are printed as notes only.")
    elif args.confirm != CONFIRM_PHRASE:
        print("")
        print("Refusing to run on hardware. This moves the arm through many transfers, nine ODTC")
        print("round trips (one overnight IVT), and four magnet round trips. Review the plan first")
        print(f"with --print, run each leg's --mode deck, stage the full deck, then add: --confirm {CONFIRM_PHRASE}")
        print("Or exercise the liquid-handling legs locally with --sim-lh.")
        return

    for kind, label, payload in plan:
        run_step(kind, label, payload)

    print("")
    print("SUCCESS: full TIP-seq column-1 choreography completed. Plate back on rail35 pos0.")
    print("Final library (post-pcr, left-side size selected) is on the beads; pool to equimolar off-deck.")


if __name__ == "__main__":
    main()

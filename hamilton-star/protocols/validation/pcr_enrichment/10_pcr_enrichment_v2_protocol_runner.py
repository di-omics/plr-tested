import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent

MM_SCRIPT = ROOT / "04_pcr_enrichment_96wp_pcr1_pcr2_mastermix_DSPH15_DRY.py"
ISWAP_TO_MAG_SCRIPT = ROOT / "test_iswap_plate_rail35pos0_to_rail35pos2_mag_variable.py"
CLEANUP_SCRIPT = ROOT / "02_pcr_enrichment_round1_cleanup_col1_dry_v2_p50low.py"
ISWAP_TO_POS0_SCRIPT = ROOT / "test_iswap_plate_rail35pos2_mag_to_rail35pos0_variable.py"


def run_step(label, cmd):
    print("")
    print("=" * 96)
    print(label)
    print("=" * 96)
    print(" ".join(str(x) for x in cmd))
    subprocess.run(cmd, cwd=ROOT, check=True)


def pause(label, enabled=True):
    if not enabled:
        return
    print("")
    print("-" * 96)
    print(label)
    print("-" * 96)
    input("Press Enter to continue...")


def main():
    parser = argparse.ArgumentParser(
        description=(
            "PCR enrichment V2 protocol runner. Runs all currently built Hamilton liquid-handling "
            "steps in protocol order, with pauses for thermocycling, gels, indexing decisions, "
            "pooling, and final off-deck QC."
        )
    )

    parser.add_argument(
        "--mode",
        choices=["dry", "wet"],
        default="dry",
        help="dry returns tips where supported; wet discards tips where supported.",
    )
    parser.add_argument(
        "--no-pauses",
        action="store_true",
        help="Skip protocol pauses. Mostly useful for pure dry choreography testing.",
    )
    parser.add_argument(
        "--skip-pcr1-mm",
        action="store_true",
        help="Skip PCR1 master-mix addition.",
    )
    parser.add_argument(
        "--skip-pcr1-cleanup",
        action="store_true",
        help="Skip PCR1 bead cleanup.",
    )
    parser.add_argument(
        "--skip-pcr2-mm",
        action="store_true",
        help="Skip PCR2 common master-mix addition.",
    )

    args = parser.parse_args()

    pauses = not args.no_pauses
    wet = args.mode == "wet"

    print("")
    print("PCR ENRICHMENT V2 PROTOCOL RUNNER")
    print("")
    print("This runs all currently built Hamilton-doable liquid handling in SOP order.")
    print("")
    print("Deck assumptions:")
    print("  rail35 pos0 = work/PCR plate")
    print("  rail35 pos1 = source 96WP")
    print("      col1 = PCR1 complete master mix")
    print("      col3 = PCR2 common master mix")
    print("  rail35 pos2 = raised magnetic block, empty before cleanup")
    print("  rail35 pos3 = reservoir/waste")
    print("      A1 = SPRI beads / bead mimic")
    print("      A2 = 80% EtOH wash 1 / mimic")
    print("      A3 = 80% EtOH wash 2 / mimic")
    print("      A4 = elution H2O / mimic")
    print("      A12 = waste")
    print("  rail48 pos1 = p50 tips")
    print("  rail48 pos2 = p300/p1000-class tips")
    print("")
    print(f"Mode: {args.mode}")
    print("  dry = return tips where supported")
    print("  wet = discard tips where supported")
    print("")
    print("Not yet automated on Hamilton:")
    print("  template loading, thermocycling, gel checks, unique i5/i7 distribution,")
    print(
        "  diluted PCR1 product transfer into PCR2, final pooled tube cleanup, "
        "fluorometric dsDNA quantification, and molarity calculation."
    )
    print("")

    pcr1_mm_cmd = [
        sys.executable,
        str(MM_SCRIPT),
        "--mode",
        "pcr1-mm",
        "--tip-col",
        "1",
    ]
    if not wet:
        pcr1_mm_cmd.append("--return-tips")

    pcr2_mm_cmd = [
        sys.executable,
        str(MM_SCRIPT),
        "--mode",
        "pcr2-mm",
        "--tip-col",
        "2",
    ]
    if not wet:
        pcr2_mm_cmd.append("--return-tips")

    cleanup_cmd = [
        sys.executable,
        str(CLEANUP_SCRIPT),
        "--mode",
        "all-dry",
    ]
    if wet:
        cleanup_cmd.append("--discard-tips")

    if not args.skip_pcr1_mm:
        pause(
            "PRE-STAGE-1 SETUP CHECK\n"
            "Prepare the destination plate and source wells according to the approved "
            "local method profile.",
            pauses,
        )

        run_step(
            "STEP 1: Hamilton PCR1 complete master-mix add",
            pcr1_mm_cmd,
        )

    pause(
        "OFF-DECK PCR-ENRICHMENT STAGE-1 THERMAL HANDOFF\n"
        "Run the approved operator-supplied thermal profile, then return the plate "
        "to rail35 pos0 for cleanup.",
        pauses,
    )

    if not args.skip_pcr1_cleanup:
        pause(
            "PRE-CLEANUP CHECK\n"
            "Start state required:\n"
            "  rail35 pos0 = PCR1 plate\n"
            "  rail35 pos2 = empty magnetic block\n"
            "  rail35 pos3 reservoir loaded per the operator profile; A12 is waste.",
            pauses,
        )

        run_step(
            "STEP 2: iSWAP PCR1 plate rail35 pos0 -> rail35 pos2 magnetic block",
            [
                sys.executable,
                str(ISWAP_TO_MAG_SCRIPT),
                "--mode",
                "move",
                "--confirm",
                "RUN_ISWAP_MAG_MOVE_TEST",
            ],
        )

        run_step(
            "STEP 3: Hamilton operator-defined cleanup",
            cleanup_cmd,
        )

        run_step(
            "STEP 4: iSWAP PCR1 cleanup plate rail35 pos2 magnetic block -> rail35 pos0",
            [
                sys.executable,
                str(ISWAP_TO_POS0_SCRIPT),
                "--mode",
                "move",
                "--confirm",
                "RUN_ISWAP_MAG_RETURN_TEST",
            ],
        )

    pause(
        "POST-CLEANUP / PRE-STAGE-2 CHECKPOINT\n"
        "Complete all operator-defined off-deck work and prepare stage-2 destination "
        "wells according to the approved local method.",
        pauses,
    )

    if not args.skip_pcr2_mm:
        run_step(
            "STEP 5: Hamilton PCR2 common master-mix add",
            pcr2_mm_cmd,
        )

    pause(
        "OFF-DECK PCR-ENRICHMENT STAGE-2 THERMAL HANDOFF AND FINISHING\n"
        "Run the approved operator-supplied thermal profile and complete the locally "
        "approved finishing and QC steps.",
        pauses,
    )

    print("")
    print("SUCCESS: PCR-enrichment V2 runner completed all currently built Hamilton LH steps.")
    print("")


if __name__ == "__main__":
    main()

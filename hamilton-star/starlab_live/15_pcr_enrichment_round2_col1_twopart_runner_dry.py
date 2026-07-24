import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
HAMILTON_ROOT = next(parent for parent in Path(__file__).resolve().parents if parent.name == "hamilton-star")
if str(HAMILTON_ROOT) not in sys.path:
    sys.path.insert(0, str(HAMILTON_ROOT))
from operator_parameters import required_positive

PCR2_TRANSFER_UL = required_positive("pcr_enrichment.round_2_transfer_ul")
SAMPLE_TRANSFER_UL = required_positive("pcr_enrichment.sample_transfer_ul")
SAMPLE_BLOWOUT_UL = required_positive("pcr_enrichment.sample_blowout_ul")

PCR2_MM_SCRIPT = ROOT / "13_pcr_enrichment_round2_col1_twopart_FROM_WORKING_MM.py"
PCR2_SAMPLE_SCRIPT = ROOT / "14_pcr_enrichment_round2_sample_col1_operator_volume_p10_FROM_WORKING_MM.py"


def run_step(label, cmd):
    print("")
    print("=" * 96)
    print(label)
    print("=" * 96)
    print(" ".join(str(x) for x in cmd))
    subprocess.run(cmd, cwd=ROOT, check=True)


def main():
    parser = argparse.ArgumentParser(
        description="PCR enrichment round 2 column-1 two-part runner using operator-profile volumes."
    )
    parser.add_argument(
        "--mode",
        choices=["dry", "wet"],
        default="dry",
        help="dry returns tips, wet discards tips.",
    )
    parser.add_argument(
        "--p50-tip-col",
        type=int,
        default=2,
        help="1-indexed p50 tip column on rail48 pos1 for PCR2 MM transfer.",
    )
    parser.add_argument(
        "--p10-tip-col",
        type=int,
        default=1,
        help="1-indexed p10 tip column on rail48 pos0 for sample transfer.",
    )
    args = parser.parse_args()

    return_flag = ["--return-tips"] if args.mode == "dry" else []

    print("")
    print("PCR ENRICHMENT ROUND 2 COLUMN-1 TWO-PART RUNNER")
    print("")
    print("Deck assumptions:")
    print("  rail35 pos1 col3 A-H = PCR2 MM + i5/i7 primers")
    print("  rail35 pos1 col1 A-H = diluted PCR1 samples")
    print("  rail35 pos0 col1 A-H = destination PCR2 wells")
    print("  rail48 pos1 = p50 tips")
    print("  rail48 pos0 = p10 tips")
    print("")
    print("Order:")
    print(f"  1. Add {PCR2_TRANSFER_UL:g} uL PCR2 reagent with p50 (operator profile)")
    print(
        f"  2. Add {SAMPLE_TRANSFER_UL:g} uL sample with p10 and "
        f"{SAMPLE_BLOWOUT_UL:g} uL blowout (operator profile)"
    )
    print("")
    print(f"Mode: {args.mode}")
    print("")

    run_step(
        f"STEP 1: PCR2 reagent, {PCR2_TRANSFER_UL:g} uL x8, source col3 -> destination col1, p50",
        [
            sys.executable,
            str(PCR2_MM_SCRIPT),
            "--mode",
            "pcr2-mm",
            "--tip-col",
            str(args.p50_tip_col),
            *return_flag,
        ],
    )

    run_step(
        f"STEP 2: sample, {SAMPLE_TRANSFER_UL:g} uL x8, source col1 -> destination col1, p10",
        [
            sys.executable,
            str(PCR2_SAMPLE_SCRIPT),
            "--mode",
            "pcr1-mm",
            "--tip-col",
            str(args.p10_tip_col),
            *return_flag,
        ],
    )

    print("")
    print("SUCCESS: PCR2 column-1 two-part runner completed.")
    print("")


if __name__ == "__main__":
    main()

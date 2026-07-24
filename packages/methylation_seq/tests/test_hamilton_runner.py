import importlib.util
import unittest
from pathlib import Path


RUNNER = (
    Path(__file__).resolve().parents[3]
    / "hamilton-star/starlab_live/methylation_seq/run_methylation_seq_odtc_1col_full_dry.py"
)
SPEC = importlib.util.spec_from_file_location("methylation_seq_hamilton_dry_runner", RUNNER)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class HamiltonRunnerTests(unittest.TestCase):
    def test_full_plan_has_36_executed_legs_and_8_odtc_notes(self):
        plan = MODULE.build_plan(sim_lh=False)
        self.assertEqual(sum(kind == "run" for kind, _, _ in plan), 36)
        self.assertEqual(sum(kind == "note" and label.startswith("ODTC thermal:")
                             for kind, label, _ in plan), 8)

    def test_deck_preflight_uses_only_scoped_deck_modes(self):
        preflight = MODULE.build_deck_preflight()
        commands = [payload for kind, _, payload in preflight if kind == "run"]
        self.assertEqual(len(commands), 6)
        for command in commands:
            self.assertIn("--mode", command)
            self.assertEqual(command[command.index("--mode") + 1], "deck")
            self.assertNotIn("--confirm", command)

    def test_hardware_gate_names_the_celltreat_labware(self):
        self.assertEqual(MODULE.CONFIRM_PHRASE, "RUN_METHYLATION_SEQ_ODTC_FULL")
        self.assertEqual(MODULE.LABWARE_ACK, "CELLTREAT_229195_WORK_SOURCE")

    def test_liquid_plate_and_heights_follow_working_pcr_enrichment_logic(self):
        repo = Path(__file__).resolve().parents[3]
        reagent = (repo / "hamilton-star/starlab_live/methylation_seq/methylation_seq_reagent_adds.py").read_text()
        cleanup = (repo / "hamilton-star/starlab_live/methylation_seq/methylation_seq_cleanup.py").read_text()
        pcr_enrichment = (
            repo
            / "hamilton-star/starlab_live/run_pcr_enrichment_odtc_LIDDED_1col_full_v2_singlehome_dry.py"
        ).read_text()
        runner = RUNNER.read_text()
        self.assertIn("work_plate = CellTreat_96_wellplate_350ul_Fb", reagent)
        self.assertIn("source_96wp = CellTreat_96_wellplate_350ul_Fb", reagent)
        for geometry_lock in (
            "P50_SOURCE_ASP_HEIGHT = [0.0] * 8",
            "P50_SOURCE_ASP_OFFSETS = [Coordinate(-0.65, 3.35, 0.0)] * 8",
            "P50_WORK_DSP_HEIGHT = [1.5] * 8",
            "P50_WORK_DSP_OFFSETS = [Coordinate(-0.68, 3.22, 0.0)] * 8",
        ):
            self.assertIn(geometry_lock, pcr_enrichment)
            self.assertIn(geometry_lock, reagent)
        self.assertIn("P10_SOURCE_ASP_HEIGHT = [0.0] * 8", reagent)
        self.assertIn("P10_WORK_DSP_HEIGHT = [0.5] * 8", reagent)
        self.assertIn("mag_plate = CellTreat_96_wellplate_350ul_Fb", cleanup)
        self.assertIn('"stage-1"', runner)
        self.assertIn('"cleanup-1"', runner)
        self.assertIn('"methylation-seq-stage-8"', runner)


if __name__ == "__main__":
    unittest.main()

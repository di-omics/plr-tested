import importlib.util
import unittest
from pathlib import Path


RUNNER = (
    Path(__file__).resolve().parents[3]
    / "hamilton-star/starlab_live/emseq/run_emseq_odtc_1col_full_dry.py"
)
SPEC = importlib.util.spec_from_file_location("emseq_hamilton_dry_runner", RUNNER)
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
        self.assertEqual(MODULE.CONFIRM_PHRASE, "RUN_EMSEQ_ODTC_FULL")
        self.assertEqual(MODULE.LABWARE_ACK, "CELLTREAT_229195_WORK_SOURCE")

    def test_liquid_plate_and_heights_follow_working_targeted_pcr_logic(self):
        repo = Path(__file__).resolve().parents[3]
        reagent = (repo / "hamilton-star/starlab_live/emseq/emseq_reagent_adds.py").read_text()
        cleanup = (repo / "hamilton-star/starlab_live/emseq/emseq_cleanup.py").read_text()
        targeted_pcr = (
            repo
            / "hamilton-star/starlab_live/run_targeted_pcr_odtc_LIDDED_1col_full_v2_singlehome_dry.py"
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
            self.assertIn(geometry_lock, targeted_pcr)
            self.assertIn(geometry_lock, reagent)
        self.assertIn("P10_SOURCE_ASP_HEIGHT = [0.0] * 8", reagent)
        self.assertIn("P10_WORK_DSP_HEIGHT = [0.5] * 8", reagent)
        self.assertIn("mag_plate = CellTreat_96_wellplate_350ul_Fb", cleanup)
        self.assertIn("CellTreat_96_wellplate_350ul_Fb work plate", runner)


if __name__ == "__main__":
    unittest.main()

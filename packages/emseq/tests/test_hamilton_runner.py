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

    def test_moving_plate_model_is_consistent_across_hamilton_scripts(self):
        repo = Path(__file__).resolve().parents[3]
        reagent = (repo / "hamilton-star/starlab_live/emseq/emseq_reagent_adds.py").read_text()
        cleanup = (repo / "hamilton-star/starlab_live/emseq/emseq_cleanup.py").read_text()
        runner = RUNNER.read_text()
        self.assertIn("work_plate = Cor_96_wellplate_360ul_Fb", reagent)
        self.assertIn("mag_plate = Cor_96_wellplate_360ul_Fb", cleanup)
        self.assertIn("Cor_96_wellplate_360ul_Fb work plate", runner)


if __name__ == "__main__":
    unittest.main()

import json
import os
import tempfile
import unittest

from methylation_seq_automation.manifest import build_run
from methylation_seq_automation.orchestrator import RunStatus, run
from methylation_seq_automation.reporting import write_artifacts


def config(two=False, blank=True):
    samples = [{"id": "water-1", "well": "A1"}]
    if two:
        samples.append({"id": "water-2", "well": "B1"})
    if blank:
        samples.append({"id": "blank", "well": "H1", "type": "process_blank"})
    return build_run({
        "run_id": "R",
        "operator": "di",
        "mode": "simulation",
        "profile_kind": "synthetic_water",
        "samples": samples,
    })


class OrchestratorTests(unittest.TestCase):
    def test_simulation_completes_and_excludes_blank(self):
        outcome = run(config(), timestamp="t")
        self.assertEqual(outcome.status, RunStatus.COMPLETED)
        self.assertEqual(outcome.final_sample_ids, ["water-1"])
        self.assertTrue(all(action.executed for action in outcome.actions))
        self.assertTrue(outcome.metrics["simulated"])

    def test_bad_deck_stops_before_protocol_actions(self):
        outcome = run(config(), poor_deck=True)
        self.assertEqual(outcome.status, RunStatus.STOPPED)
        self.assertEqual(outcome.actions, [])

    def test_one_bad_library_proceeds_as_subset(self):
        outcome = run(config(two=True), failing_sample="water-2")
        self.assertEqual(outcome.status, RunStatus.COMPLETED)
        self.assertEqual(outcome.final_sample_ids, ["water-1"])
        self.assertEqual(outcome.gates[-1].decision.value, "proceed_subset")

    def test_missing_measurements_fail_closed(self):
        observed = {"simulated": False, "liquid_handling": {"cv_percent": {}}, "samples": {}}
        outcome = run(config(), metrics=observed)
        self.assertEqual(outcome.status, RunStatus.STOPPED)
        self.assertIn("required profile volume", outcome.message)

    def test_writes_complete_artifact_set(self):
        outcome = run(config(), timestamp="t")
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = write_artifacts(outcome, tmp)
            self.assertEqual(
                set(os.listdir(run_dir)),
                {"outcome.json", "dossier.html", "run_card.md", "sequencing_samplesheet.csv"},
            )
            with open(os.path.join(run_dir, "outcome.json"), encoding="utf-8") as handle:
                self.assertEqual(json.load(handle)["profile_kind"], "synthetic_water")


if __name__ == "__main__":
    unittest.main()

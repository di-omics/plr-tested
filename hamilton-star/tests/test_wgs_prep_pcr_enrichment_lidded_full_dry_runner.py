"""Offline tests for the guarded full WGS preparation-to-PCR enrichment dry composition."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock


RUNNER = (
    Path(__file__).resolve().parents[1]
    / "starlab_live"
    / "run_wgs_prep_pcr_enrichment_LIDDED_1col_full_dry.py"
)


def load_runner():
    name = "wgs_prep_pcr_enrichment_lidded_full_dry_under_test"
    spec = importlib.util.spec_from_file_location(name, RUNNER)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load {}".format(RUNNER))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class CombinedDryRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runner = load_runner()

    def test_plan_is_inert_and_accepts_one_to_eight(self):
        for count in (1, 8):
            with self.subTest(count=count), mock.patch.object(
                self.runner.subprocess, "run"
            ) as run:
                self.runner.main(["--mode", "plan", "--sample-count", str(count)])
                run.assert_not_called()

    def test_unsupported_counts_fail_before_any_child_process(self):
        for count in (0, 9, 96):
            with self.subTest(count=count), mock.patch.object(
                self.runner.subprocess, "run"
            ) as run:
                with self.assertRaisesRegex(RuntimeError, "No released one-column"):
                    self.runner.main(["--mode", "chatterbox", "--sample-count", str(count)])
                run.assert_not_called()

    def test_star_release_requires_all_three_exact_outer_gates_before_spawn(self):
        cases = (
            [],
            ["--confirm", self.runner.CONFIRM_TOKEN],
            [
                "--confirm",
                self.runner.CONFIRM_TOKEN,
                "--acknowledge",
                self.runner.DECK_ACK,
            ],
        )
        for supplied in cases:
            with self.subTest(supplied=supplied), mock.patch.object(
                self.runner.subprocess, "run"
            ) as run:
                with self.assertRaises(RuntimeError):
                    self.runner.main(["--mode", "star", *supplied])
                run.assert_not_called()

    def test_deck_mode_runs_only_both_connection_free_child_previews(self):
        with mock.patch.object(self.runner.subprocess, "run") as run:
            self.runner.main(["--mode", "deck"])

        self.assertEqual(run.call_count, 2)
        self.assertEqual(
            run.call_args_list[0].args[0],
            self.runner.child_command(self.runner.WGS_PREP_SCRIPT, "deck"),
        )
        self.assertEqual(
            run.call_args_list[1].args[0],
            self.runner.child_command(self.runner.PCR_ENRICHMENT_SCRIPT, "deck"),
        )
        for call in run.call_args_list:
            self.assertTrue(call.kwargs["check"])

    def test_chatterbox_runs_wgs_prep_then_pcr_enrichment_without_star_tokens(self):
        with mock.patch.object(self.runner.subprocess, "run") as run:
            self.runner.main(["--mode", "chatterbox", "--sample-count", "3"])

        self.assertEqual(
            [call.args[0] for call in run.call_args_list],
            [
                self.runner.child_command(self.runner.WGS_PREP_SCRIPT, "chatterbox"),
                self.runner.child_command(self.runner.PCR_ENRICHMENT_SCRIPT, "chatterbox"),
            ],
        )
        for command in (call.args[0] for call in run.call_args_list):
            self.assertNotIn("--confirm", command)

    def test_star_runs_both_deck_preflights_before_exact_guarded_children(self):
        argv = [
            "--mode",
            "star",
            "--sample-count",
            "8",
            "--confirm",
            self.runner.CONFIRM_TOKEN,
            "--acknowledge",
            self.runner.DECK_ACK,
            "--labware-ack",
            self.runner.LABWARE_ACK,
        ]
        with mock.patch.object(self.runner.subprocess, "run") as run:
            self.runner.main(
                argv,
                input_fn=lambda _prompt: self.runner.INTERPHASE_ACK,
            )

        self.assertEqual(
            [call.args[0] for call in run.call_args_list],
            [
                self.runner.child_command(self.runner.WGS_PREP_SCRIPT, "deck"),
                self.runner.child_command(self.runner.PCR_ENRICHMENT_SCRIPT, "deck"),
                self.runner.child_command(self.runner.WGS_PREP_SCRIPT, "star"),
                self.runner.child_command(self.runner.PCR_ENRICHMENT_SCRIPT, "star"),
            ],
        )

    def test_child_failure_stops_before_the_next_phase(self):
        argv = [
            "--mode",
            "star",
            "--confirm",
            self.runner.CONFIRM_TOKEN,
            "--acknowledge",
            self.runner.DECK_ACK,
            "--labware-ack",
            self.runner.LABWARE_ACK,
        ]
        failure = subprocess.CalledProcessError(1, "wgs_prep")
        with mock.patch.object(
            self.runner.subprocess,
            "run",
            side_effect=[mock.DEFAULT, mock.DEFAULT, failure],
        ) as run:
            with self.assertRaises(subprocess.CalledProcessError):
                self.runner.main(argv)

        self.assertEqual(run.call_count, 3)
        self.assertEqual(
            run.call_args_list[-1].args[0],
            self.runner.child_command(self.runner.WGS_PREP_SCRIPT, "star"),
        )

    def test_wrong_interphase_observation_blocks_pcr_enrichment_after_wgs_prep(self):
        argv = [
            "--mode",
            "star",
            "--confirm",
            self.runner.CONFIRM_TOKEN,
            "--acknowledge",
            self.runner.DECK_ACK,
            "--labware-ack",
            self.runner.LABWARE_ACK,
        ]
        with mock.patch.object(self.runner.subprocess, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "PCR enrichment was not started"):
                self.runner.main(argv, input_fn=lambda _prompt: "NOT_CONFIRMED")

        self.assertEqual(run.call_count, 3)
        self.assertEqual(
            run.call_args_list[-1].args[0],
            self.runner.child_command(self.runner.WGS_PREP_SCRIPT, "star"),
        )

    def test_missing_interphase_input_blocks_pcr_enrichment_after_wgs_prep(self):
        def no_input(_prompt):
            raise EOFError

        argv = [
            "--mode",
            "star",
            "--confirm",
            self.runner.CONFIRM_TOKEN,
            "--acknowledge",
            self.runner.DECK_ACK,
            "--labware-ack",
            self.runner.LABWARE_ACK,
        ]
        with mock.patch.object(self.runner.subprocess, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "could not be read"):
                self.runner.main(argv, input_fn=no_input)

        self.assertEqual(run.call_count, 3)

    def test_child_star_argv_carries_each_runner_exact_release_tokens(self):
        wgs_prep = self.runner.child_command(self.runner.WGS_PREP_SCRIPT, "star")
        pcr_enrichment = self.runner.child_command(self.runner.PCR_ENRICHMENT_SCRIPT, "star")
        self.assertEqual(
            wgs_prep[-6:],
            [
                "--confirm",
                self.runner.WGS_PREP_CONFIRM_TOKEN,
                "--acknowledge",
                self.runner.WGS_PREP_DECK_ACK,
                "--labware-ack",
                self.runner.WGS_PREP_LABWARE_ACK,
            ],
        )
        self.assertEqual(
            pcr_enrichment[-6:],
            [
                "--confirm",
                self.runner.PCR_ENRICHMENT_CONFIRM_TOKEN,
                "--acknowledge",
                self.runner.PCR_ENRICHMENT_DECK_ACK,
                "--labware-ack",
                self.runner.PCR_ENRICHMENT_LABWARE_ACK,
            ],
        )


if __name__ == "__main__":
    unittest.main()

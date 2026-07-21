import unittest

from pta_ampseq_app.planner import SampleCountError, plan_samples
from pta_ampseq_app.registry import DECK_ID, combined_dry_deck, release_summary


class PlannerTests(unittest.TestCase):
    def test_one_sample_uses_one_full_actuated_column_with_blanks(self):
        plan = plan_samples(1)

        self.assertEqual(plan.sample_wells, ("A1",))
        self.assertEqual(
            plan.blank_wells,
            ("B1", "C1", "D1", "E1", "F1", "G1", "H1"),
        )
        self.assertEqual(
            plan.actuated_wells,
            ("A1", "B1", "C1", "D1", "E1", "F1", "G1", "H1"),
        )
        payload = plan.to_dict()
        self.assertEqual(payload["robot_reaction_count"], 8)
        self.assertEqual(payload["unused_positions"], 7)
        self.assertEqual(payload["mode"], "dry_planning_only")

    def test_eight_samples_fill_the_only_validated_column(self):
        plan = plan_samples(8)

        self.assertEqual(
            plan.sample_wells,
            ("A1", "B1", "C1", "D1", "E1", "F1", "G1", "H1"),
        )
        self.assertEqual(plan.blank_wells, ())

    def test_sample_count_has_no_hidden_ntc_or_control_allowance(self):
        payload = plan_samples(3).to_dict()

        self.assertEqual(payload["sample_count"], 3)
        self.assertEqual(payload["sample_wells"], ["A1", "B1", "C1"])
        self.assertEqual(payload["blank_wells"], ["D1", "E1", "F1", "G1", "H1"])
        self.assertIn(
            "Sample count is biological samples only; no NTC or control wells are added.",
            payload["notes"],
        )

    def test_zero_fails_closed(self):
        with self.assertRaises(SampleCountError) as caught:
            plan_samples(0)

        self.assertEqual(caught.exception.code, "below_minimum")

    def test_more_than_one_column_fails_closed(self):
        with self.assertRaises(SampleCountError) as caught:
            plan_samples(9)

        self.assertEqual(caught.exception.code, "no_validated_multicolumn_build")

    def test_non_integer_inputs_are_never_coerced(self):
        malformed = (None, True, False, 1.0, "8", {}, [])
        for value in malformed:
            with self.subTest(value=value):
                with self.assertRaises(SampleCountError) as caught:
                    plan_samples(value)
                self.assertEqual(caught.exception.code, "invalid_type")


class RegistryTests(unittest.TestCase):
    def test_combined_dry_deck_has_the_expected_unique_positions(self):
        deck = combined_dry_deck()
        expected = {
            (48, 0),
            (48, 1),
            (48, 2),
            (35, 0),
            (35, 1),
            (35, 2),
            (35, 3),
            (35, 4),
            (27, 2),
            (20, 1),
        }
        positions = {(item.rail, item.position) for item in deck.items}
        keys = {item.key for item in deck.items}

        self.assertEqual(deck.deck_id, DECK_ID)
        self.assertEqual(deck.mode, "dry_planning_only")
        self.assertEqual(positions, expected)
        self.assertEqual(len(positions), len(deck.items))
        self.assertEqual(len(keys), len(deck.items))

    def test_deck_calls_out_park_plate_hhs_and_odtc(self):
        deck = combined_dry_deck()
        by_key = {item.key: item for item in deck.items}

        self.assertIn("lid", by_key["r35p4_lid"].instruction.lower())
        self.assertIn("empty", by_key["r27p2_hhs"].instruction.lower())
        self.assertIn("idle", by_key["r27p2_hhs"].instruction.lower())
        self.assertIn("empty", by_key["r20p1_odtc"].instruction.lower())
        self.assertIn("idle", by_key["r20p1_odtc"].instruction.lower())

    def test_no_validated_release_manifest_means_locked(self):
        release = release_summary()

        self.assertFalse(release.available)
        self.assertEqual(release.builds, ())
        self.assertEqual(release.issues, ())
        self.assertIn("no validated", release.message.lower())


if __name__ == "__main__":
    unittest.main()

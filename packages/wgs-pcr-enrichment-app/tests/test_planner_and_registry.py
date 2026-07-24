import unittest

from wgs_pcr_enrichment_app.planner import SampleCountError, plan_samples
from wgs_pcr_enrichment_app.registry import DECK_ID, combined_dry_deck, release_summary


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
        self.assertEqual(payload["column_count"], 1)
        self.assertEqual(payload["actuated_columns"], [1])
        self.assertEqual(payload["robot_reaction_count"], 8)
        self.assertEqual(payload["unused_positions"], 7)
        self.assertEqual(payload["unused_plate_wells"], 88)
        self.assertTrue(payload["current_runner"]["eligible"])
        self.assertEqual(payload["mode"], "dry_planning_only")

    def test_eight_samples_fill_the_physically_eligible_column(self):
        payload = plan_samples(8).to_dict()

        self.assertEqual(
            payload["sample_wells"],
            ["A1", "B1", "C1", "D1", "E1", "F1", "G1", "H1"],
        )
        self.assertEqual(payload["blank_wells"], [])
        self.assertEqual(payload["column_count"], 1)
        self.assertTrue(payload["current_runner"]["eligible"])

    def test_nine_samples_fill_column_major_and_pad_final_column(self):
        payload = plan_samples(9).to_dict()

        self.assertEqual(
            payload["sample_wells"],
            ["A1", "B1", "C1", "D1", "E1", "F1", "G1", "H1", "A2"],
        )
        self.assertEqual(
            payload["blank_wells"],
            ["B2", "C2", "D2", "E2", "F2", "G2", "H2"],
        )
        self.assertEqual(payload["actuated_columns"], [1, 2])
        self.assertEqual(payload["column_count"], 2)
        self.assertEqual(payload["robot_reaction_count"], 16)
        self.assertEqual(payload["unused_plate_wells"], 80)
        self.assertFalse(payload["current_runner"]["eligible"])

    def test_partial_columns_have_blanks_only_at_the_end(self):
        expected = {
            15: (["H2"], 2),
            17: (["B3", "C3", "D3", "E3", "F3", "G3", "H3"], 3),
            95: (["H12"], 12),
        }
        for sample_count, (blank_wells, column_count) in expected.items():
            with self.subTest(sample_count=sample_count):
                payload = plan_samples(sample_count).to_dict()
                self.assertEqual(payload["blank_wells"], blank_wells)
                self.assertEqual(payload["column_count"], column_count)
                self.assertEqual(
                    payload["robot_reaction_count"],
                    column_count * 8,
                )
                self.assertEqual(
                    payload["actuated_wells"],
                    payload["sample_wells"] + payload["blank_wells"],
                )

    def test_full_plate_contains_all_96_wells(self):
        payload = plan_samples(96).to_dict()

        expected_column_major = [
            f"{row}{column}"
            for column in range(1, 13)
            for row in "ABCDEFGH"
        ]
        self.assertEqual(payload["sample_wells"], expected_column_major)
        self.assertEqual(payload["blank_wells"], [])
        self.assertEqual(payload["actuated_columns"], list(range(1, 13)))
        self.assertEqual(payload["robot_reaction_count"], 96)
        self.assertEqual(payload["unused_plate_wells"], 0)
        self.assertFalse(payload["current_runner"]["eligible"])

    def test_plate_layout_always_describes_96_unique_wells(self):
        for sample_count in (1, 9, 64, 96):
            with self.subTest(sample_count=sample_count):
                payload = plan_samples(sample_count).to_dict()
                layout = payload["plate_layout"]
                by_well = {item["well"]: item["state"] for item in layout}
                self.assertEqual(len(layout), 96)
                self.assertEqual(len(by_well), 96)
                self.assertEqual(
                    set(by_well),
                    {f"{row}{column}" for row in "ABCDEFGH" for column in range(1, 13)},
                )
                self.assertEqual(
                    sum(state == "sample" for state in by_well.values()),
                    sample_count,
                )
                self.assertEqual(
                    sum(state == "blank" for state in by_well.values()),
                    len(payload["blank_wells"]),
                )

    def test_physical_runner_eligibility_stops_after_eight_samples(self):
        for sample_count, expected in ((1, True), (8, True), (9, False), (96, False)):
            with self.subTest(sample_count=sample_count):
                payload = plan_samples(sample_count).to_dict()
                self.assertIs(payload["current_runner"]["eligible"], expected)
                self.assertEqual(payload["current_runner"]["sample_count_max"], 8)
                self.assertEqual(payload["current_runner"]["column_count_max"], 1)

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

    def test_more_than_one_plate_fails_closed(self):
        with self.assertRaises(SampleCountError) as caught:
            plan_samples(97)

        self.assertEqual(caught.exception.code, "above_plate_capacity")

    def test_non_integer_inputs_are_never_coerced(self):
        malformed = (None, True, False, 1.0, "96", {}, [])
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
        positions_by_rail = {}
        for item in deck.items:
            positions_by_rail.setdefault(item.rail, []).append(item.position)
        self.assertEqual(
            positions_by_rail,
            {48: [0, 1, 2], 35: [0, 1, 2, 3, 4], 27: [2], 20: [1]},
        )

    def test_deck_location_labels_translate_zero_based_positions(self):
        deck = combined_dry_deck()
        expected = {
            "r48p0_p10": "Rail 48 · p0 (first slot)",
            "r48p1_p50": "Rail 48 · p1 (second slot)",
            "r48p2_p300": "Rail 48 · p2 (third slot)",
            "r35p0_work": "Rail 35 · p0 (first slot)",
            "r35p1_source": "Rail 35 · p1 (second slot)",
            "r35p2_magnet": "Rail 35 · p2 (third slot)",
            "r35p3_trough": "Rail 35 · p3 (fourth slot)",
            "r35p4_lid": "Rail 35 · p4 (fifth slot)",
            "r27p2_hhs": "Rail 27 · p2 (HHS modeled target)",
            "r20p1_odtc": "Rail 20 · p1 (ODTC modeled target)",
        }

        self.assertEqual(
            {item.key: item.location_label for item in deck.items},
            expected,
        )
        self.assertEqual(
            {item["key"]: item["location_label"] for item in deck.to_dict()["items"]},
            expected,
        )

    def test_deck_calls_out_park_plate_hhs_and_odtc(self):
        deck = combined_dry_deck()
        by_key = {item.key: item for item in deck.items}

        self.assertIn("lid", by_key["r35p4_lid"].instruction.lower())
        self.assertIn("empty", by_key["r27p2_hhs"].instruction.lower())
        self.assertIn("idle", by_key["r27p2_hhs"].instruction.lower())
        self.assertIn("empty", by_key["r20p1_odtc"].instruction.lower())
        self.assertIn("idle", by_key["r20p1_odtc"].instruction.lower())
        self.assertIn("keep the hhs installed", by_key["r27p2_hhs"].instruction.lower())
        self.assertIn("keep the odtc installed", by_key["r20p1_odtc"].instruction.lower())

    def test_no_validated_release_manifest_means_locked(self):
        release = release_summary()

        self.assertFalse(release.available)
        self.assertEqual(release.builds, ())
        self.assertEqual(release.issues, ())
        self.assertIn("no validated", release.message.lower())


if __name__ == "__main__":
    unittest.main()

import copy
import unittest

from emseq_automation.config import InputTier
from emseq_automation.manifest import ManifestError, build_run


BASE = {
    "run_id": "T",
    "operator": "di",
    "mode": "simulation",
    "samples": [{"id": "s1", "well": "A1", "input_ng": 10, "udi": "UDI-1"}],
}


class ManifestTests(unittest.TestCase):
    def test_derives_unambiguous_defaults(self):
        config = build_run(copy.deepcopy(BASE))
        self.assertEqual(config.pcr_cycles, 8)
        self.assertEqual(config.input_tier, InputTier.LOW)
        self.assertEqual(config.samples[0].control_dilution, "1:100")

    def test_rejects_mixed_low_and_high_routes(self):
        data = copy.deepcopy(BASE)
        data["samples"].append({
            "id": "s2", "well": "B1", "input_ng": 50, "udi": "UDI-2",
            "control_dilution": "1:75",
        })
        data["pcr_cycles"] = 6
        with self.assertRaisesRegex(ManifestError, "cannot mix"):
            build_run(data)

    def test_rejects_duplicate_udi(self):
        data = copy.deepcopy(BASE)
        data["samples"].append({"id": "s2", "well": "B1", "input_ng": 10, "udi": "UDI-1"})
        with self.assertRaisesRegex(ManifestError, "assigned more than once"):
            build_run(data)

    def test_rejects_unimplemented_column(self):
        data = copy.deepcopy(BASE)
        data["samples"][0]["well"] = "A2"
        with self.assertRaisesRegex(ManifestError, "A1-H1"):
            build_run(data)

    def test_requires_choices_where_manual_is_ambiguous(self):
        data = copy.deepcopy(BASE)
        data["samples"][0].update({"input_ng": 50, "control_dilution": "1:75"})
        with self.assertRaisesRegex(ManifestError, "pcr_cycles is required"):
            build_run(data)
        data["pcr_cycles"] = 5
        config = build_run(data)
        self.assertEqual(config.input_tier, InputTier.HIGH)

    def test_rejects_wrong_cycles_for_exact_table_row(self):
        data = copy.deepcopy(BASE)
        data["pcr_cycles"] = 11
        with self.assertRaisesRegex(ManifestError, "conflicts with M7634"):
            build_run(data)

    def test_process_blank_does_not_change_input_tier(self):
        data = copy.deepcopy(BASE)
        data["samples"].append({
            "id": "blank", "well": "H1", "input_ng": 0, "udi": "UDI-B",
            "type": "process_blank",
        })
        self.assertEqual(build_run(data).input_tier, InputTier.LOW)

    def test_rejects_path_like_run_id(self):
        data = copy.deepcopy(BASE)
        data["run_id"] = "../outside"
        with self.assertRaisesRegex(ManifestError, "run_id"):
            build_run(data)


if __name__ == "__main__":
    unittest.main()

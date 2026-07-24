import copy
import json
import tempfile
import unittest

from methylation_seq_automation.config import ProfileKind
from methylation_seq_automation.manifest import ManifestError, build_run


BASE = {
    "run_id": "T",
    "operator": "di",
    "mode": "simulation",
    "profile_kind": "synthetic_water",
    "samples": [{"id": "water", "well": "A1"}],
}


class ManifestTests(unittest.TestCase):
    def test_public_default_is_synthetic_water(self):
        config = build_run(copy.deepcopy(BASE))
        self.assertEqual(config.profile_kind, ProfileKind.SYNTHETIC_WATER)
        self.assertTrue(config.method["water_only"])
        self.assertEqual(config.samples[0].control_dilution, "operator-configured")

    def test_hardware_rejects_public_profile(self):
        data = copy.deepcopy(BASE)
        data["mode"] = "hardware"
        with self.assertRaisesRegex(ManifestError, "requires profile_kind 'operator'"):
            build_run(data)

    def test_operator_profile_is_external_and_explicit(self):
        profile = {
            "schema_version": 1,
            "method_name": "private approved method",
            "water_only": False,
            "qualified_volumes_ul": [1.25, 27.5],
            "acceptance": {
                "lh_cv_max_percent": 4.0,
                "sample_rules": [{"metric": "qc_a", "minimum": 1.0}],
                "blank_rules": [{"metric": "blank_a", "maximum": 1.0}],
            },
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json") as handle:
            json.dump(profile, handle)
            handle.flush()
            data = copy.deepcopy(BASE)
            data.update({"profile_kind": "operator", "method_profile": handle.name})
            config = build_run(data)
        self.assertEqual(config.profile_kind, ProfileKind.OPERATOR)
        self.assertEqual(config.method["qualified_volumes_ul"], [1.25, 27.5])

    def test_rejects_duplicate_well(self):
        data = copy.deepcopy(BASE)
        data["samples"].append({"id": "water-2", "well": "A1"})
        with self.assertRaisesRegex(ManifestError, "unique A1-H1"):
            build_run(data)

    def test_rejects_unimplemented_column(self):
        data = copy.deepcopy(BASE)
        data["samples"][0]["well"] = "A2"
        with self.assertRaisesRegex(ManifestError, "A1-H1"):
            build_run(data)

    def test_rejects_path_like_run_id(self):
        data = copy.deepcopy(BASE)
        data["run_id"] = "../outside"
        with self.assertRaisesRegex(ManifestError, "run_id"):
            build_run(data)


if __name__ == "__main__":
    unittest.main()

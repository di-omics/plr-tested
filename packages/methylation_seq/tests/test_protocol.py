import unittest

from methylation_seq_automation.manifest import build_run
from methylation_seq_automation.protocol import build_protocol, qualified_volumes


def config():
    return build_run({
        "run_id": "P",
        "operator": "di",
        "mode": "simulation",
        "profile_kind": "synthetic_water",
        "samples": [{"id": "water", "well": "A1"}],
    })


class ProtocolTests(unittest.TestCase):
    def test_generic_complete_shape(self):
        steps = build_protocol(config())
        self.assertEqual(len(steps), 24)
        self.assertEqual(sum(step.operation == "ODTC" for step in steps), 8)
        self.assertEqual(
            sum(step.operation in ("STAR reagent add", "STAR per-well reagent add") for step in steps),
            11,
        )
        self.assertTrue(all(step.reaction_after_ul is None for step in steps))
        self.assertTrue(all(not step.components_ul for step in steps))

    def test_names_are_numbered_generic_stages(self):
        names = [step.name for step in build_protocol(config())]
        self.assertIn("Reagent stage 1", names)
        self.assertIn("Reagent stage 11", names)
        self.assertIn("Cleanup 3", names)
        self.assertNotIn("master mix", " ".join(names).lower())

    def test_public_qualification_is_explicitly_synthetic(self):
        self.assertEqual(qualified_volumes(config()), [20.0])


if __name__ == "__main__":
    unittest.main()

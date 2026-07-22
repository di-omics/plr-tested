import unittest

from emseq_automation.manifest import build_run
from emseq_automation.protocol import build_protocol, qualified_volumes


def config(input_ng=10, cycles=8, dilution=None):
    sample = {"id": "s", "well": "A1", "input_ng": input_ng, "udi": "UDI"}
    if dilution:
        sample["control_dilution"] = dilution
    return build_run({
        "run_id": "P", "operator": "di", "mode": "simulation",
        "pcr_cycles": cycles, "samples": [sample],
    })


class ProtocolTests(unittest.TestCase):
    def test_complete_shape_and_volumes(self):
        steps = build_protocol(config())
        self.assertEqual(len(steps), 24)
        self.assertEqual(sum(step.operation == "ODTC" for step in steps), 8)
        self.assertEqual(sum(step.operation in ("STAR reagent add", "STAR per-well reagent add")
                             for step in steps), 11)
        self.assertEqual(steps[-1].reaction_after_ul, 20.0)
        pcr = next(step for step in steps if step.name == "Library PCR")
        self.assertIn("8 x", pcr.note)

    def test_low_input_route_has_carrier(self):
        cleanup = next(step for step in build_protocol(config())
                       if step.name == "Post-ligation SPRI cleanup")
        self.assertEqual(cleanup.components_ul["Carrier DNA"], 1.0)
        self.assertIn("transfer 27 uL", cleanup.note)

    def test_high_input_route_uses_29_ul_elution(self):
        cleanup = next(step for step in build_protocol(config(50, 5, "1:75"))
                       if step.name == "Post-ligation SPRI cleanup")
        self.assertNotIn("Carrier DNA", cleanup.components_ul)
        self.assertEqual(cleanup.components_ul["Elution Buffer"], 29.0)

    def test_qualification_spans_small_and_large_transfers(self):
        volumes = qualified_volumes(config())
        self.assertIn(1.0, volumes)
        self.assertIn(45.0, volumes)
        self.assertIn(93.0, volumes)
        self.assertIn(200.0, volumes)


if __name__ == "__main__":
    unittest.main()


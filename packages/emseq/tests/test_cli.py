import io
import unittest
from contextlib import redirect_stdout

from emseq_automation.cli import main


class CliTests(unittest.TestCase):
    def test_compute_doctor_runs(self):
        stream = io.StringIO()
        with redirect_stdout(stream):
            code = main(["doctor"])
        self.assertEqual(code, 0)
        self.assertIn("deterministic simulation", stream.getvalue())


if __name__ == "__main__":
    unittest.main()


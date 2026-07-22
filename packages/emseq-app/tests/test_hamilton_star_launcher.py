import subprocess
import sys
from pathlib import Path
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
LAUNCHER = (
    REPOSITORY_ROOT
    / "hamilton-star"
    / "starlab_live"
    / "emseq"
    / "launch_bench_planner.py"
)


class HamiltonStarLauncherTests(unittest.TestCase):
    def test_star_side_launcher_resolves_the_canonical_planner(self):
        result = subprocess.run(
            [sys.executable, str(LAUNCHER), "--help"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Planning-only local EM-seq", result.stdout)
        self.assertIn("--port", result.stdout)


if __name__ == "__main__":
    unittest.main()

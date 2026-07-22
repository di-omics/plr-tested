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

    def test_legacy_visual_previews_point_to_planner_without_runtime_scaling(self):
        for filename in ("emseq-run-app.html", "emseq-run-app-desktop.html"):
            with self.subTest(filename=filename):
                html = (REPOSITORY_ROOT / "hamilton-star" / filename).read_text(
                    encoding="utf-8"
                )
                self.assertIn("legacy visual preview", html)
                self.assertIn("http://127.0.0.1:8767/", html)
                self.assertIn("runtime not estimated", html)
                self.assertNotIn("446 +", html)
                self.assertNotIn("~7h 26m", html)


if __name__ == "__main__":
    unittest.main()

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SERVER_PATH = Path(__file__).with_name("server.py")
SPEC = importlib.util.spec_from_file_location("walkup_server", SERVER_PATH)
SERVER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SERVER)


def valid_build():
    return {
        "tag": "targeted-pcr-validated-local",
        "sha": "a" * 40,
        "script": "starlab_live/run_targeted_pcr_odtc_LIDDED_1col_full_dry.py",
        "token": "RUN_TARGETED_PCR_ODTC_LIDDED_FULL",
        "runner_match": "run_targeted_pcr_odtc_LIDDED_1col_full_dry",
        "label": "1 column - 8 reactions",
        "legs": 13,
        "record": "qualified local build",
        "minutes": 18,
    }


class BuildConfigTests(unittest.TestCase):
    def write(self, root, payload):
        path = Path(root) / "builds.json"
        if isinstance(payload, str):
            path.write_text(payload)
        else:
            path.write_text(json.dumps(payload))
        return path

    def test_missing_malformed_and_empty_fail_closed(self):
        with tempfile.TemporaryDirectory() as root:
            builds, status = SERVER.load_builds(Path(root) / "missing.json")
            self.assertEqual(builds, {})
            self.assertIn("No local build", status)

            builds, status = SERVER.load_builds(self.write(root, "{"))
            self.assertEqual(builds, {})
            self.assertIn("invalid", status)

            path = self.write(root, {"schema_version": 1, "builds": {}})
            builds, status = SERVER.load_builds(path)
            self.assertEqual(builds, {})
            self.assertIn("no builds", status)

    def test_valid_registry_loads(self):
        with tempfile.TemporaryDirectory() as root:
            path = self.write(root, {
                "schema_version": 1,
                "builds": {"targeted-pcr-one-column": valid_build()},
            })
            builds, status = SERVER.load_builds(path)
            self.assertEqual(list(builds), ["targeted-pcr-one-column"])
            self.assertEqual(builds["targeted-pcr-one-column"]["legs"], 13)
            self.assertIn("Loaded 1", status)

    def test_invalid_builds_fail_the_complete_registry(self):
        cases = {
            "short sha": ("sha", "abc"),
            "uppercase sha": ("sha", "A" * 40),
            "zero legs": ("legs", 0),
            "boolean minutes": ("minutes", True),
            "absolute script": ("script", "/tmp/run.py"),
            "traversal script": ("script", "starlab_live/../run.py"),
            "wrong script root": ("script", "other/run.py"),
            "unsafe tag": ("tag", "../moving-ref"),
            "lowercase token": ("token", "run_targeted_pcr"),
            "runner path": ("runner_match", "../runner"),
            "runner mismatch": ("runner_match", "different_runner"),
            "empty label": ("label", ""),
        }
        with tempfile.TemporaryDirectory() as root:
            for name, (field, value) in cases.items():
                with self.subTest(name=name):
                    build = valid_build()
                    build[field] = value
                    path = self.write(root, {
                        "schema_version": 1,
                        "builds": {"targeted-pcr-one-column": build},
                    })
                    builds, status = SERVER.load_builds(path)
                    self.assertEqual(builds, {})
                    self.assertIn("invalid", status.lower())

    def test_missing_or_extra_fields_fail_closed(self):
        with tempfile.TemporaryDirectory() as root:
            for mutate in ("missing", "extra"):
                with self.subTest(mutate=mutate):
                    build = valid_build()
                    if mutate == "missing":
                        del build["record"]
                    else:
                        build["unexpected"] = "value"
                    path = self.write(root, {
                        "schema_version": 1,
                        "builds": {"targeted-pcr-one-column": build},
                    })
                    builds, status = SERVER.load_builds(path)
                    self.assertEqual(builds, {})
                    self.assertIn("invalid", status.lower())

    def test_ui_has_zero_build_guard(self):
        html = Path(__file__).with_name("index.html").read_text()
        self.assertIn("if(!build)", html)
        self.assertIn("no authorized local build configured", html)


if __name__ == "__main__":
    unittest.main()

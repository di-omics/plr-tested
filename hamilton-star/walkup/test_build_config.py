import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SERVER_PATH = Path(__file__).with_name("server.py")
SPEC = importlib.util.spec_from_file_location("walkup_server", SERVER_PATH)
SERVER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SERVER)


def valid_build():
    return {
        "tag": "qualified-local-build",
        "sha": "a" * 40,
        "script": "starlab_live/run_pcr_enrichment_odtc_LIDDED_1col_full_dry.py",
        "token": "RUN_PCR_ENRICHMENT_ODTC_LIDDED_FULL",
        "runner_match": "run_pcr_enrichment_odtc_LIDDED_1col_full_dry",
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
                "builds": {"pcr-enrichment-one-column": valid_build()},
            })
            builds, status = SERVER.load_builds(path)
            self.assertEqual(list(builds), ["pcr-enrichment-one-column"])
            self.assertEqual(builds["pcr-enrichment-one-column"]["legs"], 13)
            self.assertIn("Loaded 1", status)

    def test_invalid_builds_fail_the_complete_registry(self):
        cases = {
            "short sha": ("sha", "abc"),
            "uppercase sha": ("sha", "A" * 40),
            "zero legs": ("legs", 0),
            "boolean minutes": ("minutes", True),
            "absolute script": ("script", "/tmp/run.py"),
            "traversal script": ("script", "starlab_live/../run.py"),
            "dot-only script stem": ("script", "starlab_live/..py"),
            "hidden script stem": ("script", "starlab_live/.py"),
            "dotted script stem": ("script", "starlab_live/run.target.py"),
            "unsafe script directory": ("script", "starlab_live/.hidden/run.py"),
            "wrong script root": ("script", "other/run.py"),
            "unsafe tag": ("tag", "../moving-ref"),
            "lowercase token": ("token", "run_pcr_enrichment"),
            "dot runner": ("runner_match", "."),
            "regex runner": ("runner_match", "run.*"),
            "runner path": ("runner_match", "../runner"),
            "runner substring": ("runner_match", "run_pcr_enrichment_odtc"),
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
                        "builds": {"pcr-enrichment-one-column": build},
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
                        "builds": {"pcr-enrichment-one-column": build},
                    })
                    builds, status = SERVER.load_builds(path)
                    self.assertEqual(builds, {})
                    self.assertIn("invalid", status.lower())

    def test_ui_has_zero_build_guard(self):
        html = Path(__file__).with_name("index.html").read_text()
        self.assertIn("if(!build)", html)
        self.assertIn("no authorized local build configured", html)

    def test_full_sha_is_preserved_in_worktree_status(self):
        wanted = "a" * 40
        actual = "b" * 40
        build = valid_build()
        with tempfile.TemporaryDirectory() as root:
            with mock.patch.object(SERVER, "BUILDS", {"one-column": build}), \
                    mock.patch.object(SERVER, "WT_ROOT", Path(root)):
                self.assertEqual(SERVER.worktree_path("one-column").name, wanted)

                with mock.patch.object(
                        SERVER, "git", return_value=(0, actual, "")):
                    mismatch = SERVER.ensure_worktree("one-column")
                self.assertEqual(mismatch["sha"], actual)
                self.assertEqual(mismatch["want"], wanted)

                worktree = Path(root) / wanted
                worktree.mkdir()

                def clean_worktree(args, **_kwargs):
                    if args[-2:] == ["rev-parse", "HEAD"]:
                        return subprocess.CompletedProcess(args, 0, wanted + "\n", "")
                    if args[-2:] == ["status", "--porcelain"]:
                        return subprocess.CompletedProcess(args, 0, "", "")
                    raise AssertionError(f"unexpected subprocess: {args}")

                with mock.patch.object(
                        SERVER, "git", return_value=(0, wanted, "")), \
                        mock.patch.object(
                            SERVER.subprocess, "run", side_effect=clean_worktree):
                    reused = SERVER.ensure_worktree("one-column")
                self.assertTrue(reused["ok"])
                self.assertEqual(reused["sha"], wanted)

    def test_stop_pattern_is_exact_and_self_safe(self):
        runner = valid_build()["runner_match"]
        pattern = SERVER._pkill_pattern(runner)
        self.assertEqual(
            pattern,
            r"(^|/)[r]un_pcr_enrichment_odtc_LIDDED_1col_full_dry"
            r"\.py([[:space:]]|$)",
        )
        self.assertNotIn(runner, pattern)
        self.assertEqual(
            SERVER._pkill_pattern("runner-name"),
            r"(^|/)[r]unner\-name\.py([[:space:]]|$)",
        )
        with self.assertRaises(ValueError):
            SERVER._pkill_pattern(".")


if __name__ == "__main__":
    unittest.main()

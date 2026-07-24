import asyncio
import builtins
import importlib.util
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


RUNNER_PATH = (
    Path(__file__).resolve().parents[1]
    / "starlab_live"
    / "run_wgs_prep_pipetting_hhs_LIDDED_1col_dry.py"
)


def load_runner(module_name="wgs_prep_hhs_lidded_dry_runner_test"):
    spec = importlib.util.spec_from_file_location(module_name, RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {RUNNER_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


runner = load_runner()


class PlanTests(unittest.TestCase):
    def test_import_and_plan_do_not_import_pylabrobot(self):
        real_import = builtins.__import__

        def deny_plr(name, *args, **kwargs):
            if name.startswith("pylabrobot"):
                raise AssertionError("plan/import must not load the hardware stack")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=deny_plr):
            isolated = load_runner("wgs_prep_hhs_lidded_plan_inert_test")
            output = io.StringIO()
            with redirect_stdout(output):
                isolated.print_plan()
        self.assertIn("WGS preparation + HHS LIDDED", output.getvalue())

    def test_stage_order_and_corrected_geometry_are_locked(self):
        self.assertEqual(
            runner.STAGE_ORDER,
            ("wgs_prep-forward", "lid-on", "delid", "plate-return"),
        )
        self.assertEqual(runner.HHS_X, 12.0)
        self.assertEqual(runner.HHS_Y, 45.5)
        self.assertEqual(runner.HHS_DROP_Z, 17.0)
        self.assertNotEqual(runner.HHS_Y, 54.5)

    def test_all_tuned_z_values_are_literal_locked(self):
        self.assertEqual(
            (
                runner.PLATE_FORWARD_PICKUP_Z,
                runner.LID_ON_PICKUP_Z,
                runner.DELID_PICKUP_Z,
                runner.LID_PARK_DROP_Z,
                runner.PLATE_RETURN_PICKUP_Z,
                runner.PLATE_RETURN_DROP_Z,
            ),
            (5.0, 9.0, 16.0, 4.0, 10.0, 8.5),
        )
        self.assertNotEqual(runner.DELID_PICKUP_Z, 5.0)

    def test_pylabrobot_version_is_locked_to_tested_build(self):
        self.assertEqual(runner.EXPECTED_PLR_VERSION, "0.2.1")
        runner.validate_plr_version()
        with patch.object(runner, "version", return_value="0.2.2"):
            with self.assertRaisesRegex(RuntimeError, "version lock failed"):
                runner.validate_plr_version()

    def test_stale_hhs_y_is_rejected_before_execution(self):
        with patch.object(runner, "HHS_Y", 54.5):
            with self.assertRaisesRegex(RuntimeError, "geometry lock failed"):
                runner.validate_geometry_lock()

    def test_plan_names_the_plate_lid_mismatch_explicitly(self):
        output = io.StringIO()
        with redirect_stdout(output):
            runner.print_plan()
        text = output.getvalue()
        self.assertIn("CellTreat 229195/229196", text)
        self.assertIn("Corning 3603 lid", text)
        self.assertIn("UNVALIDATED", text)

    def test_dry_transfer_prompts_name_the_actual_empty_source_columns(self):
        wgs_prep = runner.load_wgs_prep_module()
        lysis = runner.dry_transfer_step(wgs_prep, "lysis", source_col=1)
        reaction = runner.dry_transfer_step(wgs_prep, "reaction", source_col=3)
        self.assertIn("column 1 is empty", lysis.manual_prep)
        self.assertIn("column 3 is empty", reaction.manual_prep)
        self.assertIn("no reagent and no sample", reaction.manual_prep)


class ReleaseGateTests(unittest.TestCase):
    @staticmethod
    def args(stage, **overrides):
        values = {
            "backend": "star",
            "stage": stage,
            "confirm": runner.STAGE_POLICIES.get(stage, SimpleNamespace(confirm="")).confirm,
            "acknowledge": "",
            "labware_ack": runner.LABWARE_ACK,
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def test_star_all_is_refused(self):
        with self.assertRaisesRegex(RuntimeError, "one stage at a time"):
            runner.validate_release(self.args("all", confirm=""))

    def test_wrong_confirm_is_refused(self):
        with self.assertRaisesRegex(RuntimeError, "RUN_WGS_PREP_FORWARD_DRY"):
            runner.validate_release(self.args("wgs_prep-forward", confirm="wrong"))

    def test_labware_ack_is_required(self):
        with self.assertRaisesRegex(RuntimeError, runner.LABWARE_ACK):
            runner.validate_release(self.args("lid-on", labware_ack=""))

    def test_forward_requires_dry_start_deck_acknowledgement(self):
        token = "DRY_DECK_MATCHED_HHS_EMPTY"
        with self.assertRaisesRegex(RuntimeError, token):
            runner.validate_release(self.args("wgs_prep-forward"))
        runner.validate_release(self.args("wgs_prep-forward", acknowledge=token))

    def test_lid_on_requires_physical_start_state(self):
        with self.assertRaisesRegex(RuntimeError, "PLATE_SEATED_HHS_LID_ON_PARK"):
            runner.validate_release(self.args("lid-on"))
        runner.validate_release(
            self.args("lid-on", acknowledge="PLATE_SEATED_HHS_LID_ON_PARK")
        )

    def test_delid_requires_specific_acknowledgement(self):
        token = "LID_FLUSH_HHS_WATCH_LID_NOT_PLATE"
        with self.assertRaisesRegex(RuntimeError, token):
            runner.validate_release(self.args("delid"))
        runner.validate_release(self.args("delid", acknowledge=token))

    def test_return_requires_plate_seated_acknowledgement(self):
        token = "BARE_PLATE_SEATED_HHS_LID_PARKED"
        with self.assertRaisesRegex(RuntimeError, token):
            runner.validate_release(self.args("plate-return"))
        runner.validate_release(
            self.args(
                "plate-return",
                acknowledge=token,
            )
        )

    def test_chatterbox_needs_no_star_tokens(self):
        args = self.args(
            "delid",
            backend="chatterbox",
            confirm="",
            acknowledge="",
            labware_ack="",
        )
        runner.validate_release(args)


class DispatchTests(unittest.TestCase):
    def test_chatterbox_all_dispatches_each_stage_in_order(self):
        seen = []

        def fake(stage):
            async def run(backend):
                seen.append((stage, backend))

            return run

        fake_runners = {stage: fake(stage) for stage in runner.STAGE_ORDER}
        args = SimpleNamespace(stage="all", backend="chatterbox")
        with patch.object(runner, "RUNNERS", fake_runners):
            asyncio.run(runner.dispatch(args))
        self.assertEqual(
            seen,
            [(stage, "chatterbox") for stage in runner.STAGE_ORDER],
        )


class ResourceTreeTests(unittest.TestCase):
    @staticmethod
    def stage_deck(stage):
        from pylabrobot.resources.hamilton import STARDeck

        wgs_prep = runner.load_wgs_prep_module()
        shell = SimpleNamespace(deck=STARDeck())
        return runner.assign_full_stage_deck(shell, stage, wgs_prep)

    def test_every_stage_models_fixed_tip_source_and_lid_park_labware(self):
        for stage in runner.STAGE_ORDER:
            with self.subTest(stage=stage):
                resources = self.stage_deck(stage)
                self.assertIs(resources["p10_tips"].parent, resources["tip_carrier"][0])
                self.assertIs(resources["p50_tips"].parent, resources["tip_carrier"][1])
                self.assertIs(resources["source_96wp"].parent, resources["plate_carrier"][1])
                self.assertIs(resources["park_plate"].parent, resources["plate_carrier"][4])
                runner.assert_stage_state(resources, stage, "before")

    def test_every_hhs_stage_uses_one_corrected_xy_source(self):
        from pylabrobot.resources import PLT_CAR_L5AC_A00

        base_site = PLT_CAR_L5AC_A00(name="geometry_reference")[runner.HHS_POS]
        expected_z = {
            "wgs_prep-forward": runner.HHS_DROP_Z,
            "lid-on": runner.HHS_DROP_Z,
            "delid": runner.DELID_PICKUP_Z,
            "plate-return": runner.PLATE_RETURN_PICKUP_Z,
        }
        for stage in runner.STAGE_ORDER:
            with self.subTest(stage=stage):
                site = self.stage_deck(stage)["hhs_site"]
                self.assertAlmostEqual(site.location.x - base_site.location.x, runner.HHS_X)
                self.assertAlmostEqual(site.location.y - base_site.location.y, runner.HHS_Y)
                self.assertAlmostEqual(
                    site.location.z - base_site.location.z,
                    expected_z[stage],
                )

    def test_geometry_snapshot_locks_cross_model_dimensions(self):
        resources = self.stage_deck("lid-on")
        output = io.StringIO()
        with redirect_stdout(output):
            runner.print_geometry_snapshot("lid-on", resources)
        text = output.getvalue()
        self.assertIn("CellTreat 127.61x85.24x14.3 mm", text)
        self.assertIn("Corning lid 127.76x85.48x8.9 mm", text)

    def test_deck_stage_creates_no_backend_and_does_not_setup(self):
        output = io.StringIO()
        with (
            patch.object(runner, "make_handler", side_effect=AssertionError("backend forbidden")),
            patch.object(runner, "create_backend", side_effect=AssertionError("backend forbidden")),
            redirect_stdout(output),
        ):
            asyncio.run(runner.run_deck("star"))
        self.assertIn("no backend created, no setup/home, no motion", output.getvalue())


class FailureCleanupTests(unittest.TestCase):
    def test_move_failure_skips_auto_park_and_disconnects(self):
        class SlowIswap:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, traceback):
                return False

        class Backend:
            def __init__(self):
                self.park_calls = 0

            def slow_iswap(self):
                return SlowIswap()

            async def park_iswap(self):
                self.park_calls += 1

        class Handler:
            def __init__(self):
                self.backend = Backend()
                self.stop_calls = 0

            async def setup(self, **_kwargs):
                return None

            async def move_lid(self, *_args, **_kwargs):
                raise RuntimeError("injected move fault")

            async def stop(self):
                self.stop_calls += 1

        handler = Handler()
        resources = {"lid": object(), "work_plate": object()}
        output = io.StringIO()
        with (
            patch.object(runner, "make_handler", return_value=handler),
            patch.object(runner, "load_wgs_prep_module", return_value=object()),
            patch.object(runner, "assign_full_stage_deck", return_value=resources),
            patch.object(runner, "assert_stage_state"),
            patch.object(runner, "print_geometry_snapshot"),
            redirect_stdout(output),
        ):
            with self.assertRaisesRegex(RuntimeError, "injected move fault"):
                asyncio.run(runner.run_lid_on("star"))
        self.assertEqual(handler.backend.park_calls, 0)
        self.assertEqual(handler.stop_calls, 1)
        self.assertIn("Physical state is UNKNOWN", output.getvalue())

    def test_partial_setup_failure_skips_park_and_disconnects_backend(self):
        class Backend:
            def __init__(self):
                self.park_calls = 0
                self.stop_calls = 0

            async def park_iswap(self):
                self.park_calls += 1

            async def stop(self):
                self.stop_calls += 1

        class Handler:
            def __init__(self):
                self.backend = Backend()
                self.stop_calls = 0

            async def setup(self, **_kwargs):
                raise RuntimeError("injected setup fault")

            async def stop(self):
                self.stop_calls += 1

        handler = Handler()
        output = io.StringIO()
        with (
            patch.object(runner, "make_handler", return_value=handler),
            patch.object(runner, "load_wgs_prep_module", return_value=object()),
            redirect_stdout(output),
        ):
            with self.assertRaisesRegex(RuntimeError, "injected setup fault"):
                asyncio.run(runner.run_lid_on("star"))
        self.assertEqual(handler.backend.park_calls, 0)
        self.assertEqual(handler.backend.stop_calls, 1)
        self.assertEqual(handler.stop_calls, 0)
        self.assertIn("Physical state is UNKNOWN", output.getvalue())


if __name__ == "__main__":
    unittest.main()

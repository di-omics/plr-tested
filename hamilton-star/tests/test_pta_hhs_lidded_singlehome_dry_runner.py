import asyncio
import builtins
import importlib.util
import os
import re
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


RUNNER_PATH = (
    Path(__file__).resolve().parents[1]
    / "starlab_live"
    / "run_pta_pipetting_hhs_LIDDED_1col_singlehome_dry.py"
)


def load_runner(module_name="pta_hhs_lidded_singlehome_test"):
    spec = importlib.util.spec_from_file_location(module_name, RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {RUNNER_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


runner = load_runner()


class SlowIswap:
    def __init__(self, backend):
        self.backend = backend

    async def __aenter__(self):
        self.backend.slow_entries += 1
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class RecordingBackend:
    def __init__(self):
        self.slow_entries = 0
        self.park_calls = 0
        self.stop_calls = 0

    def slow_iswap(self):
        return SlowIswap(self)

    async def park_iswap(self):
        self.park_calls += 1

    async def stop(self):
        self.stop_calls += 1


class RecordingHandler:
    def __init__(self, *, fail_move=None):
        from pylabrobot.resources.hamilton import STARDeck

        self.deck = STARDeck()
        self.backend = RecordingBackend()
        self.records = []
        self.fail_move = fail_move
        self.move_count = 0
        self.setup_calls = 0
        self.stop_calls = 0

    async def setup(self, **kwargs):
        self.setup_calls += 1
        self.setup_kwargs = kwargs

    async def stop(self):
        self.stop_calls += 1

    async def move_resource(self, resource, destination):
        self.move_count += 1
        self.records.append(
            (
                "plate",
                runner.coordinate_tuple(resource.location),
                runner.coordinate_tuple(resource.parent.location),
                runner.coordinate_tuple(destination.location),
            )
        )
        if self.fail_move == self.move_count:
            raise RuntimeError("injected plate move fault")
        resource.unassign()
        destination.assign_child_resource(resource)

    async def move_lid(self, lid, destination_plate):
        self.move_count += 1
        self.records.append(
            (
                "lid",
                runner.coordinate_tuple(lid.parent.parent.location),
                runner.coordinate_tuple(destination_plate.parent.location),
            )
        )
        if self.fail_move == self.move_count:
            raise RuntimeError("injected lid move fault")
        lid.unassign()
        destination_plate.assign_child_resource(lid)


def coordinate_delta(actual, base):
    return tuple(round(value - origin, 6) for value, origin in zip(actual, base))


class PlanAndGateTests(unittest.TestCase):
    def test_import_and_plan_do_not_import_pylabrobot(self):
        real_import = builtins.__import__

        def deny_plr(name, *args, **kwargs):
            if name.startswith("pylabrobot"):
                raise AssertionError("plan/import must not load PyLabRobot")
            return real_import(name, *args, **kwargs)

        output = StringIO()
        with patch("builtins.__import__", side_effect=deny_plr):
            isolated = load_runner("pta_hhs_singlehome_inert_test")
            with redirect_stdout(output):
                isolated.print_plan()
        self.assertIn("No operator pause", output.getvalue())

    def test_star_release_requires_all_exact_tokens(self):
        valid = {
            "mode": "star",
            "confirm": runner.CONFIRM_TOKEN,
            "acknowledge": runner.DECK_ACK,
            "labware_ack": runner.staged.LABWARE_ACK,
        }
        runner.validate_release(SimpleNamespace(**valid))
        for field in ("confirm", "acknowledge", "labware_ack"):
            values = dict(valid)
            values[field] = "wrong"
            with self.subTest(field=field):
                with self.assertRaises(RuntimeError):
                    runner.validate_release(SimpleNamespace(**values))

    def test_chatterbox_needs_no_star_tokens(self):
        runner.validate_release(
            SimpleNamespace(mode="chatterbox", confirm="", acknowledge="", labware_ack="")
        )

    def test_bad_star_gate_precedes_run_and_backend_creation(self):
        args = SimpleNamespace(
            mode="star",
            confirm="wrong",
            acknowledge=runner.DECK_ACK,
            labware_ack=runner.staged.LABWARE_ACK,
        )
        with (
            patch.object(runner, "run_full", new=AsyncMock()) as run_full,
            patch.object(
                runner.staged,
                "make_handler",
                side_effect=AssertionError("backend forbidden"),
            ),
        ):
            with self.assertRaises(RuntimeError):
                asyncio.run(runner.main_async(args))
        run_full.assert_not_awaited()

    def test_deck_model_creates_no_backend(self):
        output = StringIO()
        with (
            patch.object(
                runner.staged,
                "make_handler",
                side_effect=AssertionError("backend forbidden"),
            ),
            patch.object(
                runner.staged,
                "create_backend",
                side_effect=AssertionError("backend forbidden"),
            ),
            redirect_stdout(output),
        ):
            runner.run_deck()
        self.assertIn("no backend or hardware connection", output.getvalue())


class UnifiedGeometryTests(unittest.TestCase):
    def setUp(self):
        self.pta = runner.staged.load_pta_module()
        self.handler = RecordingHandler()
        self.resources = runner.assign_unified_deck(self.handler, self.pta)
        self.pristine = runner.site_snapshot(self.resources)
        self.work_plate_base = runner.coordinate_tuple(self.resources["work_plate"].location)

    def test_unified_deck_is_pristine_and_truthful(self):
        runner.staged.assert_stage_state(self.resources, "pta-forward", "before")
        runner.assert_sites_pristine(self.resources, self.pristine, "test start")
        self.assertIs(
            self.resources["p10_tips"].parent,
            self.resources["tip_carrier"][runner.staged.P10_TIP_POS],
        )
        self.assertIs(
            self.resources["p50_tips"].parent,
            self.resources["tip_carrier"][runner.staged.P50_TIP_POS],
        )
        self.assertIs(
            self.resources["source_96wp"].parent,
            self.resources["plate_carrier"][runner.staged.SOURCE_POS],
        )

    def test_complete_choreography_has_exact_geometry_and_parent_transitions(self):
        transfer_calls = []

        async def fake_transfer(_lh, _resources, step, discard_tips, **kwargs):
            transfer_calls.append(
                (
                    step.mode,
                    step.volume_ul,
                    step.tip_type,
                    discard_tips,
                    kwargs["tip_col"],
                    kwargs["source_col"],
                    kwargs["dest_col"],
                )
            )

        with patch.object(self.pta, "transfer_step", new=fake_transfer):
            asyncio.run(runner.run_choreography(self.handler, self.resources, self.pta))

        self.assertEqual(
            transfer_calls,
            [
                ("lysis", 3.0, "p10", False, 1, 1, 1),
                ("reaction", 6.0, "p10", False, 2, 3, 1),
            ],
        )
        work_base = self.pristine["work_site"]
        hhs_base = self.pristine["hhs_site"]
        park_base = self.pristine["park_site"]
        records = self.handler.records
        self.assertEqual(len(records), 4)

        self.assertEqual(records[0][0], "plate")
        self.assertEqual(
            coordinate_delta(records[0][1], self.work_plate_base),
            (0.0, 0.0, 5.0),
        )
        self.assertEqual(coordinate_delta(records[0][2], work_base), (0.0, 0.0, 0.0))
        self.assertEqual(coordinate_delta(records[0][3], hhs_base), (12.0, 45.5, 17.0))

        self.assertEqual(records[1][0], "lid")
        self.assertEqual(coordinate_delta(records[1][1], park_base), (0.0, 0.0, 9.0))
        self.assertEqual(coordinate_delta(records[1][2], hhs_base), (12.0, 45.5, 17.0))

        self.assertEqual(records[2][0], "lid")
        self.assertEqual(coordinate_delta(records[2][1], hhs_base), (12.0, 45.5, 16.0))
        self.assertEqual(coordinate_delta(records[2][2], park_base), (0.0, 0.0, 4.0))

        self.assertEqual(records[3][0], "plate")
        self.assertEqual(coordinate_delta(records[3][2], hhs_base), (12.0, 45.5, 10.0))
        self.assertEqual(coordinate_delta(records[3][3], work_base), (0.0, 0.0, 8.5))

        runner.assert_sites_pristine(self.resources, self.pristine, "full test")
        runner.staged.assert_stage_state(self.resources, "plate-return", "after")
        self.assertIs(
            self.resources["p10_tips"].parent,
            self.resources["tip_carrier"][runner.staged.P10_TIP_POS],
        )
        self.assertIs(
            self.resources["p50_tips"].parent,
            self.resources["tip_carrier"][runner.staged.P50_TIP_POS],
        )
        self.assertIs(
            self.resources["source_96wp"].parent,
            self.resources["plate_carrier"][runner.staged.SOURCE_POS],
        )
        self.assertIs(
            self.resources["park_plate"].parent,
            self.resources["plate_carrier"][runner.staged.LID_PARK_POS],
        )
        self.assertEqual(self.handler.backend.slow_entries, 4)

    def test_plate_move_failure_restores_local_and_site_coordinates(self):
        failing = RecordingHandler(fail_move=1)
        resources = runner.assign_unified_deck(failing, self.pta)
        pristine = runner.site_snapshot(resources)
        plate = resources["work_plate"]
        plate_location = runner.coordinate_tuple(plate.location)
        with self.assertRaisesRegex(RuntimeError, "injected plate move fault"):
            asyncio.run(
                runner.plate_leg(
                    failing,
                    plate,
                    resources["hhs_site"],
                    pickup_dz=5.0,
                    drop_dx=12.0,
                    drop_dy=45.5,
                    drop_dz=17.0,
                    pickup_target="plate",
                )
            )
        self.assertEqual(runner.coordinate_tuple(plate.location), plate_location)
        runner.assert_sites_pristine(resources, pristine, "failed forward")
        runner.staged.assert_stage_state(resources, "pta-forward", "before")


class LifecycleTests(unittest.TestCase):
    def test_run_full_uses_one_setup_one_deck_four_moves_one_park_stop(self):
        pta = runner.staged.load_pta_module()
        handler = RecordingHandler()
        transfer = AsyncMock()
        real_assign = runner.assign_unified_deck
        with (
            patch.object(runner.staged, "load_pta_module", return_value=pta),
            patch.object(runner.staged, "make_handler", return_value=handler),
            patch.object(
                runner.staged,
                "assign_full_stage_deck",
                side_effect=AssertionError("stage-specific deck forbidden"),
            ),
            patch.object(runner, "assign_unified_deck", wraps=real_assign) as assign,
            patch.object(pta, "transfer_step", transfer),
            redirect_stdout(StringIO()),
        ):
            asyncio.run(runner.run_full("chatterbox"))
        self.assertEqual(assign.call_count, 1)
        self.assertEqual(handler.setup_calls, 1)
        self.assertEqual(handler.setup_kwargs, {"skip_autoload": True})
        self.assertEqual(handler.move_count, 4)
        self.assertEqual(handler.backend.slow_entries, 4)
        self.assertEqual(handler.backend.park_calls, 1)
        self.assertEqual(handler.stop_calls, 1)
        self.assertEqual(transfer.await_count, 2)

    def test_each_move_failure_stops_sequence_without_park(self):
        pta = runner.staged.load_pta_module()
        for fail_move in range(1, 5):
            with self.subTest(fail_move=fail_move):
                handler = RecordingHandler(fail_move=fail_move)
                transfer = AsyncMock()
                with (
                    patch.object(runner.staged, "load_pta_module", return_value=pta),
                    patch.object(runner.staged, "make_handler", return_value=handler),
                    patch.object(pta, "transfer_step", transfer),
                    redirect_stdout(StringIO()),
                ):
                    with self.assertRaisesRegex(RuntimeError, "injected .* move fault"):
                        asyncio.run(runner.run_full("chatterbox"))
                self.assertEqual(handler.move_count, fail_move)
                self.assertEqual(handler.backend.park_calls, 0)
                self.assertEqual(handler.stop_calls, 1)

    def test_each_transfer_failure_stops_before_motion_without_park(self):
        pta = runner.staged.load_pta_module()
        for fail_transfer in (1, 2):
            with self.subTest(fail_transfer=fail_transfer):
                handler = RecordingHandler()
                call_count = 0

                async def transfer_fault(*_args, **_kwargs):
                    nonlocal call_count
                    call_count += 1
                    if call_count == fail_transfer:
                        raise RuntimeError("injected transfer fault")

                with (
                    patch.object(runner.staged, "load_pta_module", return_value=pta),
                    patch.object(runner.staged, "make_handler", return_value=handler),
                    patch.object(pta, "transfer_step", new=transfer_fault),
                    redirect_stdout(StringIO()),
                ):
                    with self.assertRaisesRegex(RuntimeError, "injected transfer fault"):
                        asyncio.run(runner.run_full("chatterbox"))
                self.assertEqual(handler.move_count, 0)
                self.assertEqual(handler.backend.park_calls, 0)
                self.assertEqual(handler.stop_calls, 1)


class ChatterboxSignatureTests(unittest.TestCase):
    def test_full_chatterbox_matches_hardware_proven_iswap_signatures(self):
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        result = subprocess.run(
            [sys.executable, str(RUNNER_PATH), "--mode", "chatterbox"],
            capture_output=True,
            text=True,
            check=True,
            env=env,
        )
        signatures = [
            re.sub(r"id\d{4}", "idXXXX", line)
            for line in result.stdout.splitlines()
            if line.startswith(("C0PP", "C0PR"))
        ]
        self.assertEqual(
            signatures,
            [
                "C0PPidXXXXxs09328xd0yj1141yd0zj2014zd0gr1th2800te2800gw4go1306gb1243gt20ga0gc0",
                "C0PRidXXXXxs07648xd0yj3516yd0zj2134zd0th2800te2800gr1go1306ga0gc0",
                "C0PPidXXXXxs09329xd0yj4982yd0zj2052zd0gr1th2800te2800gw4go1308gb1245gt20ga0gc0",
                "C0PRidXXXXxs07649xd0yj3517yd0zj2123zd0th2800te2800gr1go1308ga0gc0",
                "C0PPidXXXXxs07649xd0yj3517yd0zj2113zd0gr1th2800te2800gw4go1308gb1245gt20ga0gc0",
                "C0PRidXXXXxs09329xd0yj4982yd0zj2002zd0th2800te2800gr1go1308ga0gc0",
                "C0PPidXXXXxs07648xd0yj3516yd0zj2064zd0gr1th2800te2800gw4go1306gb1243gt20ga0gc0",
                "C0PRidXXXXxs09328xd0yj1141yd0zj2049zd0th2800te2800gr1go1306ga0gc0",
            ],
        )


if __name__ == "__main__":
    unittest.main()

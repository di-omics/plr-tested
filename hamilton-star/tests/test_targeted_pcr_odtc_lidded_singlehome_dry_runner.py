import asyncio
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
    / "run_targeted_pcr_odtc_LIDDED_1col_full_v2_singlehome_dry.py"
)


def load_runner(module_name="targeted_pcr_odtc_lidded_singlehome_test"):
    import importlib.util

    spec = importlib.util.spec_from_file_location(module_name, RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {RUNNER_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


runner = load_runner()


def coordinate_delta(actual, base):
    return tuple(round(value - origin, 6) for value, origin in zip(actual, base))


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
        self.setup_kwargs = None
        self.stop_calls = 0

    async def setup(self, **kwargs):
        self.setup_calls += 1
        self.setup_kwargs = kwargs

    async def stop(self):
        self.stop_calls += 1

    async def move_resource(self, resource, destination, **kwargs):
        self.move_count += 1
        source_site = resource.parent
        self.records.append(
            {
                "kind": "plate",
                "source_parent": source_site,
                "destination_parent": destination,
                "source_site": source_site,
                "destination_site": destination,
                "resource_location": runner.coordinate_tuple(resource.location),
                "source_location": runner.coordinate_tuple(source_site.location),
                "destination_location": runner.coordinate_tuple(destination.location),
                "kwargs": dict(kwargs),
            }
        )
        if self.fail_move == self.move_count:
            raise RuntimeError("injected plate move fault")
        resource.unassign()
        destination.assign_child_resource(resource)

    async def move_lid(self, lid, destination_plate, **kwargs):
        self.move_count += 1
        source_plate = lid.parent
        source_site = source_plate.parent
        destination_site = destination_plate.parent
        self.records.append(
            {
                "kind": "lid",
                "source_parent": source_plate,
                "destination_parent": destination_plate,
                "source_site": source_site,
                "destination_site": destination_site,
                "resource_location": runner.coordinate_tuple(lid.location),
                "source_location": runner.coordinate_tuple(source_site.location),
                "destination_location": runner.coordinate_tuple(destination_site.location),
                "kwargs": dict(kwargs),
            }
        )
        if self.fail_move == self.move_count:
            raise RuntimeError("injected lid move fault")
        lid.unassign()
        destination_plate.assign_child_resource(lid)


class LiquidFaultHandler(RecordingHandler):
    def __init__(self, *, fail_at):
        super().__init__()
        self.fail_at = fail_at
        self.pick_up_calls = 0
        self.aspirate_calls = 0
        self.dispense_calls = 0
        self.return_tip_calls = 0
        self.discard_tip_calls = 0

    async def pick_up_tips(self, *_args, **_kwargs):
        self.pick_up_calls += 1

    async def aspirate(self, *_args, **_kwargs):
        self.aspirate_calls += 1
        if self.fail_at == "aspirate":
            raise RuntimeError("injected aspirate fault")

    async def dispense(self, *_args, **_kwargs):
        self.dispense_calls += 1
        if self.fail_at == "dispense":
            raise RuntimeError("injected dispense fault")

    async def return_tips(self):
        self.return_tip_calls += 1

    async def discard_tips(self):
        self.discard_tip_calls += 1


class ReleaseGateTests(unittest.TestCase):
    def test_release_tokens_are_literal_locked_and_all_three_are_required(self):
        self.assertEqual(runner.CONFIRM_TOKEN, "RUN_TARGETED_PCR_ODTC_LIDDED_SINGLEHOME_DRY")
        self.assertEqual(
            runner.DECK_ACK,
            "R48_P10_P50_P300_R35_WORK_SOURCE_MAGNET_TROUGH_LID_R20_ODTC_EMPTY_OPEN",
        )
        self.assertEqual(
            runner.LABWARE_ACK,
            "CELLTREAT_229195_WORK_SOURCE_CORNING_3603_LID",
        )

        valid = {
            "mode": "star",
            "confirm": runner.CONFIRM_TOKEN,
            "acknowledge": runner.DECK_ACK,
            "labware_ack": runner.LABWARE_ACK,
        }
        runner.validate_release(SimpleNamespace(**valid))
        runner.validate_release(SimpleNamespace(**{**valid, "mode": "run"}))

        for field in ("confirm", "acknowledge", "labware_ack"):
            values = dict(valid)
            values[field] = "wrong"
            with self.subTest(field=field):
                with self.assertRaises(RuntimeError):
                    runner.validate_release(SimpleNamespace(**values))

    def test_bad_release_gate_precedes_run_full_and_backend_creation(self):
        valid = {
            "mode": "star",
            "confirm": runner.CONFIRM_TOKEN,
            "acknowledge": runner.DECK_ACK,
            "labware_ack": runner.LABWARE_ACK,
        }
        for field in ("confirm", "acknowledge", "labware_ack"):
            values = dict(valid)
            values[field] = "wrong"
            forbidden_run = AsyncMock(
                side_effect=AssertionError("run/backend creation forbidden before release gate")
            )
            with self.subTest(field=field), patch.object(
                runner, "run_full", new=forbidden_run
            ):
                with self.assertRaises(RuntimeError):
                    asyncio.run(runner.main_async(SimpleNamespace(**values)))
                forbidden_run.assert_not_awaited()

        allowed_run = AsyncMock()
        with patch.object(runner, "run_full", new=allowed_run), redirect_stdout(StringIO()):
            asyncio.run(runner.main_async(SimpleNamespace(**valid)))
        allowed_run.assert_awaited_once_with("star")

    def test_deck_mode_creates_no_backend(self):
        args = SimpleNamespace(
            mode="deck", confirm="", acknowledge="", labware_ack=""
        )
        output = StringIO()
        with (
            patch.object(
                runner,
                "create_backend",
                side_effect=AssertionError("deck must not create a backend"),
            ),
            patch.object(
                runner,
                "make_handler",
                side_effect=AssertionError("deck must not create a handler"),
            ),
            redirect_stdout(output),
        ):
            asyncio.run(runner.main_async(args))
        self.assertIn("no backend", output.getvalue().lower())


class InvariantAndDeckTests(unittest.TestCase):
    def test_plr_model_and_motion_geometry_are_exactly_locked(self):
        self.assertEqual(runner.EXPECTED_PLR_VERSION, "0.2.1")
        runner.validate_plr_version()
        with patch.object(runner, "version", return_value="0.2.2"):
            with self.assertRaisesRegex(RuntimeError, "version lock failed"):
                runner.validate_plr_version()

        expected_geometry = (
            (5.0, 2.0, 36.5, 12.0),
            (2.0, 36.5, 0.0, 8.5),
            (8.5, 0.0, 0.0, 18.0),
            (14.0, 0.0, 0.0, 8.5),
            (0.0, 0.0, 9.0, 2.0, 36.5, 12.0),
            (2.0, 36.5, 7.0, 0.0, 0.0, 4.0),
        )
        self.assertEqual(runner.CONFIRMED_MOVEMENT_GEOMETRY, expected_geometry)
        self.assertEqual(runner.movement_geometry(), expected_geometry)
        runner.validate_geometry_lock()
        with patch.object(runner, "LID_OFF_PICKUP_DZ", 5.0):
            with self.assertRaisesRegex(RuntimeError, "geometry lock failed"):
                runner.validate_geometry_lock()

        expected_model = (
            127.61,
            85.24,
            14.30,
            -4.05,
            127.76,
            85.48,
            14.20,
            -3.03,
            0.075,
            0.120,
            0.920,
            0.920,
        )
        self.assertEqual(runner.CONFIRMED_MOTION_MODEL, expected_model)
        self.assertEqual(runner.motion_model_snapshot(), expected_model)
        self.assertEqual(
            runner.coordinate_tuple(runner.COR_MOTION_OFFSET),
            (0.075, 0.120, 0.920),
        )
        self.assertEqual(runner.COR_MOTION_PLATE_WIDTH, 127.76)
        self.assertEqual(runner.COR_MOTION_OPEN_GRIP, 130.76)
        self.assertEqual(runner.CELLTREAT_LID_Z_COMPENSATION, 0.920)
        runner.validate_motion_model_lock()
        with patch.object(
            runner, "COR_MOTION_OFFSET", runner.Coordinate(0.076, 0.120, 0.920)
        ):
            with self.assertRaisesRegex(RuntimeError, "compensation drifted"):
                runner.validate_motion_model_lock()

        self.assertEqual(runner.P50_WORK_DSP_HEIGHT, [1.5] * 8)
        self.assertEqual(runner.MIX_POSITION_FROM_SURFACE, [1.0] * 8)
        self.assertEqual(runner.P50_MIX_BLOWOUT_AIR_VOLUME, 10.0)
        self.assertEqual(
            runner.P50_WORK_DSP_HEIGHT[0] - runner.MIX_POSITION_FROM_SURFACE[0],
            0.5,
        )

    def test_unified_deck_has_truthful_models_and_fixed_parents(self):
        handler = RecordingHandler()
        resources = runner.assign_unified_deck(handler)
        pristine = runner.site_snapshot(resources)

        self.assertIs(resources["tip_carrier"].parent, handler.deck)
        self.assertIs(resources["labware_carrier"].parent, handler.deck)
        self.assertIs(resources["odtc_carrier"].parent, handler.deck)
        self.assertIs(
            resources["p10_tips"].parent,
            resources["tip_carrier"][runner.P10_TIP_POS],
        )
        self.assertIs(
            resources["p50_tips"].parent,
            resources["tip_carrier"][runner.P50_TIP_POS],
        )
        self.assertIs(
            resources["p300_tips"].parent,
            resources["tip_carrier"][runner.P300_TIP_POS],
        )
        self.assertIs(resources["work_plate"].parent, resources["work_site"])
        self.assertIs(resources["source_96wp"].parent, resources["source_site"])
        self.assertIs(resources["trough"].parent, resources["trough_site"])
        self.assertIs(resources["lid_park"].parent, resources["lid_site"])
        self.assertIs(resources["lid"], resources["lid_park"].lid)
        self.assertIs(resources["lid"].parent, resources["lid_park"])
        self.assertEqual(resources["mag_site"].children, [])
        self.assertEqual(resources["odtc_site"].children, [])

        work = resources["work_plate"]
        park = resources["lid_park"]
        self.assertEqual(
            tuple(round(value, 2) for value in (work.get_size_x(), work.get_size_y(), work.get_size_z())),
            (127.61, 85.24, 14.30),
        )
        self.assertEqual(
            tuple(round(value, 2) for value in (park.get_size_x(), park.get_size_y(), park.get_size_z())),
            (127.76, 85.48, 14.20),
        )
        self.assertEqual(runner.coordinate_tuple(work.location), (0, 0, -4.05))
        self.assertEqual(runner.coordinate_tuple(park.location), (0, 0, -3.03))
        runner.assert_sites_pristine(resources, pristine, "unified deck test")
        runner.assert_modeled_state(
            resources,
            plate_site=resources["work_site"],
            lid_parent=resources["lid_park"],
            label="unified deck test",
        )


class ChoreographyTests(unittest.TestCase):
    def setUp(self):
        self.handler = RecordingHandler()
        self.resources = runner.assign_unified_deck(self.handler)
        self.pristine = runner.site_snapshot(self.resources)
        self.plate_base = runner.coordinate_tuple(self.resources["work_plate"].location)

    def test_full_ten_move_parent_transitions_geometry_and_site_restoration(self):
        transfer = AsyncMock()
        cleanup = AsyncMock()
        with (
            patch.object(runner, "transfer_mastermix", new=transfer),
            patch.object(runner, "cleanup_all_dry", new=cleanup),
            redirect_stdout(StringIO()),
        ):
            asyncio.run(runner.run_choreography(self.handler, self.resources))

        r = self.resources
        records = self.handler.records
        self.assertEqual(len(records), 10)
        expected_transitions = (
            ("plate", r["work_site"], r["odtc_site"]),
            ("lid", r["lid_park"], r["work_plate"]),
            ("lid", r["work_plate"], r["lid_park"]),
            ("plate", r["odtc_site"], r["work_site"]),
            ("plate", r["work_site"], r["mag_site"]),
            ("plate", r["mag_site"], r["work_site"]),
            ("plate", r["work_site"], r["odtc_site"]),
            ("lid", r["lid_park"], r["work_plate"]),
            ("lid", r["work_plate"], r["lid_park"]),
            ("plate", r["odtc_site"], r["work_site"]),
        )
        for index, (record, expected) in enumerate(zip(records, expected_transitions), 1):
            kind, source_parent, destination_parent = expected
            with self.subTest(move=index):
                self.assertEqual(record["kind"], kind)
                self.assertIs(record["source_parent"], source_parent)
                self.assertIs(record["destination_parent"], destination_parent)

        expected_site_geometry = (
            ("work_site", (0.0, 0.0, 0.0), "odtc_site", (2.0, 36.5, 12.0), (0.0, 0.0, 5.0)),
            ("lid_site", (0.0, 0.0, 9.0), "odtc_site", (2.0, 36.5, 12.0), None),
            ("odtc_site", (2.0, 36.5, 7.0), "lid_site", (0.0, 0.0, 4.0), None),
            ("odtc_site", (2.0, 36.5, 0.0), "work_site", (0.0, 0.0, 8.5), (0.0, 0.0, 0.0)),
            ("work_site", (0.0, 0.0, 0.0), "mag_site", (0.0, 0.0, 18.0), (0.0, 0.0, 8.5)),
            ("mag_site", (0.0, 0.0, 0.0), "work_site", (0.0, 0.0, 8.5), (0.0, 0.0, 14.0)),
            ("work_site", (0.0, 0.0, 0.0), "odtc_site", (2.0, 36.5, 12.0), (0.0, 0.0, 5.0)),
            ("lid_site", (0.0, 0.0, 9.0), "odtc_site", (2.0, 36.5, 12.0), None),
            ("odtc_site", (2.0, 36.5, 7.0), "lid_site", (0.0, 0.0, 4.0), None),
            ("odtc_site", (2.0, 36.5, 0.0), "work_site", (0.0, 0.0, 8.5), (0.0, 0.0, 0.0)),
        )
        for index, (record, expected) in enumerate(zip(records, expected_site_geometry), 1):
            source_key, source_delta, destination_key, destination_delta, local_delta = expected
            with self.subTest(geometry_move=index):
                self.assertIs(record["source_site"], r[source_key])
                self.assertIs(record["destination_site"], r[destination_key])
                self.assertEqual(
                    coordinate_delta(record["source_location"], self.pristine[source_key]),
                    source_delta,
                )
                self.assertEqual(
                    coordinate_delta(
                        record["destination_location"], self.pristine[destination_key]
                    ),
                    destination_delta,
                )
                if local_delta is not None:
                    self.assertEqual(
                        coordinate_delta(record["resource_location"], self.plate_base),
                        local_delta,
                    )

        plate_move_indexes = (0, 3, 4, 5, 6, 9)
        for index in plate_move_indexes:
            kwargs = records[index]["kwargs"]
            with self.subTest(compensated_plate_move=index + 1):
                self.assertEqual(
                    runner.coordinate_tuple(kwargs["pickup_offset"]),
                    (0.075, 0.120, 0.920),
                )
                self.assertEqual(
                    runner.coordinate_tuple(kwargs["destination_offset"]),
                    (0.075, 0.120, 0.920),
                )
                self.assertEqual(kwargs["plate_width"], 127.76)
                self.assertEqual(kwargs["open_gripper_position"], 130.76)

        expected_lid_offsets = (
            ((0.0, 0.0, 0.0), (0.0, 0.0, 0.920)),
            ((0.0, 0.0, 0.920), (0.0, 0.0, 0.0)),
            ((0.0, 0.0, 0.0), (0.0, 0.0, 0.920)),
            ((0.0, 0.0, 0.920), (0.0, 0.0, 0.0)),
        )
        for index, expected in zip((1, 2, 7, 8), expected_lid_offsets):
            kwargs = records[index]["kwargs"]
            with self.subTest(compensated_lid_move=index + 1):
                self.assertEqual(
                    runner.coordinate_tuple(kwargs["pickup_offset"]), expected[0]
                )
                self.assertEqual(
                    runner.coordinate_tuple(kwargs["destination_offset"]), expected[1]
                )

        self.assertEqual(self.handler.backend.slow_entries, 10)
        self.assertEqual(transfer.await_count, 2)
        self.assertEqual(cleanup.await_count, 1)
        runner.assert_sites_pristine(r, self.pristine, "full choreography test")
        runner.assert_modeled_state(
            r,
            plate_site=r["work_site"],
            lid_parent=r["lid_park"],
            label="full choreography test",
        )

    def test_failed_plate_local_move_restores_plate_and_sites(self):
        handler = RecordingHandler(fail_move=1)
        resources = runner.assign_unified_deck(handler)
        pristine = runner.site_snapshot(resources)
        plate = resources["work_plate"]
        original_parent = plate.parent
        original_location = runner.coordinate_tuple(plate.location)

        with self.assertRaisesRegex(RuntimeError, "injected plate move fault"):
            asyncio.run(
                runner.iswap_leg(
                    handler,
                    plate,
                    resources["odtc_site"],
                    pickup_dz=runner.ODTC_FWD_PICKUP_DZ,
                    drop_dx=runner.ODTC_FWD_DROP_DX,
                    drop_dy=runner.ODTC_FWD_DROP_DY,
                    drop_dz=runner.ODTC_FWD_DROP_DZ,
                    pickup_target="plate",
                )
            )

        self.assertIs(plate.parent, original_parent)
        self.assertEqual(runner.coordinate_tuple(plate.location), original_location)
        runner.assert_sites_pristine(resources, pristine, "failed plate-local move")
        self.assertEqual(handler.move_count, 1)
        self.assertEqual(handler.backend.slow_entries, 1)


class LifecycleTests(unittest.TestCase):
    def test_success_uses_one_setup_one_deck_ten_moves_one_park_one_stop(self):
        handler = RecordingHandler()
        transfer = AsyncMock()
        cleanup = AsyncMock()
        real_assign = runner.assign_unified_deck
        with (
            patch.object(runner, "make_handler", return_value=handler),
            patch.object(runner, "assign_unified_deck", wraps=real_assign) as assign,
            patch.object(runner, "transfer_mastermix", new=transfer),
            patch.object(runner, "cleanup_all_dry", new=cleanup),
            redirect_stdout(StringIO()),
        ):
            asyncio.run(runner.run_full("chatterbox"))

        self.assertEqual(handler.setup_calls, 1)
        self.assertEqual(handler.setup_kwargs, {"skip_autoload": True})
        self.assertEqual(assign.call_count, 1)
        self.assertEqual(handler.move_count, 10)
        self.assertEqual(handler.backend.slow_entries, 10)
        self.assertEqual(handler.backend.park_calls, 1)
        self.assertEqual(handler.stop_calls, 1)
        self.assertEqual(handler.backend.stop_calls, 0)
        self.assertEqual(transfer.await_count, 2)
        self.assertEqual(cleanup.await_count, 1)

    def test_each_movement_failure_stops_without_auto_park_and_restores_sites(self):
        real_assign = runner.assign_unified_deck
        for fail_move in range(1, 11):
            with self.subTest(fail_move=fail_move):
                handler = RecordingHandler(fail_move=fail_move)
                captured = {}

                def capture_assign(lh):
                    resources = real_assign(lh)
                    captured["resources"] = resources
                    captured["pristine"] = runner.site_snapshot(resources)
                    return resources

                with (
                    patch.object(runner, "make_handler", return_value=handler),
                    patch.object(runner, "assign_unified_deck", side_effect=capture_assign),
                    patch.object(runner, "transfer_mastermix", new=AsyncMock()),
                    patch.object(runner, "cleanup_all_dry", new=AsyncMock()),
                    redirect_stdout(StringIO()),
                ):
                    with self.assertRaisesRegex(RuntimeError, "injected .* move fault"):
                        asyncio.run(runner.run_full("chatterbox"))

                self.assertEqual(handler.move_count, fail_move)
                self.assertEqual(handler.backend.slow_entries, fail_move)
                self.assertEqual(handler.backend.park_calls, 0)
                self.assertEqual(handler.stop_calls, 1)
                self.assertEqual(handler.backend.stop_calls, 0)
                runner.assert_sites_pristine(
                    captured["resources"],
                    captured["pristine"],
                    "injected movement failure",
                )

    def test_representative_cleanup_liquid_failure_stops_without_auto_park(self):
        handler = RecordingHandler()
        transfer = AsyncMock()
        cleanup = AsyncMock(side_effect=RuntimeError("injected cleanup liquid fault"))
        with (
            patch.object(runner, "make_handler", return_value=handler),
            patch.object(runner, "transfer_mastermix", new=transfer),
            patch.object(runner, "cleanup_all_dry", new=cleanup),
            redirect_stdout(StringIO()),
        ):
            with self.assertRaisesRegex(RuntimeError, "injected cleanup liquid fault"):
                asyncio.run(runner.run_full("chatterbox"))

        self.assertEqual(transfer.await_count, 1)
        self.assertEqual(cleanup.await_count, 1)
        self.assertEqual(handler.move_count, 5)
        self.assertEqual(handler.backend.slow_entries, 5)
        self.assertEqual(handler.backend.park_calls, 0)
        self.assertEqual(handler.stop_calls, 1)
        self.assertEqual(handler.backend.stop_calls, 0)

    def test_each_liquid_helper_skips_tip_motion_after_aspirate_or_dispense_fault(self):
        helper_cases = (
            (
                "mastermix",
                lambda lh, r: runner.transfer_mastermix(
                    lh,
                    {
                        "p50_tips": r["p50_tips"],
                        "source_96wp": r["source_96wp"],
                        "work_plate": r["work_plate"],
                    },
                    volume_ul=runner.VOL_PCR1_MASTER_MIX,
                    discard_tips=False,
                    tip_col=1,
                ),
            ),
            (
                "p50 trough add",
                lambda lh, r: runner.p50_add_from_trough_low(
                    lh,
                    {
                        "p50_tips": r["p50_tips"],
                        "mag_plate": r["work_plate"],
                        "trough": r["trough"],
                    },
                    runner.TROUGH_BEADS,
                    runner.VOL_BEADS,
                    False,
                    1,
                ),
            ),
            (
                "p300 trough add",
                lambda lh, r: runner.p300_add_from_trough(
                    lh,
                    {
                        "p300_tips": r["p300_tips"],
                        "mag_plate": r["work_plate"],
                        "trough": r["trough"],
                    },
                    runner.TROUGH_ETOH1,
                    runner.VOL_ETHANOL_ADD,
                    False,
                    1,
                ),
            ),
            (
                "p300 waste removal",
                lambda lh, r: runner.p300_remove_to_waste(
                    lh,
                    {
                        "p300_tips": r["p300_tips"],
                        "mag_plate": r["work_plate"],
                        "trough": r["trough"],
                    },
                    runner.VOL_SUPERNATANT_REMOVE,
                    False,
                    1,
                ),
            ),
            (
                "p50 residual removal",
                lambda lh, r: runner.p50_remove_residual_ethanol_to_waste(
                    lh,
                    {
                        "p50_tips": r["p50_tips"],
                        "mag_plate": r["work_plate"],
                        "trough": r["trough"],
                    },
                    runner.VOL_RESIDUAL_ETHANOL_REMOVE,
                    False,
                    1,
                ),
            ),
        )

        for helper_name, helper in helper_cases:
            for fail_at in ("aspirate", "dispense"):
                with self.subTest(helper=helper_name, fail_at=fail_at):
                    handler = LiquidFaultHandler(fail_at=fail_at)
                    resources = runner.assign_unified_deck(handler)
                    output = StringIO()
                    with redirect_stdout(output):
                        with self.assertRaisesRegex(
                            RuntimeError, "injected {} fault".format(fail_at)
                        ):
                            asyncio.run(helper(handler, resources))

                    self.assertEqual(handler.pick_up_calls, 1)
                    self.assertEqual(handler.aspirate_calls, 1)
                    self.assertEqual(
                        handler.dispense_calls, 0 if fail_at == "aspirate" else 1
                    )
                    self.assertEqual(handler.return_tip_calls, 0)
                    self.assertEqual(handler.discard_tip_calls, 0)
                    self.assertEqual(handler.move_count, 0)
                    self.assertIn(
                        "automatic tip return/discard skipped", output.getvalue()
                    )


class ChatterboxSignatureTests(unittest.TestCase):
    def test_full_chatterbox_matches_exact_standalone_cor_motion_trace(self):
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
        odtc_block = [
            "C0PPidXXXXxs09329xd0yj1142yd0zj2023zd0gr1th2800te2800gw4go1308gb1245gt20ga0gc0",
            "C0PRidXXXXxs05974xd0yj2467yd0zj2093zd0th2800te2800gr1go1308ga0gc0",
            "C0PPidXXXXxs09329xd0yj4982yd0zj2052zd0gr1th2800te2800gw4go1308gb1245gt20ga0gc0",
            "C0PRidXXXXxs05974xd0yj2467yd0zj2082zd0th2800te2800gr1go1308ga0gc0",
            "C0PPidXXXXxs05974xd0yj2467yd0zj2032zd0gr1th2800te2800gw4go1308gb1245gt20ga0gc0",
            "C0PRidXXXXxs09329xd0yj4982yd0zj2002zd0th2800te2800gr1go1308ga0gc0",
            "C0PPidXXXXxs05974xd0yj2467yd0zj1973zd0gr1th2800te2800gw4go1308gb1245gt20ga0gc0",
            "C0PRidXXXXxs09329xd0yj1142yd0zj2058zd0th2800te2800gr1go1308ga0gc0",
        ]
        magnet_block = [
            "C0PPidXXXXxs09329xd0yj1142yd0zj2058zd0gr1th2800te2800gw4go1308gb1245gt20ga0gc0",
            "C0PRidXXXXxs09329xd0yj3062yd0zj2153zd0th2800te2800gr1go1308ga0gc0",
            "C0PPidXXXXxs09329xd0yj3062yd0zj2113zd0gr1th2800te2800gw4go1308gb1245gt20ga0gc0",
            "C0PRidXXXXxs09329xd0yj1142yd0zj2058zd0th2800te2800gr1go1308ga0gc0",
        ]
        self.assertEqual(len(signatures), 20)
        self.assertEqual(signatures, odtc_block + magnet_block + odtc_block)
        self.assertIn("SUCCESS: full LIDDED Targeted PCR", result.stdout)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Guarded whole-genome amplification pipetting plus lidded HHS dry engineering runner.

Scope (single column, empty sacrificial labware, return tips):

  1. whole-genome amplification lysis 3.0 uL: source column 1 -> work column 1
  2. whole-genome amplification reaction 6.0 uL: source column 3 -> work column 1
  3. Plate rail35 pos0 -> HHS rail27 pos2
  4. Lid rail35 pos4 -> plate on HHS
  5. Delid HHS -> rail35 pos4
  6. Plate HHS -> rail35 pos0

This is an engineering dry runner, not a validated production protocol. It uses
the validated whole-genome amplification pipetting implementation without editing it, and it corrects
the HHS drop Y from the stale 54.5 mm value to the real-plate seat-check value
45.5 mm recorded on 2026-07-17.

The physical run is deliberately stagewise. STAR mode cannot run all stages in
one command: the operator must reconcile the physical state between stages.
The delid and corrected-Y return remain unvalidated until a supervised dry run
records them. Chatterbox mode can run the complete flow without hardware.

Base repository commit: bae80c6c563e83a8ffa37678885689dbc0d482cc
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import sys
from dataclasses import dataclass, replace
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Optional


ROOT = Path(__file__).resolve().parent
PTA_SCRIPT = ROOT / "00_pta_wga_1col_src1lysis_src3rxn_dst1_hhs_DRY.py"

WORK_PLATE_MODEL = "CellTreat_96_wellplate_350ul_Fb"
WORK_PLATE_CATALOG = "CellTreat 229195/229196"
LID_MODEL = "Cor_96_wellplate_360ul_Fb_Lid"
LID_CATALOG = "Corning 3603 lid resource"
LABWARE_ACK = "CELLTREAT_229195_WITH_CORNING_3603_LID"
EXPECTED_PLR_VERSION = "0.2.1"

HHS_RAIL = 27
HHS_POS = 2
PLATE_RAIL = 35
WORK_POS = 0
SOURCE_POS = 1
LID_PARK_POS = 4
TIP_RAIL = 48
P10_TIP_POS = 0
P50_TIP_POS = 1

# Corrected real-plate mount geometry, 2026-07-17. Do not replace HHS_Y with
# the older 54.5 value; that value completed transfers but did not seat a real
# plate in the HHS nest.
CONFIRMED_HHS_XY = (12.0, 45.5)
HHS_X, HHS_Y = CONFIRMED_HHS_XY
HHS_DROP_Z = 17.0
PLATE_FORWARD_PICKUP_Z = 5.0
LID_ON_PICKUP_Z = 9.0
DELID_PICKUP_Z = 16.0
LID_PARK_DROP_Z = 4.0
PLATE_RETURN_PICKUP_Z = 10.0
PLATE_RETURN_DROP_Z = 8.5

STAGE_ORDER = ("pta-forward", "lid-on", "delid", "plate-return")


@dataclass(frozen=True)
class StagePolicy:
    label: str
    status: str
    expected_start: str
    expected_end: str
    confirm: str
    acknowledgement: Optional[str] = None


STAGE_POLICIES = {
    "pta-forward": StagePolicy(
        label="PTA dry pipetting plus plate forward to HHS",
        status=(
            "component evidence: PTA pipetting and corrected HHS mount confirmed; "
            "combined runner not yet physical"
        ),
        expected_start=(
            "r35p0 empty sacrificial CellTreat work plate; r35p1 dry source plate; "
            "p10 tips r48p0; p50 rack r48p1; lid on its park plate r35p4; HHS r27p2 empty"
        ),
        expected_end="work plate on HHS r27p2; r35p0 empty; lid remains on r35p4",
        confirm="RUN_PTA_FORWARD_DRY",
        acknowledgement="DRY_DECK_MATCHED_HHS_EMPTY",
    ),
    "lid-on": StagePolicy(
        label="Place lid onto work plate on HHS",
        status="mount confirmed with Corning plate model; CellTreat destination is first-run evidence",
        expected_start="work plate seated on HHS r27p2; lid on park plate r35p4",
        expected_end="work plate remains on HHS with lid seated; r35p4 park plate is bare",
        confirm="RUN_HHS_LID_ON_DRY",
        acknowledgement="PLATE_SEATED_HHS_LID_ON_PARK",
    ),
    "delid": StagePolicy(
        label="Remove lid from HHS plate to r35p4",
        status="UNVALIDATED: z16 is a deliberately high first pickup",
        expected_start="lidded work plate seated on HHS; bare lid park plate r35p4",
        expected_end="bare work plate remains seated on HHS; lid is on r35p4",
        confirm="RUN_HHS_DELID_DRY",
        acknowledgement="LID_FLUSH_HHS_WATCH_LID_NOT_PLATE",
    ),
    "plate-return": StagePolicy(
        label="Return bare work plate from HHS to r35p0",
        status="UNVALIDATED at corrected y45.5",
        expected_start="bare work plate visibly seated on HHS; r35p0 empty; lid on r35p4",
        expected_end="work plate on r35p0; HHS empty; lid on r35p4",
        confirm="RUN_HHS_RETURN_DRY",
        acknowledgement="BARE_PLATE_SEATED_HHS_LID_PARKED",
    ),
}


def validate_geometry_lock() -> None:
    """Refuse a stale or internally split HHS X/Y geometry before execution."""
    if (HHS_X, HHS_Y) != CONFIRMED_HHS_XY:
        raise RuntimeError(
            "HHS geometry lock failed: every mount/pickup must use corrected "
            f"x{CONFIRMED_HHS_XY[0]} y{CONFIRMED_HHS_XY[1]}; got x{HHS_X} y{HHS_Y}"
        )


def validate_plr_version() -> None:
    """Lock the command geometry to the PyLabRobot build it was tested with."""
    try:
        installed = version("pylabrobot")
    except PackageNotFoundError as exc:
        raise RuntimeError("PyLabRobot is not installed; refusing to build a run stage") from exc
    if installed != EXPECTED_PLR_VERSION:
        raise RuntimeError(
            "PyLabRobot version lock failed: this runner is tested against "
            f"{EXPECTED_PLR_VERSION}, found {installed}"
        )


def load_pta_module() -> ModuleType:
    """Load the validated whole-genome amplification implementation only when a run stage needs it."""
    validate_plr_version()
    spec = importlib.util.spec_from_file_location("pta_hhs_validated_source", PTA_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load PTA source: {PTA_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def dry_transfer_step(pta: ModuleType, name: str, source_col: int):
    """Copy a validated whole-genome amplification step with truthful dry-only operator instructions."""
    return replace(
        pta.STEPS[name],
        manual_prep=(
            f"DRY ONLY: source rail35 pos1 column {source_col} is empty; "
            "use no reagent and no sample."
        ),
    )


def create_backend(name: str):
    if name == "star":
        from pylabrobot.liquid_handling.backends import STARBackend

        return STARBackend()
    if name == "chatterbox":
        candidates = (
            ("pylabrobot.liquid_handling.backends", "STARChatterboxBackend"),
            (
                "pylabrobot.liquid_handling.backends.hamilton.STAR_chatterbox",
                "STARChatterboxBackend",
            ),
            ("pylabrobot.liquid_handling.backends.hamilton.chatterbox", "STARChatterboxBackend"),
        )
        errors = []
        for module_name, class_name in candidates:
            try:
                module = __import__(module_name, fromlist=[class_name])
                backend_cls = getattr(module, class_name)
                return backend_cls()
            except (ImportError, AttributeError) as exc:
                errors.append(f"{module_name}.{class_name}: {exc}")
        raise RuntimeError("STARChatterboxBackend not found; tried: " + "; ".join(errors))
    raise ValueError(f"Unknown backend: {name}")


def shifted(coord, dx=0.0, dy=0.0, dz=0.0):
    try:
        from pylabrobot.resources.coordinate import Coordinate
    except ImportError:
        from pylabrobot.resources import Coordinate

    return Coordinate(coord.x + dx, coord.y + dy, coord.z + dz)


def make_handler(backend_name: str):
    from pylabrobot.liquid_handling import LiquidHandler
    from pylabrobot.resources.hamilton import STARDeck

    return LiquidHandler(backend=create_backend(backend_name), deck=STARDeck())


def attach_corning_lid(plate):
    """Attach the existing Corning lid resource to a CellTreat plate model."""
    from pylabrobot.resources import Cor_96_wellplate_360ul_Fb

    donor = Cor_96_wellplate_360ul_Fb(name="lid_resource_donor", with_lid=True)
    lid = donor.lid
    if lid is None:
        raise RuntimeError("Corning lid factory returned no lid")
    donor.unassign_child_resource(lid)
    plate.lid = lid
    return lid


def assign_full_stage_deck(lh, stage: str, pta: ModuleType):
    """Assign every fixed item on the documented physical deck for one stage.

    Each physical stage runs in a fresh process, so its PLR resource tree must
    begin in the exact physical state left by the preceding stage. Fixed tip
    racks, source plate, and lid park remain modeled even when a stage does not
    touch them.
    """
    from pylabrobot.resources import (
        CellTreat_96_wellplate_350ul_Fb,
        Cor_96_wellplate_360ul_Fb,
        PLT_CAR_L5AC_A00,
    )
    from pylabrobot.resources.hamilton import TIP_CAR_480_A00

    validate_geometry_lock()
    if stage not in STAGE_ORDER:
        raise ValueError(f"Unknown stage deck state: {stage}")

    tip_carrier = TIP_CAR_480_A00(name=f"pta_{stage}_tip_carrier_r48")
    plate_carrier = PLT_CAR_L5AC_A00(name=f"pta_{stage}_plate_carrier_r35")
    hhs_carrier = PLT_CAR_L5AC_A00(name=f"pta_{stage}_hhs_carrier_r27")
    lh.deck.assign_child_resource(tip_carrier, rails=TIP_RAIL)
    lh.deck.assign_child_resource(plate_carrier, rails=PLATE_RAIL)
    lh.deck.assign_child_resource(hhs_carrier, rails=HHS_RAIL)

    p10_tips = pta.make_p10_tips(f"pta_{stage}_r48p0_p10_filter_tips")
    p50_tips = pta.make_p50_tips(f"pta_{stage}_r48p1_p50_filter_tips")
    tip_carrier[P10_TIP_POS] = p10_tips
    tip_carrier[P50_TIP_POS] = p50_tips

    source_plate = CellTreat_96_wellplate_350ul_Fb(name=f"pta_{stage}_source_r35p1")
    plate_carrier[SOURCE_POS] = source_plate

    hhs_z_by_stage = {
        "pta-forward": HHS_DROP_Z,
        "lid-on": HHS_DROP_Z,
        "delid": DELID_PICKUP_Z,
        "plate-return": PLATE_RETURN_PICKUP_Z,
    }
    park_z_by_stage = {
        "pta-forward": 0.0,
        "lid-on": LID_ON_PICKUP_Z,
        "delid": LID_PARK_DROP_Z,
        "plate-return": 0.0,
    }

    hhs_site = hhs_carrier[HHS_POS]
    hhs_site.location = shifted(
        hhs_site.location,
        dx=HHS_X,
        dy=HHS_Y,
        dz=hhs_z_by_stage[stage],
    )
    work_site = plate_carrier[WORK_POS]
    if stage == "plate-return":
        work_site.location = shifted(work_site.location, dz=PLATE_RETURN_DROP_Z)
    park_site = plate_carrier[LID_PARK_POS]
    park_site.location = shifted(park_site.location, dz=park_z_by_stage[stage])

    work_plate = CellTreat_96_wellplate_350ul_Fb(name=f"pta_{stage}_work_plate")
    work_on_hhs = stage != "pta-forward"
    if work_on_hhs:
        hhs_carrier[HHS_POS] = work_plate
    else:
        plate_carrier[WORK_POS] = work_plate

    lid_on_work = stage == "delid"
    park_plate = Cor_96_wellplate_360ul_Fb(
        name=f"pta_{stage}_lid_park_r35p4",
        with_lid=not lid_on_work,
    )
    plate_carrier[LID_PARK_POS] = park_plate
    if lid_on_work:
        lid = attach_corning_lid(work_plate)
    else:
        lid = park_plate.lid
        if lid is None:
            raise RuntimeError("Expected a Corning lid on the park plate")

    return {
        "tip_carrier": tip_carrier,
        "plate_carrier": plate_carrier,
        "hhs_carrier": hhs_carrier,
        "p10_tips": p10_tips,
        "p50_tips": p50_tips,
        "source_96wp": source_plate,
        "work_plate": work_plate,
        "work_site": work_site,
        "hhs_site": hhs_site,
        "park_site": park_site,
        "park_plate": park_plate,
        "lid": lid,
    }


def _require_resource_state(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(f"PLR resource-state invariant failed: {message}")


def assert_stage_state(resources, stage: str, phase: str) -> None:
    """Verify the PLR parent tree before and after every mechanical stage."""
    if phase not in ("before", "after"):
        raise ValueError(f"Unknown invariant phase: {phase}")
    work_plate = resources["work_plate"]
    work_site = resources["work_site"]
    hhs_site = resources["hhs_site"]
    park_plate = resources["park_plate"]
    lid = resources["lid"]

    if stage == "pta-forward":
        destination = work_site if phase == "before" else hhs_site
        empty_site = hhs_site if phase == "before" else work_site
        _require_resource_state(work_plate.parent is destination, f"{stage} work plate parent")
        _require_resource_state(destination.resource is work_plate, f"{stage} destination occupancy")
        _require_resource_state(empty_site.resource is None, f"{stage} opposite site must be empty")
        _require_resource_state(park_plate.lid is lid, f"{stage} lid must remain parked")
    elif stage == "lid-on":
        _require_resource_state(work_plate.parent is hhs_site, "lid-on plate must stay on HHS")
        if phase == "before":
            _require_resource_state(park_plate.lid is lid, "lid-on lid must start on park plate")
            _require_resource_state(work_plate.lid is None, "lid-on work plate must start bare")
        else:
            _require_resource_state(work_plate.lid is lid, "lid-on lid must end on work plate")
            _require_resource_state(park_plate.lid is None, "lid-on park plate must end bare")
    elif stage == "delid":
        _require_resource_state(work_plate.parent is hhs_site, "delid plate must stay on HHS")
        if phase == "before":
            _require_resource_state(work_plate.lid is lid, "delid lid must start on work plate")
            _require_resource_state(park_plate.lid is None, "delid park plate must start bare")
        else:
            _require_resource_state(park_plate.lid is lid, "delid lid must end on park plate")
            _require_resource_state(work_plate.lid is None, "delid work plate must end bare")
    elif stage == "plate-return":
        destination = hhs_site if phase == "before" else work_site
        empty_site = work_site if phase == "before" else hhs_site
        _require_resource_state(work_plate.parent is destination, f"{stage} work plate parent")
        _require_resource_state(destination.resource is work_plate, f"{stage} destination occupancy")
        _require_resource_state(empty_site.resource is None, f"{stage} opposite site must be empty")
        _require_resource_state(park_plate.lid is lid, f"{stage} lid must remain parked")
    else:
        raise ValueError(f"Unknown stage invariant: {stage}")


def print_geometry_snapshot(stage: str, resources) -> None:
    work_plate = resources["work_plate"]
    lid = resources["lid"]
    hhs_site = resources["hhs_site"]
    print(
        f"GEOMETRY {stage}: HHS site {hhs_site.location}; "
        f"CellTreat {work_plate.get_size_x()}x{work_plate.get_size_y()}x{work_plate.get_size_z()} mm; "
        f"Corning lid {lid.get_size_x()}x{lid.get_size_y()}x{lid.get_size_z()} mm"
    )


async def run_deck(_backend_name: str) -> None:
    """Build and print the starting resource tree without connecting to a backend."""
    from pylabrobot.resources.hamilton import STARDeck

    pta = load_pta_module()
    deck_only = SimpleNamespace(deck=STARDeck())
    resources = assign_full_stage_deck(deck_only, "pta-forward", pta)
    assert_stage_state(resources, "pta-forward", "before")
    print("")
    print("CONNECTION-FREE DECK MODEL: no backend created, no setup/home, no motion.")
    print(f"  work plate: {WORK_PLATE_CATALOG} at r35p0")
    print("  dry source plate: CellTreat at r35p1; lysis col1, reaction col3")
    print("  p10 tips: r48p0 columns 1 and 2; p50 rack: r48p1")
    print(f"  lid: {LID_CATALOG} on park plate r35p4")
    print_geometry_snapshot("starting-deck", resources)


async def run_pta_forward(backend_name: str) -> None:
    pta = load_pta_module()
    lh = make_handler(backend_name)
    setup_complete = False
    stage_succeeded = False
    try:
        await lh.setup(skip_autoload=True)
        setup_complete = True
        resources = assign_full_stage_deck(lh, "pta-forward", pta)
        assert_stage_state(resources, "pta-forward", "before")
        print_geometry_snapshot("pta-forward", resources)
        print("Dry engineering run: tips are returned. No reagents or samples.")
        await pta.transfer_step(
            lh,
            resources,
            dry_transfer_step(pta, "lysis", source_col=1),
            False,
            tip_col=1,
            source_col=1,
            dest_col=1,
        )
        await pta.transfer_step(
            lh,
            resources,
            dry_transfer_step(pta, "reaction", source_col=3),
            False,
            tip_col=2,
            source_col=3,
            dest_col=1,
        )
        work_plate = resources["work_plate"]
        work_plate.location = shifted(work_plate.location, dz=PLATE_FORWARD_PICKUP_Z)
        print("")
        print("=== iSWAP MOVE: work plate rail35 pos0 -> HHS rail27 pos2 ===")
        print(f"Pickup Z raise: {PLATE_FORWARD_PICKUP_Z} mm")
        print(f"Corrected HHS target: x{HHS_X} y{HHS_Y} z{HHS_DROP_Z}")
        async with lh.backend.slow_iswap():
            await lh.move_resource(work_plate, resources["hhs_site"])
        assert_stage_state(resources, "pta-forward", "after")
        print("SUCCESS: iSWAP moved work plate to corrected HHS rail27 pos2.")
        stage_succeeded = True
    finally:
        await stop_handler(
            lh,
            park_iswap=stage_succeeded,
            suppress_errors=not stage_succeeded,
            setup_complete=setup_complete,
        )


async def run_lid_on(backend_name: str) -> None:
    pta = load_pta_module()
    lh = make_handler(backend_name)
    setup_complete = False
    stage_succeeded = False
    try:
        await lh.setup(skip_autoload=True)
        setup_complete = True
        resources = assign_full_stage_deck(lh, "lid-on", pta)
        assert_stage_state(resources, "lid-on", "before")
        print_geometry_snapshot("lid-on", resources)
        print("LID ON: r35p4 -> CellTreat work plate on HHS r27p2")
        print(f"HHS offsets: x{HHS_X} y{HHS_Y} z{HHS_DROP_Z}; lid pickup z{LID_ON_PICKUP_Z}")
        async with lh.backend.slow_iswap():
            await lh.move_lid(resources["lid"], resources["work_plate"])
        assert_stage_state(resources, "lid-on", "after")
        stage_succeeded = True
    finally:
        await stop_handler(
            lh,
            park_iswap=stage_succeeded,
            suppress_errors=not stage_succeeded,
            setup_complete=setup_complete,
        )


async def run_delid(backend_name: str) -> None:
    pta = load_pta_module()
    lh = make_handler(backend_name)
    setup_complete = False
    stage_succeeded = False
    try:
        await lh.setup(skip_autoload=True)
        setup_complete = True
        resources = assign_full_stage_deck(lh, "delid", pta)
        assert_stage_state(resources, "delid", "before")
        print_geometry_snapshot("delid", resources)
        print("DELID: CellTreat work plate on HHS r27p2 -> park plate r35p4")
        print(f"UNVALIDATED pickup: x{HHS_X} y{HHS_Y} z{DELID_PICKUP_Z}")
        print("Watch the physical plate: the lid must lift while the plate stays seated.")
        async with lh.backend.slow_iswap():
            await lh.move_lid(resources["lid"], resources["park_plate"])
        assert_stage_state(resources, "delid", "after")
        stage_succeeded = True
    finally:
        await stop_handler(
            lh,
            park_iswap=stage_succeeded,
            suppress_errors=not stage_succeeded,
            setup_complete=setup_complete,
        )


async def run_plate_return(backend_name: str) -> None:
    pta = load_pta_module()
    lh = make_handler(backend_name)
    setup_complete = False
    stage_succeeded = False
    try:
        await lh.setup(skip_autoload=True)
        setup_complete = True
        resources = assign_full_stage_deck(lh, "plate-return", pta)
        assert_stage_state(resources, "plate-return", "before")
        print_geometry_snapshot("plate-return", resources)
        print("PLATE RETURN: HHS r27p2 -> r35p0")
        print(
            f"UNVALIDATED corrected pickup: x{HHS_X} y{HHS_Y} "
            f"z{PLATE_RETURN_PICKUP_Z}; return drop z{PLATE_RETURN_DROP_Z}"
        )
        async with lh.backend.slow_iswap():
            await lh.move_resource(resources["work_plate"], resources["work_site"])
        assert_stage_state(resources, "plate-return", "after")
        stage_succeeded = True
    finally:
        await stop_handler(
            lh,
            park_iswap=stage_succeeded,
            suppress_errors=not stage_succeeded,
            setup_complete=setup_complete,
        )


async def stop_handler(
    lh,
    *,
    park_iswap: bool,
    suppress_errors: bool,
    setup_complete: bool,
) -> None:
    """Disconnect safely, parking only after a fully successful stage.

    If a move raises, the iSWAP may still hold a resource or the physical deck
    may disagree with PLR. Automatically parking in that state can compound a
    collision, so failure cleanup disconnects without issuing another motion.
    """
    cleanup_error = None
    if park_iswap:
        try:
            await lh.backend.park_iswap()
        except Exception as exc:
            cleanup_error = exc
            print(f"park_iswap failure: {exc!r}")
    else:
        print(
            "SAFETY HOLD: stage did not complete; iSWAP auto-park skipped. "
            "Physical state is UNKNOWN and must be reconciled before any next command."
        )
    try:
        if setup_complete:
            await lh.stop()
        else:
            # LiquidHandler.stop() is guarded by setup_finished. A partial
            # setup failure still needs a best-effort backend disconnect.
            await lh.backend.stop()
    except Exception as exc:
        print(f"backend stop failure: {exc!r}")
        if cleanup_error is None:
            cleanup_error = exc
    if cleanup_error is not None and not suppress_errors:
        raise cleanup_error


RUNNERS = {
    "pta-forward": run_pta_forward,
    "lid-on": run_lid_on,
    "delid": run_delid,
    "plate-return": run_plate_return,
}


def validate_release(args) -> None:
    validate_geometry_lock()
    if args.backend != "star":
        return
    if args.stage == "all":
        raise RuntimeError(
            "STAR mode refuses --stage all. Run one stage at a time and reconcile the deck between stages."
        )
    if args.stage == "deck":
        return
    policy = STAGE_POLICIES[args.stage]
    if args.confirm != policy.confirm:
        raise RuntimeError(f"Refusing STAR motion. Add: --confirm {policy.confirm}")
    if args.labware_ack != LABWARE_ACK:
        raise RuntimeError(
            "Refusing STAR motion until physical labware is confirmed. Add: "
            f"--labware-ack {LABWARE_ACK}"
        )
    if policy.acknowledgement and args.acknowledge != policy.acknowledgement:
        raise RuntimeError(
            "This stage requires the physical-state acknowledgement: "
            f"--acknowledge {policy.acknowledgement}"
        )


def print_plan() -> None:
    validate_geometry_lock()
    print("PTA + HHS LIDDED SINGLE-COLUMN DRY ENGINEERING PLAN")
    print(f"Work plate: {WORK_PLATE_CATALOG} ({WORK_PLATE_MODEL})")
    print(f"Lid resource: {LID_CATALOG} ({LID_MODEL})")
    print(f"Corrected HHS mount: x{HHS_X} y{HHS_Y} z{HHS_DROP_Z}")
    print("No HHS heating or shaking is included in this movement/pipetting rehearsal.")
    print("")
    for index, name in enumerate(STAGE_ORDER, 1):
        policy = STAGE_POLICIES[name]
        print(f"{index}. {name}: {policy.label}")
        print(f"   status: {policy.status}")
        print(f"   start:  {policy.expected_start}")
        print(f"   end:    {policy.expected_end}")
        print(f"   STAR confirm: {policy.confirm}")
        if policy.acknowledgement:
            print(f"   extra acknowledgement: {policy.acknowledgement}")
    print("")
    print("Chatterbox (no hardware): --backend chatterbox --stage all")
    print("STAR: inspect --stage deck first, then run one named stage per command with its tokens.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="PTA dry pipetting plus staged lidded HHS round trip. Defaults to plan only."
    )
    parser.add_argument(
        "--stage",
        choices=("plan", "deck", "all") + STAGE_ORDER,
        default="plan",
        help="deck is connection-free; all is chatterbox-only; STAR motion is one stage per invocation",
    )
    parser.add_argument(
        "--backend",
        choices=("chatterbox", "star"),
        default="chatterbox",
        help="chatterbox is simulated/no hardware; star controls the physical instrument",
    )
    parser.add_argument("--confirm", default="", help="Exact per-stage STAR confirmation token")
    parser.add_argument(
        "--acknowledge",
        default="",
        help="Exact physical starting-state token required by later STAR stages",
    )
    parser.add_argument(
        "--labware-ack",
        default="",
        help="Confirms the physical CellTreat work plate and Corning lid combination",
    )
    return parser


async def dispatch(args) -> None:
    if args.stage == "deck":
        await run_deck(args.backend)
        return
    if args.stage == "all":
        for stage in STAGE_ORDER:
            print("")
            print("=" * 88)
            print(f"CHATTERBOX STAGE: {stage}")
            print("=" * 88)
            await RUNNERS[stage](args.backend)
        return
    await RUNNERS[args.stage](args.backend)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.stage == "plan":
        print_plan()
        return
    validate_release(args)
    if args.stage == "deck":
        print("DECK MODEL ONLY: no backend will be created and no hardware connection will be made.")
    elif args.backend == "star":
        policy = STAGE_POLICIES.get(args.stage)
        print("PHYSICAL STAR MODE: attended run only; hand at E-stop; one driver process.")
        if policy is not None:
            print(f"Expected start: {policy.expected_start}")
            print(f"Expected end:   {policy.expected_end}")
    else:
        print("CHATTERBOX MODE: simulation only; no hardware connection or motion.")
    asyncio.run(dispatch(args))


if __name__ == "__main__":
    main()

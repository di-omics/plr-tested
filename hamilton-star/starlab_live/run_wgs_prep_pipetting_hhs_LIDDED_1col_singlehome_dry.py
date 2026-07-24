#!/usr/bin/env python3
"""Continuous single-home WGS preparation plus lidded HHS dry engineering runner.

This runner combines the individually hardware-proven dry stages from
``run_wgs_prep_pipetting_hhs_LIDDED_1col_dry.py`` into one LiquidHandler session:

  1. Operator-profile lysis dry motion, source column 1 -> work column 1
  2. Operator-profile reaction dry motion, source column 3 -> work column 1
  3. Work plate rail35 pos0 -> HHS rail27 pos2
  4. Lid rail35 pos4 -> work plate on HHS
  5. Delid work plate on HHS -> rail35 pos4
  6. Bare work plate HHS -> rail35 pos0

It homes once, assigns one truthful deck, runs all six operations without an
operator pause, parks only after complete success, and stops once. It never
heats or shakes the HHS. It is dry only: empty sacrificial labware, no samples
or reagents, and tips returned.

Physical component evidence recorded 2026-07-21:

  - WGS preparation dry lysis/reaction plus corrected HHS forward: pass
  - Lid on at pickup z9 / HHS x12 y45.5 z17: pass after lid was seated flat
  - Delid at HHS x12 y45.5 z16 / park drop z4: pass
  - Plate return at HHS x12 y45.5 z10 / r35p0 drop z8.5: pass

The continuous composition must pass Chatterbox before STAR release. STAR mode
requires exact intent, deck-state, and labware tokens.

Continuous physical evidence recorded 2026-07-21: all six operations passed in
one setup/deck/session with exit 0 and operator-confirmed final state (work
plate r35p0, lid r35p4, HHS empty, tips returned, iSWAP parked).
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace


ROOT = Path(__file__).resolve().parent
STAGED_RUNNER = ROOT / "run_wgs_prep_pipetting_hhs_LIDDED_1col_dry.py"

CONFIRM_TOKEN = "RUN_WGS_PREP_HHS_LIDDED_FULL_DRY"
DECK_ACK = "FULL_DRY_DECK_LID_FLAT_HHS_EMPTY"


def load_staged_runner() -> ModuleType:
    """Load shared, hardware-inert helpers without importing PyLabRobot."""
    module_name = "wgs_prep_hhs_lidded_staged_for_singlehome"
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(module_name, STAGED_RUNNER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load staged runner: {STAGED_RUNNER}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


staged = load_staged_runner()


def banner(label: str) -> None:
    print("")
    print("=" * 88)
    print(label)
    print("=" * 88)


def assign_unified_deck(lh, wgs_prep):
    """Assign the pristine physical start deck once, without teach offsets."""
    from pylabrobot.resources import (
        CellTreat_96_wellplate_350ul_Fb,
        Cor_96_wellplate_360ul_Fb,
        PLT_CAR_L5AC_A00,
    )
    from pylabrobot.resources.hamilton import TIP_CAR_480_A00

    staged.validate_geometry_lock()
    staged.validate_plr_version()

    tip_carrier = TIP_CAR_480_A00(name="wgs_prep_full_tip_carrier_r48")
    plate_carrier = PLT_CAR_L5AC_A00(name="wgs_prep_full_plate_carrier_r35")
    hhs_carrier = PLT_CAR_L5AC_A00(name="wgs_prep_full_hhs_carrier_r27")
    lh.deck.assign_child_resource(tip_carrier, rails=staged.TIP_RAIL)
    lh.deck.assign_child_resource(plate_carrier, rails=staged.PLATE_RAIL)
    lh.deck.assign_child_resource(hhs_carrier, rails=staged.HHS_RAIL)

    p10_tips = wgs_prep.make_p10_tips("wgs_prep_full_r48p0_p10_filter_tips")
    p50_tips = wgs_prep.make_p50_tips("wgs_prep_full_r48p1_p50_filter_tips")
    tip_carrier[staged.P10_TIP_POS] = p10_tips
    tip_carrier[staged.P50_TIP_POS] = p50_tips

    work_plate = CellTreat_96_wellplate_350ul_Fb(name="wgs_prep_full_work_plate_r35p0")
    source_plate = CellTreat_96_wellplate_350ul_Fb(name="wgs_prep_full_source_plate_r35p1")
    park_plate = Cor_96_wellplate_360ul_Fb(
        name="wgs_prep_full_lid_park_r35p4",
        with_lid=True,
    )
    plate_carrier[staged.WORK_POS] = work_plate
    plate_carrier[staged.SOURCE_POS] = source_plate
    plate_carrier[staged.LID_PARK_POS] = park_plate
    lid = park_plate.lid
    if lid is None:
        raise RuntimeError("Expected a Corning lid on the unified park plate")

    return {
        "tip_carrier": tip_carrier,
        "plate_carrier": plate_carrier,
        "hhs_carrier": hhs_carrier,
        "p10_tips": p10_tips,
        "p50_tips": p50_tips,
        "source_96wp": source_plate,
        "work_plate": work_plate,
        "work_site": plate_carrier[staged.WORK_POS],
        "hhs_site": hhs_carrier[staged.HHS_POS],
        "park_site": plate_carrier[staged.LID_PARK_POS],
        "park_plate": park_plate,
        "lid": lid,
    }


def coordinate_tuple(coord):
    return (coord.x, coord.y, coord.z)


def site_snapshot(resources):
    return {
        "work_site": coordinate_tuple(resources["work_site"].location),
        "hhs_site": coordinate_tuple(resources["hhs_site"].location),
        "park_site": coordinate_tuple(resources["park_site"].location),
    }


def assert_sites_pristine(resources, expected, label: str) -> None:
    actual = site_snapshot(resources)
    if actual != expected:
        raise RuntimeError(f"Persistent site-coordinate bleed after {label}: {actual} != {expected}")


async def plate_leg(
    lh,
    plate,
    drop_site,
    *,
    pickup_dx: float = 0.0,
    pickup_dy: float = 0.0,
    pickup_dz: float,
    drop_dx: float = 0.0,
    drop_dy: float = 0.0,
    drop_dz: float,
    pickup_target: str,
) -> None:
    """Move one plate while restoring all persistent carrier-site mutations."""
    if pickup_target not in ("plate", "slot"):
        raise ValueError(f"Unknown plate pickup target: {pickup_target}")
    original_parent = plate.parent
    pickup_site = original_parent
    plate_base = plate.location
    pickup_site_base = pickup_site.location if pickup_site is not None else None
    drop_site_base = drop_site.location
    try:
        if pickup_target == "slot":
            if pickup_site is None or pickup_site_base is None:
                raise RuntimeError("Plate has no pickup site")
            pickup_site.location = staged.shifted(
                pickup_site_base,
                dx=pickup_dx,
                dy=pickup_dy,
                dz=pickup_dz,
            )
        else:
            plate.location = staged.shifted(
                plate_base,
                dx=pickup_dx,
                dy=pickup_dy,
                dz=pickup_dz,
            )
        drop_site.location = staged.shifted(
            drop_site_base,
            dx=drop_dx,
            dy=drop_dy,
            dz=drop_dz,
        )
        async with lh.backend.slow_iswap():
            await lh.move_resource(plate, drop_site)
    finally:
        if pickup_target == "slot" and pickup_site is not None and pickup_site_base is not None:
            pickup_site.location = pickup_site_base
        if pickup_target == "plate" and plate.parent is original_parent:
            plate.location = plate_base
        drop_site.location = drop_site_base


async def lid_leg(
    lh,
    lid,
    destination_plate,
    *,
    source_site,
    destination_site,
    pickup_dx: float = 0.0,
    pickup_dy: float = 0.0,
    pickup_dz: float,
    drop_dx: float = 0.0,
    drop_dy: float = 0.0,
    drop_dz: float,
) -> None:
    """Move one lid while restoring both persistent carrier-site mutations."""
    source_base = source_site.location
    destination_base = destination_site.location
    try:
        source_site.location = staged.shifted(
            source_base,
            dx=pickup_dx,
            dy=pickup_dy,
            dz=pickup_dz,
        )
        destination_site.location = staged.shifted(
            destination_base,
            dx=drop_dx,
            dy=drop_dy,
            dz=drop_dz,
        )
        async with lh.backend.slow_iswap():
            await lh.move_lid(lid, destination_plate)
    finally:
        source_site.location = source_base
        destination_site.location = destination_base


async def run_choreography(lh, resources, wgs_prep) -> None:
    """Run the six dry operations against one handler and one resource tree."""
    work_plate = resources["work_plate"]
    work_site = resources["work_site"]
    hhs_site = resources["hhs_site"]
    park_site = resources["park_site"]
    park_plate = resources["park_plate"]
    lid = resources["lid"]
    pristine_sites = site_snapshot(resources)

    staged.assert_stage_state(resources, "wgs_prep-forward", "before")
    assert_sites_pristine(resources, pristine_sites, "initial deck")

    banner("1/6 WGS preparation DRY LYSIS: source column 1 -> work column 1")
    await wgs_prep.transfer_step(
        lh,
        resources,
        staged.dry_transfer_step(wgs_prep, "lysis", source_col=1),
        False,
        tip_col=1,
        source_col=1,
        dest_col=1,
    )

    banner("2/6 WGS preparation DRY REACTION: source column 3 -> work column 1")
    await wgs_prep.transfer_step(
        lh,
        resources,
        staged.dry_transfer_step(wgs_prep, "reaction", source_col=3),
        False,
        tip_col=2,
        source_col=3,
        dest_col=1,
    )

    banner("3/6 PLATE FORWARD: r35p0 -> corrected HHS r27p2")
    assert_sites_pristine(resources, pristine_sites, "before plate forward")
    await plate_leg(
        lh,
        work_plate,
        hhs_site,
        pickup_dz=staged.PLATE_FORWARD_PICKUP_Z,
        drop_dx=staged.HHS_X,
        drop_dy=staged.HHS_Y,
        drop_dz=staged.HHS_DROP_Z,
        pickup_target="plate",
    )
    assert_sites_pristine(resources, pristine_sites, "plate forward")
    staged.assert_stage_state(resources, "wgs_prep-forward", "after")
    staged.assert_stage_state(resources, "lid-on", "before")

    banner("4/6 LID ON: r35p4 -> CellTreat work plate on HHS")
    assert_sites_pristine(resources, pristine_sites, "before lid on")
    await lid_leg(
        lh,
        lid,
        work_plate,
        source_site=park_site,
        destination_site=hhs_site,
        pickup_dz=staged.LID_ON_PICKUP_Z,
        drop_dx=staged.HHS_X,
        drop_dy=staged.HHS_Y,
        drop_dz=staged.HHS_DROP_Z,
    )
    assert_sites_pristine(resources, pristine_sites, "lid on")
    staged.assert_stage_state(resources, "lid-on", "after")
    staged.assert_stage_state(resources, "delid", "before")

    banner("5/6 DELID: HHS -> r35p4; lid must move and plate must stay")
    assert_sites_pristine(resources, pristine_sites, "before delid")
    await lid_leg(
        lh,
        lid,
        park_plate,
        source_site=hhs_site,
        destination_site=park_site,
        pickup_dx=staged.HHS_X,
        pickup_dy=staged.HHS_Y,
        pickup_dz=staged.DELID_PICKUP_Z,
        drop_dz=staged.LID_PARK_DROP_Z,
    )
    assert_sites_pristine(resources, pristine_sites, "delid")
    staged.assert_stage_state(resources, "delid", "after")
    staged.assert_stage_state(resources, "plate-return", "before")

    banner("6/6 PLATE RETURN: bare work plate HHS -> r35p0")
    assert_sites_pristine(resources, pristine_sites, "before plate return")
    await plate_leg(
        lh,
        work_plate,
        work_site,
        pickup_dx=staged.HHS_X,
        pickup_dy=staged.HHS_Y,
        pickup_dz=staged.PLATE_RETURN_PICKUP_Z,
        drop_dz=staged.PLATE_RETURN_DROP_Z,
        pickup_target="slot",
    )
    assert_sites_pristine(resources, pristine_sites, "plate return")
    staged.assert_stage_state(resources, "plate-return", "after")


async def run_full(backend_name: str) -> None:
    wgs_prep = staged.load_wgs_prep_module()
    lh = staged.make_handler(backend_name)
    setup_complete = False
    choreography_succeeded = False
    try:
        await lh.setup(skip_autoload=True)
        setup_complete = True
        resources = assign_unified_deck(lh, wgs_prep)
        print(
            "GEOMETRY singlehome: forward/lid HHS "
            f"x{staged.HHS_X} y{staged.HHS_Y} z{staged.HHS_DROP_Z}; "
            f"delid z{staged.DELID_PICKUP_Z}; return z{staged.PLATE_RETURN_PICKUP_Z}; "
            f"CellTreat {resources['work_plate'].get_size_x()}x"
            f"{resources['work_plate'].get_size_y()}x{resources['work_plate'].get_size_z()} mm; "
            f"Corning lid {resources['lid'].get_size_x()}x"
            f"{resources['lid'].get_size_y()}x{resources['lid'].get_size_z()} mm"
        )
        print("Dry only: empty sacrificial labware, no reagents/samples, tips returned.")
        await run_choreography(lh, resources, wgs_prep)
        choreography_succeeded = True
        print("")
        print("SUCCESS: continuous WGS preparation + HHS lid/delid/return dry sequence completed.")
        print("Final modeled state: work plate r35p0; lid r35p4; HHS empty.")
    finally:
        await staged.stop_handler(
            lh,
            park_iswap=choreography_succeeded,
            suppress_errors=not choreography_succeeded,
            setup_complete=setup_complete,
        )


def run_deck() -> None:
    """Build the pristine unified start tree without creating a backend."""
    from pylabrobot.resources.hamilton import STARDeck

    wgs_prep = staged.load_wgs_prep_module()
    shell = SimpleNamespace(deck=STARDeck())
    resources = assign_unified_deck(shell, wgs_prep)
    staged.assert_stage_state(resources, "wgs_prep-forward", "before")
    print("Unified starting deck assigned in memory; no backend or hardware connection.")
    print("  r48p0 p10 tips (columns 1/2); r48p1 p50 rack")
    print("  r35p0 empty CellTreat work; r35p1 empty CellTreat source")
    print("  r35p4 Corning lid seated flat on park plate; r27p2 HHS empty")
    print(
        f"  temporary HHS teach target: x{staged.HHS_X} y{staged.HHS_Y} "
        f"z{staged.HHS_DROP_Z} (pristine sites restored after each leg)"
    )


def validate_release(args) -> None:
    staged.validate_geometry_lock()
    if args.mode != "star":
        return
    if args.confirm != CONFIRM_TOKEN:
        raise RuntimeError(f"Refusing continuous STAR run. Add: --confirm {CONFIRM_TOKEN}")
    if args.acknowledge != DECK_ACK:
        raise RuntimeError(
            "Refusing continuous STAR run until the complete dry start deck is confirmed. Add: "
            f"--acknowledge {DECK_ACK}"
        )
    if args.labware_ack != staged.LABWARE_ACK:
        raise RuntimeError(
            "Refusing continuous STAR run until physical labware is confirmed. Add: "
            f"--labware-ack {staged.LABWARE_ACK}"
        )


def print_plan() -> None:
    staged.validate_geometry_lock()
    print("CONTINUOUS SINGLE-HOME WGS preparation + HHS LIDDED DRY PLAN")
    print("One setup/home, one deck, six operations, one park/stop.")
    print("Lysis col1 -> reaction col3 -> HHS -> lid on -> delid -> r35p0 return.")
    print("No operator pause occurs after STAR release.")
    print("No HHS heating or shaking. Empty sacrificial labware. Tips returned.")
    print(
        f"HHS mount x{staged.HHS_X} y{staged.HHS_Y} z{staged.HHS_DROP_Z}; "
        f"delid z{staged.DELID_PICKUP_Z}; return pickup z{staged.PLATE_RETURN_PICKUP_Z}."
    )
    print(f"STAR confirm: --confirm {CONFIRM_TOKEN}")
    print(f"Deck acknowledgement: --acknowledge {DECK_ACK}")
    print(f"Labware acknowledgement: --labware-ack {staged.LABWARE_ACK}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Continuous single-home one-column WGS preparation plus lidded HHS dry runner."
    )
    parser.add_argument(
        "--mode",
        choices=("plan", "deck", "chatterbox", "star"),
        default="plan",
        help="plan/deck are inert; chatterbox simulates; star runs all six operations continuously",
    )
    parser.add_argument("--confirm", default="")
    parser.add_argument("--acknowledge", default="")
    parser.add_argument("--labware-ack", default="")
    return parser


async def main_async(args) -> None:
    if args.mode == "plan":
        print_plan()
        return
    if args.mode == "deck":
        print("DECK MODEL ONLY: no backend, connection, setup/home, or motion.")
        run_deck()
        return
    validate_release(args)
    if args.mode == "star":
        print("PHYSICAL STAR CONTINUOUS MODE: no pause after release.")
        print("Attended dry run only; one driver; hand at E-stop for the entire sequence.")
    else:
        print("CHATTERBOX MODE: no hardware connection or motion.")
    await run_full("star" if args.mode == "star" else "chatterbox")


def main() -> None:
    args = build_parser().parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()

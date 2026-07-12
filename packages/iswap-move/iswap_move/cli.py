"""
cli.py - the iSWAP lid-move entrypoint.

    iswap-move plan               print the dry (coordinate-only) commands, no motion
    iswap-move lid-on  [--hardware]   the confirmed park -> work lid-on move
    iswap-move de-lid  [--hardware]   the confirmed work -> park de-lid move
    iswap-move cycle   [--hardware]   lid-on then de-lid (the hands-free cycle)

Without --hardware every command is a simulation: it validates the move and prints what
it would run. With --hardware it prints the arming run card (the exact Pi command); it
does not execute it, and it refuses to emit an arming command for a move that fails
validation. Also runnable as `python -m iswap_move ...`.
"""

from __future__ import annotations

import argparse
from typing import List

from .core import LidMove, confirmed_de_lid, confirmed_lid_on
from .runner import Action, Mode, Runner, dry_command
from .version import __version__


def _print_action(a: Action) -> None:
    flag = "REFUSED" if a.refused else ("ARMED" if a.resolved_command else "SIMULATED")
    print(f"[{flag}] {a.action}: {a.note}")
    for p in a.problems:
        print(f"    problem: {p}")
    print(f"    dry:  {a.dry_command}")
    if a.resolved_command:
        print(f"    run:  {a.resolved_command}")


def _moves_for(cmd: str) -> List[LidMove]:
    if cmd == "lid-on":
        return [confirmed_lid_on()]
    if cmd == "de-lid":
        return [confirmed_de_lid()]
    if cmd == "cycle":
        return [confirmed_lid_on(), confirmed_de_lid()]
    return []


def cmd_plan(args) -> int:
    print("iSWAP lid moves - dry (coordinate print only, NO motion):")
    for mv in (confirmed_lid_on(), confirmed_de_lid()):
        print(f"  {mv.describe()}")
        print(f"    {dry_command(mv)}")
    print("\nConfirmed on the instrument 2026-07-12. The offsets are slot- and lid-specific.")
    print("Moving INTO the ODTC is a separate geometry and is not yet taught.")
    return 0


def cmd_move(args) -> int:
    mode = Mode.HARDWARE if args.hardware else Mode.SIMULATION
    runner = Runner(mode)
    for mv in _moves_for(args.cmd):
        runner.lid_move(mv)
    for a in runner.actions:
        _print_action(a)
    if mode is Mode.HARDWARE:
        card = runner.run_card()
        print(f"\nrun card: {len(card)} arming command(s). A person watches with a hand on the E-stop.")
    return 0 if not any(a.refused for a in runner.actions) else 2


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="iswap-move",
                                description="iSWAP plate-lid moves for the Hamilton STAR (hardware-confirmed)")
    p.add_argument("--version", action="version", version=f"iswap-move {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("plan", help="print dry commands (no motion)")
    pl.set_defaults(func=cmd_plan)

    for name, helptext in [("lid-on", "park -> work lid-on move"),
                           ("de-lid", "work -> park de-lid move"),
                           ("cycle", "lid-on then de-lid")]:
        s = sub.add_parser(name, help=helptext)
        s.add_argument("--hardware", action="store_true",
                       help="print the arming run card instead of a simulation")
        s.set_defaults(func=cmd_move)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

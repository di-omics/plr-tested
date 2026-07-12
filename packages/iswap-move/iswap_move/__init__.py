"""
iswap_move - iSWAP plate and lid moves for the Hamilton STAR, hardware-confirmed.

Reduces the tuned lid-on / de-lid recipe (rail35 pos4 <-> pos0, pickup +9 / drop +18 mm,
confirmed on the instrument) to a small, tested, reusable form. Simulation-first; the
hardware path resolves to the validated Pi script rather than reimplementing the motion.

    from iswap_move import confirmed_lid_on, Runner, Mode
    r = Runner(Mode.SIMULATION)
    r.lid_move(confirmed_lid_on())
"""

from .core import (
    Direction,
    LidMove,
    Slot,
    Status,
    UnsafeMove,
    assert_safe,
    confirmed_de_lid,
    confirmed_lid_on,
    validate,
)
from .runner import Action, Mode, Runner, dry_command, move_command
from .version import __version__

__all__ = [
    "__version__",
    "Direction", "LidMove", "Slot", "Status", "UnsafeMove",
    "assert_safe", "validate", "confirmed_lid_on", "confirmed_de_lid",
    "Action", "Mode", "Runner", "dry_command", "move_command",
]

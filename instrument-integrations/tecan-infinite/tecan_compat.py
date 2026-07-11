"""
tecan_compat.py - shared setup for the Tecan Infinite ladder.

One place for the things every rung past the USB probe needs: the USB identity, a
guarded import of the PyLabRobot backend, a reader factory, and the --confirm gate.

Nothing here works around instrument behavior, because nothing has been observed on the
instrument yet. The only facts encoded are the ones the backend source already states
(the USB vendor/product, the wavelength ranges, the defaults). When a live run turns up
a firmware quirk that has to be worked around to make a run go, it lands here, the way
odtc_compat.py holds the ODTC's three, and it gets an assertion in tecan_offline_checks.py
so a PyLabRobot upgrade cannot silently undo it.
"""

from __future__ import annotations

import sys

# Tecan USB identity, from pylabrobot/tecan/infinite/driver.py.
VENDOR_ID = 0x0C47
PRODUCT_ID = 0x8007

CONFIRM_PHRASE = "i-am-watching"

# Ranges the backend enforces, restated so the probe and the offline checks can cite them
# without importing the whole stack.
ABS_WAVELENGTH_MIN_NM = 230
ABS_WAVELENGTH_MAX_NM = 1000
FLR_WAVELENGTH_MIN_NM = 230
FLR_WAVELENGTH_MAX_NM = 850


def import_backend():
    """Import the Tecan Infinite device class, with a message that says what to fix.

    The reader backend lives in the di-omics PyLabRobot fork under
    pylabrobot.tecan.infinite. If the venv on the Pi is a stock PyLabRobot, or an older
    fork commit, the import fails here rather than three commands into a live run.
    """
    try:
        from pylabrobot.tecan.infinite import TecanInfinite200Pro  # noqa: WPS433
    except ImportError as exc:
        raise SystemExit(
            "Could not import pylabrobot.tecan.infinite.TecanInfinite200Pro.\n"
            "The venv on this host does not carry the Tecan Infinite backend.\n"
            "Install the di-omics PyLabRobot fork commit that ships pylabrobot/tecan/, "
            "with the USB extra:\n"
            "    pip install -e '.[usb]'   (from a checkout of the fork)\n"
            f"Underlying import error: {exc}"
        )
    return TecanInfinite200Pro


def build_reader(name: str = "infinite"):
    """Construct a TecanInfinite200Pro. Does not connect; call setup() to do that."""
    TecanInfinite200Pro = import_backend()
    return TecanInfinite200Pro(name=name)


def require_confirm(confirm: str, what: str) -> None:
    """Refuse to proceed with a motion/optics step unless the operator confirmed.

    Mirrors the ODTC scripts: --confirm i-am-watching or the script exits. setup() on
    this reader homes the stage, so bring-up and everything below it are gated.
    """
    if confirm != CONFIRM_PHRASE:
        raise SystemExit(
            f"{what} moves the instrument. A person must be watching it.\n"
            f"Pass --confirm {CONFIRM_PHRASE} to proceed."
        )


def build_read_plate(name: str = "qc_plate"):
    """A standard flat-bottom 96-well plate to read into.

    Used by the read rungs and by the offline geometry check. Corning 360 uL flat-bottom
    is a stand-in for the labware actually on the tray; swap it for the real plate
    definition once the deck is fixed.
    """
    from pylabrobot.resources.corning.plates import Cor_96_wellplate_360ul_Fb

    return Cor_96_wellplate_360ul_Fb(name=name)


def eprint(*args) -> None:
    print(*args, file=sys.stderr)

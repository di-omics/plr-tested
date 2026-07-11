"""
tecan_offline_checks.py - assert the Tecan Infinite backend's shape, with no device.

Run this before every live session and after every PyLabRobot change, the same way as
odtc_offline_checks.py. It touches no USB and no network. It answers two questions:

  1. Does the fork on this host actually carry pylabrobot.tecan.infinite, importably.
  2. Does the backend still have the shape these scripts assume: the USB identity, the
     wavelength clamps, the documented defaults, and a well-to-stage geometry that puts a
     known 96-well plate where it should be.

If PyLabRobot changes any of these, this fails here, in the venv, rather than at the bench.

    python tecan_offline_checks.py
    ./run_on_pi.sh tecan-infinite/tecan_offline_checks.py
"""

from __future__ import annotations

import asyncio
import sys

import tecan_compat

PASS = 0
FAIL = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"[pass] {name}")
    else:
        FAIL += 1
        print(f"[FAIL] {name}" + (f"  ({detail})" if detail else ""))


def main() -> int:
    # -- import --
    from pylabrobot.tecan.infinite import TecanInfinite200Pro
    from pylabrobot.tecan.infinite.absorbance_backend import (
        TecanInfiniteAbsorbanceBackend,
        TecanInfiniteAbsorbanceParams,
    )
    from pylabrobot.tecan.infinite.driver import TecanInfiniteDriver
    from pylabrobot.tecan.infinite.fluorescence_backend import TecanInfiniteFluorescenceParams

    # -- USB identity --
    check(
        "driver USB vendor id is 0x0C47",
        TecanInfiniteDriver.VENDOR_ID == tecan_compat.VENDOR_ID == 0x0C47,
        hex(TecanInfiniteDriver.VENDOR_ID),
    )
    check(
        "driver USB product id is 0x8007",
        TecanInfiniteDriver.PRODUCT_ID == tecan_compat.PRODUCT_ID == 0x8007,
        hex(TecanInfiniteDriver.PRODUCT_ID),
    )

    # -- device exposes the four capabilities --
    reader = TecanInfinite200Pro(name="offline")
    check("reader has absorbance", hasattr(reader, "absorbance"))
    check("reader has fluorescence", hasattr(reader, "fluorescence"))
    check("reader has luminescence", hasattr(reader, "luminescence"))
    check("reader has loading_tray", hasattr(reader, "loading_tray"))
    check("reader model string", reader.model == "Tecan Infinite 200 PRO", str(reader.model))

    # -- documented defaults --
    abs_params = TecanInfiniteAbsorbanceParams()
    check("absorbance default flashes is 25", abs_params.flashes == 25, str(abs_params.flashes))
    check("absorbance default bandwidth is auto (None)", abs_params.bandwidth is None)
    check(
        "absorbance auto-bandwidth is 9 nm above 315 nm",
        TecanInfiniteAbsorbanceBackend._auto_bandwidth(600) == 9.0,
    )
    check(
        "absorbance auto-bandwidth is 5 nm at or below 315 nm",
        TecanInfiniteAbsorbanceBackend._auto_bandwidth(300) == 5.0,
    )
    flr_params = TecanInfiniteFluorescenceParams()
    check("fluorescence default flashes is 25", flr_params.flashes == 25, str(flr_params.flashes))
    check("fluorescence default gain is 100", flr_params.gain == 100, str(flr_params.gain))
    check(
        "fluorescence default integration is 20 us",
        flr_params.integration_us == 20,
        str(flr_params.integration_us),
    )

    # -- wavelength clamps raise before any command --
    plate = tecan_compat.build_read_plate()
    wells = plate.get_all_items()[:1]
    abs_backend = reader.absorbance.backend

    def clamp_raises(wavelength: int) -> bool:
        try:
            asyncio.run(abs_backend.read_absorbance(plate=plate, wells=wells, wavelength=wavelength))
        except ValueError:
            return True
        except Exception:  # noqa: BLE001 - anything else means the clamp did not fire first
            return False
        return False

    check("absorbance rejects 100 nm (below 230)", clamp_raises(100))
    check("absorbance rejects 1200 nm (above 1000)", clamp_raises(1200))

    # -- geometry math, over a real 96-well plate, no device --
    driver: object = reader.driver
    all_wells = plate.get_all_items()
    visit = driver.scan_visit_order(all_wells, serpentine=True)
    check("scan visits every well once", len(visit) == len(all_wells), f"{len(visit)}/{len(all_wells)}")

    rows = driver.group_by_row(all_wells)
    check("plate groups into 8 rows", len(rows) == 8, str(len(rows)))
    check("each row has 12 columns", all(len(r) == 12 for _, r in rows))

    # Serpentine: even rows left-to-right, odd rows right-to-left (row 0 is first).
    row0 = [w for w in visit if w.get_row() == 0]
    row1 = [w for w in visit if w.get_row() == 1]
    check(
        "row 0 runs low-to-high column",
        [w.get_column() for w in row0] == sorted(w.get_column() for w in row0),
    )
    check(
        "row 1 runs high-to-low column (serpentine)",
        [w.get_column() for w in row1] == sorted((w.get_column() for w in row1), reverse=True),
    )

    a1_x, a1_y = driver.map_well_to_stage(all_wells[0])
    check("A1 stage coordinates are integers", isinstance(a1_x, int) and isinstance(a1_y, int))
    check("A1 stage coordinates are non-negative", a1_x >= 0 and a1_y >= 0, f"({a1_x}, {a1_y})")
    h12_x, h12_y = driver.map_well_to_stage(all_wells[-1])
    check("A1 and H12 map to different stage points", (a1_x, a1_y) != (h12_x, h12_y))

    print()
    print(f"{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())

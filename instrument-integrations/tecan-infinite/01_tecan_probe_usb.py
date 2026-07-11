"""
01_tecan_probe_usb.py - is the reader on the USB bus, and can libusb have it?

No PyLabRobot. No setup(). No motion. This is the read-only rung: it only enumerates the
bus and reports what it finds for vendor 0x0C47, product 0x8007. It never claims the
interface and never sends INIT, so it cannot move the stage.

It answers the two USB questions that decide whether the next rung's setup() can succeed:

  1. Is the reader enumerated at all (cable, power, VID/PID).
  2. Is a kernel driver already bound to it. If one is, libusb cannot claim the interface
     until that driver is detached, and 02_tecan_bringup.py's setup() would fail with a
     busy/permission error that looks like a dead instrument but is not.

It tries pyusb first, for the driver and endpoint detail, and falls back to `lsusb` so it
still gives an answer on a host whose venv is broken.

    python 01_tecan_probe_usb.py
    ./run_on_pi.sh tecan-infinite/01_tecan_probe_usb.py
"""

from __future__ import annotations

import subprocess
import sys

VENDOR_ID = 0x0C47
PRODUCT_ID = 0x8007
VP = f"{VENDOR_ID:04x}:{PRODUCT_ID:04x}"


def probe_pyusb() -> bool:
    try:
        import usb.core
        import usb.util
    except ImportError:
        return False

    try:
        dev = usb.core.find(idVendor=VENDOR_ID, idProduct=PRODUCT_ID)
    except usb.core.NoBackendError:
        print("pyusb is installed but libusb is not (NoBackendError); falling back to lsusb.")
        return False
    if dev is None:
        print(f"pyusb: no device at {VP}. Check the cable and that the reader is powered.")
        return True  # pyusb worked; it just did not find the reader

    print(f"pyusb: found {VP}")
    print(f"  bus {dev.bus}  address {dev.address}")
    try:
        print(f"  manufacturer: {usb.util.get_string(dev, dev.iManufacturer)}")
        print(f"  product:      {usb.util.get_string(dev, dev.iProduct)}")
    except Exception:  # noqa: BLE001 - string descriptors need access we may not have yet
        print("  (string descriptors unreadable without claiming the device; that is fine here)")

    for cfg in dev:
        for intf in cfg:
            n = intf.bInterfaceNumber
            try:
                active = dev.is_kernel_driver_active(n)
            except Exception as exc:  # noqa: BLE001
                active = f"unknown ({exc})"
            print(f"  interface {n}: kernel driver active = {active}")
            for ep in intf:
                direction = "IN " if ep.bEndpointAddress & 0x80 else "OUT"
                print(f"    endpoint 0x{ep.bEndpointAddress:02x} {direction}")
    print()
    print("If a kernel driver is active on the data interface, the next rung's setup() has")
    print("to detach it (libusb does this when it can) or a udev rule has to grant access.")
    return True


def probe_lsusb() -> None:
    try:
        out = subprocess.run(["lsusb"], capture_output=True, text=True, timeout=10)
    except (FileNotFoundError, subprocess.SubprocessError) as exc:
        print(f"lsusb not available ({exc}); cannot probe without pyusb either.")
        return
    hits = [ln for ln in out.stdout.splitlines() if VP in ln.lower()]
    if hits:
        print("lsusb:")
        for ln in hits:
            print(f"  {ln}")
    else:
        print(f"lsusb: no device at {VP}. Check the cable and that the reader is powered.")


def main() -> int:
    print(f"Probing for Tecan Infinite at USB {VP} (read-only, no setup, no motion)")
    print()
    if not probe_pyusb():
        print("pyusb not importable; falling back to lsusb.")
        probe_lsusb()
    return 0


if __name__ == "__main__":
    sys.exit(main())

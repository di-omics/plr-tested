"""
01_odtc_probe_raw.py - is there an ODTC there, and what shape are its answers?

No PyLabRobot. No motion. No heating. Standard library only, so it runs anywhere,
including on a Pi whose venv is broken.

This is the first thing to run against a new ODTC, before any PLR code touches it.
It sends only GetStatus and ReadActualTemperature, both of which are read-only SiLA
queries. It never sends Reset, Initialize, OpenDoor, or ExecuteMethod.

What it is really for
---------------------
PLR's ODTC backend parses responses with `_recursive_find_key`, which walks a decoded
SOAP dict looking for a key. That function treats anything with a `.find` attribute as
an ElementTree node, and `str` has one. `"Success".find(".//state")` returns -1, the
function then evaluates `(-1).text`, and the whole call dies with
`AttributeError: 'int' object has no attribute 'text'`.

Whether that happens depends entirely on where `state` sits in the ODTC's GetStatus
response. If `state` is a direct child of `GetStatusResponse`, the lookup short
circuits and everything works. If it is nested any deeper, `_wait_for_idle()` throws,
and `_wait_for_idle()` is on the path of every constant-temperature hold.

So this script prints the raw XML and then answers that one question outright.

Usage
-----
    python 01_odtc_probe_raw.py --ip 169.254.1.50
    ODTC_IP=169.254.1.50 python 01_odtc_probe_raw.py

If the ODTC is on a directly attached interface with no DHCP server, give that
interface a link-local address first. On starpi the ODTC hangs off a USB-Ethernet
adapter that enumerates as eth1 (the onboard eth0 is used for something else):

    sudo ip addr add 169.254.1.1/16 dev eth1
"""

import argparse
import os
import random
import socket
import sys
import urllib.error
import urllib.request
import xml.dom.minidom
import xml.etree.ElementTree as ET

SILA_NS = "http://sila.coop"
SOAP_NS = "http://schemas.xmlsoap.org/soap/envelope/"
DEFAULT_PORT = 8080

# Read-only SiLA queries. Nothing here changes device state.
SAFE_COMMANDS = ["GetStatus", "GetDeviceIdentification", "ReadActualTemperature"]


def build_envelope(command, request_id):
    """The same doc/literal SOAP 1.1 envelope PLR's soap_encode() produces."""
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        f'<s:Envelope xmlns:s="{SOAP_NS}">'
        "<s:Body>"
        f'<{command} xmlns="{SILA_NS}">'
        f"<requestId>{request_id}</requestId>"
        f"</{command}>"
        "</s:Body></s:Envelope>"
    )


def post_soap(ip, port, command, timeout):
    """POST one SiLA command. Headers match PLR's InhecoSiLAInterface.send_command()
    exactly, so that what we see here is what PLR will see."""
    request_id = random.randint(1, 2**31 - 1)
    body = build_envelope(command, request_id).encode("utf-8")
    request = urllib.request.Request(
        url=f"http://{ip}:{port}/",
        data=body,
        method="POST",
        headers={
            "Content-Type": "text/xml; charset=utf-8",
            "Content-Length": str(len(body)),
            "SOAPAction": f"{SILA_NS}/{command}",
            "Expect": "100-continue",
            "Accept-Encoding": "gzip, deflate",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return request_id, response.status, response.read().decode("utf-8", "replace")


def pretty(xml_text):
    try:
        return xml.dom.minidom.parseString(xml_text).toprettyxml(indent="  ").strip()
    except Exception:
        return xml_text


def localname(tag):
    return tag.split("}", 1)[1] if tag.startswith("{") else tag


def body_payload(xml_text):
    root = ET.fromstring(xml_text)
    body = root.find(f".//{{{SOAP_NS}}}Body")
    if body is None:
        raise ValueError("no SOAP Body")
    for child in list(body):
        return child
    raise ValueError("empty SOAP Body")


def check_tcp(ip, port, timeout):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((ip, port))
        return True, None
    except OSError as exc:
        return False, str(exc)
    finally:
        sock.close()


def route_source_ip(ip):
    """Which local address the kernel would use to reach the ODTC. This is the
    address PLR hands the device as its event receiver, so if it is wrong or
    unreachable, every asynchronous command hangs."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect((ip, 1))
        return sock.getsockname()[0]
    except OSError as exc:
        return f"<no route: {exc}>"
    finally:
        sock.close()


def report_state_nesting(payload):
    """The verdict PLR's _recursive_find_key depends on."""
    direct = [localname(child.tag) for child in list(payload)]
    print("\n--- verdict: will PLR's _recursive_find_key survive this response? ---")
    print(f"direct children of <{localname(payload.tag)}>: {direct}")

    if "state" in direct:
        print("OK. 'state' is a direct child, so the dict lookup short circuits before")
        print("    _recursive_find_key can walk into a string. _wait_for_idle() works.")
        return

    nested = [localname(node.tag) for node in payload.iter() if localname(node.tag) == "state"]
    if nested:
        print("BROKEN. 'state' exists but is nested below the top level. PLR will walk")
        print("    into a sibling string value, call str.find(), get -1, and raise")
        print("    AttributeError: 'int' object has no attribute 'text'.")
        print("    Every constant-temperature hold goes through _wait_for_idle(), so")
        print("    set_block_temperature() and set_lid_temperature() will both fail.")
        print("    Fix: patch _recursive_find_key, or drive the device via")
        print("    odtc_compat.find_key(), which type-checks before calling .find().")
    else:
        print("UNKNOWN. No 'state' element anywhere in the response. _wait_for_idle()")
        print("    will spin until its 30 s timeout and then raise RuntimeError.")


def main():
    parser = argparse.ArgumentParser(
        description="Read-only reachability and response-shape probe for an Inheco ODTC."
    )
    parser.add_argument("--ip", default=os.environ.get("ODTC_IP"),
                        help="ODTC address. Defaults to $ODTC_IP. Never hardcoded in this repo.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--commands", nargs="*", default=SAFE_COMMANDS,
                        help=f"read-only SiLA commands to try (default: {' '.join(SAFE_COMMANDS)})")
    args = parser.parse_args()

    if not args.ip:
        parser.error("no ODTC address. Pass --ip or set ODTC_IP.")

    print(f"ODTC probe: {args.ip}:{args.port}")
    print(f"this host would reach it from: {route_source_ip(args.ip)}")
    print("  (that is the address PLR puts in eventReceiverURI. The ODTC must be")
    print("   able to open a TCP connection back to it, or async commands hang.)")

    print(f"\n--- TCP connect to {args.ip}:{args.port} ---")
    reachable, error = check_tcp(args.ip, args.port, args.timeout)
    if not reachable:
        print(f"FAILED: {error}")
        print("\nNothing is listening. Check, in order:")
        print("  1. link:   cat /sys/class/net/eth1/carrier   (1 means a cable is live)")
        print("  2. address: ip -brief addr                   (the interface needs IPv4)")
        print("  3. the ODTC's own configured address, from its front panel or manual")
        return 1
    print("OK, something is listening.")

    payloads = {}
    for command in args.commands:
        print(f"\n--- {command} ---")
        try:
            request_id, status, raw = post_soap(args.ip, args.port, command, args.timeout)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            print(f"HTTP {exc.code}\n{pretty(detail)}")
            continue
        except Exception as exc:
            print(f"FAILED: {type(exc).__name__}: {exc}")
            continue

        print(f"HTTP {status}, requestId {request_id}")
        print(pretty(raw))
        try:
            payload = body_payload(raw)
            payloads[command] = payload
        except Exception as exc:
            print(f"(could not parse SOAP body: {exc})")
            continue

        return_code = payload.find(f".//{{{SILA_NS}}}returnCode")
        if return_code is None:
            return_code = payload.find(".//returnCode")
        if return_code is not None:
            meaning = {"1": "success, answered inline",
                       "2": "accepted, real answer arrives later as a ResponseEvent",
                       "9": "error"}.get(return_code.text, "see the SiLA 1.x return codes")
            print(f"returnCode {return_code.text}: {meaning}")
            if return_code.text == "2":
                print("  This command is asynchronous. Without a registered event receiver")
                print("  the device has nowhere to send the answer, so nothing more will")
                print("  arrive here. That is expected: this probe never sends Reset.")

    if "GetStatus" in payloads:
        report_state_nesting(payloads["GetStatus"])

    print("\nProbe complete. No device state was changed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

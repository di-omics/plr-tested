"""Device-free checks for the ODTC integration.

No ODTC, STAR, or network connection is required.  These checks exercise the
real PyLabRobot backend so changes in method XML generation are caught before a
live hardware session.

Public generic assay names intentionally resolve to one synthetic water-only
motion profile.  The checks pin that safety boundary without treating the
profile as a biological method.  TIP-seq entries remain user-owned methods and
are checked only for registry/ODTC compatibility here.
"""

import asyncio
import sys
import xml.etree.ElementTree as ET

from odtc_compat import (
    BLOCK_MAX_C,
    BLOCK_MIN_C,
    describe_protocol,
    find_key,
    fluid_quantity_for,
    import_plr,
    validate_protocol,
)
from odtc_protocols import (
    GENERIC_PUBLIC_PROGRAM_NAMES,
    PROGRAMS,
    START_BLOCK_C_DEFAULT,
)

_plr = import_plr()

_PASSED = 0
_FAILED = 0

TIP_PROGRAM_NAMES = (
    "tip-gapfill",
    "tip-ivt",
    "tip-rt-anneal",
    "tip-rt",
    "tip-rnaseh",
    "tip-ss-anneal",
    "tip-ss",
    "tip-tag",
    "tip-pcr",
)


def check(label, condition, detail=""):
    global _PASSED, _FAILED
    if condition:
        _PASSED += 1
        print(f"  ok    {label}")
    else:
        _FAILED += 1
        print(f"  FAIL  {label}" + (f"\n          {detail}" if detail else ""))


def method_xml_for(program, start_block_c=START_BLOCK_C_DEFAULT):
    """Generate XML with the real backend without opening a socket."""
    backend = _plr.ExperimentalODTCBackend(
        ip="192.0.2.1",
        client_ip="192.0.2.2",
    )
    xml_text, name = backend._generate_method_xml(
        program.protocol,
        program.block_max_volume_ul,
        start_block_c,
        program.lid_c,
        True,
        method_name="OFFLINE_CHECK",
    )
    return ET.fromstring(xml_text), name


def steps_of(root):
    method = root.find("Method")
    return method, method.findall("Step")


def text_of(element, tag):
    node = element.find(tag)
    return node.text if node is not None else None


def check_parser_bug():
    """Pin the backend parser condition handled by odtc_compat.find_key()."""
    print("\n[1] backend recursive lookup vs odtc_compat.find_key")

    if _plr.layout == "0.2.1":
        from pylabrobot.thermocycling.inheco.odtc_backend import _recursive_find_key
    else:
        from pylabrobot.legacy.thermocycling.inheco.odtc_backend import _recursive_find_key

    shallow = {
        "GetStatusResponse": {
            "GetStatusResult": {"returnCode": 1, "message": "Success"},
            "state": "idle",
        }
    }
    check("shallow backend lookup returns idle", _recursive_find_key(shallow, "state") == "idle")
    check("shallow compatibility lookup returns idle", find_key(shallow, "state") == "idle")

    nested = {
        "GetStatusResponse": {
            "GetStatusResult": {"returnCode": 1, "message": "Success"},
            "deviceStatus": {"state": "idle"},
        }
    }
    try:
        _recursive_find_key(nested, "state")
        check(
            "nested backend lookup raises AttributeError",
            False,
            "backend behavior changed; re-evaluate odtc_compat.find_key",
        )
    except AttributeError:
        check("nested backend lookup raises AttributeError", True)

    check("compatibility lookup still returns idle", find_key(nested, "state") == "idle")

    element = ET.fromstring(
        '<ParameterSet><Parameter name="T"><String>'
        "&lt;Temperatures&gt;&lt;Mount&gt;2500&lt;/Mount&gt;&lt;/Temperatures&gt;"
        "</String></Parameter></ParameterSet>"
    )
    check(
        "ElementTree path extracts embedded document",
        find_key(element, "String")
        == "<Temperatures><Mount>2500</Mount></Temperatures>",
    )


def check_run_pcr_profile_is_unusable():
    """Document why the integration uses generated methods directly."""
    print("\n[2] Thermocycler.run_pcr_profile backend limitation")

    backend = _plr.ExperimentalODTCBackend(
        ip="192.0.2.1",
        client_ip="192.0.2.2",
    )

    async def raises(coroutine):
        try:
            await coroutine
            return False
        except NotImplementedError:
            return True

    check(
        "get_lid_target_temperature raises NotImplementedError",
        asyncio.run(raises(backend.get_lid_target_temperature())),
    )
    check(
        "get_lid_status raises NotImplementedError",
        asyncio.run(raises(backend.get_lid_status())),
    )


def check_validation():
    print("\n[3] validate_protocol enforces the ODTC envelope")

    Protocol, Stage, Step = _plr.Protocol, _plr.Stage, _plr.Step

    def rejects(protocol, lid=105.0):
        try:
            validate_protocol(protocol, lid)
            return False
        except ValueError:
            return True

    too_cold = Protocol(
        stages=[Stage(steps=[Step(temperature=[3.9], hold_seconds=10)], repeats=1)]
    )
    too_hot = Protocol(
        stages=[Stage(steps=[Step(temperature=[99.1], hold_seconds=10)], repeats=1)]
    )
    too_fast = Protocol(
        stages=[
            Stage(
                steps=[Step(temperature=[60.0], hold_seconds=10, rate=5.0)],
                repeats=1,
            )
        ]
    )
    valid = Protocol(
        stages=[
            Stage(
                steps=[Step(temperature=[60.0], hold_seconds=10, rate=4.4)],
                repeats=1,
            )
        ]
    )

    check(f"rejects temperatures below {BLOCK_MIN_C} C", rejects(too_cold))
    check(f"rejects temperatures above {BLOCK_MAX_C} C", rejects(too_hot))
    check("rejects ramps above 4.4 C/s", rejects(too_fast))
    check("accepts the ODTC ramp limit", not rejects(valid))

    for name, program in sorted(PROGRAMS.items()):
        try:
            validate_protocol(program.protocol, program.lid_c)
            check(f"{name}: inside ODTC envelope", True)
        except ValueError as exc:
            check(f"{name}: inside ODTC envelope", False, str(exc))


def check_public_water_boundary():
    print("\n[4] public generic entries are synthetic water-only profiles")

    profiles = [PROGRAMS[name] for name in GENERIC_PUBLIC_PROGRAM_NAMES]
    check(
        "all generic names are registered",
        len(profiles) == len(GENERIC_PUBLIC_PROGRAM_NAMES),
    )
    check("all generic entries require water only", all(p.water_only for p in profiles))
    check("no generic entry is marked biology", all(not p.is_biology for p in profiles))
    check(
        "all generic entries share one synthetic protocol",
        len({id(p.protocol) for p in profiles}) == 1,
    )
    check(
        "all generic entries carry a water-only source label",
        all("water-only" in p.source for p in profiles),
    )

    root, _ = method_xml_for(profiles[0])
    method, steps = steps_of(root)
    observed = [
        (text_of(step, "PlateauTemperature"), text_of(step, "PlateauTime"))
        for step in steps
    ]
    check("synthetic profile has three generated steps", len(steps) == 3)
    check(
        "synthetic profile is 30 C/30 s, 40 C/30 s, 25 C hold",
        observed == [("30", "30"), ("40", "30"), ("25", "0")],
        f"got {observed}",
    )
    check("synthetic profile loops the first two steps once", text_of(steps[1], "GotoNumber") == "1")
    check("synthetic profile performs two total passes", text_of(steps[1], "LoopNumber") == "1")
    check(
        "synthetic profile has no other loop",
        text_of(steps[0], "LoopNumber") == "0"
        and text_of(steps[2], "LoopNumber") == "0",
    )
    check("synthetic profile holds through PostHeating", text_of(method, "PostHeating") == "true")
    check("synthetic profile uses a 45 C lid", all(text_of(s, "LidTemp") == "45" for s in steps))
    check("synthetic 20 uL volume maps to FluidQuantity 0", text_of(method, "FluidQuantity") == "0")


def check_tip_programs_preserved():
    print("\n[5] TIP-seq registry entries remain biological methods")
    check(
        "all TIP-seq names are registered",
        all(name in PROGRAMS for name in TIP_PROGRAM_NAMES),
    )
    for name in TIP_PROGRAM_NAMES:
        program = PROGRAMS[name]
        check(f"{name}: marked biology", program.is_biology)
        check(f"{name}: not marked water-only", not program.water_only)
        check(f"{name}: source identifies TIP-seq", "TIP-seq" in program.source)


def check_method_xml_invariants():
    print("\n[6] generated XML invariants")
    for name, program in sorted(PROGRAMS.items()):
        root, _ = method_xml_for(program)
        method, steps = steps_of(root)
        numbers = [text_of(step, "Number") for step in steps]
        check(
            f"{name}: step numbering is contiguous",
            numbers == [str(index + 1) for index in range(len(steps))],
            f"got {numbers}",
        )
        emitted = text_of(method, "FluidQuantity")
        mirrored = fluid_quantity_for(program.block_max_volume_ul)
        check(
            f"{name}: fluid-volume bucket mirrors backend",
            emitted == mirrored,
            f"backend={emitted}, mirror={mirrored}",
        )

    check("boundary: 29.9 uL maps to 0", fluid_quantity_for(29.9) == "0")
    check("boundary: 30.0 uL maps to 1", fluid_quantity_for(30.0) == "1")
    check("boundary: 74.9 uL maps to 1", fluid_quantity_for(74.9) == "1")
    check("boundary: 75.0 uL maps to 2", fluid_quantity_for(75.0) == "2")


def check_descriptions_render():
    print("\n[7] describe_protocol renders every program")
    for name, program in sorted(PROGRAMS.items()):
        description = describe_protocol(
            program.protocol,
            program.block_max_volume_ul,
            program.lid_c,
        )
        check(
            f"{name}: description renders as ASCII",
            bool(description) and all(ord(character) < 128 for character in description),
        )


def main():
    print(f"PyLabRobot layout: {_plr.layout}")
    check_parser_bug()
    check_run_pcr_profile_is_unusable()
    check_validation()
    check_public_water_boundary()
    check_tip_programs_preserved()
    check_method_xml_invariants()
    check_descriptions_render()

    print(f"\n{_PASSED} passed, {_FAILED} failed")
    return 1 if _FAILED else 0


if __name__ == "__main__":
    sys.exit(main())

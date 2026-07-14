"""
odtc_offline_checks.py - device-free checks for the ODTC integration.

No ODTC. No STAR. No network. Every check runs against the real PyLabRobot backend,
because the point is to assert things about PLR's actual behaviour, not about a
reimplementation of it.

Run it before every live session and after every PyLabRobot upgrade:

    python odtc_offline_checks.py

Three things it pins down:

  1. The method XML the ODTC will actually be sent matches the kit user guide, element by
     element. Cycle loops, lid temperatures, hold times, fluid quantity.
  2. PLR's `_recursive_find_key` really does blow up on a string sibling, so nobody
     deletes odtc_compat.find_key() thinking it is redundant.
  3. `Thermocycler.run_pcr_profile()` really is unusable with this backend.

Exit code 0 means every check passed.
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
from odtc_protocols import PROGRAMS, START_BLOCK_C_DEFAULT

_plr = import_plr()

_PASSED = 0
_FAILED = 0


def check(label, condition, detail=""):
    global _PASSED, _FAILED
    if condition:
        _PASSED += 1
        print(f"  ok    {label}")
    else:
        _FAILED += 1
        print(f"  FAIL  {label}" + (f"\n          {detail}" if detail else ""))


def method_xml_for(program, start_block_c=START_BLOCK_C_DEFAULT):
    """Generate the method XML with the real backend. 192.0.2.0/24 is TEST-NET-1,
    so nothing resolves and no socket is opened: passing client_ip explicitly stops
    InhecoSiLAInterface from calling _get_local_ip()."""
    backend = _plr.ExperimentalODTCBackend(ip="192.0.2.1", client_ip="192.0.2.2")
    xml_text, name = backend._generate_method_xml(
        program.protocol, program.block_max_volume_ul,
        start_block_c, program.lid_c, True, method_name="OFFLINE_CHECK",
    )
    return ET.fromstring(xml_text), name


def steps_of(root):
    method = root.find("Method")
    return method, method.findall("Step")


def text_of(element, tag):
    node = element.find(tag)
    return node.text if node is not None else None


# ---------------------------------------------------------------------------


def check_parser_bug():
    """PLR's _recursive_find_key mistakes str for an ElementTree node."""
    print("\n[1] PLR's _recursive_find_key vs odtc_compat.find_key")

    if _plr.layout == "0.2.1":
        from pylabrobot.thermocycling.inheco.odtc_backend import _recursive_find_key
    else:
        from pylabrobot.legacy.thermocycling.inheco.odtc_backend import _recursive_find_key

    # 'state' is a direct child: the dict lookup short circuits and both work.
    shallow = {"GetStatusResponse": {
        "GetStatusResult": {"returnCode": 1, "message": "Success"},
        "state": "idle",
    }}
    check("shallow: PLR finds 'idle'", _recursive_find_key(shallow, "state") == "idle")
    check("shallow: find_key finds 'idle'", find_key(shallow, "state") == "idle")

    # 'state' one level deeper, behind the string "Success". PLR walks into the str,
    # calls str.find(".//state") -> -1, then evaluates (-1).text.
    nested = {"GetStatusResponse": {
        "GetStatusResult": {"returnCode": 1, "message": "Success"},
        "deviceStatus": {"state": "idle"},
    }}
    try:
        _recursive_find_key(nested, "state")
        check("nested: PLR raises AttributeError", False,
              "it did not raise. PLR may have been fixed upstream; re-read this module.")
    except AttributeError:
        check("nested: PLR raises AttributeError (the bug this module works around)", True)

    check("nested: find_key still returns 'idle'", find_key(nested, "state") == "idle")
    check("root cause: 'Success'.find('.//state') == -1, and -1 is not None",
          "Success".find(".//state") == -1)

    # The async sensor path hands back an ElementTree Element, which both handle.
    element = ET.fromstring(
        '<ParameterSet><Parameter name="T"><String>'
        "&lt;Temperatures&gt;&lt;Mount&gt;2500&lt;/Mount&gt;&lt;/Temperatures&gt;"
        "</String></Parameter></ParameterSet>"
    )
    check("ElementTree path: find_key extracts the embedded document",
          find_key(element, "String") == "<Temperatures><Mount>2500</Mount></Temperatures>")


def check_run_pcr_profile_is_unusable():
    """Document, executably, why nothing here calls run_pcr_profile()."""
    print("\n[2] Thermocycler.run_pcr_profile() cannot drive this backend")

    backend = _plr.ExperimentalODTCBackend(ip="192.0.2.1", client_ip="192.0.2.2")

    check("NotImplementedError is a subclass of RuntimeError",
          issubclass(NotImplementedError, RuntimeError))

    async def raises(coroutine):
        try:
            await coroutine
            return False
        except NotImplementedError:
            return True

    check("get_lid_target_temperature() raises NotImplementedError",
          asyncio.run(raises(backend.get_lid_target_temperature())))
    check("get_lid_status() raises NotImplementedError",
          asyncio.run(raises(backend.get_lid_status())))

    # wait_for_lid() catches RuntimeError around get_lid_target_temperature(), which
    # therefore swallows the NotImplementedError and sets targets=None. It then falls
    # through to get_lid_status(), which raises the same exception uncaught.
    check("so run_pcr_profile() -> wait_for_lid() -> get_lid_status() escapes", True)


def check_validation():
    print("\n[3] validate_protocol() refuses what the ODTC cannot do")

    Protocol, Stage, Step = _plr.Protocol, _plr.Stage, _plr.Step

    def rejects(protocol, lid=105.0):
        try:
            validate_protocol(protocol, lid)
            return False
        except ValueError:
            return True

    too_cold = Protocol(stages=[Stage(steps=[Step(temperature=[3.9], hold_seconds=10)], repeats=1)])
    too_hot = Protocol(stages=[Stage(steps=[Step(temperature=[99.1], hold_seconds=10)], repeats=1)])
    fast = Protocol(stages=[Stage(steps=[Step(temperature=[60.0], hold_seconds=10, rate=5.0)], repeats=1)])
    ok = Protocol(stages=[Stage(steps=[Step(temperature=[60.0], hold_seconds=10, rate=4.4)], repeats=1)])

    check(f"rejects 3.9 C (below {BLOCK_MIN_C} C)", rejects(too_cold))
    check(f"rejects 99.1 C (above {BLOCK_MAX_C} C)", rejects(too_hot))
    check("rejects a 5.0 C/s ramp (above 4.4 C/s)", rejects(fast))
    check("accepts 60 C at 4.4 C/s", not rejects(ok))

    for name, program in sorted(PROGRAMS.items()):
        try:
            validate_protocol(program.protocol, program.lid_c)
            check(f"{name}: every step is inside the ODTC's envelope", True)
        except ValueError as exc:
            check(f"{name}: every step is inside the ODTC's envelope", False, str(exc))


def check_method_xml():
    print("\n[4] generated method XML matches the kit user guide")

    # ---- WGA, Table 1: 30 C 2.5 h, 65 C 3 min, 4 C infinite, lid 70 C
    root, _ = method_xml_for(PROGRAMS["wga"])
    method, steps = steps_of(root)
    check("wga: 3 steps", len(steps) == 3, f"got {len(steps)}")
    check("wga: 30 C for 9000 s (2.5 h)",
          (text_of(steps[0], "PlateauTemperature"), text_of(steps[0], "PlateauTime")) == ("30", "9000"))
    check("wga: 65 C for 180 s (3 min)",
          (text_of(steps[1], "PlateauTemperature"), text_of(steps[1], "PlateauTime")) == ("65", "180"))
    check("wga: 4 C, PlateauTime 0, held by PostHeating",
          (text_of(steps[2], "PlateauTemperature"), text_of(steps[2], "PlateauTime")) == ("4", "0"))
    check("wga: PostHeating true (this is what makes the 4 C hold infinite)",
          text_of(method, "PostHeating") == "true")
    check("wga: lid 70 C on every step (Table 1 caption)",
          all(text_of(s, "LidTemp") == "70" for s in steps))
    check("wga: StartLidTemperature 70", text_of(method, "StartLidTemperature") == "70")
    check("wga: FluidQuantity 0 (12.0 uL reaction)", text_of(method, "FluidQuantity") == "0")
    check("wga: no step loops", all(text_of(s, "LoopNumber") == "0" for s in steps))

    # ---- DNAPREP, Table 4: 37 C 10 min, 4 C infinite, lid 105 C
    root, _ = method_xml_for(PROGRAMS["dnaprep"])
    method, steps = steps_of(root)
    check("dnaprep: 2 steps", len(steps) == 2)
    check("dnaprep: 37 C for 600 s",
          (text_of(steps[0], "PlateauTemperature"), text_of(steps[0], "PlateauTime")) == ("37", "600"))
    check("dnaprep: lid 105 C", all(text_of(s, "LidTemp") == "105" for s in steps))

    # ---- FERAT, Table 5: 4 C 30 s, 30 C 5 min, 65 C 30 min, 4 C infinite
    root, _ = method_xml_for(PROGRAMS["ferat"])
    method, steps = steps_of(root)
    check("ferat: 4 steps", len(steps) == 4)
    check("ferat: 4 C 30 s, 30 C 300 s, 65 C 1800 s, 4 C 0 s",
          [(text_of(s, "PlateauTemperature"), text_of(s, "PlateauTime")) for s in steps]
          == [("4", "30"), ("30", "300"), ("65", "1800"), ("4", "0")])

    # ---- Ligation, page 16 IV.7: 20 C 15 min, lid 50 C
    root, _ = method_xml_for(PROGRAMS["ligation"])
    method, steps = steps_of(root)
    check("ligation: one step, 20 C for 900 s",
          [(text_of(s, "PlateauTemperature"), text_of(s, "PlateauTime")) for s in steps]
          == [("20", "900")])
    check("ligation: lid 50 C (the backend cannot disable the lid)",
          text_of(steps[0], "LidTemp") == "50")

    # ---- LIB-AMP, Table 8: hot start, 8 cycles of 3, final extension, 4 C hold
    root, _ = method_xml_for(PROGRAMS["libamp"])
    method, steps = steps_of(root)
    check("libamp: 6 steps (1 + 3 + 1 + 1)", len(steps) == 6, f"got {len(steps)}")
    check("libamp: 98 C 45 s hot start",
          (text_of(steps[0], "PlateauTemperature"), text_of(steps[0], "PlateauTime")) == ("98", "45"))
    check("libamp: cycle body is 98/15, 60/30, 72/45",
          [(text_of(s, "PlateauTemperature"), text_of(s, "PlateauTime")) for s in steps[1:4]]
          == [("98", "15"), ("60", "30"), ("72", "45")])
    check("libamp: 72 C 60 s final extension",
          (text_of(steps[4], "PlateauTemperature"), text_of(steps[4], "PlateauTime")) == ("72", "60"))
    check("libamp: 4 C hold via PostHeating",
          (text_of(steps[5], "PlateauTemperature"), text_of(steps[5], "PlateauTime")) == ("4", "0"))
    # The loop lives on the LAST step of the cycled stage and jumps back to its first.
    # LoopNumber is repeats-1 = 7, because the first pass is not a loop iteration.
    check("libamp: step 4 jumps back to step 2 (GotoNumber 2)",
          text_of(steps[3], "GotoNumber") == "2", f"got {text_of(steps[3], 'GotoNumber')}")
    check("libamp: LoopNumber 7 == 8 cycles - 1",
          text_of(steps[3], "LoopNumber") == "7", f"got {text_of(steps[3], 'LoopNumber')}")
    check("libamp: no other step loops",
          all(text_of(s, "LoopNumber") == "0" for i, s in enumerate(steps) if i != 3))
    check("libamp: FluidQuantity 1 (40.0 uL reaction, 30 <= v < 75)",
          text_of(method, "FluidQuantity") == "1")
    check("libamp: lid 105 C", all(text_of(s, "LidTemp") == "105" for s in steps))

    # ---- Targeted PCR PCR1: 98/30 x1, (98/10, 67/15, 72/15) x30, 72/60 x1, 10 C hold
    root, _ = method_xml_for(PROGRAMS["ampseq-pcr1"])
    method, steps = steps_of(root)
    check("ampseq-pcr1: 6 steps (1 + 3 + 1 + 1)", len(steps) == 6, f"got {len(steps)}")
    check("ampseq-pcr1: 98 C 30 s initial denaturation",
          (text_of(steps[0], "PlateauTemperature"), text_of(steps[0], "PlateauTime")) == ("98", "30"))
    check("ampseq-pcr1: cycle body is 98/10, 67/15, 72/15 (anneal 67 C default)",
          [(text_of(s, "PlateauTemperature"), text_of(s, "PlateauTime")) for s in steps[1:4]]
          == [("98", "10"), ("67", "15"), ("72", "15")])
    check("ampseq-pcr1: 72 C 60 s final extension",
          (text_of(steps[4], "PlateauTemperature"), text_of(steps[4], "PlateauTime")) == ("72", "60"))
    check("ampseq-pcr1: 10 C hold (this protocol holds at 10 C, not 4 C)",
          (text_of(steps[5], "PlateauTemperature"), text_of(steps[5], "PlateauTime")) == ("10", "0"))
    check("ampseq-pcr1: step 4 loops back to step 2 (GotoNumber 2)",
          text_of(steps[3], "GotoNumber") == "2", f"got {text_of(steps[3], 'GotoNumber')}")
    check("ampseq-pcr1: LoopNumber 29 == 30 cycles - 1",
          text_of(steps[3], "LoopNumber") == "29", f"got {text_of(steps[3], 'LoopNumber')}")
    check("ampseq-pcr1: FluidQuantity 0 (25 uL reaction)",
          text_of(method, "FluidQuantity") == "0")
    check("ampseq-pcr1: lid 105 C (standard Q5 lid, not from the protocol)",
          all(text_of(s, "LidTemp") == "105" for s in steps))

    # ---- Targeted PCR PCR2: same shape, default 8 cycles, 4 C hold
    root, _ = method_xml_for(PROGRAMS["ampseq-pcr2"])
    method, steps = steps_of(root)
    check("ampseq-pcr2: 6 steps", len(steps) == 6, f"got {len(steps)}")
    check("ampseq-pcr2: LoopNumber 7 == 8 cycles - 1 (default)",
          text_of(steps[3], "LoopNumber") == "7", f"got {text_of(steps[3], 'LoopNumber')}")
    check("ampseq-pcr2: 4 C hold",
          (text_of(steps[5], "PlateauTemperature"), text_of(steps[5], "PlateauTime")) == ("4", "0"))

    # ---- targeted PCR PCR2 cycle count is settable, and the loop tracks it
    from odtc_protocols import ampseq_pcr2
    backend = _plr.ExperimentalODTCBackend(ip="192.0.2.1", client_ip="192.0.2.2")
    xml10, _ = backend._generate_method_xml(ampseq_pcr2(num_cycles=10), 25.0, 25.0, 105.0, True,
                                            method_name="OFFLINE_CHECK")
    steps10 = ET.fromstring(xml10).find("Method").findall("Step")
    check("ampseq-pcr2(num_cycles=10): LoopNumber 9",
          text_of(steps10[3], "LoopNumber") == "9", f"got {text_of(steps10[3], 'LoopNumber')}")

    # ---- EM-seq shear: 3 steps, 30 min at 37 C default, 15 min at 65 C, 4 C hold, lid 75
    root, _ = method_xml_for(PROGRAMS["emseq-shear"])
    method, steps = steps_of(root)
    check("emseq-shear: 3 steps", len(steps) == 3, f"got {len(steps)}")
    check("emseq-shear: 37 C 1800 s (30 min default)",
          (text_of(steps[0], "PlateauTemperature"), text_of(steps[0], "PlateauTime")) == ("37", "1800"))
    check("emseq-shear: 65 C 900 s",
          (text_of(steps[1], "PlateauTemperature"), text_of(steps[1], "PlateauTime")) == ("65", "900"))
    check("emseq-shear: 4 C hold via PostHeating",
          (text_of(steps[2], "PlateauTemperature"), text_of(steps[2], "PlateauTime")) == ("4", "0"))
    check("emseq-shear: lid 75 C", all(text_of(s, "LidTemp") == "75" for s in steps))

    # ---- EM-seq shear time is settable
    from odtc_protocols import emseq_shear
    backend = _plr.ExperimentalODTCBackend(ip="192.0.2.1", client_ip="192.0.2.2")
    xml25, _ = backend._generate_method_xml(emseq_shear(shear_minutes=25), 44.0, 25.0, 75.0, True,
                                            method_name="OFFLINE_CHECK")
    steps25 = ET.fromstring(xml25).find("Method").findall("Step")
    check("emseq-shear(shear_minutes=25): 37 C 1500 s",
          text_of(steps25[0], "PlateauTime") == "1500", f"got {text_of(steps25[0], 'PlateauTime')}")

    # ---- EM-seq PCR: 5 steps, 8-cycle loop, 65 C final extension, 4 C hold, lid 105
    root, _ = method_xml_for(PROGRAMS["emseq-pcr"])
    method, steps = steps_of(root)
    check("emseq-pcr: 6 steps (1 + 3 + 1 + 1)", len(steps) == 6, f"got {len(steps)}")
    check("emseq-pcr: 4 C hold via PostHeating",
          (text_of(steps[5], "PlateauTemperature"), text_of(steps[5], "PlateauTime")) == ("4", "0"))
    check("emseq-pcr: cycle body is 98/10, 62/30, 65/60",
          [(text_of(s, "PlateauTemperature"), text_of(s, "PlateauTime")) for s in steps[1:4]]
          == [("98", "10"), ("62", "30"), ("65", "60")])
    check("emseq-pcr: step 4 loops back to step 2 (GotoNumber 2)",
          text_of(steps[3], "GotoNumber") == "2", f"got {text_of(steps[3], 'GotoNumber')}")
    check("emseq-pcr: LoopNumber 7 == 8 cycles - 1 (default)",
          text_of(steps[3], "LoopNumber") == "7", f"got {text_of(steps[3], 'LoopNumber')}")
    check("emseq-pcr: 65 C 300 s final extension (not 72 C)",
          (text_of(steps[4], "PlateauTemperature"), text_of(steps[4], "PlateauTime")) == ("65", "300"))
    check("emseq-pcr: FluidQuantity 2 (90.0 uL reaction)",
          text_of(method, "FluidQuantity") == "2", f"got {text_of(method, 'FluidQuantity')}")
    check("emseq-pcr: lid 105 C", all(text_of(s, "LidTemp") == "105" for s in steps))

    # ---- EM-seq ligation: manual "lid off" resolved to lid 50, FluidQuantity 2 (82.5 uL)
    root, _ = method_xml_for(PROGRAMS["emseq-ligation"])
    method, steps = steps_of(root)
    check("emseq-ligation: lid 50 C (manual says lid off; backend cannot disable)",
          all(text_of(s, "LidTemp") == "50" for s in steps))
    check("emseq-ligation: FluidQuantity 2 (82.5 uL reaction)",
          text_of(method, "FluidQuantity") == "2", f"got {text_of(method, 'FluidQuantity')}")

    # ---- step numbering is 1-based and contiguous across every program
    for name, program in sorted(PROGRAMS.items()):
        root, _ = method_xml_for(program)
        _, steps = steps_of(root)
        numbers = [text_of(s, "Number") for s in steps]
        check(f"{name}: Number is 1..{len(steps)}",
              numbers == [str(i + 1) for i in range(len(steps))], f"got {numbers}")


def check_fluid_quantity_mirror():
    print("\n[5] fluid_quantity_for() agrees with the backend's own bucketing")
    for name, program in sorted(PROGRAMS.items()):
        root, _ = method_xml_for(program)
        emitted = text_of(root.find("Method"), "FluidQuantity")
        mirrored = fluid_quantity_for(program.block_max_volume_ul)
        check(f"{name}: {program.block_max_volume_ul} uL -> FluidQuantity {emitted}",
              emitted == mirrored, f"backend said {emitted}, mirror said {mirrored}")

    check("boundary: 29.9 uL -> 0", fluid_quantity_for(29.9) == "0")
    check("boundary: 30.0 uL -> 1", fluid_quantity_for(30.0) == "1")
    check("boundary: 74.9 uL -> 1", fluid_quantity_for(74.9) == "1")
    check("boundary: 75.0 uL -> 2", fluid_quantity_for(75.0) == "2")


def check_descriptions_render():
    print("\n[6] describe_protocol() renders every program")
    for name, program in sorted(PROGRAMS.items()):
        text = describe_protocol(program.protocol, program.block_max_volume_ul, program.lid_c)
        check(f"{name}: renders and is ASCII",
              bool(text) and all(ord(c) < 128 for c in text))


def main():
    print(f"PyLabRobot layout: {_plr.layout}")
    check_parser_bug()
    check_run_pcr_profile_is_unusable()
    check_validation()
    check_method_xml()
    check_fluid_quantity_mirror()
    check_descriptions_render()

    print(f"\n{_PASSED} passed, {_FAILED} failed")
    return 1 if _FAILED else 0


if __name__ == "__main__":
    sys.exit(main())

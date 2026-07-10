"""
odtc_compat.py - PyLabRobot compatibility shim and defensive helpers for the
Inheco ODTC (On Deck Thermal Cycler).

Everything in this module is device-free. It does not move hardware and does not
heat anything. The scripts in this directory build on it.

Why this module exists
----------------------
PyLabRobot ships an ODTC backend (`ExperimentalODTCBackend`). It works, but three
things about it will bite an integrator, and all three are handled here.

1. The import path moved.
     PLR 0.2.1 (what starpi runs):  pylabrobot.thermocycling.inheco
     PLR main after the capability-composition refactor (#931):
                                    pylabrobot.legacy.thermocycling.inheco
   `import_plr()` tries the 0.2.1 layout first and falls back to the legacy layout,
   so the same script runs against either.

2. `_recursive_find_key` in the backend mistakes a `str` for an ElementTree node.
   `str.find(".//state")` is a valid call: it returns `-1`, not `None`. The backend
   then does `node.text` on the int and raises
   `AttributeError: 'int' object has no attribute 'text'`.
   Reproduced offline against real PLR code, see odtc_offline_checks.py.
   `find_key()` below is the type-checked replacement.

3. `ExperimentalODTCBackend.get_sensor_data()` catches every exception and returns
   the last cached reading, which starts out as `{}`. `get_block_current_temperature()`
   then returns `[temps.get("Mount", 0.0)]`, so a failed read reports the block as
   0.0 C. For a thermocycler that is the worst possible default. `read_sensors()`
   below raises instead.

A fourth trap, not fixable here, is documented so nobody rediscovers it:
   `Thermocycler.run_pcr_profile()` cannot be used with this backend. It calls
   `wait_for_lid()`, which calls `get_lid_target_temperature()` (backend raises
   `NotImplementedError`, a subclass of `RuntimeError`, so it is swallowed) and then
   `get_lid_status()` (also `NotImplementedError`, not swallowed). Use
   `run_protocol()` instead. PLR's own ODTC notebook uses `run_protocol()`.

Transport, in one paragraph
---------------------------
Despite the PLR docs saying "SiLA 2", the shipped implementation speaks SiLA 1.x
over SOAP/HTTP: it POSTs to `http://<odtc-ip>:8080/` with a
`SOAPAction: http://sila.coop/<Command>` header. Synchronous commands answer with
returnCode 1 and the decoded body is returned as a dict. Asynchronous commands
answer with returnCode 2, and the real answer arrives later as a `ResponseEvent`
POSTed back to an HTTP server that PLR starts on the client. That server binds to
an ephemeral port, and the port is handed to the device in the `Reset` call's
`eventReceiverURI`. Consequences:
  - The ODTC must be able to open a TCP connection back to the Pi. This is not
    optional and it is the most common reason a run hangs.
  - Because the port is new on every process, `Reset` must be re-sent every run.
    `setup()` does that.
  - An asynchronous command that never gets its callback waits forever. Every SiLA
    call in this module goes through `sila_call()`, which imposes a timeout.
  - `ExecuteMethod` is asynchronous, and its `ResponseEvent` fires when the method
    *finishes*. So `await run_protocol(...)` blocks for the whole run. A 2.5 hour
    WGA hold is a 2.5 hour await. Confirm this on the first live run.

Sources
-------
  - Block range 4 C to 99 C, ramp up to 4.4 C/s, 96-well, and the module footprint
    below: PyLabRobot user guide, "Inheco ODTC (On Deck Thermal Cycler)"
    (docs/user_guide/01_material-handling/thermocycling/inheco-odtc.ipynb, v0.2.1).
  - Everything about the SOAP transport: read out of the PLR source at v0.2.1,
    pylabrobot/storage/inheco/scila/inheco_sila_interface.py.
"""

import asyncio
import socket
import xml.etree.ElementTree as ET
from typing import Any, Dict, Optional, Tuple

# ---------------------------------------------------------------------------
# Device limits and geometry. Do not invent values here; cite them.
# ---------------------------------------------------------------------------

# PLR ODTC user guide, "Specifications".
BLOCK_MIN_C = 4.0
BLOCK_MAX_C = 99.0
MAX_RAMP_C_PER_S = 4.4

# Highest lid temperature that appears in either the PLR ODTC notebook or in
# BioSkryb TAS-068.5. Above this we warn rather than refuse, because the lid
# ceiling is not documented in either source.
DOCUMENTED_MAX_LID_C = 105.0

# PLR ODTC notebook, Thermocycler(...) constructor.
ODTC_SIZE_X_MM = 159.0
ODTC_SIZE_Y_MM = 245.0
ODTC_SIZE_Z_MM = 228.0

# TODO(geometry): the PLR notebook passes Coordinate(0, 0, 0) with the comment
# "TODO: resource modeling". It is a placeholder, not a measurement. Nothing may
# hand a plate to the ODTC with the iSWAP until this is measured on the deck the
# same way every other coordinate in this repo was measured. Treat a nonzero value
# here as unverified until a dated note says otherwise.
ODTC_CHILD_LOCATION_IS_MEASURED = False

# The ODTC SOAP endpoint. Hardcoded in PLR's InhecoSiLAInterface.send_command().
ODTC_SOAP_PORT = 8080

# An asynchronous SiLA command whose ResponseEvent never arrives waits forever.
DEFAULT_SILA_TIMEOUT_S = 30.0

# A pre-method (constant-temperature hold) pre-warms block and lid before it
# reports done. The backend's own docstring says 7 to 10 minutes.
PRE_METHOD_TIMEOUT_S = 900.0

# setup() sends Reset and then Initialize. Initialize homes the door mechanism, so
# this is a mechanical timeout, not a network one.
SETUP_TIMEOUT_S = 180.0


class OdtcError(RuntimeError):
    """Raised when the ODTC answers in a shape we refuse to guess at."""


# ---------------------------------------------------------------------------
# Import shim
# ---------------------------------------------------------------------------


class PlrOdtc:
    """The PLR symbols this integration needs, plus which layout they came from."""

    def __init__(self, layout, backend_cls, thermocycler_cls, chatterbox_cls,
                 protocol_cls, stage_cls, step_cls, sila_error_cls, coordinate_cls):
        self.layout = layout
        self.ExperimentalODTCBackend = backend_cls
        self.Thermocycler = thermocycler_cls
        self.ThermocyclerChatterboxBackend = chatterbox_cls
        self.Protocol = protocol_cls
        self.Stage = stage_cls
        self.Step = step_cls
        self.SiLAError = sila_error_cls
        self.Coordinate = coordinate_cls


_PLR_CACHE = None


def import_plr():
    """Import the ODTC symbols from whichever PLR layout is installed.

    Returns a PlrOdtc. `layout` is "0.2.1" or "legacy". Raises ImportError with a
    useful message if neither layout is present.
    """
    global _PLR_CACHE
    if _PLR_CACHE is not None:
        return _PLR_CACHE

    from pylabrobot.resources.coordinate import Coordinate

    try:
        # PLR 0.2.1, which is what the Pi has. Probe the `inheco` subpackage first:
        # on newer PLR, `pylabrobot.thermocycling` still resolves (it is a
        # deprecation shim that re-exports legacy) but `.inheco` under it does not.
        from pylabrobot.thermocycling.inheco import ExperimentalODTCBackend
        from pylabrobot.thermocycling.chatterbox import ThermocyclerChatterboxBackend
        from pylabrobot.thermocycling.standard import Protocol, Stage, Step
        from pylabrobot.thermocycling.thermocycler import Thermocycler
        from pylabrobot.storage.inheco.scila.inheco_sila_interface import SiLAError
        layout = "0.2.1"
    except ImportError:
        from pylabrobot.legacy.thermocycling.inheco import ExperimentalODTCBackend
        from pylabrobot.legacy.thermocycling.chatterbox import ThermocyclerChatterboxBackend
        from pylabrobot.legacy.thermocycling.standard import Protocol, Stage, Step
        from pylabrobot.legacy.thermocycling.thermocycler import Thermocycler
        from pylabrobot.legacy.storage.inheco.scila.inheco_sila_interface import SiLAError
        layout = "legacy"

    _PLR_CACHE = PlrOdtc(
        layout, ExperimentalODTCBackend, Thermocycler, ThermocyclerChatterboxBackend,
        Protocol, Stage, Step, SiLAError, Coordinate,
    )
    return _PLR_CACHE


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def find_key(data: Any, key: str) -> Any:
    """Depth-first search for `key` in a decoded SOAP body or an ElementTree node.

    Type-checked replacement for the backend's `_recursive_find_key`. That function
    branches on `hasattr(data, "find")`, which is true for `str`. `str.find` returns
    an int, so the caller then does `(-1).text` and dies. See the module docstring.
    """
    if isinstance(data, dict):
        if key in data:
            return data[key]
        for value in data.values():
            found = find_key(value, key)
            if found is not None:
                return found
    elif isinstance(data, (list, tuple)):
        for value in data:
            found = find_key(value, key)
            if found is not None:
                return found
    elif isinstance(data, ET.Element):
        node = data.find(f".//{key}")
        if node is not None:
            return node.text
        if str(data.tag).endswith(key):
            return data.text
    return None


def local_ip_toward(machine_ip: str) -> str:
    """The source address the kernel would pick to reach `machine_ip`.

    Same technique PLR uses to fill in `eventReceiverURI`. No packet is sent. This
    is the address the ODTC has to be able to reach back on.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect((machine_ip, 1))
        addr = sock.getsockname()[0]
    finally:
        sock.close()
    if not addr or addr.startswith("127."):
        raise OdtcError(
            f"no route to {machine_ip}: the kernel picked {addr!r} as the source "
            "address. Give the interface facing the ODTC an IPv4 address first."
        )
    return addr


# ---------------------------------------------------------------------------
# Talking to the device
# ---------------------------------------------------------------------------


def _backend_of(obj: Any) -> Any:
    return getattr(obj, "backend", obj)


async def sila_call(obj: Any, command: str,
                    timeout: float = DEFAULT_SILA_TIMEOUT_S, **kwargs) -> Any:
    """Send one SiLA command, with a timeout.

    Accepts either a Thermocycler or an ExperimentalODTCBackend.

    The timeout is the point. PLR's `send_command` awaits a future that is only
    resolved by an inbound HTTP callback from the device. If the ODTC cannot reach
    this host, or if `Reset` never registered our event receiver, that future is
    never resolved and the await hangs for the life of the process.

    Returns whatever PLR returns: a dict for synchronous commands (returnCode 1),
    an ElementTree Element for asynchronous ones (returnCode 2, answered by a
    ResponseEvent carrying `responseData`).
    """
    interface = _backend_of(obj)._sila_interface
    try:
        return await asyncio.wait_for(interface.send_command(command, **kwargs),
                                      timeout=timeout)
    except asyncio.TimeoutError as exc:
        raise OdtcError(
            f"SiLA command {command!r} timed out after {timeout:.0f} s. If the POST "
            "was accepted, the device took the command but its ResponseEvent never "
            "came back. Check that the ODTC can reach "
            f"{interface.client_ip}:{interface.bound_port} over TCP."
        ) from exc


async def setup_odtc(obj: Any, timeout: float = SETUP_TIMEOUT_S) -> None:
    """Call setup() with a timeout. Never call setup() bare.

    setup() sends Reset, which registers this process's event receiver, and then
    Initialize. Both are asynchronous SiLA commands, so both await a future that only
    an inbound callback resolves. If the ODTC cannot reach us, Reset never returns.

    PLR's `_reset_and_initialize()` wraps both in `except Exception`, which cannot help
    here: a hang is not an exception. It also means a genuine failure is downgraded to a
    printed warning and setup() "succeeds", leaving every later command to hang instead.
    Cancelling from the outside works because asyncio.CancelledError derives from
    BaseException, so the backend's `except Exception` does not swallow it.
    """
    try:
        await asyncio.wait_for(obj.setup(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        raise OdtcError(
            f"setup() did not finish within {timeout:.0f} s. Reset was probably accepted "
            "but its ResponseEvent never came back, which means the ODTC cannot open a "
            "TCP connection to this host. Check the route and any firewall."
        ) from exc


async def get_status(obj: Any, timeout: float = DEFAULT_SILA_TIMEOUT_S) -> Tuple[Any, Optional[str]]:
    """Issue GetStatus. Returns (decoded_response, state_or_None).

    GetStatus is synchronous, so no event callback is involved. It is the cheapest
    proof that the SOAP endpoint is alive, and it is safe at any time.
    """
    response = await sila_call(obj, "GetStatus", timeout=timeout)
    state = find_key(response, "state")
    if state is not None and not isinstance(state, str):
        state = str(state)
    return response, state


async def read_sensors(obj: Any, timeout: float = DEFAULT_SILA_TIMEOUT_S) -> Dict[str, float]:
    """Read every temperature sensor. Raises rather than reporting a fake 0.0 C.

    The device answers with an XML document nested inside a `<String>` element, and
    the values are hundredths of a degree Celsius (3700 means 37.00 C).

    Sensor names seen in the PLR notebook: Mount, Mount_Monitor, Lid, Lid_Monitor,
    Ambient, PCB, Heatsink, Heatsink_TEC. `Mount` is the block.
    """
    response = await sila_call(obj, "ReadActualTemperature", timeout=timeout)
    embedded = find_key(response, "String")
    if not isinstance(embedded, str) or not embedded.strip():
        raise OdtcError(
            "ReadActualTemperature returned no <String> payload. Refusing to guess "
            f"a temperature. Raw response: {response!r}"
        )

    sensors: Dict[str, float] = {}
    for child in ET.fromstring(embedded):
        if child.tag and child.text:
            try:
                sensors[child.tag] = float(child.text) / 100.0
            except ValueError:
                continue
    if not sensors:
        raise OdtcError(f"no sensor values parsed from: {embedded!r}")
    return sensors


def block_temperature(sensors: Dict[str, float]) -> float:
    """The block temperature, or an error. Never a silent default."""
    if "Mount" not in sensors:
        raise OdtcError(f"no 'Mount' sensor in reading: {sorted(sensors)}")
    return sensors["Mount"]


def format_sensors(sensors: Dict[str, float]) -> str:
    return "  ".join(f"{name}={value:.2f}C" for name, value in sorted(sensors.items()))


# ---------------------------------------------------------------------------
# Constructing the resource
# ---------------------------------------------------------------------------


def make_odtc(ip: str, name: str = "odtc", client_ip: Optional[str] = None):
    """Build a PLR Thermocycler backed by the ODTC. Does not connect; call setup().

    `client_ip` overrides the address handed to the device as its event receiver.
    Set it when the host has more than one interface and the automatic choice would
    pick the wrong one. starpi has exactly this problem: wlan0 carries the lab
    network and eth0 faces the ODTC.
    """
    plr = import_plr()
    return plr.Thermocycler(
        name=name,
        size_x=ODTC_SIZE_X_MM,
        size_y=ODTC_SIZE_Y_MM,
        size_z=ODTC_SIZE_Z_MM,
        backend=plr.ExperimentalODTCBackend(ip=ip, client_ip=client_ip),
        # Placeholder, see ODTC_CHILD_LOCATION_IS_MEASURED above.
        child_location=plr.Coordinate(0, 0, 0),
    )


def make_dry_odtc(name: str = "odtc_dry"):
    """A device-free Thermocycler for rehearsals, per this repo's dry-run rule.

    Caveat: `ThermocyclerChatterboxBackend.run_protocol()` takes only
    (protocol, block_max_volume). It rejects the ODTC-specific keywords
    (start_lid_temperature, post_heating, ...), so callers must strip them. See
    `run_protocol_kwargs()`.
    """
    plr = import_plr()
    return plr.Thermocycler(
        name=name,
        size_x=ODTC_SIZE_X_MM,
        size_y=ODTC_SIZE_Y_MM,
        size_z=ODTC_SIZE_Z_MM,
        backend=plr.ThermocyclerChatterboxBackend(),
        child_location=plr.Coordinate(0, 0, 0),
    )


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------


def fluid_quantity_for(block_max_volume_ul: float) -> str:
    """Mirror of the backend's volume bucketing, so a script can print what it sends.

    Kept in sync by odtc_offline_checks.py, which asserts against the backend's own
    generated XML rather than trusting this copy.
    """
    if block_max_volume_ul < 30.0:
        return "0"
    if block_max_volume_ul < 75.0:
        return "1"
    return "2"


def validate_protocol(protocol, lid_temperature_c: float) -> None:
    """Refuse to send a protocol the ODTC cannot physically run.

    Checks every step against the documented 4 C to 99 C block range and the
    documented 4.4 C/s ramp ceiling. Raises ValueError listing every offending step,
    not just the first, so one run of the script finds all the problems.
    """
    problems = []
    for stage_index, stage in enumerate(protocol.stages):
        if stage.repeats < 1:
            problems.append(f"stage {stage_index}: repeats={stage.repeats}, must be >= 1")
        for step_index, step in enumerate(stage.steps):
            where = f"stage {stage_index} step {step_index}"
            for temperature in step.temperature:
                if not BLOCK_MIN_C <= temperature <= BLOCK_MAX_C:
                    problems.append(
                        f"{where}: {temperature} C is outside the ODTC block range "
                        f"{BLOCK_MIN_C} to {BLOCK_MAX_C} C"
                    )
            if step.hold_seconds < 0:
                problems.append(f"{where}: hold_seconds={step.hold_seconds}, must be >= 0")
            if step.rate is not None and not 0 < step.rate <= MAX_RAMP_C_PER_S:
                problems.append(
                    f"{where}: rate={step.rate} C/s is outside (0, {MAX_RAMP_C_PER_S}]"
                )

    if lid_temperature_c > DOCUMENTED_MAX_LID_C:
        print(
            f"[warn] lid {lid_temperature_c} C is above the highest documented lid "
            f"temperature ({DOCUMENTED_MAX_LID_C} C). No source says this is legal."
        )

    if problems:
        raise ValueError("protocol is not runnable on the ODTC:\n  " + "\n  ".join(problems))


def describe_protocol(protocol, block_max_volume_ul: float, lid_temperature_c: float) -> str:
    """A human-readable rendering of exactly what will run. Print this before running."""
    lines = [
        f"lid {lid_temperature_c:.0f}C   block_max_volume {block_max_volume_ul:.1f} uL "
        f"(FluidQuantity {fluid_quantity_for(block_max_volume_ul)})",
    ]
    step_number = 1
    total_seconds = 0.0
    for stage_index, stage in enumerate(protocol.stages):
        suffix = f" x{stage.repeats}" if stage.repeats > 1 else ""
        lines.append(f"  stage {stage_index}{suffix}")
        for step in stage.steps:
            temperature = step.temperature[0]
            rate = f"  ramp {step.rate} C/s" if step.rate is not None else ""
            hold = ("hold until stopped (post_heating)" if step.hold_seconds == 0
                    else f"{step.hold_seconds:.0f} s")
            lines.append(f"    step {step_number}: {temperature:>5.1f} C  {hold}{rate}")
            step_number += 1
            total_seconds += step.hold_seconds * stage.repeats
    lines.append(f"  nominal hold time total (excludes ramps): {total_seconds / 60.0:.1f} min")
    return "\n".join(lines)


async def hold_block_and_lid(obj, block_c: float, lid_c: float,
                             dynamic_time: bool = True,
                             timeout: float = PRE_METHOD_TIMEOUT_S) -> None:
    """Bring block and lid to a constant temperature in a single pre-method.

    Why not `set_block_temperature()` then `set_lid_temperature()`:

      - Each call runs its own pre-method, and a pre-method takes 7 to 10 minutes.
        Two calls is twice the wait.
      - `set_block_temperature([30.0])` sets the lid to 105 C unless a lid target was
        already stashed on the backend. For the ResolveDNA WGA hold the lid must be
        70 C. Getting the order wrong silently bakes the plate at 105 C.

    So set both targets and run one pre-method. This reaches into the backend's
    private state, which is the price of not running two pre-methods.
    """
    backend = _backend_of(obj)
    backend._block_target_temp = block_c
    backend._lid_target_temp = lid_c
    await asyncio.wait_for(
        backend._run_pre_method(block_c, lid_c, dynamic_time=dynamic_time),
        timeout=timeout,
    )

"""Local planning-only HTTP server.

The server has no execution adapter and no instrument imports. All POST routes
enforce localhost Host, exact same-origin Origin, JSON content type, and browser
fetch-site checks. The arm route is a server-side hard refusal.
"""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from typing import Dict, Optional, Tuple
from urllib.parse import urlsplit

from . import __version__
from .planner import (
    DEFAULT_PCR_CYCLES,
    DEFAULT_THERMAL_HOLD_MINUTES,
    MAX_HARDWARE_VALIDATED_SAMPLE_COUNT,
    MAX_PLANNABLE_SAMPLE_COUNT,
    MIN_SAMPLE_COUNT,
    OBSERVED_DRY_RUNTIME_MINUTES,
    PLATE_COLUMN_COUNT,
    PLATE_WELL_COUNT,
    SampleCountError,
    plan_samples,
)
from .registry import emseq_dry_deck, release_summary


DEFAULT_PORT = 8767
MAX_REQUEST_BYTES = 4096


class PlanningHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def app_state() -> Dict[str, object]:
    return {
        "app": {
            "name": "EM-seq v2 + UltraShear bench planner",
            "version": __version__,
            "planning_only": True,
        },
        "constraints": {
            "sample_count_min": MIN_SAMPLE_COUNT,
            "sample_count_max": MAX_PLANNABLE_SAMPLE_COUNT,
            "sample_count_basis": "library_positions_only",
            "automatic_control_wells": 0,
            "conversion_controls": "lambda_and_puc19_spike_ins_per_sample",
            "plate_well_count": PLATE_WELL_COUNT,
            "plate_column_count": PLATE_COLUMN_COUNT,
            "channels_per_column": 8,
            "current_runner_sample_count_max": MAX_HARDWARE_VALIDATED_SAMPLE_COUNT,
            "current_runner_column_count_max": 1,
        },
        "runtime": {
            "observed_physical_dry_minutes": OBSERVED_DRY_RUNTIME_MINUTES,
            "default_thermal_hold_minutes": DEFAULT_THERMAL_HOLD_MINUTES,
            "default_pcr_cycles": DEFAULT_PCR_CYCLES,
            "multi_column_estimate_available": False,
        },
        "deck": emseq_dry_deck().to_dict(),
        "release": release_summary().to_dict(),
        "capabilities": {
            "hardware_execution": False,
            "network_instrument_access": False,
            "process_launch": False,
        },
    }


class PlanningHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = f"EMSeqBenchPlanner/{__version__}"

    def log_message(self, _format: str, *_args: object) -> None:
        return

    @property
    def _port(self) -> int:
        return int(self.server.server_address[1])

    @property
    def _allowed_hosts(self) -> Tuple[str, str]:
        return (f"127.0.0.1:{self._port}", f"localhost:{self._port}")

    @property
    def _allowed_origins(self) -> Tuple[str, str]:
        return (
            f"http://127.0.0.1:{self._port}",
            f"http://localhost:{self._port}",
        )

    def _base_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=()",
        )
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; connect-src 'self'; "
            "img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; "
            "form-action 'none'",
        )

    def _send_bytes(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self._base_headers()
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, code: int, payload: Dict[str, object]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self._send_bytes(code, body, "application/json; charset=utf-8")

    def _host_allowed(self) -> bool:
        return (self.headers.get("Host") or "").strip() in self._allowed_hosts

    def _require_local_host(self) -> bool:
        if self._host_allowed():
            return True
        self._send_json(
            403,
            {
                "error": "host",
                "message": "Unexpected Host header. Use this localhost app directly.",
            },
        )
        return False

    def _guard_post(self) -> bool:
        if not self._require_local_host():
            return False

        site = self.headers.get("Sec-Fetch-Site")
        if site is not None and site not in ("same-origin", "none"):
            self._send_json(
                403,
                {
                    "error": "cross-site",
                    "message": "Cross-site POST refused.",
                },
            )
            return False

        origin = (self.headers.get("Origin") or "").strip()
        if origin not in self._allowed_origins:
            self._send_json(
                403,
                {
                    "error": "cross-origin",
                    "message": "Missing or unexpected Origin header.",
                },
            )
            return False

        content_type = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip()
        if content_type != "application/json":
            self._send_json(
                415,
                {
                    "error": "content-type",
                    "message": "POST body must use application/json.",
                },
            )
            return False
        return True

    def _read_json_object(self) -> Optional[Dict[str, object]]:
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            self._send_json(
                411,
                {"error": "content-length", "message": "Content-Length is required."},
            )
            return None
        try:
            length = int(raw_length)
        except ValueError:
            self._send_json(
                400,
                {"error": "content-length", "message": "Invalid Content-Length."},
            )
            return None
        if length < 0 or length > MAX_REQUEST_BYTES:
            self._send_json(
                413,
                {"error": "request-too-large", "message": "Request body is too large."},
            )
            return None
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_json(400, {"error": "bad-json", "message": "Malformed JSON."})
            return None
        if not isinstance(payload, dict):
            self._send_json(
                400,
                {"error": "bad-json-shape", "message": "JSON body must be an object."},
            )
            return None
        return payload

    def do_GET(self) -> None:
        if not self._require_local_host():
            return
        path = urlsplit(self.path).path
        if path in ("/", "/index.html"):
            index = resources.files("emseq_app").joinpath("static").joinpath("index.html")
            self._send_bytes(200, index.read_bytes(), "text/html; charset=utf-8")
            return
        if path == "/api/state":
            self._send_json(200, app_state())
            return
        if path == "/healthz":
            self._send_json(
                200,
                {
                    "ok": True,
                    "planning_only": True,
                    "hardware_execution": False,
                },
            )
            return
        self._send_json(404, {"error": "not-found"})

    def do_POST(self) -> None:
        if not self._guard_post():
            return
        payload = self._read_json_object()
        if payload is None:
            return

        path = urlsplit(self.path).path
        if path == "/api/plan":
            try:
                plan = plan_samples(payload.get("sample_count"))  # type: ignore[arg-type]
            except SampleCountError as exc:
                self._send_json(
                    422,
                    {
                        "error": "sample-count",
                        "code": exc.code,
                        "message": str(exc),
                    },
                )
                return
            self._send_json(
                200,
                {
                    "plan": plan.to_dict(),
                    "deck": emseq_dry_deck().to_dict(),
                    "release": release_summary().to_dict(),
                    "hardware_execution": False,
                },
            )
            return

        if path == "/api/arm":
            release = release_summary()
            self._send_json(
                423,
                {
                    "error": "hardware-disabled",
                    "message": (
                        "This package is planning-only and has no hardware execution layer. "
                        + release.message
                    ),
                    "release": release.to_dict(),
                    "hardware_execution": False,
                },
            )
            return

        self._send_json(404, {"error": "not-found"})

    def do_OPTIONS(self) -> None:
        if not self._require_local_host():
            return
        self._send_json(
            405,
            {
                "error": "method-not-allowed",
                "message": "CORS preflight is not supported.",
            },
        )


def create_server(port: int = DEFAULT_PORT) -> PlanningHTTPServer:
    if isinstance(port, bool) or not isinstance(port, int) or not (0 <= port <= 65535):
        raise ValueError("port must be an integer from 0 through 65535")
    return PlanningHTTPServer(("127.0.0.1", port), PlanningHandler)


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="emseq-app",
        description="Planning-only local EM-seq v2 + UltraShear bench wizard.",
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv)

    server = create_server(args.port)
    port = server.server_address[1]
    print(f"EM-seq v2 bench planner: http://127.0.0.1:{port}")
    print("Planning only. Hardware execution is not installed and all arm requests are refused.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nPlanner stopped. No hardware process was started.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

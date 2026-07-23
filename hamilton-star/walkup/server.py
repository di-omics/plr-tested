#!/usr/bin/env python3
"""Local, gated walk-up runner for targeted PCR and ODTC choreography.

The server binds to localhost and drives real hardware through ``run_on_pi.sh``.
Builds are supplied only through an external local JSON file. Missing, empty, or
invalid configuration exposes zero runnable builds. Every configured build is
pinned by both a tag and a full commit SHA, materialized in a detached worktree,
and rejected if the tag no longer resolves to the configured SHA.

The launch path also requires same-origin JSON, an idle STAR, explicit deck
staging, and a human at the E-stop. Stop is a leg-boundary request: the leg in
flight finishes before the runner exits. That stop path is not a substitute for
the E-stop and requires a supervised hardware qualification before reliance.

Usage: ``python3 server.py`` then open http://127.0.0.1:8765.
"""

import json
import os
import queue
import re
import shlex
import signal
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath

HERE = Path(__file__).resolve().parent
HAMILTON = HERE.parent
REPO = HAMILTON.parent
HISTORY = HERE / "runs.jsonl"
PORT = int(os.environ.get("WALKUP_PORT", "8765"))
PI = os.environ.get("PI", "starpi")

# Pinned worktrees live outside the repo so they never show up as untracked
# noise in anyone's git status, and so a stray `git clean` cannot eat them.
WT_ROOT = Path(os.environ.get(
    "WALKUP_WORKTREES",
    str(Path.home() / ".cache" / "targeted-pcr-walkup" / "worktrees")))
BUILDS_FILE = Path(os.environ.get(
    "WALKUP_BUILDS_FILE",
    str(Path.home() / ".config" / "plr-tested" / "walkup-builds.json")))

BUILD_FIELDS = {
    "tag", "sha", "script", "token", "runner_match",
    "label", "legs", "record", "minutes",
}
BUILD_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
TAG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")
TOKEN_RE = re.compile(r"^[A-Z][A-Z0-9_]{3,127}$")
PATH_COMPONENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
RUNNER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


def _validate_build(key, value):
    if not isinstance(key, str) or not BUILD_KEY_RE.fullmatch(key):
        raise ValueError("build keys must match [a-z0-9][a-z0-9_-]{0,63}")
    if type(value) is not dict:
        raise ValueError(f"build {key!r} must be an object")
    fields = set(value)
    if fields != BUILD_FIELDS:
        missing = sorted(BUILD_FIELDS - fields)
        extra = sorted(fields - BUILD_FIELDS)
        raise ValueError(
            f"build {key!r} has invalid fields; missing={missing}, extra={extra}")

    for field in ("tag", "sha", "script", "token", "runner_match", "label", "record"):
        if type(value[field]) is not str:
            raise ValueError(f"build {key!r} field {field!r} must be a string")

    tag = value["tag"]
    if (not TAG_RE.fullmatch(tag) or tag.endswith((".", "/")) or "//" in tag
            or "@{" in tag or any(part in ("", ".", "..") for part in tag.split("/"))):
        raise ValueError(f"build {key!r} has an unsafe tag")
    if not SHA_RE.fullmatch(value["sha"]):
        raise ValueError(f"build {key!r} sha must be 40 lowercase hex characters")

    script = value["script"]
    script_path = PurePosixPath(script)
    script_stem = script_path.stem
    if (not script or script != script_path.as_posix() or script_path.is_absolute()
            or any(part in ("", ".", "..") for part in script_path.parts)
            or len(script_path.parts) < 2 or script_path.parts[0] != "starlab_live"
            or any(not PATH_COMPONENT_RE.fullmatch(part)
                   for part in script_path.parts[1:-1])
            or script_path.name != f"{script_stem}.py"
            or not RUNNER_RE.fullmatch(script_stem)):
        raise ValueError(
            f"build {key!r} script must be a safe starlab_live/*.py relative path")

    if not TOKEN_RE.fullmatch(value["token"]):
        raise ValueError(f"build {key!r} has an invalid confirmation token")
    runner = value["runner_match"]
    if not RUNNER_RE.fullmatch(runner) or runner != script_stem:
        raise ValueError(
            f"build {key!r} runner_match must exactly equal the safe script stem")

    for field in ("label", "record"):
        text = value[field]
        if not text.strip() or len(text) > 200 or CONTROL_RE.search(text):
            raise ValueError(f"build {key!r} field {field!r} must be 1-200 safe characters")
    for field, maximum in (("legs", 1000), ("minutes", 1440)):
        number = value[field]
        if type(number) is not int or not 1 <= number <= maximum:
            raise ValueError(
                f"build {key!r} field {field!r} must be a positive integer <= {maximum}")
    return dict(value)


def load_builds(path=BUILDS_FILE):
    """Load and validate the external build registry; any error fails closed."""
    try:
        raw = json.loads(Path(path).read_text())
    except FileNotFoundError:
        return {}, "No local build configuration is available."
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {}, f"Local build configuration is invalid: {type(exc).__name__}."

    if type(raw) is not dict or set(raw) != {"schema_version", "builds"}:
        return {}, "Local build configuration must contain schema_version and builds."
    if type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
        return {}, "Unsupported local build configuration schema."
    if type(raw["builds"]) is not dict:
        return {}, "Local build configuration builds must be an object."
    if not raw["builds"]:
        return {}, "Local build configuration contains no builds."
    try:
        builds = {
            key: _validate_build(key, value)
            for key, value in raw["builds"].items()
        }
    except ValueError as exc:
        return {}, f"Local build configuration is invalid: {exc}."
    return builds, f"Loaded {len(builds)} authorized local build(s)."


BUILDS, BUILDS_STATUS = load_builds()

# Physical items. Get these wrong and an iSWAP releases into open space.
# Order matches the deck, left to right, so the human's eye can sweep once.
DECK_ITEMS = [
    ("magnet", "MAGNET BLOCK is physically on rail35 pos2",
     "The cleanup hands the plate here. If it is missing the iSWAP opens over bare deck."),
    ("lid", "LID is parked on rail35 pos4",
     "The lid rides pos4 to the ODTC and back, twice. If it is absent, LID ON grips nothing."),
    ("nest", "ODTC nest rail20 pos1 is EMPTY and open",
     "The plate is placed into this nest. Anything already in it is a collision."),
    ("plate", "WORK PLATE is on rail35 pos0",
     "Sacrificial CellTreat 96 well. This is the plate that gets moved around."),
    ("source", "SOURCE master mix plate is on rail35 pos1",
     "Column 1 holds the mix. Dry run, so wells may be empty."),
    ("tips", "TIP RACKS loaded: p50 on rail48 pos1, p300 on rail48 pos2",
     "Dry run returns tips, so column 1 is reused. Racks must still be present."),
]

_state_lock = threading.Lock()
_run = {
    "active": False,
    "starting": False,   # claimed under _state_lock across the slow gates
    "id": None,
    "build": None,
    "proc": None,
    "started": None,
    "lines": [],
    "steps": [],
    "success": 0,
    "failed": False,
    "stopping": False,
    "exit": None,
    "samples": [],
}
_subs = []          # SSE subscriber queues
_subs_lock = threading.Lock()


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def broadcast(evt):
    payload = json.dumps(evt)
    with _subs_lock:
        dead = []
        for q in _subs:
            try:
                q.put_nowait(payload)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _subs.remove(q)


def git(*args):
    try:
        r = subprocess.run(["git", "-C", str(REPO)] + list(args),
                           capture_output=True, text=True, timeout=15)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except Exception as e:
        return 1, "", str(e)


def worktree_path(key):
    # Keyed by SHA, not tag name. If a tag is force-moved, the new sha gets a new
    # path instead of silently reusing (or rebuilding) the old one, and a run
    # already launched from the old sha keeps its tree underneath it.
    return WT_ROOT / BUILDS[key]["sha"]


def ensure_worktree(key):
    """Materialize a detached worktree pinned at this build's EXACT SHA.

    This is the safety property the whole app exists for. run_on_pi.sh rsyncs
    whatever tree it is invoked from, so invoking it from a tree that IS the
    validated commit makes "we ran the validated build" a fact rather than a
    promise. Idempotent: reuses an existing worktree already parked on the sha.

    The tag is only a convenience label. The sha in BUILDS is the pin, and a tag
    that no longer resolves to it is treated as an error, not as new truth.
    """
    b = BUILDS[key]
    tag, want = b["tag"], b["sha"]
    rc, sha, err = git("rev-list", "-n1", tag)
    if rc != 0:
        return {"ok": False, "reason": "tag-missing", "tag": tag,
                "detail": "Tag not in this repo. `git fetch --tags` first."}
    if sha != want:
        return {"ok": False, "reason": "tag-moved", "tag": tag,
                "sha": sha, "want": want,
                "detail": ("Tag %s now resolves to %s but the validated build is %s. "
                           "A ref moved under us. Refusing to run: the code behind this "
                           "tag is no longer the code that passed on hardware."
                           % (tag, sha, want))}
    wt = worktree_path(key)

    if wt.exists():
        r = subprocess.run(["git", "-C", str(wt), "rev-parse", "HEAD"],
                           capture_output=True, text=True)
        head = r.stdout.strip()
        if r.returncode == 0 and head == sha:
            # Parked on the right commit. Confirm nobody has edited inside it.
            d = subprocess.run(["git", "-C", str(wt), "status", "--porcelain"],
                               capture_output=True, text=True)
            dirty = [l for l in d.stdout.splitlines() if l.strip()]
            if dirty:
                return {"ok": False, "reason": "worktree-dirty", "tag": tag,
                        "sha": sha, "path": str(wt), "dirty": dirty[:10],
                        "detail": "The pinned worktree has local edits. It is meant to be "
                                  "read-only. Delete it and it will be rebuilt from the "
                                  "configured commit."}
            return {"ok": True, "tag": tag, "sha": sha, "path": str(wt), "fresh": False}
        # Wrong commit: rebuild rather than try to reconcile.
        subprocess.run(["git", "-C", str(REPO), "worktree", "remove", str(wt), "--force"],
                       capture_output=True, text=True)

    WT_ROOT.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        ["git", "-C", str(REPO), "worktree", "add", "--detach", str(wt), want],
        capture_output=True, text=True)
    if r.returncode != 0:
        return {"ok": False, "reason": "worktree-failed", "tag": tag,
                "detail": (r.stderr or r.stdout).strip()[:400]}
    if not (wt / "hamilton-star" / "run_on_pi.sh").exists():
        return {"ok": False, "reason": "worktree-incomplete", "tag": tag,
                "detail": "Worktree built but run_on_pi.sh is missing from it."}
    return {"ok": True, "tag": tag, "sha": sha, "path": str(wt), "fresh": True}


def _pkill_pattern(runner):
    """Return an exact full-command regex for the configured Python basename.

    Bracketing the first character keeps the remote pkill command from matching
    its own shell command line while preserving an exact match for the runner.
    """
    if not RUNNER_RE.fullmatch(runner):
        raise ValueError("unsafe runner basename")
    basename = f"[{runner[0]}]{re.escape(runner[1:])}"
    return rf"(^|/){basename}\.py([[:space:]]|$)"


def main_drift(key):
    """Informational only. How far your main checkout has wandered from the tag.

    Deliberately NOT a gate. What runs comes from the pinned worktree, so this
    cannot affect the robot. It is surfaced because it is the thing that used to
    be dangerous, and it is worth being able to see it is now inert.
    """
    tag = BUILDS[key]["tag"]
    rc, _, _ = git("diff", "--quiet", tag, "--", "hamilton-star/")
    if rc == 0:
        return {"drifted": False, "files": []}
    _, out, _ = git("diff", "--name-only", tag, "--", "hamilton-star/")
    return {"drifted": True, "files": [l for l in out.splitlines() if l.strip()]}


def tag_status(key):
    st = ensure_worktree(key)
    st["main_drift"] = main_drift(key)
    return st


def star_free():
    """Is any process already holding the STAR? Two drivers race the USB and give
    'Resource busy'. Cheaper to ask than to find out mid-transfer."""
    try:
        r = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=6", PI,
             "pgrep -af 'python.*(starlab_live|plr-tested-run)' || true"],
            capture_output=True, text=True, timeout=15)
    except Exception as e:
        return {"ok": False, "reason": "unreachable", "detail": str(e)}
    if r.returncode != 0:
        return {"ok": False, "reason": "unreachable",
                "detail": (r.stderr or "ssh failed").strip()[:300]}
    procs = [l for l in r.stdout.splitlines() if l.strip()]
    if procs:
        return {"ok": False, "reason": "in-flight", "procs": procs}
    return {"ok": True}


def _reader(proc, run_id):
    """Pump the runner's stdout. The runner already prints STEP N: banners and
    SUCCESS: lines, so the progress stream is structured for us; we only classify."""
    step_re = re.compile(r"^(STEP\s+[0-9]+[a-z]?):\s*(.+)$")
    for raw in iter(proc.stdout.readline, ""):
        line = raw.rstrip("\n")
        with _state_lock:
            if _run["id"] != run_id:
                break
            _run["lines"].append(line)
            _run["lines"] = _run["lines"][-4000:]
            kind = "log"
            m = step_re.match(line.strip())
            if m:
                kind = "step"
                _run["steps"].append(m.group(1))
            elif line.strip().startswith("SUCCESS:"):
                kind = "success"
                _run["success"] += 1
            elif re.search(r"Traceback|Error|FAILED|assert|Resource busy|No route to host",
                           line):
                kind = "error"
                _run["failed"] = True
            snap = {"success": _run["success"], "steps": len(_run["steps"])}
        broadcast({"t": "line", "kind": kind, "line": line, **snap})
    proc.stdout.close()
    rc = proc.wait()
    with _state_lock:
        if _run["id"] != run_id:
            return
        _run["active"] = False
        _run["exit"] = rc
        rec = {
            "id": run_id,
            "at": _run["started"],
            "ended": now(),
            "build": _run["build"],
            "tag": BUILDS[_run["build"]]["tag"],
            "sha": _run.get("sha"),
            "samples": _run["samples"],
            "note": _run.get("note", ""),
            "success": _run["success"],
            "steps": len(_run["steps"]),
            "exit": rc,
            "stopped": _run["stopping"],
            "failed": _run["failed"],
        }
    try:
        with HISTORY.open("a") as f:
            f.write(json.dumps(rec) + "\n")
    except OSError:
        pass
    broadcast({"t": "end", "exit": rc, "record": rec})


def start_run(key, samples, note, wt_path, sha):
    """Launch from the PINNED WORKTREE, never from the user's checkout.

    cwd is the worktree's hamilton-star/, so run_on_pi.sh rsyncs the tagged tree.
    This is the difference between "we ran the validated build" and "we ran
    whatever was on disk".
    """
    b = BUILDS[key]
    cwd = Path(wt_path) / "hamilton-star"
    cmd = ["./run_on_pi.sh", b["script"], "--confirm", b["token"]]
    run_id = uuid.uuid4().hex[:8]
    proc = subprocess.Popen(
        cmd, cwd=str(cwd), stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, bufsize=1, env=dict(os.environ),
        # New session so a stray Ctrl-C in the launching terminal cannot
        # SIGINT the runner mid-leg.
        start_new_session=True,
    )
    with _state_lock:
        _run.update({
            "active": True, "id": run_id, "build": key, "proc": proc,
            "started": now(), "lines": [], "steps": [], "success": 0,
            "failed": False, "stopping": False, "exit": None,
            "samples": samples, "note": note, "sha": sha,
        })
    threading.Thread(target=_reader, args=(proc, run_id), daemon=True).start()
    broadcast({"t": "start", "id": run_id, "build": key, "sha": sha,
               "cmd": " ".join(cmd), "cwd": str(cwd)})
    return run_id


def stop_run():
    """Leg-boundary abort. See the module docstring before changing this.

    We SIGTERM the runner on the Pi, matched on its filename. The leg currently
    in flight is a different filename and is deliberately NOT matched, so it
    completes its motion and the plate ends somewhere defined. Then no further
    legs launch because their parent is gone.
    """
    with _state_lock:
        if not _run["active"]:
            return {"ok": False, "detail": "nothing running"}
        b = BUILDS[_run["build"]]
        _run["stopping"] = True
    match = _pkill_pattern(b["runner_match"])
    broadcast({"t": "stopping"})
    try:
        # Report what pkill actually DID. An earlier cut used `|| true` and then
        # claimed "SIGTERM sent" unconditionally, so a stop that matched NOTHING
        # (wrong pattern, runner already gone, ssh up but Pi wedged) still told
        # the operator the run was stopping. That is the worst possible lie to
        # tell someone standing next to a moving arm. `echo rc:$?` carries the
        # real exit code back: 0 = signalled something, 1 = matched nothing.
        r = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=6", PI,
             f"pkill -TERM -f -- {shlex.quote(match)}; echo rc:$?"],
            capture_output=True, text=True, timeout=15)
        out = (r.stdout + r.stderr).strip()
    except Exception as e:
        return {"ok": False, "matched": False,
                "detail": f"ssh failed: {e}. The runner was NOT signalled. Use the E-stop."}

    m = re.search(r"rc:(\d+)", out)
    rc = int(m.group(1)) if m else None
    if rc == 0:
        return {"ok": True, "matched": True,
                "detail": "SIGTERM sent to the runner. The leg in flight finishes, then "
                          "it stops. Watch the deck."}
    if rc == 1:
        return {"ok": False, "matched": False,
                "detail": "pkill matched NOTHING on the Pi. Nothing was signalled. Either "
                          "the runner already exited, or it is not named what we expect. "
                          "If the arm is still moving, use the E-stop now."}
    return {"ok": False, "matched": False,
            "detail": "Could not confirm the stop (pkill rc=%s, output %r). Assume it did "
                      "NOT stop. Use the E-stop." % (rc, out[:160])}


def history(n=25):
    if not HISTORY.exists():
        return []
    out = []
    try:
        for line in HISTORY.read_text().splitlines()[-n:]:
            if line.strip():
                out.append(json.loads(line))
    except (OSError, json.JSONDecodeError):
        pass
    return list(reversed(out))


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        raw = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/index"):
            p = HERE / "index.html"
            if not p.exists():
                return self._send(500, "index.html missing", "text/plain")
            return self._send(200, p.read_bytes(), "text/html; charset=utf-8")

        if self.path == "/api/state":
            with _state_lock:
                active = _run["active"]
                snap = {
                    "active": active,
                    "build": _run["build"],
                    "success": _run["success"],
                    "steps": len(_run["steps"]),
                    "stopping": _run["stopping"],
                    "exit": _run["exit"],
                }
            builds = {}
            for k in BUILDS:
                builds[k] = {**{kk: vv for kk, vv in BUILDS[k].items()
                                if kk not in ("proc",)},
                             "tag_status": tag_status(k)}
            return self._send(200, json.dumps({
                "run": snap,
                "builds": builds,
                "build_config": {
                    "path": str(BUILDS_FILE),
                    "loaded": bool(BUILDS),
                    "status": BUILDS_STATUS,
                },
                "deck": [{"key": k, "label": l, "why": w} for k, l, w in DECK_ITEMS],
                "pi": PI,
                "history": history(),
            }))

        if self.path == "/api/star":
            return self._send(200, json.dumps(star_free()))

        if self.path == "/api/stream":
            q = queue.Queue(maxsize=1000)
            with _subs_lock:
                _subs.append(q)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            try:
                while True:
                    try:
                        item = q.get(timeout=15)
                        self.wfile.write(f"data: {item}\n\n".encode())
                    except queue.Empty:
                        self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                with _subs_lock:
                    if q in _subs:
                        _subs.remove(q)
            return

        return self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        # GATE 0 -- the request must come from THIS page.
        #
        # Binding to 127.0.0.1 stops remote TCP. It does NOT stop the operator's
        # own browser from being made to POST here by any other tab. Without this
        # guard, any page open anywhere runs
        #
        #   fetch('http://127.0.0.1:8765/api/run', {method:'POST', mode:'no-cors',
        #         body: '{"build":"1col","deck":[...all six...],"present":true}'})
        #
        # which is a CORS *simple request*: no preflight, the browser sends it,
        # and gates 3 and 4 happily read `deck` and `present` out of a body that
        # no human ever filled in. The arm starts with nobody at the E-stop.
        # Worst of all, the sibling targeted_pcr-run-app*.html sims are documented as
        # safe to publish: publish one, open it while this is running, and it
        # fires the real STAR. Found by adversarial review 2026-07-16.
        #
        # Three independent layers, each sufficient on its own:
        site = self.headers.get("Sec-Fetch-Site")
        if site is not None and site not in ("same-origin", "none"):
            return self._send(403, json.dumps({
                "error": "cross-site",
                "message": "Cross-site POST refused. Use the walk-up page itself."}))
        origin = self.headers.get("Origin")
        allowed = {"http://127.0.0.1:%d" % PORT, "http://localhost:%d" % PORT}
        if origin is not None and origin not in allowed:
            return self._send(403, json.dumps({
                "error": "cross-origin",
                "message": "Cross-origin POST refused. Use the walk-up page itself."}))
        # Requiring JSON removes the simple-request path entirely: a simple
        # request can only send text/plain, form-urlencoded, or multipart, so a
        # cross-origin fetch must preflight, and this server answers no preflight.
        # Never add Access-Control-Allow-Origin here; it would undo this layer.
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip()
        if ctype != "application/json":
            return self._send(415, json.dumps({
                "error": "content-type", "message": "POST must be application/json."}))
        # Host check closes DNS rebinding, which would otherwise present a
        # same-origin-looking request.
        host = (self.headers.get("Host") or "").strip()
        if host not in {"127.0.0.1:%d" % PORT, "localhost:%d" % PORT}:
            return self._send(403, json.dumps({
                "error": "host", "message": "Unexpected Host header."}))

        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return self._send(400, json.dumps({"error": "bad json"}))

        if self.path == "/api/stop":
            return self._send(200, json.dumps(stop_run()))

        if self.path == "/api/run":
            key = body.get("build")
            if key not in BUILDS:
                return self._send(400, json.dumps({"error": "unknown build"}))

            # CLAIM THE SLOT ATOMICALLY, BEFORE the gates.
            #
            # The gates below take seconds (ssh to the Pi, git worktree work) and
            # this is a ThreadingHTTPServer, so two POSTs land concurrently. An
            # earlier cut checked _run["active"], released the lock, ran the slow
            # gates, and only then launched. Both requests passed the check and
            # both launched: two drivers on one STAR, which is the "Resource busy"
            # failure at best and two runners fighting over the arm at worst.
            # The claim must be taken under the same lock as the check.
            with _state_lock:
                if _run["active"] or _run.get("starting"):
                    return self._send(409, json.dumps({
                        "error": "busy",
                        "message": "A run is already in flight or starting. Only one "
                                   "driver may hold the STAR."}))
                _run["starting"] = True
            try:
                # GATE 1 -- the tag pin. Materialize the tag in its own worktree
                # and run from there. Not bypassable, and not dependent on what
                # the user's checkout happens to be doing. The point of the app.
                ts = ensure_worktree(key)
                if not ts["ok"]:
                    return self._send(412, json.dumps({
                        "error": "tag-pin", "detail": ts,
                        "message": "Could not pin the tag to a clean worktree, so there "
                                   "is no guarantee the validated build is what would "
                                   "run. Refusing to launch."}))

                # GATE 2 -- nobody else on the USB.
                sf = star_free()
                if not sf["ok"]:
                    return self._send(412, json.dumps({
                        "error": "star", "detail": sf,
                        "message": "The STAR is not free, or the Pi is unreachable."}))

                # GATE 3 -- every deck item confirmed by a human who looked.
                # The UI disables the button, but the UI is just JavaScript and a
                # POST can be sent by hand. The gate that counts is this one.
                checked = set(body.get("deck") or [])
                missing = [k for k, _, _ in DECK_ITEMS if k not in checked]
                if missing:
                    return self._send(412, json.dumps({
                        "error": "deck", "missing": missing,
                        "message": "Deck staging not fully confirmed."}))

                # GATE 4 -- a human is standing there.
                if body.get("present") is not True:
                    return self._send(412, json.dumps({
                        "error": "present",
                        "message": "Nobody has confirmed they are at the deck."}))

                samples = [s.strip() for s in (body.get("samples") or []) if s.strip()]
                run_id = start_run(key, samples, (body.get("note") or "").strip(),
                                   ts["path"], ts["sha"])
                return self._send(200, json.dumps({
                    "ok": True, "id": run_id, "sha": ts["sha"], "tag": ts["tag"]}))
            finally:
                # start_run has already set active=True under the lock, so
                # releasing the claim here cannot open a window.
                with _state_lock:
                    _run["starting"] = False

        return self._send(404, json.dumps({"error": "not found"}))


def main():
    if not (HAMILTON / "run_on_pi.sh").exists():
        sys.exit("run_on_pi.sh not found. Run this from inside the repo.")
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)   # localhost only, on purpose
    print("")
    print("  walk-up runner  ->  http://127.0.0.1:%d" % PORT)
    print("  repo: %s" % REPO)
    print("  pi:   %s" % PI)
    print("  builds: %s" % BUILDS_STATUS)
    print("  config: %s" % BUILDS_FILE)
    print("")
    print("  This drives the real arm. Bound to localhost only. Do not expose it.")
    print("  A human stays at the deck, hand near the E-stop.")
    print("")
    print("  DO NOT Ctrl-C THIS WHILE A RUN IS IN FLIGHT.")
    print("  run_on_pi.sh runs a FOREGROUND ssh (its own header, lines 22-23, says to")
    print("  launch detached for long runs; it does not). Killing this server kills")
    print("  that ssh, which SIGHUPs the remote python and can stop the arm MID-LEG,")
    print("  stranding the plate. Same is true if the laptop sleeps or wifi drops.")
    print("  This is inherited from run_on_pi.sh, not introduced here, and it is the")
    print("  top open issue. Use Stop in the UI, or the E-stop.")
    print("")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        with _state_lock:
            live = _run["active"]
        if live:
            print("\n  *** A RUN WAS IN FLIGHT. The ssh it owned has just died with this")
            print("      process, which may have stopped the arm mid-leg. GO LOOK AT THE")
            print("      DECK NOW. If the plate is stranded, see starlab_live/recover_*.py")
        else:
            print("\n  server down. No run was in flight.")


if __name__ == "__main__":
    main()

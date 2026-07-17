#!/usr/bin/env python3
"""
Walk-up runner for the ampseq + ODTC choreography. Local, stdlib only.

WHAT THIS IS
  A gated front end for run_on_pi.sh, so a non-programmer can start a validated
  choreography without a terminal. It does NOT re-derive geometry, does NOT
  replace the runner, and does NOT invent protocol values. It orchestrates the
  same command you would type by hand, with the hand-typed safety steps turned
  into gates that cannot be skipped.

WHAT THIS IS NOT
  Not a simulator. The sibling files hamilton-star/ampseq-run-app*.html are
  visual sims badged SIMULATION and cannot reach the Pi. This one really drives
  the arm. Do not publish it, do not expose it off localhost, and do not let the
  SIMULATION habit carry over: when this says RUNNING, metal is moving.

THE FRICTION IS THE FEATURE
  Every gate below exists because something went wrong once. The confirm token
  --confirm RUN_AMPSEQ_ODTC_LIDDED_FULL is not auto-filled into a Run button.
  It is released only after four gates pass:
    0. SAME ORIGIN  the POST came from this page, not some other browser tab.
    1. SHA PIN      the validated commit, materialized to its own worktree.
    2. STAR FREE    no other process may hold the USB.
    3. DECK STAGED  every physical item confirmed by a human who looked.
    4. PRESENT      explicit affirmation, hand near the E-stop, hold to arm.
  Removing any of these turns this into the thing the operator asked it not to be.
  Gate 0 is not paranoia: without it, ANY page in ANY tab can POST here and forge
  gates 3 and 4, because they are just JSON fields. Found by review, see README.

WHY THE TAG PIN MATTERS MOST, AND HOW IT IS DONE
  run_on_pi.sh rsyncs the LOCAL WORKING TREE, not a commit. Parallel sessions
  land on main constantly (5 landed overnight 07-15/16, one of which would have
  driven 8 tips into the plate). Running "the latest code" is how you ship a
  tip-crusher.

  The first cut of this file only CHECKED that the tree matched the tag and
  blocked otherwise. That was wrong in practice: on main the check fires every
  single time (main's run_on_pi.sh legitimately differs from the tagged one), and
  a gate that always fires is a gate people learn to route around.

  So this does not nag, it removes the hazard structurally. Each build gets its
  own detached git worktree materialized at its EXACT SHA (not its tag name: tags
  are mutable and this repo force-rewrites refs), and run_on_pi.sh is invoked from
  inside that worktree. rsync therefore ships the validated tree, byte for byte,
  no matter what your main checkout is doing. Consequences:
    - You never check out a tag and never have to remember to go back to main.
    - Parallel chats can keep landing on main mid-run. It cannot reach the robot.
    - A tag that has been moved off the validated sha is refused, not obeyed.
    - What ran is recorded as a sha, not a promise.

ABORT SEMANTICS -- READ THIS
  Aborting mid-leg strands the plate wherever that leg left it (it has happened;
  a plate sat in the ODTC nest). The clean stop is BETWEEN legs. Stop here sends
  SIGTERM to the RUNNER process on the Pi only, matched on the runner filename.
  The leg child has a different filename and is not matched, so the leg in flight
  finishes its motion, and no further legs launch. That is a leg-boundary abort.

  THIS ABORT PATH HAS NOT BEEN EXERCISED ON HARDWARE. It is reasoned from the
  runner's structure (subprocess.run per leg, parent blocks in wait) and not yet
  proven. Give it one supervised shakeout before trusting it. Until then the
  E-stop remains the real stop, which is why a human stands at the deck.

usage:  python3 server.py            # then open http://127.0.0.1:8765
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
from pathlib import Path

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
    str(Path.home() / ".cache" / "ampseq-walkup" / "worktrees")))

# The two builds that have actually passed on hardware. Nothing else is offered.
# Adding an entry here is a claim that it is validated; do not add speculatively.
BUILDS = {
    "1col": {
        "tag": "ampseq-lidded-inwellmix-2026-07-16",
        # The tag NAME is not the pin. A tag is a mutable ref, and this repo
        # force-rewrites refs; a moved tag would resolve to unvalidated code and
        # the app would cheerfully call it "validated". The sha IS the pin. If
        # the tag stops resolving to this, the app refuses rather than guesses.
        "sha": "2bd1b00695b17786566d5049fac87e5ebed1fc1d",
        "script": "starlab_live/run_ampseq_odtc_LIDDED_1col_full_dry.py",
        "token": "RUN_AMPSEQ_ODTC_LIDDED_FULL",
        "runner_match": "run_ampseq_odtc_LIDDED_1col_full_dry",
        "label": "1 column - 8 reactions",
        "legs": 13,   # the runner's STEPS list. progress divides by this.
        "record": "13/13 clean, twice",
        "minutes": 18,
    },
    "4col": {
        "tag": "ampseq-lidded-4col-dry-2026-07-16",
        "sha": "6998eb46e262f31052fbae72fa8a2cffb71ee347",
        "script": "starlab_live/run_ampseq_odtc_LIDDED_4col_full_dry.py",
        "token": "RUN_AMPSEQ_ODTC_LIDDED_4COL",
        "runner_match": "run_ampseq_odtc_LIDDED_4col_full_dry",
        "label": "4 columns - 32 reactions",
        "legs": 13,   # the runner's STEPS list. progress divides by this.
        "record": "50 SUCCESS / 0 fail, twice",
        "minutes": 42,
    },
}

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
    return WT_ROOT / BUILDS[key]["sha"][:12]


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
                "sha": sha[:7], "want": want[:7],
                "detail": ("Tag %s now resolves to %s but the validated build is %s. "
                           "A ref moved under us. Refusing to run: the code behind this "
                           "tag is no longer the code that passed on hardware."
                           % (tag, sha[:7], want[:7]))}
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
                        "sha": sha[:7], "path": str(wt), "dirty": dirty[:10],
                        "detail": "The pinned worktree has local edits. It is meant to be "
                                  "read-only. Delete it and it will be rebuilt from the tag."}
            return {"ok": True, "tag": tag, "sha": sha[:7], "path": str(wt), "fresh": False}
        # Wrong commit: rebuild rather than try to reconcile.
        subprocess.run(["git", "-C", str(REPO), "worktree", "remove", str(wt), "--force"],
                       capture_output=True, text=True)

    WT_ROOT.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        ["git", "-C", str(REPO), "worktree", "add", "--detach", str(wt), tag],
        capture_output=True, text=True)
    if r.returncode != 0:
        return {"ok": False, "reason": "worktree-failed", "tag": tag,
                "detail": (r.stderr or r.stdout).strip()[:400]}
    if not (wt / "hamilton-star" / "run_on_pi.sh").exists():
        return {"ok": False, "reason": "worktree-incomplete", "tag": tag,
                "detail": "Worktree built but run_on_pi.sh is missing from it."}
    return {"ok": True, "tag": tag, "sha": sha[:7], "path": str(wt), "fresh": True}


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
    match = b["runner_match"]
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
             f"pkill -TERM -f {shlex.quote(match)}; echo rc:$?"],
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
        # Worst of all, the sibling ampseq-run-app*.html sims are documented as
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

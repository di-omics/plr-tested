# walk-up runner

A gated front end for the validated ampseq + ODTC choreography, so a person who
does not use a terminal can start a run. Local, stdlib only, no dependencies.

```bash
cd hamilton-star/walkup
python3 server.py
# open http://127.0.0.1:8765
```

## Status: DO NOT USE FOR A RUN THAT MATTERS. NOT YET RUN ON HARDWARE.

Built 2026-07-16. An adversarial review the same night raised 13 attacks and
**12 survived refutation, 3 of them critical**. The three criticals are fixed and
the fixes are verified locally. One serious issue is NOT fixed (see below), the
launch and abort paths have **never driven the arm**, and the Pi was unreachable
from this machine when it was written, so nothing here has met hardware.

Use the command line for tomorrow, and for anything that matters, until this has
had a supervised shakeout:

```bash
cd /Users/DiLoaner/Downloads/plr-tested
git checkout ampseq-lidded-inwellmix-2026-07-16
cd hamilton-star
./run_on_pi.sh starlab_live/run_ampseq_odtc_LIDDED_1col_full_dry.py \
  --confirm RUN_AMPSEQ_ODTC_LIDDED_FULL
cd .. && git checkout main
```

That command is the thing this app automates. It has four clean passes behind it.
The app has none.

## This is not a simulator

`hamilton-star/ampseq-run-app*.html` are visual sims: badged SIMULATION, cannot
reach the Pi, safe to publish. **This one really drives the arm.** It binds to
127.0.0.1 on purpose. Do not expose it, do not publish it, do not port-forward it.
A published page must never be able to fire a robot.

## What it does about the four hazards

**1. Running the wrong code (the big one).**
`run_on_pi.sh` rsyncs the working tree, not a commit, and main moved five times
overnight on 07-15/16 without anyone touching it. One of those commits would have
driven 8 tips into the plate.

The app does not ask you to check out a tag and remember to go back. It creates a
detached git worktree parked on the tag under
`~/.cache/ampseq-walkup/worktrees/<tag>/` and invokes `run_on_pi.sh` from inside
it. rsync therefore ships the tagged tree byte for byte. Your checkout is never
touched, never consulted, and parallel sessions can keep landing on main mid-run
without reaching the robot. The sha that ran is written to the history.

An earlier cut only *checked* that your tree matched the tag and blocked
otherwise. That was wrong: on main the check fires every single time, because
main's `run_on_pi.sh` legitimately differs from the tagged one, and a gate that
always fires is a gate people learn to route around.

**2. Firing with nobody at the deck.**
Four gates, all enforced server side. The UI disables the button, but the UI is
just JavaScript and a POST can be sent by hand, so the gate that counts is in
`server.py`:

| gate | what it means |
|---|---|
| tag pin | the tag materialized to a clean worktree |
| star free | `pgrep` on the Pi says nobody holds the USB |
| deck staged | all six physical items confirmed by a human who looked |
| present | explicit affirmation, plus a 2 second hold on the button |

The confirm token `--confirm RUN_AMPSEQ_ODTC_LIDDED_FULL` is **not** auto-filled
into a one-click button. It is released only once all four pass. The 2 second
hold is what replaces typing it. The friction was re-expressed, not removed.

**3. Two drivers on one STAR.**
The slot is claimed under `_state_lock` *before* the slow gates (ssh, git) run,
not after. An earlier cut checked `active`, released the lock, spent seconds in
the gates, then launched, so two concurrent POSTs both passed and both launched.
Proven fixed: concurrent requests give one 409 and one gate failure.

**4. Aborting mid-leg.**
Aborting mid-leg strands the plate wherever the leg left it. It has happened: a
plate sat in the ODTC nest. The clean stop is between legs.

Stop sends SIGTERM to the **runner** process on the Pi, matched on the runner's
filename. The leg in flight has a different filename and is deliberately not
matched, so it finishes its motion and the plate ends somewhere defined; then no
further legs launch because their parent is gone.

**This is reasoned from the runner's structure, not proven on hardware.** Until it
has had a supervised shakeout, the E-stop is the real stop. If a plate does get
stranded, `starlab_live/recover_*.py` brings it home.

## Adversarial review, 2026-07-16: 13 raised, 12 confirmed

### Fixed and verified

**CRITICAL. Any web page in any tab could fire the arm (CSRF).**
`/api/run` checked no Origin. Binding to 127.0.0.1 stops remote TCP but not the
operator's own browser. A `mode:'no-cors'` POST is a CORS *simple request*: no
preflight, and gates 3 and 4 read `deck` and `present` straight out of the
attacker's JSON. The gates that assert "a human looked at the deck" were fields
in a request no human sent. The sting: the sibling sim pages are documented as
safe to publish, so publishing one and opening it while this server ran would
have fired the real STAR. Fixed with Gate 0 (Sec-Fetch-Site + Origin + required
`application/json` + Host). Verified: the reviewer's exact payload now gets 403
on every vector, and the real UI still passes.

**CRITICAL. The "tag pin" pinned a mutable ref.**
`BUILDS` held only a tag NAME and `ensure_worktree` resolved it at run time, in a
repo whose refs get force-rewritten. A moved tag would have materialized
unvalidated code that the app then called validated. Fixed: `BUILDS` now records
the exact sha, a tag that no longer resolves to it is refused (`tag-moved`), and
the worktree path is keyed by sha so a moved tag cannot reuse the old path.

**CRITICAL. `main()` told the operator a lie.** It printed "Ctrl-C here does not
stop a run in flight". The opposite is true (see below). Now it says so, and
Ctrl-C during a live run prints a GO LOOK AT THE DECK warning.

**Stop reported success when it had done nothing.** `pkill ... || true` swallowed
the exit code and `stop_run` claimed "SIGTERM sent" unconditionally, even when it
matched nothing. That is the worst possible lie to tell someone standing next to
a moving arm. Now the real `rc` comes back and a no-match says so and points at
the E-stop.

**Two drivers on one STAR.** The `active` check released the lock before the slow
gates (ssh, git), so two concurrent POSTs both passed and both launched. Fixed
with a claim taken under the same lock. Verified: concurrent POSTs give one 409.

**Stored XSS.** Sample IDs arrived over a POST and were rendered back through
`innerHTML` unescaped, in a page that can fire a robot. Now escaped.

### NOT fixed. This is the blocking issue.

**Killing this server can stop the arm MID-LEG and strand the plate.**
`run_on_pi.sh:66` is a bare foreground `ssh` with no `nohup`/`setsid`. Its own
header, lines 22-23, says: *"For long runs, launch detached on the Pi so that a
dropped SSH session cannot interrupt the arm mid-transfer."* It does not do that,
and neither does this app. So Ctrl-C, a crash, a laptop sleep, or a wifi drop
kills the ssh, which SIGHUPs the remote python and can stop it mid-motion. Rule 5
says mid-leg abort strands the plate, and it has happened before.

This hazard is **inherited from `run_on_pi.sh`, not introduced here** - the
command-line path has it too. But this app invites longer unattended-ish sessions
in front of a browser, so it makes the hazard easier to hit.

The fix is to launch detached on the Pi and tail a logfile instead of holding the
pipe. That changes the execution model, so it needs hardware to prove. Until then
the warning in `main()` is the mitigation, which is not a mitigation.

**Also open:** a dropped ssh makes the server declare the run finished while the
arm may still be moving, which also disarms Stop. Same root cause.

## Adding a build

`BUILDS` in `server.py`. Adding an entry is a claim that the build is validated on
hardware. Do not add speculatively: the point of the list is that everything in it
has a record.

## Requirements

- The laptop must be on the lab network. `starpi` resolves via mDNS
  (`starpi.local`); there is also a `starpi-ip` alias in `~/.ssh/config`. From
  off-network both fail and every gate fails closed, which is correct but means
  you cannot demo from a coffee shop.
- Python 3.9+. No pip installs.

## Files

```
server.py    gates, worktree pin, launch, SSE progress, leg-boundary stop, history
index.html   the UI. deck checklist is the gate, not decoration
runs.jsonl   append-only history: tag, sha, samples, success count, exit
```

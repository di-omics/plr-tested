# iswap-move

iSWAP plate and lid moves for the Hamilton STAR, with the deck geometry confirmed on the
instrument.

Moving a plate lid off and back on (de-lid / lid-on) is a small motion the whole rest of
an automated run leans on: you lid a plate to carry it or park it, and de-lid it to
pipette. This package takes the tuned lid recipe that was walked in on the STAR and turns
it into a small, tested, reusable form, so any protocol can ask for a lid move without
re-teaching the arm.

It is a planning-and-run-card package, the same shape as the others in this repo: the
tuned motion lives in `hamilton-star/starlab_live/test_iswap_lid_variable.py`; this
package encodes the confirmed geometry, validates a move against the lessons learned
teaching it, and in hardware mode resolves the move to the exact Pi command. It does not
reimplement the motion.

## The confirmed recipe

Walked in on the instrument, 2026-07-12, multiple clean successes, both directions:

| | source | dest | pickup z | drop z |
| --- | --- | --- | --- | --- |
| lid-on | rail35 pos4 (lid park) | rail35 pos0 (work) | +9 mm | +18 mm |
| de-lid | rail35 pos0 (work) | rail35 pos4 (lid park) | +9 mm | +18 mm |

Same offsets both ways (the z-geometry is position-independent for this carrier and
labware), so lid-on and de-lid are one recipe reversed and they chain into a hands-free
cycle. The offsets are slot- and lid-specific, not global defaults. See
`configs/confirmed_offsets.yaml`.

## Use it

```bash
# from packages/iswap-move/
pip install -e .            # stdlib-only core; adds the `iswap-move` command

iswap-move plan             # print the dry (coordinate-only) commands, no motion
iswap-move lid-on           # simulate the confirmed park -> work lid-on
iswap-move cycle --hardware # print the arming run card for lid-on then de-lid
```

Or from Python:

```python
from iswap_move import confirmed_lid_on, Runner, Mode
r = Runner(Mode.HARDWARE)
r.lid_move(confirmed_lid_on())
print(r.run_card())   # the exact Pi commands to run
```

Also runnable as `python -m iswap_move ...`. Run the tests with `pytest` (10 offline).

## The safety lessons are validation, not comments

Teaching this move taught two things, and the package enforces both:

- **Prefer too high over too low.** A lid pickup driven too low crashes the Z drive into
  the plate (firmware "drive locked"); too high cleanly misses ("plate not found"). The
  `move_lid` computed grip (offset 0) is the truth and is only nudged in small steps. A
  pickup-z offset below the floor is refused unless you explicitly override it while
  watching.
- **A move needs a real source and dest.** Source must hold a lid, dest must hold a
  plate, and a move to the same slot is rejected.

In hardware mode the runner will not emit an arming command for a move that fails
validation; it emits the dry (coordinate-print) command instead so you can inspect it.
The arming command carries the script's own `--confirm RUN_LID_MOVE` gate, so nothing
moves by accident and a person watches with a hand on the E-stop.

## What is not taught yet

Deck-to-deck lid moves (rail35 pos4 <-> pos0) are confirmed. Lidding or de-lidding a
plate seated **inside the ODTC** is a different geometry and is not taught; it is marked
TODO (`core.ODTC_LID_GEOMETRY`) and a move that depends on it must not run for real until
it is walked in on the instrument.

## Layout

```
iswap_move/
  core.py     the confirmed geometry, provenance (CONFIRMED / TUNABLE / TODO), the
              move types, and validation (the safety lessons as checks)
  runner.py   simulation vs hardware; resolves a move to a dry or an arming run card
  cli.py      iswap-move plan | lid-on | de-lid | cycle
configs/      confirmed_offsets.yaml (the geometry, auditable)
tests/        10 offline tests
```

# next-steps: reading Rhodamine B, and the STAR iSWAP handoff

Front-loaded plan for the two things after bring-up. Nothing here has run. Values that are
physical constants are cited as such; values that are reader settings to tune on the
instrument are marked `TUNE`; anything that has to come from the ladder definition rather
than be invented is marked `FROM plr-epigenome`.

---

## A. Reading Rhodamine B on the Tecan Infinite

### Why Rhodamine B is the QC dye

Rhodamine B is the closed-loop check that the STAR dispensed what it claims. The STAR lays
down a known pattern of the dye, the reader quantifies every well, and the two are compared:
linearity, well-to-well CV, and no missed wells. It is a good QC dye because it is cheap,
bright, reasonably photostable, and linear over a wide range. This reader reports the raw
matrix; the pass/fail thresholds live with the ladder in plr-epigenome, not here.

### What the dye does, physically

Rhodamine B is a xanthene fluorophore. In aqueous solution its absorption maximum is about
554 nm and its emission maximum is about 570-580 nm (both shift a little with solvent, pH,
and concentration; they red-shift in water). The Stokes shift is small, which matters: the
emission sits close to the excitation, so excitation light scatter can bleed into the
emission channel if the two are set too near each other.

### Two ways to read it, and why both

- **Fluorescence (primary).** Sensitive, wide dynamic range, works at low concentration and
  small volume. This is the ladder read. Backend clamp is ex/em 230-850 nm, so the
  monochromator can sit anywhere sensible.
- **Absorbance at ~554 nm (cross-check).** Simpler and Beer-Lambert-linear at moderate OD,
  but less sensitive and path-length dependent. Path length depends on fill volume, which is
  exactly why it is a useful independent check of dispensed volume. Backend clamp 230-1000 nm.

### Settings to start from (all `TUNE` on the instrument)

Fluorescence, via `05_tecan_read_rhodamine.py`:

| Setting | Start | Why |
| --- | --- | --- |
| excitation | ~535-554 nm `TUNE` | at or just below the ~554 nm absorption max |
| emission | ~590-595 nm `TUNE` | deliberately red of the ~575 nm emission peak, to dodge excitation scatter/bleed-through at the cost of a little signal |
| gain | start 100 of 255, then `TUNE` | set so the brightest ladder rung sits ~80-90% of full scale, off saturation |
| focal height | 20.0 mm, then `TUNE` | top-read focus depends on plate and meniscus |
| flashes | 25 | averaging; the default is fine |
| integration | 20 us | the default is fine |

Absorbance cross-check, via `04_tecan_read_absorbance.py --wavelength 554`.

### The ladder itself

Two ladder shapes, and they answer different questions:

- **Volume ladder** (fixed dye concentration, the STAR dispenses a range of volumes). Signal
  should scale with volume. This is the one that actually tests the liquid handler. Lay it out
  down a column, decreasing, and `05 --ladder-col N` checks it is monotonic.
- **Concentration ladder** (fixed volume, a serial dilution of the dye). Signal should scale
  with concentration. This tests the reader's linearity and gain, independent of the STAR.

Concentrations, replicate count, and the diluent are `FROM plr-epigenome` (its ladder owns
them). Do not invent them here.

### Tuning procedure at the bench, in order

1. Read **blank wells** (diluent only) first, for background subtraction and to see the noise floor.
2. **Gain sweep** on the brightest well: raise/lower gain until it is ~80-90% of full scale. If the brightest rung saturates at gain 100, drop it; if the dimmest is in the noise, raise it (or accept the top rung is the anchor).
3. **Focal sweep** around 20 mm to maximize signal for this plate and fill.
4. Read the **full ladder**, subtract background.
5. Check **linearity (R^2)**, **replicate CV**, and **no missed wells** (a zero where signal is expected is a missed dispense, not a dim one).
6. Cross-read in **absorbance at 554 nm** and confirm the two modes agree on the pattern.

### Gotchas

- **Photobleaching.** Rhodamine B is fairly stable but not immune. Minimize re-reads and keep flashes modest; read the ladder once and trust it rather than re-scanning the same wells repeatedly.
- **Excitation bleed-through.** The small Stokes shift is why emission is set red of the peak. If the blank wells read unexpectedly high, widen the ex/em gap before blaming the dye.
- **Meniscus and edge effects.** Focal height is meniscus-sensitive; edge wells evaporate faster. Prefer interior wells for the ladder, or read promptly after dispense.
- **Saturation reads as a plateau, not an error.** If the top rungs flatten, that is gain too high, not a bad dispense.
- **counts_per_mm still unproven** (see the main README). If the whole matrix is wrong or empty, it is the internal stage geometry, not the dye.

---

## B. Putting the reader on the STAR deck for the iSWAP handoff

The goal: the reader sits within iSWAP reach, the STAR opens the drawer, the arm places a
plate into it, the reader reads, and the arm takes it back. This is the same unsolved
geometry problem as the ODTC handoff, and it gets solved the same way: by hand, against the
physical deck, one small step at a time, with known-bad values kept.

### The choreography

Sequenced so the arm never moves while the drawer is mid-travel:

1. Reader: `loading_tray.open()` -> wait for the drawer to fully settle (`BY#T` in the backend).
2. STAR: iSWAP picks the plate from its deck position, moves to the reader-tray drop coordinate, places it flat into the drawer nest, releases.
3. Reader: `loading_tray.close()`.
4. Reader: `absorbance.read(...)` or `fluorescence.read(...)`.
5. Reader: `loading_tray.open()`.
6. STAR: iSWAP picks the plate back off the drawer nest, returns it to the deck.
7. Reader: `loading_tray.close()`.

### The first physical unknown, before any geometry

**Does the drawer travel far enough OUT to clear the reader housing so the iSWAP can reach
the plate nest?** Some reader drawers do not fully expose the nest. Measure the open-drawer
nest exposure first. If it does not clear, the plate has to be staged on a deck-side landing
and the reader loaded some other way, and the whole handoff plan changes. This gates
everything below.

### Geometry to tune (hand-tuned, like the HHS and ODTC handoffs)

- **Reader-tray nest position** in STAR deck coordinates (rail / x / y / z). This is the iSWAP target.
- **Plate orientation** in the nest: which corner is A1, so the read matrix maps to the right wells.
- **iSWAP grip**: which long edge, grip width, and a pickup +Z clearance over the drawer walls, then a drop Z onto the nest. Mirror the ODTC/HHS pattern (pickup +5.0 mm worked for the HHS; the reader will have its own number).
- Keep known-bad values in the dated comment block, so a landing that collides is not rediscovered.

### PyLabRobot representation

`TecanInfinite200Pro` currently has `size_x/y/z = 0` and its `loading_tray` child at
`Coordinate.zero()` (placeholders, the same way the ODTC's `child_location` is a flagged
TODO, not a measurement). To hand the arm a real target, give the reader its measured
footprint and the tray-nest offset, and assign a landing coordinate on a deck rail. None of
those numbers exist yet; they are bench measurements.

### Concurrency and safety

- **No USB bus contention with the STAR.** STAR is USB vendor `08af`, the Tecan is `0c47`,
  the ODTC is on the network. They coexist (STAR + ODTC already ran concurrently). But only
  one process may hold a given USB interface, so either one Python process drives both the
  STAR and the reader in sequence, or ownership is coordinated between processes.
- **`setup()` homes the reader stage.** Bring the reader up and settle it before the arm is
  allowed near the drawer, not during.
- **The drawer is the fragile collision point.** Confirm it is fully out before the arm
  moves in, and fully clear of the arm before `close()`. Never `close()` on a plate the arm
  is still gripping.
- Everything in `hamilton-star/README.md` still applies: `--mode deck` first, a person
  watching, hand near the E-stop.

### Scripts to write (mirroring the ODTC handoff legs)

- `test_iswap_plate_deck_to_tecan_variable.py` - deck source to the open drawer, variable geometry, `--mode deck` first.
- its return twin - drawer back to the deck.
- then fold the read between them into an end-to-end: open, place, close, read, open, retrieve, close.

---

## Tomorrow, in order

1. `02_tecan_bringup.py --confirm i-am-watching` (INIT FORCE homes the stage), then `03` tray, then `04` absorbance on a known plate to judge `counts_per_mm`.
2. Once `counts_per_mm` is trusted, `05` on the Rhodamine ladder: blank, gain sweep, focal sweep, read, check.
3. Only after the reader reads correctly by hand: measure the drawer clearance, then start the iSWAP handoff geometry.

---

## Update 2026-07-12: the reader is too tall, so prove the transfer first

Fit reality: a full-size Infinite does not drop onto the STAR deck. The specific clash is
height (Z) - the drawer's plate-nest sits above the iSWAP's maximum lift, so the arm cannot
reach up to it. The fix is a **drop / recess mount**: lower the reader below the deck plane
until the drawer nest falls into the iSWAP's Z window. Size it as

    drop = (drawer-nest height above the deck) - (iSWAP max lift height) + gripper clearance

so the nest lands in the middle of the window, not at its ceiling. Two builds: recess the
reader into a bench cutout, or hang it on a rigid lower shelf off the STAR frame. Rigid and
kinematically located either way (locating pins / hard stops), so the tuned coordinate is
repeatable. If the drop comes out impractically deep, fall back to a plate-transfer shuttle
(arm places on a landing nest at reachable Z, a lift raises it into the drawer).

The good tip that unblocks all of this: **you do not need the reader, or its fitting, on the
deck to prove the plate move.** Decouple the transfer and test it standalone first, against a
stand-in landing nest at the target coordinate. The reader inherits that coordinate later,
once the recess sets the drawer's reachable X/Y/Z.

The transfer-first test:

- Dry plate move, no read: iSWAP picks a plate from a source deck position, places it on a
  stand-in landing nest at the target, picks it back, returns. No reader, no optics.
- What it proves: edge-grip on the plate, XY to target, pickup +Z clearance, drop Z onto the
  nest, and repeatability (run it 3x, like the HHS stress test - that is what earns trust).
- Low risk: it is a variant of the already-validated legs (rail35 pos0 to HHS with +5.0 mm
  pickup; the drafted ODTC legs), so it is mostly geometry tuning. `--mode deck` first.
- Target: either a stand-in nest at the future reader-drawer coordinate (so the transfer you
  tune becomes the real handoff), or an existing deck nest just to rehearse the motion.
- Script to write, in `hamilton-star/`: `test_iswap_plate_deck_to_landing_variable.py` plus
  its return twin, with target rail / x / y / z / pickup-Z as CLI args (same pattern as the
  existing `..._variable.py` legs), so the geometry is tuned live at the bench, not hardcoded.

---

## Verified specs and constraints (2026-07-12 research)

From the official Tecan IFU (No. 30125943) and the PyLabRobot / Hamilton STAR resource
definitions, adversarially verified. The two numbers that matter most are not published and
must be measured on the instrument; they are called out.

Reader (Infinite 200 PRO):

- Footprint 425 W x 457 D x 253 H mm; 14.0 kg (F) / 15.8 kg (M). The injector/pump module is a
  separate box (+250 x 156 x 155 mm, 3.4 kg) that sits beside the reader, off the handoff path.
- The plate loads on an OPEN, flat, motorized plate carrier with a centering clamp, not an
  enclosed drawer. Tecan states the reader "is robotic compatible"; the ejected carrier is the
  designed automation handoff surface, and Tecan's own S-LAB Pro / RoMa / RGA arms load it the
  same way an iSWAP would. External-gripper loading is a supported, proven pattern - good news.
- Hard limits: max load on the carrier is 100 g, so the arm must fully release and be
  support-free before it retracts (it cannot press down on the carrier); max plate height 23 mm
  incl. lid; 10 cm rear ventilation clearance (do not box the back in against the STAR).

iSWAP envelope:

- Safe traverse height 145 mm above the deck (~245 mm above origin); absolute finger ceiling
  ~173 mm above deck. So the carrier nest has to sit at or below ~145 mm above the deck to be
  placed into cleanly.
- The iSWAP reaches only ~90 mm off the chassis to the left (~20 mm right). That small off-deck
  reach is exactly how Hamilton does "off-deck integration of third-party devices": the reader
  body sits off-deck and only the ejected carrier reaches into that ~90 mm zone.
- Deck rail model: rails at 22.5 mm pitch, x = 100 + (rail - 1) x 22.5 mm.

What this changes about the plan:

- It is not "on the deck". It is OFF-deck, at the deck EDGE, with the reader oriented so its
  ejected carrier presents into the iSWAP's ~90 mm reach zone at <= 145 mm height. Best-practice
  precedent agrees: readers with an "extended nest" (the Infinite is called out by name) are
  placed off-deck with the arm accessing the plate at the edge. The recess / drop mount lowers
  the reader so the carrier nest lands inside that box.
- Recess sizing, now with the real ceiling:
  `drop = (measured nest height above deck) - ~145 mm + gripper clearance`, aiming the nest
  comfortably below 145 mm, not at the ceiling.
- The two numbers to MEASURE (not published anywhere): the carrier extension distance out the
  front, and the nest height above the benchtop. Measure them with the carrier out, or request a
  Tecan mechanical / integration drawing from the Tecan knowledge portal (IFU 30125943).

Handoff risk, and why transfer-first is right:

- The closest STAR precedent (a VSpin centrifuge at the deck edge) shows the iSWAP CAN reach in
  and place a plate directly, but practitioners flag direct-into-device placement as "more
  dangerous" (hard to teach, poor visibility) and often use a dedicated landing station instead.
  That is exactly why we prove the transfer to a stand-in landing nest first; a permanent landing
  station between the arm and the carrier is the fallback if direct placement is twitchy.
- The iSWAP has no collision awareness and can pick a joint configuration that crashes into
  adjacent labware (tip carriers), so define keep-out zones and verify the path by hand.
- Resolve plate orientation (portrait vs landscape, A1 corner) to match the carrier. The
  carrier's chamfered edges self-center within the ~1.2 mm placement tolerance, but only if the
  reader is rigidly fixtured (bolt / dowel) so the taught position does not drift.

Sources: Tecan IFU 30125943; PyLabRobot STAR resource definitions; Hamilton iSWAP manual.

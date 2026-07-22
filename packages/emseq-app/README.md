# EM-seq v2 + UltraShear bench planner

A local, planning-only browser wizard for NEBNext EM-seq v2 with UltraShear on the
Hamilton STAR. It ships beside the protocol package and uses the same plain-language
deck terminology as the whole-genome amplification + Targeted PCR bench planner.

Status: the complete one-column Hamilton physical dry run passed all 36 of 36 legs on
2026-07-21 with no command or USB fault and the plate returned to rail35 p0. Wet liquid,
heated ODTC programs, and multi-column execution are the next qualification scope.

The operator enters 1 through 96 library positions. The planner fills one 96-well
plate column-major: A1:H1, then A2:H2, through A12:H12. The final partial column is
explicitly blank-padded so the eight-channel actuation footprint is visible.

## What the app includes

- Interactive 1-96 sample plate map.
- Quick 8 / 24 / 48 / 96 position presets plus an exact 1-96 entry.
- Planned eight-channel column and blank-well counts.
- Runtime context: the observed one-column physical dry rehearsal took about 1 h 7 min;
  the default programmed thermal holds total about 6 h 29 min before ramps, swaps,
  cleanup waits, seal/spin, and QC.
- Plain-language Hamilton STAR deck checklist with `p0 = first slot` terminology.
- Compact deck table, reservoir map, 11-stage workflow, eight ODTC program profiles,
  input-mass PCR-cycle guidance, and reviewed run-posture commands.
- Print / save setup sheet for the physically dry-validated one-column envelope.
- A release-evidence panel tied to source commit `c375117` and the 2026-07-21 dry-run
  record.

## Safety boundary

This package cannot run hardware. It has no SSH, USB, Pi, PyLabRobot, process-launch,
or instrument code. The server binds to `127.0.0.1`, and its arm API always refuses.

The physical dry release applies only to 1-8 planned positions in A1:H1 with empty
labware, returned tips, and no ODTC heat. Plans containing 9-96 positions are layout
proposals only. Wet transfers, ODTC programs, multi-column tips/sources/cleanups, timed
holds, and biological performance remain blocked until separately implemented and
validated.

## Count and control policy

- Accepted input: 1-96 planned library positions.
- No hidden process-blank well is added. If the team wants a dedicated process blank,
  include it in the entered count and label that well in the run manifest.
- Lambda and pUC19 conversion controls are spike-ins within every sample; they are not
  additional plate wells.
- Complete columns fill A1:H1, A2:H2, and so on. A partial final column is padded with
  explicit blank channel positions.

## Deck terminology

- Rail numbers mean the printed Hamilton STAR rail labels.
- Carrier positions are zero-based: `p0` = first slot, `p1` = second, `p2` = third,
  and `p3` = fourth.
- The ODTC row says “modeled target” because the instrument remains installed.
- Position codes do not mean left/right/front/back. Follow the full location label.

## Run locally

```bash
cd packages/emseq-app
python3 -m emseq_app --port 8767
```

Open `http://127.0.0.1:8767` on the same computer.

The Hamilton STAR EM-seq folder also exposes the same canonical app through its local
launcher:

```bash
python3 hamilton-star/starlab_live/emseq/launch_bench_planner.py
```

That launcher contains no planner copy and no instrument execution code; it resolves
this package and starts the same localhost-only server.

## Test

```bash
cd packages/emseq-app
python3 -m unittest discover -s tests -v
```

The app and tests use only the Python standard library. Tests never connect to an
instrument and use only a temporary localhost server.

## Research use only

This is a planning aid for a research-use-only workflow. It is not a wet-run release,
not walkaway automation, and not validated for diagnostic use.

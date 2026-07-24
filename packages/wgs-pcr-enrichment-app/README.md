# WGS preparation + PCR enrichment bench planner

A local, planning-only wizard for the combined Hamilton STAR WGS preparation + HHS and
PCR enrichment + ODTC dry workflow.

The operator enters a sample count. Planner v0.2.1 lays out 1 through 96
biological samples column-major across as many as 12 eight-channel columns,
identifies sample and blank wells, and presents the corresponding planning
information. Sample count means biological samples only. The app does not add
NTCs or control wells, and there is no hidden control-well allowance.

## Safety boundary

This package cannot run hardware. It has no SSH, USB, Pi, PyLabRobot, process
launch, or instrument code. The server binds to `127.0.0.1`, and its arm API
always refuses requests.

No combined build is currently released through the app. The Hardware run
button remains locked while `wgs_pcr_enrichment_app/data/releases/` contains no valid
combined physical-validation manifest. Adding such a manifest in the future
will make the release visible, but this planning-only package will still need a
separately reviewed execution layer before it can move metal.

## Planner v0.2.1 capacity

- Accepted planning input: 1 through 96 biological samples.
- NTC/control allocation: none.
- Layout order: column-major, filling A1:H1, then A2:H2, through A12:H12.
- Each complete group of eight samples occupies one vertical eight-channel
  column.
- A final partial column is blank-padded after the last biological sample. For
  example, 10 samples fill A1:H1 and A2:B2, with C2:H2 marked as blanks.

Planning capacity is not physical-release capacity. The hardened combined
Hamilton runner remains locked to 1 through 8 samples and one A1:H1 column.
The printable validated deck checklist is likewise available only for that
1-through-8 release envelope. Plans containing 9 through 96 samples must not be
used to run hardware or represented as validated setup sheets.

Multi-column physical execution remains blocked until its tip allocation,
source layout, per-column liquid handling and motion have been implemented,
tested offline, and validated in attended bench runs.

The planned mode is dry only: empty sacrificial labware, returned tips, no HHS
heating or shaking, and no ODTC command or heating.

## Team setup sheet

For the validated 1-through-8 physical-release envelope, the deck section
includes **Print / save setup sheet**. It produces a compact,
green-and-grayscale checklist containing the selected biological-sample count,
the complete rail/position setup, global safety checks, and operator/date/Git
SHA sign-off lines. Browser print can send it to paper or save it as a PDF.

For plans of 9 through 96 samples, the printable validated checklist remains
locked because no combined multi-column hardware release exists yet.

### Deck terminology built into the app

- **Rail 35** means the Hamilton STAR deck rail with the printed label `35`.
- Carrier positions are zero-based: `p0` = first slot, `p1` = second,
  `p2` = third, `p3` = fourth, and `p4` = fifth.
- **Rail 35 · p2 (third slot)** therefore means the carrier on labeled rail 35,
  software position 2, which is its third slot.
- HHS and ODTC rows say **modeled target** instead of carrier slot because those
  devices remain installed.
- Position codes do not encode left/right/front/back. Follow the validated deck
  map and the full location label shown on each row.

The shareable package also includes the standalone
[one-column full dry setup guide](../../hamilton-star/starlab_live/WGS_PREP_PCR_ENRICHMENT_FULL_DRY_DECK_CHECKLIST.md).

## Run locally

```bash
cd packages/wgs-pcr-enrichment-app
python3 -m wgs_pcr_enrichment_app --port 8766
```

Then open `http://127.0.0.1:8766` in a browser on the same computer.

## Test

```bash
cd packages/wgs-pcr-enrichment-app
python3 -m unittest discover -s tests -v
```

The tests are standard-library only and never connect to an instrument or the
network beyond a temporary localhost test server.

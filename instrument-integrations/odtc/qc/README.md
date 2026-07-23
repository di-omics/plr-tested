# odtc/qc

The robustness QC for the targeted PCR round 1 run on the Inheco ODTC,
2026-07-10. The report is derived from the raw instrument log retained with the
local validation record.

## What is here

| File | What it is |
| --- | --- |
| Local validation run log | The raw run output. The block temperatures in it are the ODTC's own SiLA DataEvent stream, sampled about every 5 seconds, plus the completion message with its warnings. This is the evidence; everything else is derived from it. |
| `make_qc_report.py` | Parses the log into setpoint-robustness metrics and renders the report. Self-contained, standard library only. |
| `odtc_qc_report.html` | The report `make_qc_report.py` produces. Self-contained HTML, opens in any browser. |

## Regenerate

```bash
python make_qc_report.py --log /path/to/validation-run.log --out odtc_qc_report.html
```

That renders on a system font stack. The committed report embeds the house typeface;
to reproduce it exactly, pass a Manrope variable woff2 (SIL Open Font License, e.g. the
fontsource latin variable file) with `--font`:

```bash
python make_qc_report.py --log <log> --out <html> --font manrope-latin-wght-normal.woff2
```

## What the numbers are, and are not

The report leads with the result and does not bury the catch:

- **30 of 30 cycles completed**, and the block held every setpoint to a **mean 0.27 C**
  deviation (per-phase SD 0.23 to 0.44 C). Tight and repeatable.
- **The one caveat:** the 98 C denaturation sits 1 C under the ODTC's 99 C block ceiling,
  so the block grazed it on the ramp-in (peak 99.04 C) and the device logged 91
  "temperature out of specification" warnings, about three per cycle. Warnings, not faults;
  the method finished. Fix is to drop denaturation to 97 C or soften the overshoot.

One honest framing to keep in mind: these are **control-loop fidelity** numbers, the
device's own block sensor tracking its own setpoint. That is a real "does it hold
temperature" measure, not an externally calibrated accuracy figure. For calibrated
accuracy you would compare against an independent traceable probe in a well.

The typeface embedded in the committed report is Manrope, used under the SIL Open Font
License.

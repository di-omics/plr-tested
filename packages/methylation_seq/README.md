# Methylation sequencing run-card package

This package plans and evaluates supervised methylation-sequencing runs without
publishing a kit recipe. The checked-in demonstration is a synthetic water-only
profile with generic QC signals.

The public run card contains only:

- generic reagent stages 1–11;
- generic ODTC handoffs 1–8;
- generic magnetic cleanups 1–3;
- deck roles, safety gates, provenance, and artifact generation.

Biological reagent identities, compositions, transfer volumes, cleanup settings,
thermal methods, and QC thresholds belong in an external operator-owned profile.
Hardware mode fails closed without `profile_kind: operator` and a
`method_profile` path. The profile format is documented by
`operator-method-profile.schema.json`.

Run the non-actionable demonstration:

```bash
cd packages/methylation_seq
python -m methylation_seq_automation demo --output runs
```

The generated water-demo metrics are synthetic values, not measurements. This
package emits reviewed run cards only; it does not execute instruments.

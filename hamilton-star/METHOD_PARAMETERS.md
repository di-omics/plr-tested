# Operator-supplied method parameters

The public scripts keep Hamilton STAR deck geometry, collision safeguards,
calibrated liquid-handling heights, offsets, blowout settings, and recovery
behavior. Assay chemistry values are deliberately not stored in this
repository.

Before importing or running an assay script, set
`PLR_METHOD_PARAMETERS_FILE` to a local JSON file approved under the lab's
current SOP:

```text
export PLR_METHOD_PARAMETERS_FILE=/path/outside/the/repository/method.json
```

The checked-in [`method-parameters.schema.json`](method-parameters.schema.json)
defines the accepted shape but supplies no recipe values. Keep the populated
file outside version control. Missing, non-numeric, non-finite, zero, or
negative liquid volumes fail before robot setup. Incubation durations may be
zero only where the schema and loader explicitly accept a non-negative value.

The WGS profile owns the input and seven stage volumes, named thermal handoffs,
cleanup volumes, wash count and incubation, and the manual binding, post-wash,
and elution handoff identifiers. PCR enrichment and normalization likewise load
their assay-specific values from the same local profile. For scRNA-seq cleanup,
`stage_mode` is either `single` or `operator_defined_second_stage`; when the
optional second stage is enabled, all of its liquid and output volumes must be
positive. These names describe only operator-controlled stages and do not
encode a reagent identity or biological recipe.

Run the existing deck-assignment check and chatterbox rehearsal before any
human-gated hardware run. The local method profile does not override hardware
calibration constants in the scripts.

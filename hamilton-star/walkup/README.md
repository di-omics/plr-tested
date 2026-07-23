# Targeted PCR walk-up runner

Local, gated browser control for a validated targeted PCR and ODTC choreography.
This server drives the real Hamilton STAR through `run_on_pi.sh`; it is not a
simulation and must remain bound to localhost.

## Start

```bash
cd hamilton-star/walkup
python3 server.py
```

Open `http://127.0.0.1:8765`. A human must remain at the deck with access to the
E-stop for the entire run.

## Local build registry

Runnable builds come from a JSON file outside the repository. The default is:

```text
~/.config/plr-tested/walkup-builds.json
```

Set `WALKUP_BUILDS_FILE` to use another local path. Missing, empty, malformed, or
invalid configuration exposes zero builds and keeps the Run action disabled.

The registry uses this schema:

```json
{
  "schema_version": 1,
  "builds": {
    "targeted-pcr-one-column": {
      "tag": "targeted-pcr-validated-local",
      "sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "script": "starlab_live/run_targeted_pcr_odtc_LIDDED_1col_full_dry.py",
      "token": "RUN_TARGETED_PCR_ODTC_LIDDED_FULL",
      "runner_match": "run_targeted_pcr_odtc_LIDDED_1col_full_dry",
      "label": "1 column - 8 reactions",
      "legs": 13,
      "record": "qualified local build",
      "minutes": 18
    }
  }
}
```

The values above illustrate the structure only. A local operator supplies the
tag, exact 40-character commit SHA, script, confirmation token, runner match,
qualification record, and timing for a genuinely authorized build.

Validation is strict:

- top-level keys are exactly `schema_version` and `builds`;
- schema version is `1`;
- build keys use lowercase letters, numbers, `_`, or `-`;
- every build contains exactly the nine fields shown above;
- `sha` is 40 lowercase hexadecimal characters;
- `script` is a traversal-free relative Python path under `starlab_live/`;
- `tag`, `token`, and `runner_match` use restricted safe character sets;
- `runner_match` is part of the script stem;
- `legs` and `minutes` are positive bounded integers;
- `label` and `record` are non-empty bounded text.

Any invalid build makes the complete registry fail closed.

## Safety gates

The server requires all of the following:

1. A same-origin JSON request from the local page.
2. A configured tag that resolves to the configured full commit SHA.
3. A clean detached worktree at that SHA.
4. No other STAR-driving process on the Pi.
5. Every physical deck item explicitly confirmed.
6. A human explicitly present at the deck.
7. A two-second hold on the Run control.

The selected worktree, SHA, samples, result, and exit status are recorded in
`runs.jsonl`, which is ignored by Git.

## Stop behavior

Stop sends `SIGTERM` to the configured runner process on the Pi. The leg already
in flight is expected to finish before the runner exits, so no later leg starts.
This path requires supervised hardware qualification. Use the E-stop whenever
motion must cease immediately, then follow the appropriate recovery procedure.

## Environment

| Variable | Default | Purpose |
|---|---|---|
| `WALKUP_BUILDS_FILE` | `~/.config/plr-tested/walkup-builds.json` | external validated-build registry |
| `WALKUP_WORKTREES` | `~/.cache/targeted-pcr-walkup/worktrees` | detached pinned worktrees |
| `WALKUP_PORT` | `8765` | localhost HTTP port |
| `PI` | `starpi` | robot-control host |

Research use only. Not for diagnostic use.

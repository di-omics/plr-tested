# Setup

Install the package in an isolated environment:

```bash
cd packages/methylation_seq
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev,yaml]'
python -m pytest -q
```

Use `configs/example_run.json` for the synthetic water-only demonstration.

For an operator-controlled plan, create a private JSON file conforming to
`operator-method-profile.schema.json`, then set:

```json
{
  "mode": "simulation",
  "profile_kind": "operator",
  "method_profile": "/secure/operator/methylation-method.json"
}
```

Hardware mode additionally requires the site safety workflow and remains
non-executing in this package. Keep method files outside the repository.

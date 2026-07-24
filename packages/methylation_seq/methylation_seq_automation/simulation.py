"""Deterministic synthetic measurements, quarantined from real run data."""

from __future__ import annotations

import hashlib
import random
from typing import Any, Dict, Optional

from .config import RunConfig, SampleType
from .protocol import qualified_volumes


def _rng(*parts: str) -> random.Random:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def simulate_metrics(
    config: RunConfig,
    poor_deck: bool = False,
    failing_sample: Optional[str] = None,
) -> Dict[str, Any]:
    deck_rng = _rng(config.run_id, "deck")
    cv = {
        f"{volume:g}": round(1.8 + deck_rng.random() * 1.6, 3)
        for volume in qualified_volumes(config)
    }
    if poor_deck and cv:
        first = next(iter(cv))
        cv[first] = config.acceptance.lh_cv_max_percent + 2.0

    samples: Dict[str, Dict[str, float]] = {}
    for sample in config.samples:
        if sample.sample_type is SampleType.PROCESS_BLANK:
            record = {
                rule.metric: (
                    (rule.maximum * 0.25) if rule.maximum is not None else 0.0
                )
                for rule in config.acceptance.blank_rules
            }
        else:
            record = {
                rule.metric: (
                    (rule.minimum + 1.0) if rule.minimum is not None
                    else (rule.maximum * 0.5 if rule.maximum is not None else 1.0)
                )
                for rule in config.acceptance.sample_rules
            }
            if sample.id == failing_sample and config.acceptance.sample_rules:
                rule = config.acceptance.sample_rules[0]
                record[rule.metric] = (
                    rule.minimum - 1.0 if rule.minimum is not None
                    else rule.maximum + 1.0
                )
        samples[sample.id] = record
    return {
        "simulated": True,
        "liquid_handling": {"cv_percent": cv},
        "samples": samples,
    }

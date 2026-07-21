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


def simulate_metrics(config: RunConfig, poor_deck: bool = False,
                     failing_sample: Optional[str] = None) -> Dict[str, Any]:
    deck_rng = _rng(config.run_id, "deck")
    cv = {}
    for volume in qualified_volumes(config):
        cv[f"{volume:g}"] = round(1.8 + deck_rng.random() * 1.6, 3)
    if poor_deck:
        first = f"{qualified_volumes(config)[0]:g}"
        cv[first] = config.acceptance.lh_cv_max_percent + 2.0

    samples: Dict[str, Dict[str, float]] = {}
    # A simple size response to the allowed 25-35 min shear range: longer shear is smaller.
    expected_bp = 510.0 - (config.shear_minutes - 30.0) * 10.0
    for sample in config.samples:
        rng = _rng(config.run_id, sample.id)
        if sample.sample_type is SampleType.PROCESS_BLANK:
            samples[sample.id] = {
                "library_concentration_ng_ul": round(0.15 + rng.random() * 0.2, 3),
            }
            continue
        record = {
            "lambda_reads": int(7200 + rng.random() * 2200),
            "puc19_reads": int(760 + rng.random() * 520),
            "lambda_conversion_percent": round(99.65 + rng.random() * 0.25, 4),
            "puc19_protection_percent": round(96.2 + rng.random() * 2.5, 4),
            "library_mean_bp": round(expected_bp - 18.0 + rng.random() * 36.0, 2),
            "library_concentration_ng_ul": round(8.0 + rng.random() * 18.0, 3),
        }
        if sample.id == failing_sample:
            record["lambda_conversion_percent"] = 92.0
        samples[sample.id] = record
    return {
        "simulated": True,
        "liquid_handling": {"cv_percent": cv},
        "samples": samples,
    }


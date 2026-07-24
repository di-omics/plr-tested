"""Fail-closed loader for assay parameters that are intentionally not in git.

Hamilton deck geometry, motion offsets, liquid classes, and other hardware
calibration values remain in the individual scripts. Wet-lab method values do
not: an operator must provide an approved local JSON profile through
``PLR_METHOD_PARAMETERS_FILE`` before an assay script is imported.
"""

from __future__ import annotations

import json
import math
import os
from functools import lru_cache
from pathlib import Path
from typing import Any


PROFILE_ENV = "PLR_METHOD_PARAMETERS_FILE"


class MethodParameterError(RuntimeError):
    """Raised before hardware setup when a local method profile is unavailable."""


@lru_cache(maxsize=1)
def _profile() -> dict[str, Any]:
    raw_path = os.environ.get(PROFILE_ENV)
    if not raw_path:
        raise MethodParameterError(
            f"{PROFILE_ENV} must point to an operator-approved local JSON profile"
        )

    path = Path(raw_path).expanduser()
    if not path.is_file():
        raise MethodParameterError(f"method profile does not exist: {path}")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MethodParameterError(f"cannot load method profile {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise MethodParameterError("method profile root must be a JSON object")
    return data


def _value(path: str) -> Any:
    value: Any = _profile()
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            raise MethodParameterError(f"missing required method parameter: {path}")
        value = value[part]
    return value


def required_positive(path: str) -> float:
    """Return a finite positive number from the operator profile."""

    value = _value(path)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MethodParameterError(f"{path} must be numeric")
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise MethodParameterError(f"{path} must be finite and greater than zero")
    return number


def required_nonnegative(path: str) -> float:
    """Return a finite non-negative number from the operator profile."""

    value = _value(path)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MethodParameterError(f"{path} must be numeric")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise MethodParameterError(f"{path} must be finite and non-negative")
    return number


def required_integer(
    path: str, *, minimum: int = 1, maximum: int | None = None
) -> int:
    """Return an integer inside the requested bounds from the operator profile."""

    value = _value(path)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise MethodParameterError(f"{path} must be an integer >= {minimum}")
    if maximum is not None and value > maximum:
        raise MethodParameterError(f"{path} must be an integer <= {maximum}")
    return value


def required_number_list(
    path: str, *, minimum_items: int = 1, nonnegative: bool = False
) -> list[float]:
    """Return a finite numeric list from the operator profile."""

    value = _value(path)
    if not isinstance(value, list) or len(value) < minimum_items:
        raise MethodParameterError(
            f"{path} must be an array with at least {minimum_items} items"
        )

    numbers: list[float] = []
    for index, item in enumerate(value):
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise MethodParameterError(f"{path}[{index}] must be numeric")
        number = float(item)
        if not math.isfinite(number):
            raise MethodParameterError(f"{path}[{index}] must be finite")
        if nonnegative and number < 0:
            raise MethodParameterError(f"{path}[{index}] must be non-negative")
        numbers.append(number)
    return numbers


def required_text(path: str) -> str:
    """Return a non-empty operator-supplied text value."""

    value = _value(path)
    if not isinstance(value, str) or not value.strip():
        raise MethodParameterError(f"{path} must be a non-empty string")
    return value.strip()

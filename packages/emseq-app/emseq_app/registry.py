"""Read-only deck and release registries for the planning app.

Deck data is package-owned configuration. Release manifests are intentionally
separate files under data/releases. A valid manifest records physical dry
evidence, but never installs instrument execution in this planning app.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import Dict, List, Tuple


DECK_ID = "emseq_v2_ultrashear_dry_v1"
RELEASE_STATUS = "validated_physical_dry"
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class RegistryError(RuntimeError):
    pass


@dataclass(frozen=True)
class DeckItem:
    key: str
    rail: int
    position: int
    location_label: str
    labware_id: str
    role: str
    dry_run_state: str
    instruction: str
    why: str

    def to_dict(self) -> Dict[str, object]:
        return {
            "key": self.key,
            "rail": self.rail,
            "position": self.position,
            "location_label": self.location_label,
            "labware_id": self.labware_id,
            "role": self.role,
            "dry_run_state": self.dry_run_state,
            "instruction": self.instruction,
            "why": self.why,
        }


@dataclass(frozen=True)
class GlobalCheck:
    key: str
    instruction: str
    why: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "key": self.key,
            "instruction": self.instruction,
            "why": self.why,
        }


@dataclass(frozen=True)
class DeckDefinition:
    deck_id: str
    label: str
    mode: str
    items: Tuple[DeckItem, ...]
    global_checks: Tuple[GlobalCheck, ...]

    def to_dict(self) -> Dict[str, object]:
        return {
            "id": self.deck_id,
            "label": self.label,
            "mode": self.mode,
            "items": [item.to_dict() for item in self.items],
            "global_checks": [item.to_dict() for item in self.global_checks],
        }


@dataclass(frozen=True)
class ReleaseSummary:
    available: bool
    builds: Tuple[Dict[str, object], ...]
    issues: Tuple[str, ...]
    message: str

    def to_dict(self) -> Dict[str, object]:
        return {
            "available": self.available,
            "builds": [dict(build) for build in self.builds],
            "issues": list(self.issues),
            "message": self.message,
        }


def _package_root():
    return resources.files("emseq_app")


@lru_cache(maxsize=1)
def emseq_dry_deck() -> DeckDefinition:
    path = _package_root().joinpath("data").joinpath("decks.json")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RegistryError(f"could not load deck registry: {exc}") from exc

    if raw.get("schema_version") != 1:
        raise RegistryError("unsupported deck registry schema")
    deck_raw = (raw.get("decks") or {}).get(DECK_ID)
    if not isinstance(deck_raw, dict):
        raise RegistryError(f"deck {DECK_ID!r} is missing")

    items_raw = deck_raw.get("items")
    checks_raw = deck_raw.get("global_checks")
    if not isinstance(items_raw, list) or not items_raw:
        raise RegistryError("deck items must be a non-empty list")
    if not isinstance(checks_raw, list) or not checks_raw:
        raise RegistryError("global checks must be a non-empty list")

    items: List[DeckItem] = []
    seen_keys = set()
    seen_positions = set()
    for entry in items_raw:
        if not isinstance(entry, dict):
            raise RegistryError("each deck item must be an object")
        key = entry.get("key")
        rail = entry.get("rail")
        position = entry.get("position")
        location_label = entry.get("location_label")
        if not isinstance(key, str) or not key:
            raise RegistryError("each deck item needs a non-empty key")
        if isinstance(rail, bool) or not isinstance(rail, int):
            raise RegistryError(f"deck item {key!r} has an invalid rail")
        if isinstance(position, bool) or not isinstance(position, int):
            raise RegistryError(f"deck item {key!r} has an invalid position")
        if not isinstance(location_label, str) or not location_label.strip():
            raise RegistryError(f"deck item {key!r} has an invalid location label")
        if key in seen_keys:
            raise RegistryError(f"duplicate deck key {key!r}")
        coordinate = (rail, position)
        if coordinate in seen_positions:
            raise RegistryError(f"duplicate deck position rail{rail} pos{position}")
        seen_keys.add(key)
        seen_positions.add(coordinate)
        try:
            item = DeckItem(
                key=key,
                rail=rail,
                position=position,
                location_label=location_label,
                labware_id=str(entry["labware_id"]),
                role=str(entry["role"]),
                dry_run_state=str(entry["dry_run_state"]),
                instruction=str(entry["instruction"]),
                why=str(entry["why"]),
            )
        except KeyError as exc:
            raise RegistryError(f"deck item {key!r} is missing {exc.args[0]!r}") from exc
        items.append(item)

    checks: List[GlobalCheck] = []
    for entry in checks_raw:
        if not isinstance(entry, dict):
            raise RegistryError("each global check must be an object")
        try:
            checks.append(
                GlobalCheck(
                    key=str(entry["key"]),
                    instruction=str(entry["instruction"]),
                    why=str(entry["why"]),
                )
            )
        except KeyError as exc:
            raise RegistryError(f"global check is missing {exc.args[0]!r}") from exc

    return DeckDefinition(
        deck_id=DECK_ID,
        label=str(deck_raw.get("label", DECK_ID)),
        mode=str(deck_raw.get("mode", "dry")),
        items=tuple(items),
        global_checks=tuple(checks),
    )


def _validate_release(raw: object, filename: str) -> Dict[str, object]:
    if not isinstance(raw, dict):
        raise RegistryError(f"{filename}: release manifest must be an object")
    required = (
        "id",
        "release_status",
        "commit_sha",
        "runner",
        "validation_record",
        "deck_id",
        "sample_count_min",
        "sample_count_max",
        "dry_only",
        "validated_at",
        "validation_log_sha256",
        "executed_leg_count",
        "odtc_heat_run",
        "wet_liquid_run",
    )
    missing = [key for key in required if key not in raw]
    if missing:
        raise RegistryError(f"{filename}: missing fields {', '.join(missing)}")
    if raw.get("schema_version") != 1:
        raise RegistryError(f"{filename}: unsupported schema")
    if raw["release_status"] != RELEASE_STATUS:
        raise RegistryError(f"{filename}: build is not physical-dry validated")
    if raw["deck_id"] != DECK_ID:
        raise RegistryError(f"{filename}: deck id does not match {DECK_ID}")
    if not isinstance(raw["commit_sha"], str) or not _SHA_RE.match(raw["commit_sha"]):
        raise RegistryError(f"{filename}: commit_sha must be 40 lowercase hex characters")
    if raw["dry_only"] is not True:
        raise RegistryError(f"{filename}: only a dry-only release is accepted")
    if raw["odtc_heat_run"] is not False or raw["wet_liquid_run"] is not False:
        raise RegistryError(f"{filename}: release must record no heat and no wet liquid")
    if raw["sample_count_min"] != 1 or raw["sample_count_max"] != 8:
        raise RegistryError(f"{filename}: release must match the 1..8 planning envelope")
    if not isinstance(raw["validated_at"], str) or not raw["validated_at"]:
        raise RegistryError(f"{filename}: validated_at must be a non-empty timestamp")
    if not isinstance(raw["validation_log_sha256"], str) or not _SHA256_RE.match(
        raw["validation_log_sha256"]
    ):
        raise RegistryError(f"{filename}: validation_log_sha256 must be 64 lowercase hex characters")
    if raw["executed_leg_count"] != 36:
        raise RegistryError(f"{filename}: expected the complete 36-leg choreography")
    return {key: raw[key] for key in required}


@lru_cache(maxsize=1)
def release_summary() -> ReleaseSummary:
    release_dir = _package_root().joinpath("data").joinpath("releases")
    builds: List[Dict[str, object]] = []
    issues: List[str] = []
    try:
        entries = sorted(release_dir.iterdir(), key=lambda entry: entry.name)
    except Exception as exc:
        return ReleaseSummary(
            available=False,
            builds=(),
            issues=(f"could not inspect release manifests: {exc}",),
            message="Hardware release locked: release registry could not be read.",
        )

    for entry in entries:
        if not entry.name.endswith(".json"):
            continue
        try:
            raw = json.loads(entry.read_text(encoding="utf-8"))
            builds.append(_validate_release(raw, entry.name))
        except Exception as exc:
            issues.append(str(exc))

    if builds and not issues:
        return ReleaseSummary(
            available=True,
            builds=tuple(builds),
            issues=(),
            message=(
                "Physical dry evidence is present for one A1:H1 column. This app remains "
                "planning-only; wet, heated, and multi-column execution are blocked."
            ),
        )
    if issues:
        return ReleaseSummary(
            available=False,
            builds=(),
            issues=tuple(issues),
            message="Hardware release locked: release manifest validation failed.",
        )
    return ReleaseSummary(
        available=False,
        builds=(),
        issues=(),
        message=(
            "Hardware release locked: no validated EM-seq physical dry manifest exists."
        ),
    )

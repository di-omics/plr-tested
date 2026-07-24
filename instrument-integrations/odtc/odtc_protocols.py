"""ODTC protocol registry and controlled operator-profile loader.

Generic WGS, PCR-enrichment, methylation-sequencing, and scRNA-seq names resolve
to a short synthetic water-only motion profile in this public repository.  The
profile exists to exercise method generation, pre-warming, cycling, completion,
and post-heating without encoding a biological method.

Biological temperatures, durations, cycle counts, lid settings, and reaction
volumes belong in a controlled operator method and are intentionally not
committed here.  ``load_operator_program()`` accepts those values from an
operator-owned JSON file at run time.

TIP-seq remains a user-owned workflow and retains its cited thermal programs.
The ``timecheck`` and ``selftest`` programs are hardware exercises.
"""

import json
from pathlib import Path

from odtc_compat import import_plr

_plr = import_plr()
Protocol = _plr.Protocol
Stage = _plr.Stage
Step = _plr.Step


# ODTC integration constants, not biological method values.
INFINITE_HOLD_SECONDS = 0
START_BLOCK_C_DEFAULT = 25.0


class Program:
    """A protocol plus the parameters needed by the ODTC backend."""

    def __init__(
        self,
        name,
        protocol,
        lid_c,
        block_max_volume_ul,
        source,
        *,
        is_biology=True,
        water_only=False,
    ):
        self.name = name
        self.protocol = protocol
        self.lid_c = lid_c
        self.block_max_volume_ul = block_max_volume_ul
        self.source = source
        self.is_biology = is_biology
        self.water_only = water_only


_OPERATOR_PROFILE_KEYS = {
    "schema_version",
    "method_name",
    "lid_c",
    "block_max_volume_ul",
    "stages",
}
_OPERATOR_STAGE_KEYS = {"repeats", "steps"}
_OPERATOR_STEP_KEYS = {
    "temperature_c",
    "hold_seconds",
    "rate_c_per_s",
}


def _require_number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number")
    return float(value)


def _reject_unknown(mapping, allowed, label):
    unknown = sorted(set(mapping) - allowed)
    if unknown:
        raise ValueError(f"{label} contains unknown field(s): {', '.join(unknown)}")


def load_operator_program(path):
    """Load an operator-controlled ODTC method from JSON.

    The file is intentionally external to the public registry.  It must contain
    every biological thermal and volume parameter needed to generate the method;
    this loader supplies no assay defaults.
    """
    profile_path = Path(path).expanduser()
    try:
        data = json.loads(profile_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load operator profile {profile_path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("operator profile must be a JSON object")
    _reject_unknown(data, _OPERATOR_PROFILE_KEYS, "operator profile")
    missing = sorted(_OPERATOR_PROFILE_KEYS - set(data))
    if missing:
        raise ValueError(
            f"operator profile is missing required field(s): {', '.join(missing)}"
        )
    if data["schema_version"] != 1:
        raise ValueError("operator profile schema_version must be 1")

    method_name = str(data["method_name"]).strip()
    if not method_name:
        raise ValueError("operator profile method_name cannot be empty")

    lid_c = _require_number(data["lid_c"], "lid_c")
    block_volume = _require_number(
        data["block_max_volume_ul"],
        "block_max_volume_ul",
    )
    if block_volume <= 0:
        raise ValueError("block_max_volume_ul must be positive")

    raw_stages = data["stages"]
    if not isinstance(raw_stages, list) or not raw_stages:
        raise ValueError("operator profile stages must be a non-empty list")

    stages = []
    for stage_index, raw_stage in enumerate(raw_stages):
        label = f"stages[{stage_index}]"
        if not isinstance(raw_stage, dict):
            raise ValueError(f"{label} must be an object")
        _reject_unknown(raw_stage, _OPERATOR_STAGE_KEYS, label)
        if set(raw_stage) != _OPERATOR_STAGE_KEYS:
            raise ValueError(f"{label} requires repeats and steps")
        repeats = raw_stage["repeats"]
        if isinstance(repeats, bool) or not isinstance(repeats, int) or repeats < 1:
            raise ValueError(f"{label}.repeats must be a positive integer")

        raw_steps = raw_stage["steps"]
        if not isinstance(raw_steps, list) or not raw_steps:
            raise ValueError(f"{label}.steps must be a non-empty list")
        steps = []
        for step_index, raw_step in enumerate(raw_steps):
            step_label = f"{label}.steps[{step_index}]"
            if not isinstance(raw_step, dict):
                raise ValueError(f"{step_label} must be an object")
            _reject_unknown(raw_step, _OPERATOR_STEP_KEYS, step_label)
            required = {"temperature_c", "hold_seconds"}
            missing_step = sorted(required - set(raw_step))
            if missing_step:
                raise ValueError(
                    f"{step_label} is missing required field(s): "
                    f"{', '.join(missing_step)}"
                )
            temperature = _require_number(
                raw_step["temperature_c"],
                f"{step_label}.temperature_c",
            )
            hold_seconds = _require_number(
                raw_step["hold_seconds"],
                f"{step_label}.hold_seconds",
            )
            if hold_seconds < 0:
                raise ValueError(f"{step_label}.hold_seconds cannot be negative")
            kwargs = {
                "temperature": [temperature],
                "hold_seconds": hold_seconds,
            }
            if raw_step.get("rate_c_per_s") is not None:
                rate = _require_number(
                    raw_step["rate_c_per_s"],
                    f"{step_label}.rate_c_per_s",
                )
                if rate <= 0:
                    raise ValueError(f"{step_label}.rate_c_per_s must be positive")
                kwargs["rate"] = rate
            steps.append(Step(**kwargs))
        stages.append(Stage(steps=steps, repeats=repeats))

    return Program(
        name=method_name,
        protocol=Protocol(stages=stages),
        lid_c=lid_c,
        block_max_volume_ul=block_volume,
        source=f"operator-owned profile: {profile_path}",
        is_biology=True,
        water_only=False,
    )


# ---------------------------------------------------------------------------
# Public generic entries: deliberately synthetic, uniform, and water-only.
# These numbers are a hardware exercise and have no wet-lab interpretation.
# ---------------------------------------------------------------------------
PUBLIC_WATER_MOTION = Protocol(
    stages=[
        Stage(
            steps=[
                Step(temperature=[30.0], hold_seconds=30),
                Step(temperature=[40.0], hold_seconds=30),
            ],
            repeats=2,
        ),
        Stage(
            steps=[
                Step(
                    temperature=[START_BLOCK_C_DEFAULT],
                    hold_seconds=INFINITE_HOLD_SECONDS,
                )
            ],
            repeats=1,
        ),
    ]
)
PUBLIC_WATER_LID_C = 45.0
PUBLIC_WATER_VOLUME_UL = 20.0

GENERIC_PUBLIC_PROGRAM_NAMES = (
    "wgs_prep",
    "dna-fragmentation",
    "end-repair",
    "ligation",
    "library-pcr",
    "pcr-enrichment-round1",
    "pcr-enrichment-round2",
    "methylation-seq-stage-1",
    "methylation-seq-stage-2",
    "methylation-seq-stage-3",
    "methylation-seq-stage-4",
    "methylation-seq-stage-5",
    "methylation-seq-stage-6",
    "methylation-seq-stage-7",
    "methylation-seq-stage-8",
    "scrnaseq-stage-1",
    "scrnaseq-stage-2",
    "scrnaseq-stage-3",
    "scrnaseq-stage-4",
    "scrnaseq-stage-5",
    "scrnaseq-stage-6",
    "scrnaseq-stage-7",
)


def public_water_program():
    """Return the public synthetic program used by generic registry entries."""
    return PUBLIC_WATER_MOTION


# ---------------------------------------------------------------------------
# TIP-seq. User-owned assay programs are intentionally preserved.
# ---------------------------------------------------------------------------
LID_C_TIP_GAPFILL = 105.0
LID_C_TIP_IVT = 47.0
LID_C_TIP_RT_ANNEAL = 105.0
LID_C_TIP_RT = 105.0
LID_C_TIP_RNASEH = 47.0
LID_C_TIP_SS_ANNEAL = 105.0
LID_C_TIP_SS = 105.0
LID_C_TIP_TAG = 105.0
LID_C_TIP_PCR = 105.0

VOL_UL_TIP_GAPFILL = 10.0
VOL_UL_TIP_IVT = 16.3
VOL_UL_TIP_RT_ANNEAL = 11.5
VOL_UL_TIP_RT = 20.0
VOL_UL_TIP_RNASEH = 21.0
VOL_UL_TIP_SS_ANNEAL = 23.5
VOL_UL_TIP_SS = 29.4
VOL_UL_TIP_TAG = 11.0
VOL_UL_TIP_PCR = 40.0

TIP_GAPFILL = Protocol(
    stages=[
        Stage(
            steps=[Step(temperature=[72.0], hold_seconds=3 * 60)],
            repeats=1,
        ),
        Stage(
            steps=[
                Step(temperature=[4.0], hold_seconds=INFINITE_HOLD_SECONDS)
            ],
            repeats=1,
        ),
    ]
)


def tip_ivt(ivt_hours: float = 17.0) -> "Protocol":
    """T7 IVT linear amplification; the cited method permits 16-19 hours."""
    return Protocol(
        stages=[
            Stage(
                steps=[
                    Step(
                        temperature=[37.0],
                        hold_seconds=ivt_hours * 60 * 60,
                    )
                ],
                repeats=1,
            ),
            Stage(
                steps=[
                    Step(
                        temperature=[4.0],
                        hold_seconds=INFINITE_HOLD_SECONDS,
                    )
                ],
                repeats=1,
            ),
        ]
    )


TIP_RT_ANNEAL = Protocol(
    stages=[
        Stage(
            steps=[Step(temperature=[70.0], hold_seconds=3 * 60)],
            repeats=1,
        ),
        Stage(
            steps=[
                Step(temperature=[4.0], hold_seconds=INFINITE_HOLD_SECONDS)
            ],
            repeats=1,
        ),
    ]
)

TIP_RT = Protocol(
    stages=[
        Stage(
            steps=[Step(temperature=[22.0], hold_seconds=10 * 60)],
            repeats=1,
        ),
        Stage(
            steps=[Step(temperature=[42.0], hold_seconds=60 * 60)],
            repeats=1,
        ),
        Stage(
            steps=[Step(temperature=[70.0], hold_seconds=10 * 60)],
            repeats=1,
        ),
        Stage(
            steps=[
                Step(temperature=[4.0], hold_seconds=INFINITE_HOLD_SECONDS)
            ],
            repeats=1,
        ),
    ]
)

TIP_RNASEH = Protocol(
    stages=[
        Stage(
            steps=[Step(temperature=[37.0], hold_seconds=20 * 60)],
            repeats=1,
        ),
        Stage(
            steps=[
                Step(temperature=[4.0], hold_seconds=INFINITE_HOLD_SECONDS)
            ],
            repeats=1,
        ),
    ]
)

TIP_SS_ANNEAL = Protocol(
    stages=[
        Stage(
            steps=[Step(temperature=[65.0], hold_seconds=2 * 60)],
            repeats=1,
        ),
        Stage(
            steps=[
                Step(temperature=[4.0], hold_seconds=INFINITE_HOLD_SECONDS)
            ],
            repeats=1,
        ),
    ]
)

TIP_SS = Protocol(
    stages=[
        Stage(
            steps=[Step(temperature=[72.0], hold_seconds=8 * 60)],
            repeats=1,
        ),
        Stage(
            steps=[
                Step(temperature=[4.0], hold_seconds=INFINITE_HOLD_SECONDS)
            ],
            repeats=1,
        ),
    ]
)

TIP_TAG = Protocol(
    stages=[
        Stage(
            steps=[Step(temperature=[55.0], hold_seconds=6 * 60)],
            repeats=1,
        ),
        Stage(
            steps=[
                Step(temperature=[4.0], hold_seconds=INFINITE_HOLD_SECONDS)
            ],
            repeats=1,
        ),
    ]
)


def tip_pcr(num_cycles: int = 8) -> "Protocol":
    """TIP-seq library indexing PCR from the cited TIP-seq/CUT&Tag method."""
    return Protocol(
        stages=[
            Stage(
                steps=[Step(temperature=[72.0], hold_seconds=5 * 60)],
                repeats=1,
            ),
            Stage(
                steps=[Step(temperature=[98.0], hold_seconds=30)],
                repeats=1,
            ),
            Stage(
                steps=[
                    Step(temperature=[98.0], hold_seconds=10),
                    Step(temperature=[63.0], hold_seconds=30),
                ],
                repeats=num_cycles,
            ),
            Stage(
                steps=[Step(temperature=[72.0], hold_seconds=60)],
                repeats=1,
            ),
            Stage(
                steps=[
                    Step(
                        temperature=[8.0],
                        hold_seconds=INFINITE_HOLD_SECONDS,
                    )
                ],
                repeats=1,
            ),
        ]
    )


TIP_IVT = tip_ivt()
TIP_PCR = tip_pcr()


# ---------------------------------------------------------------------------
# Hardware exercises. These are not biology.
# ---------------------------------------------------------------------------
LID_C_HARDWARE_EXERCISE = 105.0
TIMECHECK = Protocol(
    stages=[
        Stage(
            steps=[Step(temperature=[50.0], hold_seconds=60)],
            repeats=1,
        )
    ]
)

SELFTEST = Protocol(
    stages=[
        Stage(
            steps=[
                Step(temperature=[95.0], hold_seconds=10),
                Step(temperature=[60.0], hold_seconds=10),
            ],
            repeats=3,
        ),
        Stage(
            steps=[
                Step(
                    temperature=[START_BLOCK_C_DEFAULT],
                    hold_seconds=INFINITE_HOLD_SECONDS,
                )
            ],
            repeats=1,
        ),
    ]
)


PROGRAMS = {
    name: Program(
        name,
        PUBLIC_WATER_MOTION,
        PUBLIC_WATER_LID_C,
        PUBLIC_WATER_VOLUME_UL,
        "public synthetic water-only motion profile; operator method required for biology",
        is_biology=False,
        water_only=True,
    )
    for name in GENERIC_PUBLIC_PROGRAM_NAMES
}

PROGRAMS.update(
    {
        "tip-gapfill": Program(
            "tip-gapfill",
            TIP_GAPFILL,
            LID_C_TIP_GAPFILL,
            VOL_UL_TIP_GAPFILL,
            "TIP-seq (JCB 2021, e202103078), Taq gap-fill",
        ),
        "tip-ivt": Program(
            "tip-ivt",
            TIP_IVT,
            LID_C_TIP_IVT,
            VOL_UL_TIP_IVT,
            "TIP-seq (JCB 2021, e202103078), T7 IVT",
        ),
        "tip-rt-anneal": Program(
            "tip-rt-anneal",
            TIP_RT_ANNEAL,
            LID_C_TIP_RT_ANNEAL,
            VOL_UL_TIP_RT_ANNEAL,
            "TIP-seq (JCB 2021, e202103078), random-hexamer anneal",
        ),
        "tip-rt": Program(
            "tip-rt",
            TIP_RT,
            LID_C_TIP_RT,
            VOL_UL_TIP_RT,
            "TIP-seq (JCB 2021, e202103078), first-strand synthesis",
        ),
        "tip-rnaseh": Program(
            "tip-rnaseh",
            TIP_RNASEH,
            LID_C_TIP_RNASEH,
            VOL_UL_TIP_RNASEH,
            "TIP-seq (JCB 2021, e202103078), RNase H",
        ),
        "tip-ss-anneal": Program(
            "tip-ss-anneal",
            TIP_SS_ANNEAL,
            LID_C_TIP_SS_ANNEAL,
            VOL_UL_TIP_SS_ANNEAL,
            "TIP-seq (JCB 2021, e202103078), second-strand anneal",
        ),
        "tip-ss": Program(
            "tip-ss",
            TIP_SS,
            LID_C_TIP_SS,
            VOL_UL_TIP_SS,
            "TIP-seq (JCB 2021, e202103078), second-strand synthesis",
        ),
        "tip-tag": Program(
            "tip-tag",
            TIP_TAG,
            LID_C_TIP_TAG,
            VOL_UL_TIP_TAG,
            "TIP-seq (JCB 2021, e202103078), cDNA tagging",
        ),
        "tip-pcr": Program(
            "tip-pcr",
            TIP_PCR,
            LID_C_TIP_PCR,
            VOL_UL_TIP_PCR,
            "TIP-seq (JCB 2021, e202103078), library indexing PCR",
        ),
        "timecheck": Program(
            "timecheck",
            TIMECHECK,
            LID_C_HARDWARE_EXERCISE,
            20.0,
            "hardware exercise, not biology",
            is_biology=False,
        ),
        "selftest": Program(
            "selftest",
            SELFTEST,
            LID_C_HARDWARE_EXERCISE,
            20.0,
            "hardware exercise, not biology",
            is_biology=False,
        ),
    }
)

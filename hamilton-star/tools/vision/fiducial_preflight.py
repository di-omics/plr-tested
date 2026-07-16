#!/usr/bin/env python3

"""Read-only fiducial pre-flight gate for the iSWAP choreography.

Phase 1 of tools/vision/iswap_vision_autonomy.md. Before a leg moves the arm,
look at one camera frame and answer a narrow question: is the expected labware /
lid actually present at its slot, and roughly where the geometry expects it? If
not, abort with a clear message instead of committing a grip into an empty slot
or onto a shifted lid. Those two misses ("empty pos4 after a success", "the lid
was shifted") cost repeated hand recovery during tuning; this catches them before
any motion.

This module reads pixels and returns a verdict. It NEVER moves the robot. Wiring
it into a hardware run means: capture a frame, call preflight(), and refuse to
run the leg if ok is False. The gate is only as good as its config and the camera
being fixed relative to the deck; treat a PASS as "nothing obviously wrong", not
a seating guarantee (seating verification is Phase 3).

Config (see example_fiducial_config_star.json):

    {
      "dict": "DICT_4X4_50",
      "marker_mm": 12.0,                     # optional; only used with --calib
      "slots": [
        {"name": "rail35_pos0_work_plate", "tag_id": 0,
         "expect_px": {"cx": 210, "cy": 170, "tol_px": 60}},
        {"name": "rail35_pos4_lid", "tag_id": 4,
         "expect_px": {"cx": 900, "cy": 170, "tol_px": 60}}
      ]
    }

Each slot may carry expect_px (pixel-space check, always available) and/or
expect_mm (pose-space check in mm, used only when a calibration is supplied). A
slot with neither expectation is a presence-only check.
"""

from pathlib import Path
import argparse
import json
import sys

import cv2

from fiducial_detect import (
    DEFAULT_DICT,
    build_detector,
    detect_frame,
    load_calibration,
    to_gray,
)


STATUS_PASS = "PASS"
STATUS_MISSING = "MISSING"
STATUS_SHIFTED = "SHIFTED"


def load_config(config_path):
    data = json.loads(Path(config_path).read_text())
    slots = data.get("slots")
    if not isinstance(slots, list) or not slots:
        raise RuntimeError(f"Config must contain a non-empty 'slots' list: {config_path}")

    cleaned = []
    for index, slot in enumerate(slots):
        try:
            name = str(slot["name"])
            tag_id = int(slot["tag_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(f"Invalid slot at index {index}: {slot}") from exc
        if not name:
            raise RuntimeError(f"Slot at index {index} has an empty name")
        entry = {"name": name, "tag_id": tag_id}
        if "expect_px" in slot:
            entry["expect_px"] = slot["expect_px"]
        if "expect_mm" in slot:
            entry["expect_mm"] = slot["expect_mm"]
        cleaned.append(entry)

    return {
        "dict": data.get("dict", DEFAULT_DICT),
        "marker_mm": data.get("marker_mm"),
        "slots": cleaned,
    }


def _check_px(expect, measured_center):
    cx = float(expect["cx"])
    cy = float(expect["cy"])
    tol = float(expect.get("tol_px", 40.0))
    dx = measured_center[0] - cx
    dy = measured_center[1] - cy
    dist = (dx * dx + dy * dy) ** 0.5
    return dist <= tol, (dx, dy), dist, tol


def _check_mm(expect, measured_pose):
    ex = float(expect["x"])
    ey = float(expect["y"])
    ez = float(expect["z"])
    tol = float(expect.get("tol_mm", 2.0))
    dx = measured_pose[0] - ex
    dy = measured_pose[1] - ey
    dz = measured_pose[2] - ez
    dist = (dx * dx + dy * dy + dz * dz) ** 0.5
    return dist <= tol, (dx, dy, dz), dist, tol


def preflight(image, config, detect=None, calibration=None):
    """Evaluate every configured slot against one frame.

    Returns {ok: bool, slots: [ per-slot report ]}. ok is True only when every
    slot is PASS. Pose-space (mm) checks run only when calibration is provided;
    otherwise expect_mm is skipped and the pixel check governs.
    """
    if detect is None:
        detect = build_detector(config["dict"])

    marker_mm = config.get("marker_mm") if calibration is not None else None
    markers = detect_frame(to_gray(image), detect, marker_mm, calibration)
    by_id = {m["id"]: m for m in markers}

    reports = []
    all_ok = True
    for slot in config["slots"]:
        name = slot["name"]
        tag_id = slot["tag_id"]
        marker = by_id.get(tag_id)

        if marker is None:
            reports.append(
                {
                    "name": name,
                    "tag_id": tag_id,
                    "status": STATUS_MISSING,
                    "measured_px": None,
                    "delta_px": None,
                    "measured_mm": None,
                    "delta_mm": None,
                    "message": f"{name}: MISSING (tag {tag_id} not detected) -> ABORT",
                }
            )
            all_ok = False
            continue

        status = STATUS_PASS
        messages = []
        delta_px = None
        delta_mm = None

        if "expect_px" in slot:
            ok, delta_px, dist, tol = _check_px(slot["expect_px"], marker["center"])
            if not ok:
                status = STATUS_SHIFTED
                messages.append(
                    f"px off by {dist:.1f} (dx={delta_px[0]:+.1f} dy={delta_px[1]:+.1f}, tol {tol:.0f})"
                )

        if "expect_mm" in slot and marker["pose_mm"] is not None:
            ok, delta_mm, dist, tol = _check_mm(slot["expect_mm"], marker["pose_mm"])
            if not ok:
                status = STATUS_SHIFTED
                messages.append(
                    f"mm off by {dist:.2f} (dx={delta_mm[0]:+.2f} dy={delta_mm[1]:+.2f} "
                    f"dz={delta_mm[2]:+.2f}, tol {tol:.1f})"
                )

        cx, cy = marker["center"]
        if status == STATUS_PASS:
            message = f"{name}: PASS (tag {tag_id} at {cx:.0f},{cy:.0f})"
        else:
            message = f"{name}: SHIFTED (tag {tag_id} at {cx:.0f},{cy:.0f}; " + "; ".join(messages) + ") -> ABORT"
            all_ok = False

        reports.append(
            {
                "name": name,
                "tag_id": tag_id,
                "status": status,
                "measured_px": marker["center"],
                "delta_px": delta_px,
                "measured_mm": marker["pose_mm"],
                "delta_mm": delta_mm,
                "message": message,
            }
        )

    return {"ok": all_ok, "slots": reports}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Read-only fiducial pre-flight check for a single frame. Exit 0 pass, 2 abort."
    )
    parser.add_argument("--frame", required=True, help="Image path (a single captured frame).")
    parser.add_argument("--config", required=True, help="Expected-fiducials JSON.")
    parser.add_argument("--calib", default=None, help="Camera calibration JSON (enables mm checks).")
    return parser.parse_args()


def main():
    args = parse_args()

    frame = cv2.imread(str(args.frame))
    if frame is None:
        raise RuntimeError(f"Could not read frame: {args.frame}")

    config = load_config(args.config)
    calibration = load_calibration(args.calib) if args.calib else None
    detect = build_detector(config["dict"])

    report = preflight(frame, config, detect=detect, calibration=calibration)
    for slot in report["slots"]:
        print(slot["message"])
    print(f"ok={report['ok']}")

    sys.exit(0 if report["ok"] else 2)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3

"""Offline self-test for the fiducial pre-flight gate. No robot, no camera.

Proves the sensor is trustworthy the way the design note asks (see the "smallest
experiment" in iswap_vision_autonomy.md): synthesize a frame with tags at known
positions, inject a known offset, and confirm the gate measures that offset back
out and aborts on it. Also confirms a removed tag aborts as MISSING.

Run directly:
    python test_fiducial_preflight.py
or under pytest (the test_* functions are collectable):
    pytest test_fiducial_preflight.py
"""

import numpy as np

from fiducial_detect import build_detector, detect_frame, generate_marker_image, to_gray
from fiducial_preflight import STATUS_MISSING, STATUS_PASS, STATUS_SHIFTED, preflight


DICT = "DICT_4X4_50"
FRAME_H = 720
FRAME_W = 1280
TAG_SIDE = 120
TAG_QUIET = 24

# id -> intended center (cx, cy) in the synthetic frame.
LAYOUT = {0: (210, 170), 2: (660, 170), 4: (900, 170)}


def _blank_frame():
    # Light gray background acts as extra quiet zone; markers carry their own white pad.
    return np.full((FRAME_H, FRAME_W), 235, dtype=np.uint8)


def _paste_tag(frame, tag_id, center):
    tile = generate_marker_image(DICT, tag_id, side_px=TAG_SIDE, border_quiet_px=TAG_QUIET)
    th, tw = tile.shape
    cx, cy = int(center[0]), int(center[1])
    x0 = cx - tw // 2
    y0 = cy - th // 2
    frame[y0 : y0 + th, x0 : x0 + tw] = tile
    return frame


def _synthetic_frame(layout):
    frame = _blank_frame()
    for tag_id, center in layout.items():
        _paste_tag(frame, tag_id, center)
    return frame


def _config(tol_px=40):
    return {
        "dict": DICT,
        "marker_mm": None,
        "slots": [
            {"name": f"slot_{tid}", "tag_id": tid,
             "expect_px": {"cx": c[0], "cy": c[1], "tol_px": tol_px}}
            for tid, c in LAYOUT.items()
        ],
    }


def test_detects_every_placed_tag_at_its_center():
    detect = build_detector(DICT)
    frame = _synthetic_frame(LAYOUT)
    markers = {m["id"]: m for m in detect_frame(to_gray(frame), detect)}
    assert set(markers) == set(LAYOUT), f"detected ids {set(markers)} != placed {set(LAYOUT)}"
    for tag_id, center in LAYOUT.items():
        cx, cy = markers[tag_id]["center"]
        assert abs(cx - center[0]) <= 2 and abs(cy - center[1]) <= 2, (
            f"tag {tag_id} center ({cx:.1f},{cy:.1f}) off from placed {center}"
        )


def test_all_present_and_aligned_passes():
    detect = build_detector(DICT)
    frame = _synthetic_frame(LAYOUT)
    report = preflight(frame, _config(), detect=detect)
    assert report["ok"] is True, [s["message"] for s in report["slots"]]
    assert all(s["status"] == STATUS_PASS for s in report["slots"])


def test_injected_offset_is_measured_back_and_aborts():
    # Inject a known +80 px x shift on tag 0 and confirm the gate reports ~ +80.
    detect = build_detector(DICT)
    shifted = dict(LAYOUT)
    shifted[0] = (LAYOUT[0][0] + 80, LAYOUT[0][1])
    frame = _synthetic_frame(shifted)

    report = preflight(frame, _config(tol_px=40), detect=detect)
    assert report["ok"] is False

    slot0 = next(s for s in report["slots"] if s["tag_id"] == 0)
    assert slot0["status"] == STATUS_SHIFTED, slot0["message"]
    dx, dy = slot0["delta_px"]
    assert abs(dx - 80) <= 3, f"measured dx {dx:.1f}, expected ~ +80"
    assert abs(dy) <= 3, f"measured dy {dy:.1f}, expected ~ 0"

    others = [s for s in report["slots"] if s["tag_id"] != 0]
    assert all(s["status"] == STATUS_PASS for s in others), [s["message"] for s in others]


def test_missing_tag_aborts_as_missing():
    detect = build_detector(DICT)
    partial = {tid: c for tid, c in LAYOUT.items() if tid != 4}
    frame = _synthetic_frame(partial)

    report = preflight(frame, _config(), detect=detect)
    assert report["ok"] is False
    slot4 = next(s for s in report["slots"] if s["tag_id"] == 4)
    assert slot4["status"] == STATUS_MISSING, slot4["message"]


def _run_all():
    tests = [
        test_detects_every_placed_tag_at_its_center,
        test_all_present_and_aligned_passes,
        test_injected_offset_is_measured_back_and_aborts,
        test_missing_tag_aborts_as_missing,
    ]
    passed = 0
    for fn in tests:
        fn()
        print(f"PASS {fn.__name__}")
        passed += 1
    print(f"ok={passed}/{len(tests)}")


if __name__ == "__main__":
    _run_all()

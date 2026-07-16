#!/usr/bin/env python3

"""Fiducial (ArUco) detection for the STAR deck.

Phase 1 of tools/vision/iswap_vision_autonomy.md: read-only perception. This
looks at pixels only and never moves the robot. It detects ArUco markers in a
frame or a video and reports, per marker: the id, the pixel center, the apparent
edge length in pixels, and (only when a camera calibration is supplied) the
6-DoF pose with the translation in mm.

Two things this module is careful about:

  1. OpenCV moved the ArUco API around. The class-based ArucoDetector arrived in
     4.7 and is the only path in 5.x; the flat cv2.aruco.detectMarkers function
     is the <= 4.6 path. build_detector() picks whichever the installed OpenCV
     exposes, so the same code runs on the Pi and on a host regardless of build.

  2. cv2.aruco.estimatePoseSingleMarkers was deprecated in 4.7 and removed in
     5.x. Pose here goes through cv2.solvePnP with SOLVEPNP_IPPE_SQUARE, which is
     stable across every version and returns tvec in the same unit as the marker
     side length (mm).

Nothing here is in the control loop. It is a sensor that reports; the pre-flight
gate (fiducial_preflight.py) is what turns a report into a go / abort decision.
"""

from pathlib import Path
import argparse
import json

import cv2
import numpy as np


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp"}
DEFAULT_DICT = "DICT_4X4_50"


def resolve_dictionary(dict_name):
    """Return the cv2.aruco predefined dictionary for a name like DICT_4X4_50."""
    const = getattr(cv2.aruco, dict_name, None)
    if const is None:
        raise RuntimeError(f"Unknown ArUco dictionary: {dict_name}")
    getter = getattr(cv2.aruco, "getPredefinedDictionary", None)
    if getter is not None:
        return getter(const)
    legacy = getattr(cv2.aruco, "Dictionary_get", None)
    if legacy is not None:
        return legacy(const)
    raise RuntimeError("This OpenCV build exposes no ArUco dictionary getter")


def build_detector(dict_name=DEFAULT_DICT):
    """Return a callable detect(gray) -> (corners, ids) across OpenCV versions.

    corners is a list of (1, 4, 2) float arrays and ids is an (N, 1) int array or
    None, matching the shapes both ArUco APIs already return.
    """
    dictionary = resolve_dictionary(dict_name)

    if hasattr(cv2.aruco, "ArucoDetector"):
        params = cv2.aruco.DetectorParameters()
        detector = cv2.aruco.ArucoDetector(dictionary, params)

        def detect(gray):
            corners, ids, _rejected = detector.detectMarkers(gray)
            return corners, ids

        return detect

    # Legacy <= 4.6 function API.
    params_ctor = getattr(cv2.aruco, "DetectorParameters_create", None)
    params = params_ctor() if params_ctor is not None else cv2.aruco.DetectorParameters()

    def detect(gray):
        corners, ids, _rejected = cv2.aruco.detectMarkers(gray, dictionary, parameters=params)
        return corners, ids

    return detect


def to_gray(image):
    if image.ndim == 2:
        return image
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def marker_center(corner):
    """Pixel center (cx, cy) of one marker given its (4, 2) corner array."""
    pts = np.asarray(corner, dtype=np.float64).reshape(4, 2)
    return float(pts[:, 0].mean()), float(pts[:, 1].mean())


def marker_edge_px(corner):
    """Mean side length in pixels of one marker (a rough distance/scale proxy)."""
    pts = np.asarray(corner, dtype=np.float64).reshape(4, 2)
    sides = [
        np.linalg.norm(pts[0] - pts[1]),
        np.linalg.norm(pts[1] - pts[2]),
        np.linalg.norm(pts[2] - pts[3]),
        np.linalg.norm(pts[3] - pts[0]),
    ]
    return float(np.mean(sides))


def load_calibration(calib_path):
    """Load {camera_matrix: 3x3, dist_coeffs: [...]} from JSON."""
    data = json.loads(Path(calib_path).read_text())
    camera_matrix = np.asarray(data["camera_matrix"], dtype=np.float64)
    dist_coeffs = np.asarray(data.get("dist_coeffs", [0, 0, 0, 0, 0]), dtype=np.float64)
    if camera_matrix.shape != (3, 3):
        raise RuntimeError("camera_matrix must be 3x3")
    return camera_matrix, dist_coeffs


def estimate_pose(corner, marker_mm, camera_matrix, dist_coeffs):
    """Return (rvec, tvec) for one marker via solvePnP. tvec is in mm.

    Replaces the removed estimatePoseSingleMarkers. Object points are the marker
    corners in its own frame, ordered to match ArUco's corner order
    (top-left, top-right, bottom-right, bottom-left), centered on the marker.
    """
    half = float(marker_mm) / 2.0
    object_points = np.array(
        [[-half, half, 0.0], [half, half, 0.0], [half, -half, 0.0], [-half, -half, 0.0]],
        dtype=np.float64,
    )
    image_points = np.asarray(corner, dtype=np.float64).reshape(4, 2)
    flags = getattr(cv2, "SOLVEPNP_IPPE_SQUARE", cv2.SOLVEPNP_ITERATIVE)
    ok, rvec, tvec = cv2.solvePnP(
        object_points, image_points, camera_matrix, dist_coeffs, flags=flags
    )
    if not ok:
        return None, None
    return rvec, tvec


def detect_frame(gray, detect, marker_mm=None, calibration=None):
    """Detect markers in one grayscale frame.

    Returns a list of dicts, one per marker:
        {id, center: (cx, cy), edge_px, corners: 4x2 list,
         pose_mm: (x, y, z) or None}
    pose_mm is populated only when both marker_mm and calibration are given.
    """
    corners, ids = detect(gray)
    results = []
    if ids is None:
        return results

    camera_matrix = dist_coeffs = None
    if calibration is not None:
        camera_matrix, dist_coeffs = calibration

    for corner, marker_id in zip(corners, ids.flatten()):
        pts = np.asarray(corner, dtype=np.float64).reshape(4, 2)
        entry = {
            "id": int(marker_id),
            "center": marker_center(corner),
            "edge_px": marker_edge_px(corner),
            "corners": pts.tolist(),
            "pose_mm": None,
        }
        if marker_mm is not None and camera_matrix is not None:
            _rvec, tvec = estimate_pose(corner, marker_mm, camera_matrix, dist_coeffs)
            if tvec is not None:
                t = np.asarray(tvec, dtype=float).reshape(-1)
                entry["pose_mm"] = (float(t[0]), float(t[1]), float(t[2]))
        results.append(entry)

    return results


def generate_marker_image(dict_name, marker_id, side_px=600, border_quiet_px=80):
    """Render a printable marker: black-bordered tag on a white quiet zone.

    The quiet zone matters: ArUco needs white around the tag's black border to
    detect it, so a bare marker pasted edge-to-edge on a dark surface will not be
    found. This returns a white canvas with the marker centered.
    """
    dictionary = resolve_dictionary(dict_name)
    generator = getattr(cv2.aruco, "generateImageMarker", None) or getattr(
        cv2.aruco, "drawMarker", None
    )
    if generator is None:
        raise RuntimeError("This OpenCV build exposes no ArUco marker generator")
    marker = generator(dictionary, int(marker_id), int(side_px))

    pad = int(border_quiet_px)
    canvas = np.full((side_px + 2 * pad, side_px + 2 * pad), 255, dtype=np.uint8)
    canvas[pad : pad + side_px, pad : pad + side_px] = marker
    return canvas


def iter_frames(source_path, every_sec=None):
    """Yield (label, bgr_frame) from an image file or a video file.

    For an image, yields one frame. For a video, yields one frame every
    every_sec seconds (default: every frame if None).
    """
    path = Path(source_path)
    if path.suffix.lower() in IMAGE_SUFFIXES:
        image = cv2.imread(str(path))
        if image is None:
            raise RuntimeError(f"Could not read image: {path}")
        yield path.name, image
        return

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    step = max(1, int(fps * every_sec)) if (every_sec and fps) else 1
    idx = 0
    try:
        while True:
            ok = cap.grab()
            if not ok:
                break
            if idx % step == 0:
                ok, frame = cap.retrieve()
                if ok:
                    t_sec = idx / fps if fps else 0.0
                    yield f"t{t_sec:08.2f}s", frame
            idx += 1
    finally:
        cap.release()


def parse_args():
    parser = argparse.ArgumentParser(
        description="Detect ArUco fiducials in a frame or video (read-only; no robot motion)."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_detect = sub.add_parser("detect", help="Detect markers in an image or video.")
    p_detect.add_argument("source", help="Image (.jpg/.png) or video (.mp4) path.")
    p_detect.add_argument("--dict", default=DEFAULT_DICT, help="ArUco dictionary, e.g. DICT_4X4_50.")
    p_detect.add_argument("--every-sec", type=float, default=None, help="For video: sample interval.")
    p_detect.add_argument("--calib", default=None, help="Camera calibration JSON for mm pose.")
    p_detect.add_argument("--marker-mm", type=float, default=None, help="Marker side length in mm.")

    p_make = sub.add_parser("make-marker", help="Render a printable marker PNG.")
    p_make.add_argument("marker_id", type=int)
    p_make.add_argument("--out", required=True, help="Output PNG path.")
    p_make.add_argument("--dict", default=DEFAULT_DICT)
    p_make.add_argument("--side-px", type=int, default=600)
    p_make.add_argument("--quiet-px", type=int, default=80)

    return parser.parse_args()


def main():
    args = parse_args()

    if args.command == "make-marker":
        image = generate_marker_image(args.dict, args.marker_id, args.side_px, args.quiet_px)
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(out), image)
        print(f"dict={args.dict}")
        print(f"marker_id={args.marker_id}")
        print(out)
        return

    detect = build_detector(args.dict)
    calibration = load_calibration(args.calib) if args.calib else None

    total_markers = 0
    total_frames = 0
    for label, frame in iter_frames(args.source, args.every_sec):
        total_frames += 1
        markers = detect_frame(to_gray(frame), detect, args.marker_mm, calibration)
        total_markers += len(markers)
        for m in markers:
            cx, cy = m["center"]
            line = f"{label} id={m['id']} center=({cx:.1f},{cy:.1f}) edge_px={m['edge_px']:.1f}"
            if m["pose_mm"] is not None:
                x, y, z = m["pose_mm"]
                line += f" pose_mm=({x:.1f},{y:.1f},{z:.1f})"
            print(line)

    print(f"frames={total_frames}")
    print(f"markers={total_markers}")


if __name__ == "__main__":
    main()

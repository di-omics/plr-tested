#!/usr/bin/env python3

from pathlib import Path
import argparse
import csv
import json

import cv2
import numpy as np


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}
CSV_FIELDS = [
    "frame_file",
    "frame_index",
    "roi_name",
    "mean_brightness",
    "absdiff_mean",
    "absdiff_p95",
]


def find_frames(frames_dir):
    return sorted(
        path
        for path in frames_dir.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    )


def load_rois(roi_config):
    data = json.loads(roi_config.read_text())
    rois = data.get("rois")
    if not isinstance(rois, list) or not rois:
        raise RuntimeError(f"ROI config must contain a non-empty 'rois' list: {roi_config}")

    cleaned = []
    for index, roi in enumerate(rois):
        try:
            name = str(roi["name"])
            x = int(roi["x"])
            y = int(roi["y"])
            width = int(roi["w"])
            height = int(roi["h"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(f"Invalid ROI at index {index}: {roi}") from exc

        if not name:
            raise RuntimeError(f"ROI at index {index} has an empty name")
        if width <= 0 or height <= 0:
            raise RuntimeError(f"ROI '{name}' must have positive w/h")

        cleaned.append({"name": name, "x": x, "y": y, "w": width, "h": height})

    return cleaned


def crop_roi(gray, roi):
    frame_height, frame_width = gray.shape[:2]
    x0 = max(0, roi["x"])
    y0 = max(0, roi["y"])
    x1 = min(frame_width, roi["x"] + roi["w"])
    y1 = min(frame_height, roi["y"] + roi["h"])

    if x1 <= x0 or y1 <= y0:
        return None
    return gray[y0:y1, x0:x1]


def motion_stats(current, previous):
    if previous is None:
        return 0.0, 0.0

    height = min(current.shape[0], previous.shape[0])
    width = min(current.shape[1], previous.shape[1])
    if height <= 0 or width <= 0:
        return 0.0, 0.0

    diff = cv2.absdiff(current[:height, :width], previous[:height, :width])
    return float(np.mean(diff)), float(np.percentile(diff, 95))


def parse_args():
    parser = argparse.ArgumentParser(
        description="Measure brightness and frame-to-frame motion in configured ROIs."
    )
    parser.add_argument("--frames-dir", required=True)
    parser.add_argument("--roi-config", required=True)
    parser.add_argument("--output-csv", required=True)
    return parser.parse_args()


def main():
    args = parse_args()

    frames_dir = Path(args.frames_dir)
    roi_config = Path(args.roi_config)
    output_csv = Path(args.output_csv)

    if not frames_dir.exists():
        raise RuntimeError(f"Frames directory does not exist: {frames_dir}")
    if not roi_config.exists():
        raise RuntimeError(f"ROI config does not exist: {roi_config}")

    frame_paths = find_frames(frames_dir)
    if not frame_paths:
        raise RuntimeError(f"No jpg/png frames found in {frames_dir}")

    rois = load_rois(roi_config)
    previous_by_roi = {}

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()

        for frame_index, frame_path in enumerate(frame_paths):
            gray = cv2.imread(str(frame_path), cv2.IMREAD_GRAYSCALE)
            if gray is None:
                raise RuntimeError(f"Could not read frame: {frame_path}")

            for roi in rois:
                roi_name = roi["name"]
                current = crop_roi(gray, roi)
                if current is None:
                    mean_brightness = 0.0
                    absdiff_mean = 0.0
                    absdiff_p95 = 0.0
                    previous_by_roi[roi_name] = None
                else:
                    mean_brightness = float(np.mean(current))
                    absdiff_mean, absdiff_p95 = motion_stats(
                        current, previous_by_roi.get(roi_name)
                    )
                    previous_by_roi[roi_name] = current.copy()

                writer.writerow(
                    {
                        "frame_file": frame_path.name,
                        "frame_index": frame_index,
                        "roi_name": roi_name,
                        "mean_brightness": f"{mean_brightness:.4f}",
                        "absdiff_mean": f"{absdiff_mean:.4f}",
                        "absdiff_p95": f"{absdiff_p95:.4f}",
                    }
                )

    print(f"frames={len(frame_paths)}")
    print(f"rois={len(rois)}")
    print(output_csv)


if __name__ == "__main__":
    main()

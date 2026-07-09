#!/usr/bin/env python3

from pathlib import Path
import argparse
import csv
import json

import cv2


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


def find_frames(frames_dir):
    return sorted(
        path
        for path in frames_dir.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    )


def read_motion_summary(roi_csv):
    roi_names = set()
    max_motion_roi = None
    max_motion_score = 0.0
    row_count = 0

    with roi_csv.open(newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            row_count += 1
            roi_name = row.get("roi_name", "")
            if roi_name:
                roi_names.add(roi_name)

            try:
                score = float(row.get("absdiff_p95", 0.0) or 0.0)
            except ValueError:
                score = 0.0

            if max_motion_roi is None or score > max_motion_score:
                max_motion_roi = roi_name or None
                max_motion_score = score

    return {
        "roi_count": len(roi_names),
        "max_motion_roi": max_motion_roi,
        "max_motion_score": max_motion_score,
        "row_count": row_count,
    }


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate a small offline dashboard summary from frames and ROI CSV."
    )
    parser.add_argument("--frames-dir", required=True)
    parser.add_argument("--roi-csv", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def main():
    args = parse_args()

    frames_dir = Path(args.frames_dir)
    roi_csv = Path(args.roi_csv)
    output_dir = Path(args.output_dir)

    if not frames_dir.exists():
        raise RuntimeError(f"Frames directory does not exist: {frames_dir}")
    if not roi_csv.exists():
        raise RuntimeError(f"ROI CSV does not exist: {roi_csv}")

    frame_paths = find_frames(frames_dir)
    if not frame_paths:
        raise RuntimeError(f"No jpg/png frames found in {frames_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)

    latest_frame = frame_paths[-1]
    latest_image = cv2.imread(str(latest_frame))
    if latest_image is None:
        raise RuntimeError(f"Could not read latest frame: {latest_frame}")

    latest_output = output_dir / "latest.jpg"
    if not cv2.imwrite(str(latest_output), latest_image):
        raise RuntimeError(f"Could not write latest frame copy: {latest_output}")

    motion_summary = read_motion_summary(roi_csv)
    notes = [
        "Offline summary generated from extracted frames and ROI motion CSV.",
        "max_motion_score is the highest absdiff_p95 value in the ROI CSV.",
    ]
    if motion_summary["row_count"] == 0:
        notes.append("No ROI motion rows were found in the CSV.")

    summary = {
        "latest_frame": latest_frame.name,
        "frame_count": len(frame_paths),
        "roi_count": motion_summary["roi_count"],
        "max_motion_roi": motion_summary["max_motion_roi"],
        "max_motion_score": motion_summary["max_motion_score"],
        "notes": notes,
    }

    summary_path = output_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")

    print(latest_output)
    print(summary_path)


if __name__ == "__main__":
    main()

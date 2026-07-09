#!/usr/bin/env python3

from pathlib import Path
import argparse

import cv2
import numpy as np


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


def find_frames(frames_dir):
    return sorted(
        path
        for path in frames_dir.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    )


def resize_to_width(image, width):
    height, current_width = image.shape[:2]
    if height <= 0 or current_width <= 0:
        raise RuntimeError("Encountered image with invalid dimensions")

    scale = width / current_width
    resized_height = max(1, int(round(height * scale)))
    interpolation = cv2.INTER_AREA if width < current_width else cv2.INTER_LINEAR
    return cv2.resize(image, (width, resized_height), interpolation=interpolation)


def fit_label(label, max_width, font, scale, thickness):
    if cv2.getTextSize(label, font, scale, thickness)[0][0] <= max_width:
        return label

    suffix = "..."
    trimmed = label
    while len(trimmed) > len(suffix):
        trimmed = trimmed[:-1]
        candidate = trimmed + suffix
        if cv2.getTextSize(candidate, font, scale, thickness)[0][0] <= max_width:
            return candidate

    return suffix


def parse_args():
    parser = argparse.ArgumentParser(
        description="Create a labeled contact sheet from extracted video frames."
    )
    parser.add_argument("--frames-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--thumb-width", type=int, default=320)
    parser.add_argument("--cols", type=int, default=5)
    parser.add_argument("--max-frames", type=int, default=40)
    return parser.parse_args()


def main():
    args = parse_args()

    frames_dir = Path(args.frames_dir)
    output = Path(args.output)

    if args.thumb_width <= 0:
        raise RuntimeError("--thumb-width must be greater than 0")
    if args.cols <= 0:
        raise RuntimeError("--cols must be greater than 0")
    if args.max_frames <= 0:
        raise RuntimeError("--max-frames must be greater than 0")
    if not frames_dir.exists():
        raise RuntimeError(f"Frames directory does not exist: {frames_dir}")

    frame_paths = find_frames(frames_dir)[: args.max_frames]
    if not frame_paths:
        raise RuntimeError(f"No jpg/png frames found in {frames_dir}")

    thumbnails = []
    for frame_path in frame_paths:
        image = cv2.imread(str(frame_path))
        if image is None:
            raise RuntimeError(f"Could not read frame: {frame_path}")
        thumbnails.append((frame_path.name, resize_to_width(image, args.thumb_width)))

    max_thumb_height = max(thumb.shape[0] for _, thumb in thumbnails)
    label_height = 34
    tile_width = args.thumb_width
    tile_height = max_thumb_height + label_height
    rows = (len(thumbnails) + args.cols - 1) // args.cols

    sheet = np.full(
        (rows * tile_height, args.cols * tile_width, 3), 255, dtype=np.uint8
    )

    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.55
    thickness = 1

    for index, (label, thumb) in enumerate(thumbnails):
        row = index // args.cols
        col = index % args.cols
        x0 = col * tile_width
        y0 = row * tile_height

        thumb_height = thumb.shape[0]
        sheet[y0 : y0 + thumb_height, x0 : x0 + tile_width] = thumb
        sheet[
            y0 + max_thumb_height : y0 + tile_height,
            x0 : x0 + tile_width,
        ] = 245

        display_label = fit_label(label, tile_width - 12, font, font_scale, thickness)
        cv2.putText(
            sheet,
            display_label,
            (x0 + 6, y0 + max_thumb_height + 22),
            font,
            font_scale,
            (20, 20, 20),
            thickness,
            cv2.LINE_AA,
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output), sheet):
        raise RuntimeError(f"Could not write contact sheet: {output}")

    print(f"frames={len(thumbnails)}")
    print(output)


if __name__ == "__main__":
    main()

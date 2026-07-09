#!/usr/bin/env python3

from pathlib import Path
import argparse
import cv2


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("video")
    parser.add_argument("--outdir", default="frames")
    parser.add_argument("--every-sec", type=float, default=5.0)
    parser.add_argument("--prefix", default="frame")
    args = parser.parse_args()

    video = Path(args.video)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open {video}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    step = max(1, int(fps * args.every_sec))

    print(f"video={video}")
    print(f"fps={fps}")
    print(f"frames={total}")
    print(f"extracting every {step} frames / {args.every_sec} sec")

    idx = 0
    saved = 0

    while True:
        ok = cap.grab()
        if not ok:
            break

        if idx % step == 0:
            ok, frame = cap.retrieve()
            if ok:
                t_sec = idx / fps if fps else 0
                path = outdir / f"{args.prefix}_{saved:04d}_t{t_sec:08.2f}s.jpg"
                cv2.imwrite(str(path), frame)
                print(path)
                saved += 1

        idx += 1

    cap.release()
    print(f"saved={saved}")


if __name__ == "__main__":
    main()

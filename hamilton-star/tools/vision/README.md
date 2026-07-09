# STAR vision tools

Offline computer-vision helpers for the Hamilton STAR deck observation.

Initial use case:
- Analyze GoPro protocol videos offline.
- Extract timestamped frames for quick review and ROI calibration.
- Define deck ROIs for plate/tip/reservoir/mag-block motion checks.
- Keep this separate from active PyLabRobot protocol scripts until validated.

Do not commit raw GoPro videos or extracted frames to this repo.

## Offline GoPro workflow

From a local video file:

    python tools/vision/extract_frames.py star_protocol_001.mp4 --outdir frames --every-sec 10 --prefix star_protocol_001

Example GoPro setup:

    mkdir -p ~/Desktop/star_gopro
    cp /Volumes/Untitled/DCIM/100GOPRO/GH020008.MP4 ~/Desktop/star_gopro/star_protocol_001.mp4

    cd ~/Desktop/star_gopro
    python3 -m venv cv_env
    source cv_env/bin/activate
    python -m pip install opencv-python numpy

### 1. Extract frames from a 4x video

For a GoPro video already sped up to 4x, extracting every 2.5 video seconds samples about every 10 seconds of real protocol time:

    python ~/Desktop/star/tools/vision/extract_frames.py star_protocol_001.mp4 --outdir frames --every-sec 2.5 --prefix star_protocol_001

For normal-speed video, use the real sampling interval directly:

    python ~/Desktop/star/tools/vision/extract_frames.py star_protocol_001.mp4 --outdir frames --every-sec 10 --prefix star_protocol_001

### 2. Make a contact sheet

Create a tiled review image with filenames for quick calibration:

    python ~/Desktop/star/tools/vision/make_contact_sheet.py --frames-dir frames --output contact_sheet.jpg --thumb-width 320 --cols 5 --max-frames 40

### 3. Edit the ROI config

Copy the example config and calibrate every `x`, `y`, `w`, and `h` against the contact sheet or a representative frame:

    cp ~/Desktop/star/tools/vision/example_roi_config_star.json roi_config_star.json

The example coordinates are placeholders only. They must be adjusted for the camera mount, GoPro crop, deck lighting, and video resolution.

### 4. Analyze ROI motion

Measure per-frame brightness and frame-to-frame absolute differences for each configured ROI:

    python ~/Desktop/star/tools/vision/analyze_roi_motion.py --frames-dir frames --roi-config roi_config_star.json --output-csv roi_motion.csv

The first frame for each ROI has `absdiff_mean=0` and `absdiff_p95=0` because there is no previous frame to compare.

### 5. Generate dashboard summary

Write a small output directory with the latest frame copy and a JSON summary:

    python ~/Desktop/star/tools/vision/vision_dashboard_summary.py --frames-dir frames --roi-csv roi_motion.csv --output-dir vision_dashboard

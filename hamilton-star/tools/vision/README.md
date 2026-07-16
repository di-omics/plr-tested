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

## Phase 1: fiducial pre-flight (read-only)

`fiducial_detect.py` + `fiducial_preflight.py` are the first step of the CV plan
in `iswap_vision_autonomy.md`: before a leg moves the arm, look at one camera
frame and confirm the expected labware / lid is present at its slot, roughly
where the geometry expects it. It reads pixels only and never moves the robot.
This catches the "empty pos4" and "shifted lid" misses that cost hand recovery
during tuning.

It works today against synthetic frames and any footage; going live on the deck
needs three physical things first: (1) an ArUco tag on each slot to be checked
(and on the iSWAP gripper for Phase 2), (2) the overhead camera fixed relative to
the deck, (3) `cx`/`cy` in the config calibrated against a representative frame.
mm-space pose (`--calib`) additionally needs a camera calibration; pixel-space
presence and shift checks work without one.

The code runs on both the OpenCV >= 4.7 `ArucoDetector` API and the legacy <= 4.6 function
API, so the same file works on the Pi and on a host.

### Two things measured on the real deck, before you fit any tags

Both came from running the real detector over 20 min of real footage; neither is a
preference.

1. **Do not run 4x4 dictionaries on this deck. Use AprilTag 36h11.** Over 77 frames x 10
   dictionaries (770 detector calls) the 4x4 families returned 4 spurious ids and nothing
   else did. They lock onto the **cooling-block fin stripes**, which read as a 4x4 code. A
   dense 750-frame sweep gave 5 mutually-inconsistent ids at max persistence 15/750 -- noise,
   where a real tag holds one id in nearly every frame. `DICT_5X5_*`, `DICT_6X6_*` and the
   AprilTag families all returned a clean 0/770. `example_fiducial_config_star.json` now
   defaults to `DICT_APRILTAG_36h11` for this reason. `fiducial_detect.py`'s module default
   is still `DICT_4X4_50` because it is a generic library default, not a deck setting -- pass
   the dictionary explicitly, or take it from the config.

2. **A flat 12 mm tag does not work on the current camera, and megapixels will not save it.**
   Measured scale on the labware row is 2.63 px/mm. A 12 mm tag is ~31.6 px facing the
   camera (5.3 px/module, fine), but flat on the deck at the camera's ~28 deg grazing view it
   is ~31.6 x 14.6 px = **2.4 px/module**, under the ~4 px/module floor measured from the real
   point-spread (sigma 1.56 px across 67 step edges) and confirmed by pasting real tags into
   real frames with matched blur and codec loss. **Flat tags on this camera need >= 20 mm.**
   It fails on grazing incidence, not resolution. A near-nadir camera moves every tag from the
   flat case to the square-on case and drops the floor to ~10 mm, which is the quantitative
   argument for fitting that camera first.

### 1. Print the tags to place on the deck

    python tools/vision/fiducial_detect.py make-marker 0 --out tag0_pos0.png
    python tools/vision/fiducial_detect.py make-marker 4 --out tag4_lid.png

Each PNG has a white quiet zone already (ArUco needs white around the black
border or it will not detect). Print, mount one per slot, keep the id-to-slot
mapping.

### 2. Configure the expected tags

Copy the example and set each slot's `tag_id` and expected pixel center against a
representative frame:

    cp tools/vision/example_fiducial_config_star.json tools/vision/fiducial_config_star.json

### 3. Detect / sanity-check a frame or video

    python tools/vision/fiducial_detect.py detect frame.jpg
    python tools/vision/fiducial_detect.py detect run.mp4 --every-sec 2.5

### 4. Run the pre-flight gate on one captured frame

    python tools/vision/fiducial_preflight.py --frame frame.jpg --config tools/vision/fiducial_config_star.json

Exit code is 0 when every slot passes and 2 on any MISSING or SHIFTED slot, so a
runner can gate a leg on it. Add `--calib calib.json` to also enforce mm-space
pose where a slot defines `expect_mm`. To wire it into a run, import
`preflight()` and refuse the leg when `ok` is False:

    from fiducial_preflight import build_detector, load_config, preflight
    config = load_config("tools/vision/fiducial_config_star.json")
    detect = build_detector(config["dict"])
    report = preflight(frame, config, detect=detect)
    if not report["ok"]:
        raise RuntimeError("pre-flight abort: " + "; ".join(
            s["message"] for s in report["slots"] if s["status"] != "PASS"))

### 5. Self-test (offline, no robot, no camera)

    python tools/vision/test_fiducial_preflight.py

Synthesizes tags, injects a known offset, and confirms the gate measures it back
and aborts on a missing tag. This is the "inject a known offset, measure it back"
trust check from the design note, done fully in software.

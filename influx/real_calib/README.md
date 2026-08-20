# Real Camera Calibration Utilities

This directory contains the InFlux workflow for processing real calibration recordings and producing calibration results for each lens setting. These results are later used for representative trial selection and lookup table construction.

Complete the installation and path configuration in the [InFlux Utility Scripts guide](../README.md) before using this workflow.

## Supported Scope

The primary supported workflow uses AprilGrid boards recorded with an ARRI camera and an InFlux lens configuration. The pipeline extracts frames and metadata, detects the target in every frame, selects a subset of the frames using adaptive non-maximal suppression based on target detection quality, runs repeated Kalibr calibration trials, and writes one parsed result JSON per trial.

This directory also contains LED flash and RTK preprocessing scripts used to generate 2D-3D correspondences from drone calibration experiments.

## Files

| File | Role |
|---|---|
| `copy_from_camera_card.py` | Copy ARRIRAW MXF clips, read metadata from one frame, map clips to generated experiment settings, hardlink clips into experiment folders, and append processing commands to the queue |
| `run_from_queue.sh` | Activate the `influx` environment and execute trusted commands from the configured queue |
| `process_video_by_detections.py` | Main entrypoint for frame and metadata extraction, target detection, frame selection, repeated Kalibr calibration, and result parsing |
| `process_mxf.sh` | Invoke `art-cmd` to extract MXF frames and metadata |
| `write_aprilgrid_config.py` | Write the AprilGrid `target.yaml` used by Kalibr |
| `select_frames_by_anms.py` | Select a subset of high quality frames for downstream camera calibration based on target detection quality |
| `utils.py` | Shared paths, completion flags, image size lookup, cached observation filtering, and subprocess helpers |
| `hue_calib.py` | LED flash detector used to generate 2D observations from raw drone calibration footage |

## Prerequisites

This workflow requires the external dependencies described in the [InFlux Utility Scripts guide](../README.md):

- Docker
- The modified Kalibr image named `kalibr:latest`
- `rsync` for camera card ingestion
- ARRI Reference Tool 0.3.0 with `art-cmd` available on `PATH` for ARRIRAW MXF frame and metadata extraction

Run the commands in this guide from `influx/real_calib/`.

## Configure the Workflow

Edit [`../config.yaml`](../config.yaml) before running the pipeline. The `real_calib` section defines the main media, experiment, and queue paths used by this workflow:

```yaml
real_calib:
  VIDEO_DEST_DIR: /path/to/copied/calibration/videos
  EXP_ROOT: /path/to/calibration/experiments
  QUEUE_FILE: /path/to/queue.txt
  COMPLETED_FILE: /path/to/completed.txt
  ONHOLD_FILE: /path/to/onhold.txt
  SKIP_IF_FAIL_FLAG: /path/to/skip
```

The same configuration file also defines the path used to generate and load real calibration setting files:

```yaml
LENS_SETTINGS_DIR: /path/to/generated/real/lens/settings
```

The following camera, lens, sampling, and metadata fields are also used by `select_experiments.py`, camera card ingestion, metadata parsing, board assignment, and focal length initialization:

```yaml
cameras:
  arri:
    sensor_width_mm: 28.25
    sensor_height_mm: 18.17
    sensor_resolution_x: 3424
    sensor_resolution_y: 2202
    resolution_percentage: 100

lenses:
  <lens_identifier>:
    min_lens_focal_length: <millimeters>
    max_lens_focal_length: <millimeters>
    min_focus_distance: <millimeters>
    lens_name: <metadata/display name>
    max_board_size: <meters>
    soft_min_focus_distance: <millimeters>

n_focus_distance_samples: 9

metadata_lens_mapping:
  <ARRI lens model string>: <base lens identifier>
```

Use `config.yaml` as the primary source of truth for the camera card and queue-driven workflow. Keep `VIDEO_DEST_DIR`, `EXP_ROOT`, `LENS_SETTINGS_DIR`, and the queue paths coordinated rather than overriding only one script with an unrelated path.

## Step 1: Generate Real Calibration Settings

From `influx/`, run `select_experiments.py` in empirical mode:

```bash
cd ..
python select_experiments.py --camera arri --lens canon17 --empirical-mode
cd real_calib
```

Replace `canon17` with one of the lens identifiers configured in `config.yaml`:

```text
canon17
premista80
canon17v2
premista80v2
```

The command writes `<lens>.json` to `LENS_SETTINGS_DIR`. Each experiment entry specifies a recorded lens focal length in millimeters, a focus distance in millimeters, and either an AprilGrid board size or the special value `drone`.

## Step 2: Record Calibration Media

### Board-based Calibration

For each generated setting, record the specified board size at the corresponding lens focal length and focus distance. During a recording, hold the board briefly in a useful pose, then move it quickly to a different pose. Variation in target visibility, pose, and motion blur is used by the downstream frame selection step.

A single setting may be recorded across multiple clips. The camera card ingestion script can either keep duplicate settings in separate experiment folders or combine multiple clips in one experiment.

### Drone-based Calibration

The drone-based workflow expects footage of a flashing LED target and an RTK file at:

```text
<experiment>/drone_rtk/flash_rtk.json
```

The JSON file contains positions in temporal flash order:

```json
[
  {
    "x": 1.0,
    "y": 2.0,
    "alt": 0.5,
    "timestamp": 1740989380.4
  }
]
```

All `x`, `y`, and `alt` values must use the same Cartesian reference frame and are interpreted in meters. The ordering of the entries must match the temporal ordering of the LED flashes in the footage.

The detector identifies the LED observations, keeps the first detection in each flash interval, converts the 2D coordinates to Kalibr's pixel center convention, and pairs the resulting observations with the RTK positions. In Kalibr's convention, coordinate `(0, 0)` refers to the center of the top-left pixel.

## Step 3: Copy and Organize Camera Card Media

`copy_from_camera_card.py` copies ARRIRAW MXF clips into a timestamped landing directory, extracts metadata from one frame of each clip with `art-cmd`, assigns each recording to the nearest generated lens setting, hardlinks the clip into an experiment folder, and appends a processing command to the configured queue.

A typical invocation uses the destination, experiment root, and queue paths from `config.yaml`:

```bash
python copy_from_camera_card.py \
  --src /path/to/mounted/camera/card \
  --lens-name-suffix v2 \
  --allow-dup-settings \
  --merge-same-setting-videos \
  --num_trials 100
```

Important options:

- `--src`: Mounted camera card directory. Required unless requeuing a previously copied timestamp directory.
- `--lens-name-suffix`: Distinguishes versions of the same lens family. Omit this flag for the original InFlux lens settings and use `v2` for the corresponding InFlux++ lens settings.
- `--allow-dup-settings`: Permits multiple recordings to map to the same generated setting.
- `--merge-same-setting-videos`: Places multiple recordings for the same setting in one experiment so their frames are combined before calibration.
- `--num_trials`: Number of Kalibr trials written into each queued command.
- `--skip`: One or more 1-indexed source card clip positions to omit after filename sorting.
- `--settings-path`: Use a custom generated settings JSON instead of the default `<lens>.json`.
- `--no-hardlink`: Print video-to-experiment mappings without creating experiment hardlinks or queue commands.
- `--no-rsync --timestamp <timestamp>`: Reuse an already copied timestamp directory and rebuild its experiment mapping and queue commands.
- `--wipe`: Prompt before deleting the contents of the source camera card directory.

The generated experiment folders are placed under:

```text
<EXP_ROOT>/<lens>/<experiment_name>/
```

Experiment names encode the focal length index, focus distance index, and lens identifier. When duplicate settings are allowed without merging, additional recordings receive an `_additional_trial_<n>` suffix.

For drone-based experiments, place the corresponding `flash_rtk.json` file into the generated experiment before processing:

```text
<EXP_ROOT>/<lens>/<experiment_name>/
├── drone_rtk/
│   └── flash_rtk.json
└── raw_data/
    └── <video>.mxf
```

## Step 4: Run the Queue

Start the queue runner from this directory:

```bash
./run_from_queue.sh
```

The script activates the Conda environment named `influx`, reads the queue paths from `../config.yaml`, and repeatedly executes the first line of `QUEUE_FILE`.

Queue lines are trusted shell commands and are executed with `eval`.

When a command succeeds, it is removed from the queue and appended to `COMPLETED_FILE`. Failure behavior depends on `SKIP_IF_FAIL_FLAG`:

- If the skip file does not exist, the failed command remains at the front of the queue and the runner waits for confirmation before retrying.
- If the skip file exists, the failed command is appended to `ONHOLD_FILE`, removed from the active queue, and processing continues.

Enable or disable skip-on-failure while the queue is running:

```bash
touch /path/from/config/to/skip
rm /path/from/config/to/skip
```

## Direct Processing

`process_video_by_detections.py` can also be run directly.

### Process an Existing Experiment Folder

```bash
python process_video_by_detections.py \
  --lens canon17 \
  --exp_name real_exp_zoom_0_focus_distance_0_canon17 \
  --num_trials 100
```

When `--exp_name` is supplied without `--video`, the script reads MXF, MOV, or MP4 files from that experiment's `raw_data/` directory. Use `--allow_duplicates False` to require exactly one media file in the experiment.

### Process One Media File Directly

For an MXF file, the initial focal length estimate is derived from the recorded lens focal length, focus distance, and configured ARRI camera properties using a thin lens approximation:

```bash
python process_video_by_detections.py \
  --lens canon17 \
  --video /absolute/path/to/calibration.mxf \
  --board_size 0.8 \
  --num_trials 100
```

For an MP4 or MOV file, provide an explicit focal length estimate in pixels because the ARRI lens metadata used by the initialization is unavailable:

```bash
python process_video_by_detections.py \
  --lens canon17 \
  --video /absolute/path/to/calibration.mov \
  --board_size 0.8 \
  --focal_length_guess 2100 \
  --num_trials 100
```

When no experiment name is supplied, the media file stem becomes the experiment name. The experiment is written below `<EXP_ROOT>/<lens>/` unless `--root-folder` is supplied.

The optional range argument is inclusive and applies to MXF extraction:

```bash
--start_end_idx 0 500
```

MP4 and MOV decoding currently processes the complete video.

## Expected Experiment Structures

### Board-based Calibration

A completed board-based experiment has the following high-level structure:

```text
<EXP_ROOT>/<lens>/<experiment_name>/
├── flags/
│   ├── step1_extract_meta_and_frames_complete.txt
│   ├── step2_write_per_frame_and_run_metadata_complete.txt
│   ├── step3_write_target_complete.txt
│   ├── step4_detect_corners_complete.txt
│   ├── step5_select_frames_complete.txt
│   └── step6_calib_complete.txt
├── kalibr_common_cache/
│   ├── coords_2d.csv
│   ├── coords_2d_successes.csv
│   └── target.yaml
├── raw_data/
│   ├── <one or more media files>
│   ├── <per-clip extraction folders>
│   ├── <combined zero-padded TIFF frames>
│   ├── metadata_export.json
│   ├── per_frame_metadata.json
│   ├── coords_2d_full.csv
│   ├── coords_2d_successes_full.csv
│   └── detections_per_frame.json
├── selected_frames/
│   ├── <Kalibr-formatted image symlinks>
│   └── anms_selected_frames.png
├── run_metadata/
│   ├── actual_parameters.json
│   └── target_parameters.json
├── results/
│   └── trial_<n>_calib_result.json
└── trial_<n>/calibration/
    ├── calib-camchain.yaml
    ├── calib-report-cam.pdf
    ├── calib-results-cam.txt
    └── kalibr_calib_log.txt
```

Batched target detection CSV and JSON files may also remain in `raw_data/`.

### Drone-based Calibration

A processed drone-based experiment has the following high-level structure:

```text
<EXP_ROOT>/<lens>/<experiment_name>/
├── detection_frames/
├── drone_rtk/
│   └── flash_rtk.json
├── flags/
├── kalibr_common_cache/
│   ├── coords_2d.csv
│   ├── coords_2d_successes.csv
│   └── target.yaml
├── raw_data/
│   ├── <video>.mxf
│   ├── coords_2d_full.csv
│   ├── coords_2d_successes_full.csv
│   ├── metadata_export.json
│   └── per_frame_metadata.json
├── results/
│   └── trial_<n>_calib_result.json
├── run_metadata/
│   ├── actual_parameters.json
│   └── target_parameters.json
├── selected_frames/
└── trial_<n>/calibration/
    ├── calib-camchain.yaml
    ├── calib-report-cam.pdf
    ├── calib-results-cam.txt
    └── kalibr_calib_log.txt
```

## Resume and Retry Behavior

Each major stage writes a completion flag under `flags/`. By default, a later invocation reuses a stage whose flag is present.

Use:

```bash
--overwrite
```

to rerun stages even when their completion flags exist. This option does not automatically remove every prior intermediate file, so inspect the experiment folder before rerunning a partially completed workflow.

Interrupted MXF extraction resumes from the highest existing TIFF index in a per-clip extraction directory when no explicit range is supplied.

## Next Step: Select Calibration Results and Build a LUT

The parsed trial JSON files under `results/` are consumed by the utilities under `../lut_creation/`, which select representative calibration results and construct calibration lookup tables.

# Real-World Benchmark Video Preprocessing

This directory contains the InFlux workflow for copying and renaming recorded benchmark videos, extracting per-frame TIFF images, and exporting the lens metadata used to assign per-frame camera intrinsics from a calibration lookup table.

Complete the installation and path configuration in the [InFlux Utility Scripts guide](../README.md) before using this workflow.

## Supported Scope

The primary workflow processes benchmark videos recorded as ARRIRAW MXF files. It copies and renames clips according to a CSV mapping, extracts TIFF frames and ARRI lens metadata, and writes simplified per-frame metadata for downstream LUT application.

`process_world_video.py` can also decode MP4 and MOV inputs directly. Those inputs do not contain the ARRI metadata used by the standard InFlux LUT workflow.

## Files

| File | Role |
|---|---|
| `copy_rename_from_camera_card.py` | Copy videos from a mounted camera card, rename them from a CSV mapping, create one benchmark video folder per clip, and append processing commands to the configured queue |
| `run_from_queue.sh` | Activate the `influx` environment and execute trusted commands from the configured queue |
| `process_world_video.py` | Extract TIFF frames and, when available, export and simplify per-frame ARRI lens metadata |
| `utils.py` | Shared file names, completion flags, image size lookup, and subprocess helpers |

## Prerequisites

This workflow uses the external dependencies described in the [InFlux Utility Scripts guide](../README.md):

- `rsync` for camera card copying
- ARRI Reference Tool 0.3.0 with `art-cmd` available on `PATH` for MXF frame and metadata extraction

The preprocessing workflow does not run Kalibr. The extracted per-frame metadata is used later by the LUT utilities.

## Configure the Workflow

Edit the `real_world` section of [`../config.yaml`](../config.yaml):

```yaml
real_world:
  VIDEO_ROOT: /path/to/benchmark/videos
  QUEUE_FILE: /path/to/queue.txt
  COMPLETED_FILE: /path/to/completed.txt
  ONHOLD_FILE: /path/to/onhold.txt
  SKIP_IF_FAIL_FLAG: /path/to/skip
```

The same configuration file also maps the lens model strings exported by ARRI Reference Tool to the base InFlux lens identifiers:

```yaml
metadata_lens_mapping:
  <ARRI lens model string>: <base lens identifier>
```

The optional `--lens-name-suffix` is appended to the mapped base identifier. Omit the suffix for the original InFlux lens settings and use `v2` for the corresponding InFlux++ lens settings.

Use `config.yaml` as the source of truth for the queue-driven workflow. Although `copy_rename_from_camera_card.py` exposes `--video-root` and `--queue-path` overrides, the generated queue commands do not include a matching `--root-folder` override. To keep copying and downstream processing aligned, set `VIDEO_ROOT` and the queue paths in `config.yaml` and omit those CLI overrides in the normal workflow.

## Step 1: Create a Video Naming CSV

During filming, record the desired benchmark video names in a CSV with the following columns:

```csv
Camera Card,Target Filename
a,example_room1_shot1.mxf
a,example_room1_shot2.mxf
b,example_room1_shot3.mxf
b,example_room1_shot4.mxf
```

Assign each camera card a short identifier such as `a`, `b`, or `c`. The `--card` argument selects the rows whose `Camera Card` value matches the mounted card.

For each selected card, `Target Filename` values are paired in order with the source videos after the source filenames are sorted. Ensure that the number and order of CSV rows match the recordings on that card. The target filename extension determines the name of the copied media file.

## Step 2: Copy and Rename the Videos

Run the copy script from `influx/real_world/`:

```bash
python copy_rename_from_camera_card.py \
  --src /path/to/mounted/camera/card \
  --name-mapping /path/to/video_names.csv \
  --card a \
  --lens-name-suffix v2
```

For each matched clip, the script:

1. Creates `<VIDEO_ROOT>/<video_stem>/raw_data/`.
2. Copies the source video to the target filename from the CSV.
3. Runs a one-frame `art-cmd export` as an early check that the clip can be read and its metadata can be exported.
4. Appends a `process_world_video.py` command to the configured queue.

Important options:

- `--src`: Mounted camera card directory.
- `--name-mapping`: CSV containing `Camera Card` and `Target Filename` columns.
- `--card`: Camera card label to select from the CSV; accepted values are `a` through `g`.
- `--lens-name-suffix`: Optional suffix appended to the detected lens identifier. Omit this flag for the original InFlux lens settings and use `v2` for the corresponding InFlux++ lens settings.
- `--skip`: One or more 1-indexed positions to omit after source filenames are sorted.
- `--no-rsync`: Skip copying. In the current implementation, this also means no metadata extraction or queue commands are produced.
- `--video-root` and `--queue-path`: Path overrides. For the normal queue-driven workflow, configure the corresponding values in `../config.yaml` instead.

The script enumerates `.mxf`, `.mov`, and `.mp4` files case-insensitively. The camera card ingestion workflow is intended for ARRIRAW MXF recordings because it performs an `art-cmd` metadata export before adding the processing command to the queue. For MP4 or MOV inputs, arrange the benchmark video folder directly and use `process_world_video.py` as described below.

## Step 3: Run the Processing Queue

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

`process_world_video.py` processes one benchmark video folder under `VIDEO_ROOT`:

```bash
python process_world_video.py \
  --exp_name example_room1_shot1 \
  --lens-name-suffix v2
```

The expected input is:

```text
<VIDEO_ROOT>/<exp_name>/raw_data/<video>.mxf
```

The script requires `--exp_name` and expects exactly one `.mxf`, `.mov`, or `.mp4` file in the folder. Media discovery is sorted and case-insensitive.

Use `--root-folder` only when running the complete command directly and intentionally bypassing `VIDEO_ROOT` from `config.yaml`:

```bash
python process_world_video.py \
  --root-folder /path/to/benchmark/videos \
  --exp_name example_room1_shot1 \
  --lens-name-suffix v2
```

The optional inclusive range applies to MXF extraction:

```bash
python process_world_video.py \
  --exp_name example_room1_shot1 \
  --start_end_idx 0 500
```

MP4 and MOV decoding currently processes the complete video.

## MXF, MP4, and MOV Inputs

For MXF input, `process_world_video.py` invokes `../real_calib/process_mxf.sh`. The script uses `art-cmd` to write TIFF frames and `metadata_export.json`, then creates `per_frame_metadata.json` with the detected lens identifier and per-frame:

```text
focal_length_mm
focus_distance_m
```

For MP4 or MOV input, frames are decoded with OpenCV. These files can be converted to TIFF images, but no ARRI metadata export is produced by this path. Without the recorded per-frame lens metadata, the standard InFlux LUT application workflow cannot assign the original per-frame camera intrinsics in the same way as it does for ARRIRAW recordings.

## Expected Output Structure

A processed benchmark video folder has the following high-level structure:

```text
<VIDEO_ROOT>/<exp_name>/
├── flags/
│   ├── step1_extract_meta_and_frames_complete.txt
│   └── step2_write_per_frame_and_run_metadata_complete.txt
└── raw_data/
    ├── <original-video>.mxf
    ├── 0000000.tiff
    ├── 0000001.tiff
    ├── ...
    ├── metadata_export.json
    └── per_frame_metadata.json
```

For MP4 or MOV inputs, `metadata_export.json` and `per_frame_metadata.json` are absent unless compatible metadata was provided separately.

The simplified metadata file contains the detected lens identifier and a `frames` dictionary keyed by frame ID. Each frame records the lens focal length in millimeters and focus distance in meters. It also retains descriptive and clip-level metadata from the ARRI export.

## Resume and Retry Behavior

Each processing stage writes a completion flag under `flags/`. By default, later invocations reuse a stage whose flag is already present.

Use:

```bash
--overwrite
```

to rerun the extraction and metadata stages.

When processing MXF without an explicit range, the script checks for existing zero-padded TIFF files and resumes extraction from the highest existing frame index.

## Next Step: Apply the Calibration LUT

The output of this workflow is a benchmark video folder containing per-frame images and, for ARRIRAW recordings, per-frame lens focal length and focus distance metadata. The utilities under `../lut_creation/` use this metadata together with the selected calibration results to generate per-frame camera intrinsics.

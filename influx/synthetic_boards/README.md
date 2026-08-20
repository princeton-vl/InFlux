# Synthetic Board Calibration Utilities

This directory contains the InFlux workflow for creating controlled synthetic AprilGrid experiments with exact ground truth camera intrinsics. These experiments make it possible to measure the accuracy of the InFlux-modified Kalibr calibration pipeline directly across lens focal length (LFL) and focus distance (FD) settings for board-based calibration.

Complete the installation and path configuration in the [InFlux Utility Scripts guide](../README.md) before using this workflow.

## Supported Scope

The public workflow supports synthetic board calibration experiments for the following lenses:

```text
canon17
premista80
canon17v2
premista80v2
```

## Files

| File or directory | Role |
|---|---|
| `run_all_boards.py` | Run synthetic board calibration experiments across one or more lenses |
| `run_board.py` | Render, distort, detect, calibrate, evaluate, parse results, and resume one LFL/FD experiment setting |
| `board_generation.py` | Create the Blender camera and AprilGrid plane, generate board motion, render images, and project exact board coordinates |
| `distort_utils.py` | Apply the synthetic lens distortion model to images and coordinates; also used by the synthetic drone workflow |
| `kalibr_detect_corners.sh` | Run InFlux-modified Kalibr target detection in Docker |
| `kalibr_run_calibration_with_guess.sh` | Run one InFlux-modified Kalibr calibration trial with a focal length initialization |
| `kalibr_run_evaluation.sh` | Evaluate fixed calibrated intrinsics and distortion and generate Kalibr evaluation outputs |
| `board_designs/` | Seven PNG AprilGrid textures referenced by `board_generation.py` |

## Prerequisites

In addition to the Python dependencies installed through `.[dev]`, this workflow requires:

- Docker
- The InFlux-modified Kalibr Docker image named `kalibr:latest`
- An X11 display and `xhost`, as used by the included Kalibr wrappers
- `jq` and `bc`, used by the evaluation wrapper

Run the commands in this guide from `influx/synthetic_boards/`. The current modules, board texture paths, and shell-wrapper calls are relative to that directory.

## Configure the Workflow

Generate the synthetic settings described in the [top-level utility guide](../README.md), then review the following fields in [`../config.yaml`](../config.yaml):

```yaml
LENS_SETTINGS_DIR_SYNTH: /path/to/generated/synthetic/lens/settings

cameras:
  arri:
    sensor_width_mm: 28.25
    sensor_height_mm: 18.17
    sensor_resolution_x: 3424
    sensor_resolution_y: 2202
    resolution_percentage: 100

lenses:
  <lens_identifier>:
    min_k1: <wide-end radial distortion coefficient>
```

The generated `<lens>_synth.json` files provide the LFL values, FD values in millimeters, and the assigned board size or `drone` label for every setting. `run_all_boards.py` runs only settings whose assignment is a board size.

`min_k1` controls radial distortion at the shortest synthetic camera focal length. Conceptually, the code determines the radial pixel displacement represented by this wide-end value, then chooses the long-focal-length endpoint so that the displacement has the same magnitude in the opposite direction. Intermediate settings vary smoothly between those endpoints in a visual-distortion space normalized by focal length, rather than by linearly interpolating raw `k1` values.

## Step 1: Generate Synthetic Lens Settings

From `influx/`, generate one synthetic settings file per lens:

```bash
python select_experiments.py --camera arri --lens canon17
python select_experiments.py --camera arri --lens premista80
python select_experiments.py --camera arri --lens canon17v2
python select_experiments.py --camera arri --lens premista80v2
```

The files are written to:

```text
<LENS_SETTINGS_DIR_SYNTH>/<lens>_synth.json
```

## Step 2: Run the Default Four Lens Workflow

From `influx/synthetic_boards/`, run:

```bash
python run_all_boards.py \
  --root_folder /path/to/synthetic/experiments \
  --num_trials 100
```

`--root_folder` is the parent output directory. The script creates one subdirectory per lens and one experiment folder for each board-assigned LFL/FD setting. `--num_trials` controls how many InFlux-modified Kalibr calibration trials are run for every experiment setting.

The default `--lenses` and `--settings-paths` lists are positional pairs. They must contain the same number of entries in the same order, with each settings path corresponding to the lens at the same position. When running a subset, supply both lists explicitly. For example:

```bash
python run_all_boards.py \
  --lenses canon17 canon17v2 \
  --settings-paths \
    /path/to/settings/canon17_synth.json \
    /path/to/settings/canon17v2_synth.json \
  --root_folder /path/to/synthetic/experiments \
  --num_trials 100
```

## Step 3: Render and Distort the AprilGrid Observations

For each LFL/FD setting, the workflow computes the camera focal length and pinhole-to-board distance using the thin lens model, renders the assigned AprilGrid texture over a generated sequence of board poses, and writes exact 2D and 3D board coordinates.

At the shortest camera focal length, `k1` equals the configured `min_k1`. The code uses the radial pixel displacement associated with that value to define an opposite-sign long-focal-length endpoint with the same displacement magnitude. Intermediate settings interpolate smoothly in a visual-distortion space normalized by focal length, then convert that interpolated effect back into the setting-specific `k1`. The remaining distortion coefficients `k2`, `p1`, and `p2` are set to zero.

The workflow applies the resulting distortion to the rendered images and projected coordinates, then runs InFlux-modified Kalibr target detection over the distorted images.

## Step 4: Run Calibration and Evaluation Trials

Each trial uses InFlux-modified Kalibr with a focal length initialization in pixels derived from the configured LFL and camera sensor geometry. This initialization does not leak the ground truth camera focal length (CFL): LFL and CFL are distinct values, and the LFL associated with InFlux footage is known. The synthetic renderer computes CFL from LFL and FD through the thin lens model, but that rendered ground truth CFL is not supplied to the calibration optimization.

The evaluation stage receives the calibrated intrinsics and distortion through Kalibr's override mode and evaluates those values exactly without additional optimization. It writes the evaluation report and reprojection outputs for the supplied calibration result.

## Output Structure

A completed experiment has the following high-level structure:

```text
<root>/<lens>/<experiment_name>/
├── flags/
├── ground_truth/
│   └── gt_intrinsics.json
├── kalibr_common_cache/
│   ├── image_dims.json
│   ├── kalibr_coords_2d.csv
│   ├── kalibr_coords_2d_successes.csv
│   └── target.yaml
├── no_distortion_data/
│   ├── frame_*.png
│   ├── calibration_matrix.txt
│   ├── coords_2d.csv
│   └── coords_3d.csv
├── with_distortion_data/
│   ├── frame_*.png
│   └── coords_2d.csv
├── results/
│   ├── trial_<n>_with_guess_calib_result.json
│   └── trial_<n>_with_guess_eval_result.json
└── trial_<n>_with_guess/
    ├── calibration/
    └── evaluation/
```

The calibration and evaluation folders contain Kalibr logs, text results, and PDF reports.

## Resume Behavior

Each major stage writes a completion flag under `flags/`. A later invocation reuses completed rendering, distortion, target detection, calibration, or evaluation work when the corresponding flag is present.

Before intentionally rerunning a completed stage, remove the relevant flag and inspect or clear any stale outputs for that stage. Do not mix outputs from different settings, distortion values, or trial counts in the same experiment directory.

## Next Step: Select Results and Build a LUT

The generated `trial_<n>_with_guess_*_result.json` files are consumed by [`../lut_creation/select_trials.py`](../lut_creation/select_trials.py). Use the synthetic selection mode `new_guess` for results generated by this public workflow.

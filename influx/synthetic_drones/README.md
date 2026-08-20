# Synthetic Drone Calibration Utilities

This directory contains the InFlux workflow for creating controlled synthetic 2D-3D correspondence experiments with exact ground truth camera intrinsics. These experiments make it possible to measure the accuracy of the InFlux-modified Kalibr generalized calibration pipeline for a calibration target with customized 3D structure, such as drone-based calibration.

Complete the installation and path configuration in the [InFlux Utility Scripts guide](../README.md) before using this workflow.

## Supported Scope

The public workflow supports synthetic drone calibration experiments for the original InFlux lenses:

```text
canon17
premista80
```

The synthetic observations model the flashing red LED carried by the drone as the calibration target. The workflow renders and detects that LED at known 3D positions rather than rendering the complete drone platform.

## Files

| File | Role |
|---|---|
| `run_all_drones.py` | Run synthetic drone calibration experiments across one or more lenses |
| `run_drone_pipeline.py` | Generate, render, distort, detect, calibrate, evaluate, parse results, batch trials, and resume one LFL/FD experiment setting |
| `generate_drone_movements.py` | Generate target positions, reported 3D coordinates, camera geometry, and movement files |
| `render_distort_detect.py` | Render the moving red LED target, apply distortion, detect the target, and prepare Kalibr observation files |
| `syn_drone_single.py` | Create the Blender camera and target, apply the movement sequence, and render images |
| `utils.py` | Define synthetic drone paths, flags, filenames, and argument helpers |
| `kalibr_calibrate_with_guess.sh` | Run one InFlux-modified Kalibr calibration trial with a focal length initialization |
| `kalibr_evaluate.sh` | Evaluate fixed calibrated intrinsics and distortion and generate Kalibr evaluation outputs |

The drone workflow imports image and coordinate distortion helpers from `../synthetic_boards/distort_utils.py`.

## Prerequisites

In addition to the Python dependencies installed through `.[dev]`, this workflow requires:

- Docker
- The InFlux-modified Kalibr Docker image named `kalibr:latest`
- `jq` and `bc`, used by the evaluation wrapper

The Docker wrappers mount the host X11 socket and forward `DISPLAY`, matching the InFlux-modified Kalibr setup used by the other calibration workflows.

Run the commands in this guide from `influx/synthetic_drones/`. The current modules and shell-wrapper calls are relative to that directory.

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

The generated `<lens>_synth.json` files provide the LFL values, FD values in millimeters, and the assigned board size or `drone` label for every setting. `run_all_drones.py` runs only settings whose assignment is `drone` unless `--hardcoded-settings` is supplied.

`min_k1` controls radial distortion at the shortest synthetic camera focal length. Conceptually, the code determines the radial pixel displacement represented by this wide-end value, then chooses the long-focal-length endpoint so that the displacement has the same magnitude in the opposite direction. Intermediate settings vary smoothly between those endpoints in a visual-distortion space normalized by focal length, rather than by linearly interpolating raw `k1` values.

## Step 1: Generate Synthetic Lens Settings

From `influx/`, generate the default synthetic settings files:

```bash
python select_experiments.py --camera arri --lens canon17
python select_experiments.py --camera arri --lens premista80
```

The files are written to:

```text
<LENS_SETTINGS_DIR_SYNTH>/<lens>_synth.json
```

## Step 2: Run the Default Two Lens Workflow

From `influx/synthetic_drones/`, run:

```bash
python run_all_drones.py \
  --root-folder /path/to/synthetic/experiments \
  --num-trials 1
```

`--root-folder` is the parent output directory. The script creates one subdirectory per lens and one experiment folder for each drone-assigned LFL/FD setting. `--num-trials` controls how many InFlux-modified Kalibr calibration trials are run for every experiment setting. The default is one trial because the generalized 2D-3D correspondence calibration is deterministic, so repeating a setting does not provide independent optimization outcomes.

The default `--lenses` and `--settings-paths` lists are positional pairs. They must contain the same number of entries in the same order, with each settings path corresponding to the lens at the same position. To run only one default lens, supply both arguments:

```bash
python run_all_drones.py \
  --lenses canon17 \
  --settings-paths /path/to/settings/canon17_synth.json \
  --root-folder /path/to/synthetic/experiments \
  --num-trials 1
```

## Optional Target and Noise Settings

The top-level runner exposes the following experiment controls:

```text
--drone-radius <meters>
--led-radius <meters>
--gps-noise-m <meters>
--rtk-noise-cm <centimeters>
```

The default target and LED radii are both `0.02` meters. GPS noise defaults to zero, and reported RTK jitter defaults to `1.0` centimeter.

Use `--hardcoded-settings` to bypass the settings-file target assignment and supply LFL/FD pairs directly:

```bash
python run_all_drones.py \
  --lenses canon17 \
  --settings-paths /path/to/settings/canon17_synth.json \
  --hardcoded-settings 17 853.44 33 1500 \
  --root-folder /path/to/synthetic/experiments
```

Each pair is `LFL_mm FD_mm`.

## Step 3: Generate, Render, Distort, and Detect the Target Path

For each setting, the workflow computes the camera focal length and pinhole-to-target distance using the thin lens model. It generates a multi-plane target path, writes the exact and reported 3D coordinates, renders the red LED target, applies radial distortion, and detects the target center in each distorted image.

At the shortest camera focal length, `k1` equals the configured `min_k1`. The code uses the radial pixel displacement associated with that value to define an opposite-sign long-focal-length endpoint with the same displacement magnitude. Intermediate settings interpolate smoothly in a visual-distortion space normalized by focal length, then convert that interpolated effect back into the setting-specific `k1`. The remaining distortion coefficients `k2`, `p1`, and `p2` are set to zero.

## Step 4: Run Calibration and Evaluation Trials

Each trial uses InFlux-modified Kalibr with a focal length initialization in pixels derived from the configured LFL and camera sensor geometry. This initialization does not leak the ground truth camera focal length (CFL): LFL and CFL are distinct values, and the LFL associated with InFlux footage is known. The synthetic renderer computes CFL from LFL and FD through the thin lens model, but that rendered ground truth CFL is not supplied to the calibration optimization.

The evaluation stage receives the calibrated intrinsics and distortion through Kalibr's override mode and evaluates those values exactly without additional optimization. It writes the evaluation report and reprojection outputs for the supplied calibration result.

The orchestration chooses a memory-aware worker count for calibration and evaluation trials, and the subprocess helper honors that limit.

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
│   ├── coords_3d.csv
│   ├── coords_3d_norm.csv
│   └── gt_coords_3d.csv
├── with_distortion_data/
│   ├── frame_*.png
│   ├── coords_2d_gt.csv
│   ├── coords_2d.csv
│   └── coords_2d_successes.csv
├── results/
│   ├── trial_<n>_with_guess_calib_result.json
│   └── trial_<n>_with_guess_eval_result.json
├── run_metadata/
│   └── target_parameters.json
└── trial_<n>_with_guess/
    ├── calibration/
    └── evaluation/
```

The calibration and evaluation folders contain Kalibr logs, text results, and PDF reports.

## Resume Behavior

Each major stage writes a completion flag under `flags/`. By default, a later invocation reuses completed movement generation, rendering, distortion, detection, calibration, and evaluation work.

Before intentionally rerunning a completed stage, remove the relevant flag and inspect or clear any stale outputs for that stage. Do not mix outputs from different target dimensions, noise settings, distortion values, or trial counts in the same experiment directory.

## Next Step: Select Results and Build a LUT

The generated `trial_<n>_with_guess_*_result.json` files are consumed by [`../lut_creation/select_trials.py`](../lut_creation/select_trials.py). Use the synthetic selection mode `new_guess` for results generated by this public workflow.

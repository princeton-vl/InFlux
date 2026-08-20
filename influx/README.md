# InFlux Utility Scripts

This directory contains the higher-level utilities used to develop the InFlux real-world benchmark, run real and synthetic calibration workflows, process benchmark recordings, and construct calibration lookup tables. These scripts are intended for reproducing or adapting the benchmark development pipeline. They are not required for downloading the released datasets, using the InFlux++ Synth data loader, or submitting predictions to the leaderboard.

## Installation

First complete the [basic InFlux installation](../docs/README_download.md#base-installation). Then activate the same Conda environment and install the additional dependencies for the InFlux utility scripts from the repository root:

```bash
conda activate influx
pip install -e ".[dev]"
```

## Additional External Dependencies

Some workflows require external tools that are not installed through `pip`:

- **InFlux-modified Kalibr Docker image:** Used to perform camera calibration for real and synthetic calibration experiments. Build the image named `kalibr:latest` by following the [Kalibr extension guide](../third_party/kalibr/README.md).
- **Docker:** Used to run the InFlux-modified Kalibr image during camera calibration.
- **`rsync`:** Used by the camera card ingestion scripts to copy recorded media into the configured local data directories.
- **ARRI Reference Tool 0.3.0 (`art-cmd`):** Used to process ARRIRAW footage filmed for InFlux and InFlux++ and to export frame-level camera and lens metadata. The InFlux utilities were developed against version 0.3.0. Obtain ARRI Reference Tool from the [official ARRI download page](https://www.arri.com/en/learn-help/learn-help-camera-system/tools/arri-reference-tool). Newer releases may work, but the generated metadata JSON schema may differ from the version expected by these scripts.
- **X11 display access and `xhost`:** Used by the synthetic calibration Kalibr wrappers to share the display socket with Docker.
- **`jq` and `bc`:** Used by the synthetic calibration evaluation wrappers to parse calibrated intrinsics and convert principal point coordinates.

After installing ARRI Reference Tool, add its `bin/` directory to your shell `PATH`. For Bash, add the following line to `~/.bashrc`, replacing the example path with the absolute path to the extracted package:

```bash
export PATH="/absolute/path/to/arri-reference-tool/bin:$PATH"
```

Reload the shell configuration and confirm that `art-cmd` is available:

```bash
source ~/.bashrc
command -v art-cmd
```

For Zsh, add the same `export` line to `~/.zshrc` and run `source ~/.zshrc`.

## Configure Paths and Experiment Settings

Before running the utilities, edit [`config.yaml`](config.yaml). This file is the primary source of truth for:

- Real calibration media, experiment, and queue paths
- Real-world benchmark video and queue paths
- Real and synthetic lens setting output directories
- LUT input and output paths
- Camera sensor dimensions and image resolution
- Lens names, lens metadata mappings, focal length ranges, focus distance ranges, and experiment settings

The default `/data1/...` and `/data2/...` values are the original InFlux paths and should be replaced with paths that you define. To ensure proper behavior of the utility scripts, we strongly encourage you to specify the desired paths in this configuration file instead of mixing one-off path overrides across different scripts. This is especially important for queue-driven workflows, where one script may create commands that expect a downstream script to read the same configured root.

## Generate Lens Setting Files

[`select_experiments.py`](select_experiments.py) generates the focal length, focus distance, and target size grid used by the real and synthetic calibration workflows.

From `influx/`, generate real camera settings with `--empirical-mode`:

```bash
cd influx
python select_experiments.py --camera arri --lens canon17 --empirical-mode
```

Generate synthetic settings by omitting `--empirical-mode`:

```bash
python select_experiments.py --camera arri --lens canon17
```

The configured lens identifiers are:

```text
canon17
premista80
canon17v2
premista80v2
```

`canon17` and `premista80` identify the settings used for the original InFlux benchmark. `canon17v2` and `premista80v2` identify the settings used for InFlux++.

Real settings are written to:

```text
LENS_SETTINGS_DIR/<lens>.json
```

Synthetic settings are written to:

```text
LENS_SETTINGS_DIR_SYNTH/<lens>_synth.json
```

The output directories must already exist. Each generated JSON contains the sampled lens focal lengths, focus distances in millimeters, and target assignment for every calibration experiment.

## Component Guides

Use the component-specific guides below to continue with the workflow relevant to your task.

| Workflow | Purpose | Guide |
|---|---|---|
| Real camera calibration | Prepare calibration recordings, select frames based on target detection quality, run repeated Kalibr trials, and write calibration results for each lens setting | [Real Camera Calibration](real_calib) |
| Real-world benchmark video preprocessing | Copy and rename recorded benchmark videos, extract TIFF frames and per-frame lens metadata, and prepare video folders for LUT application | [Real-World Benchmark Video Preprocessing](real_world) |
| Calibration lookup table construction and application | Select representative calibration results, construct and inspect lookup tables, visualize intrinsics, and write per-frame intrinsics for processed benchmark videos | [Calibration Lookup Table Utilities](lut_creation) |
| Synthetic board calibration experiments | Render synthetic AprilGrid images across camera settings with exact ground truth intrinsics, then use InFlux-modified Kalibr to estimate intrinsics and quantify calibration pipeline accuracy | [Synthetic Board Calibration Utilities](synthetic_boards) |
| Synthetic drone calibration experiments | Render and detect a moving red LED target at known 3D positions with exact ground truth intrinsics, then use InFlux-modified Kalibr's 2D-3D correspondence mode to estimate intrinsics and quantify calibration pipeline accuracy | [Synthetic Drone Calibration Utilities](synthetic_drones) |

## Citation

For the InFlux and InFlux++ citations, see the [repository README](../README.md#publications-and-citation).

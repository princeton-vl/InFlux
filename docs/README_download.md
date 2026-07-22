# Installation and Data Downloads

This page is the starting point for installing the InFlux repository and accessing the data, evaluation tools, and additional code released with InFlux and InFlux++.

## Base Installation

Clone the repository:

```bash
git clone https://github.com/princeton-vl/InFlux.git
cd InFlux
```

We recommend creating a dedicated Conda environment named `influx` with Python 3.11:

```bash
conda create --name influx python=3.11
conda activate influx
```

From the repository root, install the dependencies:

```bash
conda install -c conda-forge ffmpeg
pip install -e .
```

Python 3.11 is the tested configuration. The package requires Python 3.10 or later.

The base installation provides the Python dependencies and command-line utilities for:

- Downloading InFlux-Real and InFlux-Synth
- Extracting the downloaded data
- Generating and uploading benchmark submissions

FFmpeg is used when decoding InFlux-Real videos into TIFF frames and when decoding InFlux-Synth surface normal containers.

## Additional Installations and Downloads

| Goal | What it provides | Instructions |
|---|---|---|
| Download InFlux-Real | Download either real-world benchmark partition or the complete release, with optional MP4-to-TIFF decoding | [Download and Extract InFlux-Real](README_download_real.md) |
| Download InFlux-Synth | Select dataset partitions and modalities, download samples or complete partitions, and optionally extract the data | [Download and Extract InFlux-Synth](README_download_synth.md) |
| Submit and evaluate predictions | Validate and upload test-set predictions and receive benchmark results | [Submit and Evaluate Results](README_evaluation.md) |
| Use the InFlux-Synth data loader | Load RGB images and camera metadata and apply lens distortion and other data augmentations | [InFlux-Synth Data Loader](README_dataloader.md) |
| Use the Kalibr extension | Build and use the modified Kalibr release from the original InFlux work | [Kalibr Extension](../third_party/kalibr/) |
| Use the InFlux utility scripts | Install and use the scripts that supported development of the real-world benchmark and calibration lookup tables | [InFlux Utility Scripts](../influx/README.md) |
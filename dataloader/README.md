# InFlux++ Synth Data Loader

This directory contains the official data loader for **InFlux++ Synth**, which is distributed through the [InFlux-Synth](https://huggingface.co/datasets/princeton-vl/InFlux-Synth) Hugging Face repository.

The RGB images released in InFlux++ Synth are undistorted. This data loader allows users to sample realistic radial or radial-tangential lens distortion based on each frame's lens metadata and image dimensions and apply the resulting remap to the image as a data augmentation step. It also provides additional photometric and geometric data augmentations that may be useful during training, such as color jitter, aspect ratio changes, and more.

In addition to data augmentation, this directory provides utilities for preparing InFlux++ Synth for training or finetuning dynamic intrinsics prediction models. Starting from an extracted version of InFlux++ Synth, the included scripts create training, validation, and test splits and prepare them for use as PyTorch batches. Each batch contains an augmented RGB image and its corresponding ground truth camera intrinsics. For radial-only distortion, per-pixel ground truth camera ray directions are also available. This directory also provides two toy models that demonstrate direct intrinsics regression and dense ray supervision using InFlux++ Synth data.

This data loader is derived in part from [AnyCalib](https://github.com/javrtg/AnyCalib).

**Resources:** [InFlux-Synth Dataset](https://huggingface.co/datasets/princeton-vl/InFlux-Synth) · [Download and Extraction](../docs/README_download_synth.md) · [InFlux++ Paper](https://arxiv.org/abs/2607.05389)

## Getting Started

To use our data loader, you'll need:

- one or more extracted InFlux++ Synth scenes containing the `Image/` and `camview/` modalities; see the [download and extraction guide](../docs/README_download_synth.md);
- Conda and Python 3.10 or newer;
- enough storage for the prepared image tree and H5 files. We recommend keeping the extracted source and prepared output on the same filesystem so that hardlink preparation can avoid duplicating the RGB files and greatly reduce additional storage use.

The extracted InFlux++ Synth source root may contain any subset of the four dataset partitions:

```text
<extracted-root>/
├── indoors/
├── nature/
├── indoors_full/
└── nature_full/
```

Each selected scene must contain matching extracted RGB and camera metadata directories:

```text
<extracted-root>/
└── indoors/
    └── indoors_000000/
        ├── Image/
        │   └── *.png
        └── camview/
            └── *.npz
```

A complete released scene contains 240 RGB frames and 240 matching `camview` files. The preparation utility reports incomplete or mismatched scenes instead of silently preparing partial videos.

### Step 1: Install Data Loader Dependencies

We recommend creating a dedicated Conda environment named `influx_synth_dataloader` with Python 3.11, the version used for release validation.

```bash
conda create --name influx_synth_dataloader python=3.11
conda activate influx_synth_dataloader
```

Next, install a compatible PyTorch and torchvision pair for your system. For example, the following installs a CUDA 11.8 build on Linux or Windows:

```bash
pip install torch torchvision \
    --index-url https://download.pytorch.org/whl/cu118
```

Then, from this directory, install the data loader in editable mode:

```bash
pip install -e .
```

The included examples use `train.device=cpu` by default.

### Step 2: Prepare Train, Validation, and Test Splits

Choose an output path whose basename is `influx_synth`:

```bash
SOURCE_ROOT="/absolute/path/to/extracted/InFlux-Synth"
OUTPUT_ROOT="/absolute/path/to/loader_data/influx_synth"

python -m siclib.datasets.utils.prepare_influx_synth \
    --source-dir "$SOURCE_ROOT" \
    --output-dir "$OUTPUT_ROOT" \
    --mode hardlink
```

By default, scenes are assigned deterministically using:

```text
train: 0.8
validation: 0.1
test: 0.1
split seed: 42
```

The assignment is performed at the scene level, so every frame from one video remains in the same split. The ratios and seed can also be modified:

```bash
python -m siclib.datasets.utils.prepare_influx_synth \
    --source-dir "$SOURCE_ROOT" \
    --output-dir "$OUTPUT_ROOT" \
    --mode hardlink \
    --train-ratio 0.8 \
    --val-ratio 0.1 \
    --test-ratio 0.1 \
    --split-seed 42
```

Use `--dry-run` to inspect the assignment without writing files:

```bash
python -m siclib.datasets.utils.prepare_influx_synth \
    --source-dir "$SOURCE_ROOT" \
    --output-dir "$OUTPUT_ROOT" \
    --train-ratio 0.8 \
    --val-ratio 0.1 \
    --test-ratio 0.1 \
    --split-seed 42 \
    --dry-run
```

You can also explicitly assign videos to each split through `--split-manifest`. Run the following command for the complete interface:

```bash
python -m siclib.datasets.utils.prepare_influx_synth --help
```

The prepared output under `$OUTPUT_ROOT` has the following structure:

```text
influx_synth/
├── train/
│   └── <video-id>/
│       ├── 0000000.png
│       ├── 0000000.json
│       └── ...
├── val/
│   └── <video-id>/
│       └── ...
└── test/
    └── <video-id>/
        └── ...
```

The JSON files contain the camera and lens fields required for H5 generation in the next step. The preparation utility is resumable and skips scenes whose prepared outputs are already complete.

### Step 3: Generate H5 Metadata

During H5 generation, the system reads the prepared PNG/JSON tree and writes one H5 file for each split. Use `--config-name` to choose the camera mode and `distortion=<profile-name>` to choose the distortion sampling distribution.

#### Camera Mode Configurations

The `--config-name` argument accepts the two configurations below. When distortion is enabled, the selected configuration determines whether the loader applies radial-only distortion or radial-tangential distortion. It also determines whether per-pixel ground truth ray directions are available.

| Config name | Camera mode | Applied distortion parameters | Per-pixel ground truth ray directions |
|---|---|---|---|
| `influx_synth_radial` | `radial:2` | `k1`, `k2` | Available |
| `influx_synth_radtan` | `radtan:4` | `k1`, `k2`, `p1`, `p2` | Not currently available |

#### Distortion Profile Sampling Distributions

The `distortion=<profile-name>` override selects how the distortion coefficients and image-remapping grids are generated. Both camera-mode configurations use `distortion=influx_pp` by default. The included `none` profile instead produces zero distortion coefficients and identity remapping grids.

##### How the Default Profile Samples Distortion

For the radial coefficients `k1` and `k2`, the `influx_pp` profile does not sample coefficient values directly. Instead, it selects two control points—the image corner and the top-center point—samples a signed target radial displacement in pixels at each point, and solves for the `k1` and `k2` values that produce those displacements.

To express the control-point locations in normalized camera coordinates, the sampler converts the lens focal length (`LFL`) and lens to object distance (`LTO`) from the prepared metadata into camera focal length (`CFL`) via the thin lens equation:

```text
CFL = (1 / LFL - 1 / LTO)^-1
```

`CFL` is then converted into pixel focal lengths:

```text
fx = W / sensor.width_m  × CFL
fy = H / sensor.height_m × CFL
f  = (fx + fy) / 2
```

Using the average pixel focal length `f`, the normalized radii of the two control points are:

```text
r_corner = sqrt((H / 2)^2 + (W / 2)^2) / f
r_top    = (H / 2) / f
```

The sampler chooses a signed target displacement in pixels at each control point. Positive displacement moves the point outward from the image center, while negative displacement moves it inward. The corner displacement is sampled from a truncated Gaussian whose mean varies linearly with focal length. A second truncated-Gaussian factor multiplies the sampled corner displacement to obtain the top-center target, which is then clipped to its configured bounds. Allowing the two control-point displacements to have matching or opposing signs supports both monotonic barrel or pincushion behavior and higher-order mustache-like distortion.

The two target displacements define a linear system under the radial Brown–Conrady model:

```text
[ f r_corner^3   f r_corner^5 ] [ k1 ]   [ delta_corner ]
[ f r_top^3      f r_top^5    ] [ k2 ] = [ delta_top    ]
```

Solving this system gives `k1` and `k2`. For `radtan:4`, the sampler additionally draws `p1` and `p2` independently from a zero-mean Gaussian. The sampled coefficients and their image-remapping grids are stored in the H5 files; runtime loading reuses those stored maps rather than resampling distortion for every batch.

##### Default `influx_pp` Profile Values

The default profile is defined in:

```text
siclib/datasets/configs/distortion/influx_pp.yaml
```

Its current values are:

| Configuration | Default | Role |
|---|---:|---|
| `sensor.width_m` | `0.032` | Physical sensor width used to convert `CFL` to `fx` |
| `sensor.height_m` | `0.018` | Physical sensor height used to convert `CFL` to `fy` |
| `corner_displacement.min_px` | `-50.0` | Lower truncation bound for signed corner displacement |
| `corner_displacement.max_px` | `80.0` | Upper truncation bound for signed corner displacement |
| `corner_displacement.std_px` | `50.0` | Standard deviation of the corner-displacement Gaussian |
| `corner_displacement.mean_by_focal_px` | `[[1500.0, 20.0], [30000.0, 80.0]]` | Two `[focal length in pixels, mean displacement in pixels]` control points used for linear interpolation or extrapolation |
| `top_mid_factor.min` | `-0.10` | Lower truncation bound for the top-center/corner displacement factor |
| `top_mid_factor.max` | `0.50` | Upper truncation bound for the factor |
| `top_mid_factor.mean` | `0.14285714285714285` | Mean factor (`1/7`) |
| `top_mid_factor.std` | `0.15` | Standard deviation of the factor Gaussian |
| `top_mid_displacement.min_px` | `-25.0` | Lower clipping bound for top-center displacement |
| `top_mid_displacement.max_px` | `40.0` | Upper clipping bound for top-center displacement |
| `tangential.std` | `0.0001` | Standard deviation of the zero-mean Gaussian used independently for `p1` and `p2` |

#### Generate H5 Files

If `distortion=<profile-name>` is omitted, both camera-mode configurations use the default `influx_pp` profile described above.

##### Radial Mode with the Default Profile

```bash
python -m siclib.datasets.create_dataset_from_images \
    --config-name influx_synth_radial \
    base_dir="$OUTPUT_ROOT" \
    overwrite=false
```

##### Radial-Tangential Mode with the Default Profile

```bash
python -m siclib.datasets.create_dataset_from_images \
    --config-name influx_synth_radtan \
    base_dir="$OUTPUT_ROOT" \
    overwrite=false
```

##### No Distortion

To generate H5 files without adding lens distortion, select the included `none` profile. For example, for radial mode:

```bash
python -m siclib.datasets.create_dataset_from_images \
    --config-name influx_synth_radial \
    base_dir="$OUTPUT_ROOT" \
    distortion=none \
    overwrite=false
```

The same override can be used with `--config-name influx_synth_radtan`. The `none` profile stores zero distortion coefficients and identity image-remapping grids. Manual distortion-range overrides are ignored when this profile is selected.

##### Custom Distortion Profiles

To alter the distortion distribution for one H5-generation command, override the profile values through Hydra. The following example changes every configurable value:

```bash
python -m siclib.datasets.create_dataset_from_images \
    --config-name influx_synth_radtan \
    base_dir="$OUTPUT_ROOT" \
    distortion=influx_pp \
    distortion.sensor.width_m=0.036 \
    distortion.sensor.height_m=0.024 \
    distortion.corner_displacement.min_px=-30.0 \
    distortion.corner_displacement.max_px=50.0 \
    distortion.corner_displacement.std_px=25.0 \
    'distortion.corner_displacement.mean_by_focal_px=[[1500.0,10.0],[30000.0,50.0]]' \
    distortion.top_mid_factor.min=-0.05 \
    distortion.top_mid_factor.max=0.35 \
    distortion.top_mid_factor.mean=0.12 \
    distortion.top_mid_factor.std=0.10 \
    distortion.top_mid_displacement.min_px=-15.0 \
    distortion.top_mid_displacement.max_px=25.0 \
    distortion.tangential.std=0.00005 \
    overwrite=false
```

For a reusable profile, copy `influx_pp.yaml` within `siclib/datasets/configs/distortion/`, edit the copied values, and select the new file by name:

```bash
cp \
    siclib/datasets/configs/distortion/influx_pp.yaml \
    siclib/datasets/configs/distortion/my_distortion.yaml

python -m siclib.datasets.create_dataset_from_images \
    --config-name influx_synth_radtan \
    base_dir="$OUTPUT_ROOT" \
    distortion=my_distortion \
    overwrite=false
```

#### H5 Path Behavior

The H5 files store absolute paths to the prepared images. Do not move the prepared `influx_synth/` tree after generating its H5 files. Regenerate the H5 files if the prepared tree moves.

### Step 4: Run the Toy Training Examples

After generating the H5 files, run one of the two examples below. Both examples load PyTorch batches through `InFluxSynthDataset` and demonstrate how loader outputs can be connected to model predictions and supervision. The toy models are intentionally small and are not intended as competitive calibration models.

#### Raw Intrinsics Regression

For radial data:

```bash
python examples/train.py \
    --config-name example_train_intrinsics \
    data=influx_synth_radial \
    data.dataset_dir="$OUTPUT_ROOT" \
    train.steps=100
```

For radial-tangential data:

```bash
python examples/train.py \
    --config-name example_train_intrinsics \
    data=influx_synth_radtan \
    data.dataset_dir="$OUTPUT_ROOT" \
    train.steps=100
```

The model directly regresses the camera parameters returned for the transformed image:

```text
radial:2  → [fx, fy, cx, cy, k1, k2]
radtan:4  → [fx, fy, cx, cy, k1, k2, p1, p2]
```

#### Dense Ray Regression

For radial data:

```bash
python examples/train.py \
    --config-name example_train_rays \
    data=influx_synth_radial \
    data.dataset_dir="$OUTPUT_ROOT" \
    train.steps=40
```

The ground truth ray directions are generated by the loader after it transforms the radial intrinsics to match the returned image. The toy model predicts one ray direction per pixel and uses a masked cosine loss.

Dense ray regression is unavailable for `radtan:4` in this release.

Add `--print-config` to print the fully resolved `data`, `model`, and `train` configuration after defaults, interpolation, and command-line overrides are composed and before training begins:

```bash
python examples/train.py \
    --config-name example_train_intrinsics \
    --print-config \
    data=influx_synth_radial \
    data.dataset_dir="$OUTPUT_ROOT" \
    train.steps=1
```

## Other Non-Distortion Augmentation Details

### Photometric Augmentations

The `influx_synth` preset retains the default color and basic noise perturbations from public AnyCalib's `geocalib` augmentation preset, with the same parameter ranges and probabilities:

| Transformation | Parameters |
|---|---|
| Random gamma | range `80`–`180`, probability `0.8` |
| Random tone curve | scale `0.1`, probability `0.5` |
| Brightness and contrast | probability `0.5` |
| Color jitter | brightness, contrast, saturation, and hue magnitude `0.2`; probability `0.4` |
| Grayscale / sepia / unchanged | probabilities `0.1` / `0.1` / `0.8` |
| Gaussian noise | variance range `5`–`112`, probability `0.75` |
| JPEG compression | quality range `20`–`100`, probability `1.0` |
| ISO noise | color shift `0.01`–`0.05`, intensity `0.1`–`0.5`, probability `0.5` |

The InFlux++ Synth preset disables the AnyCalib preset's downscaling branch and its advanced-blur/sharpening branch.

Set:

```text
data.augmentations.name=identity
```

to disable photometric augmentation.

### Geometric Augmentations

The released geometric configuration samples a target aspect ratio in `H/W` order from:

```text
[0.5, 0.632812]
```

This range is geometrically centered around the native InFlux++ Synth aspect ratio:

```text
720 / 1280 = 0.5625
```

The loader combines the sampled aspect ratio with the target resolution, center-crops the image to the requested geometry, and resizes it. This centered crop preserves the image center apart from integer and edge-divisibility rounding. `intrinsics`, `scale_xy`, and `shift_xy` are updated to match the returned image.

Note that asymmetric cropping to vary the location of the principal point is available via a separate `data.im_geom_transform.crop` option; however, the released InFlux++ Synth preset uses `crop: null`, which disables this behavior.

## Configuration Reference

The public configuration files are:

| Configuration | Purpose |
|---|---|
| `siclib/configs/data/influx_synth.yaml` | Shared loader, preprocessing, photometric, and geometric settings |
| `siclib/configs/data/influx_synth_radial.yaml` | `radial:2` runtime mode with ray support |
| `siclib/configs/data/influx_synth_radtan.yaml` | `radtan:4` runtime mode without ray support |
| `siclib/datasets/configs/influx_synth_radial.yaml` | Radial H5 generation |
| `siclib/datasets/configs/influx_synth_radtan.yaml` | Radial-tangential H5 generation |
| `siclib/datasets/configs/distortion/influx_pp.yaml` | Released distortion sampler |
| `siclib/datasets/configs/distortion/none.yaml` | Zero-distortion profile |
| `siclib/configs/example_train_intrinsics.yaml` | Raw-intrinsics toy example |
| `siclib/configs/example_train_rays.yaml` | Dense-ray toy example |

## Troubleshooting

### The Dataset Directory Name Is Rejected

The current loader expects the dataset-directory basename to be:

```text
influx_synth
```

Use a parent directory to distinguish radial, radial-tangential, and experimental variants:

```text
loader_data/radial/influx_synth
loader_data/radtan/influx_synth
```

### H5 Files Cannot Find Images

The H5 files contain absolute prepared-image paths. Restore the prepared tree to its original location or regenerate the H5 files after moving it.

### `radtan:4` Fails When Rays Are Enabled

Ray-grid generation is not implemented for radial-tangential cameras in this release. Use `data=influx_synth_radtan` with `produce_rays: false`, or generate `radial:2` H5 files when rays are required.

### Hardlink Preparation Fails

Use source and output paths on a filesystem that supports hardlinks and permits linking the extracted RGB files.

### Albumentations API Warnings

This release requires:

```text
albumentations < 2
```

Install the package through its `pyproject.toml` so the supported dependency constraint is applied.

## Provenance and License

This standalone data loader is distributed under the [Apache License 2.0](LICENSE).

The camera models, camera factory, augmentation infrastructure, and supporting utilities are derived in part from [AnyCalib](https://github.com/javrtg/AnyCalib). The upstream Apache license is preserved verbatim in this directory. This release adds the InFlux++ Synth dataset reader and preparation workflow, radial-tangential camera support, configurable InFlux++ distortion profiles, public data configurations, and the toy training examples documented above.

Files modified from their upstream AnyCalib counterparts carry a short modification notice. Exact upstream files and exact historical upstream snapshots are retained without an InFlux modification label. The InFlux-specific changes are maintained by the Princeton Vision & Learning Lab and are not part of the upstream AnyCalib release.

## Citation

If you use this data loader or InFlux++ Synth, please cite InFlux++.

```bibtex
@misc{liang2026influxrealsyntheticdata,
    title = {InFlux++: Real and Synthetic Data for Estimating Dynamic Camera Intrinsics},
    author = {Erich Liang and Caleb Kha-Uong and Chinmaya Saran and Sreemanti Dey and David W. Liu and Junhan Ouyang and Benjamin Zhou and Jia Deng},
    year = {2026},
    eprint = {2607.05389},
    archivePrefix = {arXiv},
    primaryClass = {cs.CV},
    url = {https://arxiv.org/abs/2607.05389}
}
```

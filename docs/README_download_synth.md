# Downloading and Extracting InFlux-Synth

[InFlux-Synth](https://huggingface.co/datasets/princeton-vl/InFlux-Synth) is the synthetic training dataset introduced as InFlux++ Synth.

The `influx-download-synth` utility supports:

- Selecting individual dataset partitions
- Selecting depth and surface normal modalities
- Downloading a small sample before beginning a full download
- Extracting downloaded compressed files

Complete the [base installation instructions](README_download.md#base-installation) before continuing.

Because the complete release is several terabytes, we recommend reviewing the partitions and storage requirements below and testing the workflow with `--sample` first.

## Dataset Partitions

| Partition | Scene type | Videos | Frames | Available contents |
|---|---|---:|---:|---|
| **`indoors/`** | Indoor | 515 | 123,600 | RGB images, camera intrinsics, camera pose, and camera metadata |
| **`nature/`** | Nature | 508 | 121,920 | RGB images, camera intrinsics, camera pose, and camera metadata |
| **`indoors_full/`** | Indoor | 525 | 126,000 | Base contents, plus depth and surface normals |
| **`nature_full/`** | Nature | 293 | 70,320 | Base contents, plus depth and surface normals |
| **Combined** | — | **1,841** | **441,840** | — |

All videos contain 240 frames.

The `_full` partitions contain distinct videos rather than duplicate copies of videos in the corresponding base partitions. They include the same RGB and camera metadata modalities as the base partitions, with depth and surface normal modalities available in addition.

If `--partitions` is omitted, all four partitions are selected.

## Storage Requirements

Review the storage requirements before beginning a full download:

| Data group | As distributed | After extraction and decoding |
|---|---:|---:|
| Images, camera intrinsics, and camera poses | 573 GiB | 573 GiB |
| `Depth` + `DepthSharp` | 1.14 TiB | 1.41 TiB |
| `SurfaceNormal` + `SurfaceNormalSharp` | 1.38 TiB | 4.20 TiB |
| **Complete release** | **3.08 TiB** | **6.16 TiB** |

Actual disk usage may vary slightly with filesystem overhead.

The depth and surface normal modalities are each provided in two variants:

- **`Depth` and `SurfaceNormal`** are rendered with depth of field using Blender's thin-lens camera model. Each pixel may aggregate information over multiple sampled aperture rays, so values can blend near object boundaries.
- **`DepthSharp` and `SurfaceNormalSharp`** are rendered without depth of field. These variants correspond to an ideal pinhole camera model and preserve sharp object and surface boundaries.

Depth and surface normal modalities are available only in the `indoors_full/` and `nature_full/` partitions.

## Quick Start

### Download and Extract a Small RGB and Intrinsics Sample

```bash
influx-download-synth \
    --partitions indoors nature_full \
    --sample \
    --extract
```

This downloads one scene from each selected partition. The sample contains RGB images and their corresponding camera intrinsics, camera pose, and lens metadata.

Because no additional modalities are selected, this command does not download depth or surface normals from `nature_full/`.

By default, data is stored under:

```text
<repository-root>/influx_synth_data/
```

### Download and Extract All RGB and Intrinsics Data

This is the primary workflow for users who do not require depth or surface normals:

```bash
influx-download-synth \
    --extract
```

By default, all four partitions are selected. `Image.tar.gz` and `camview.tar.gz` are downloaded and extracted for every scene.

### Download and Extract a Small Sample with Depth and Surface Normals

```bash
influx-download-synth \
    --partitions nature_full \
    --include depth_sharp surface_normals \
    --sample \
    --extract
```

This downloads one `nature_full` scene with:

- RGB images
- Camera intrinsics, camera pose, and lens metadata
- Sharp depth
- Surface normals rendered with depth of field

### Download and Extract All Available Data

```bash
influx-download-synth \
    --include \
        depth \
        depth_sharp \
        surface_normals \
        surface_normals_sharp \
    --extract
```

This selects all four partitions and downloads every available modality. Depth and surface normal modalities are downloaded only for the `_full` partitions.

### Use a Custom Output Directory

```bash
influx-download-synth \
    --partitions nature_full \
    --sample \
    --extract \
    --output-dir /path/to/InFlux-Synth
```

Options may be combined as needed when selecting partitions, modalities, extraction behavior, and an output directory.

## Command-Line Options

| Option | Description | Default |
|---|---|---|
| `--output-dir PATH` | Directory in which to store the dataset | `<repository-root>/influx_synth_data` |
| `--partitions PARTITION [...]` | Partitions to download | All four |
| `--include EXTRA [...]` | Depth and surface normal modalities to download for selected `_full` partitions | None |
| `--max-workers N` | Number of concurrent Hugging Face file downloads | `8` |
| `--sample` | Download one scene from each selected partition | Disabled |
| `--extract` | Extract downloaded files and decode selected surface normal data | Disabled |

Accepted partition values are:

```text
indoors
indoors_full
nature
nature_full
```

Accepted `--include` values are:

```text
depth
depth_sharp
surface_normals
surface_normals_sharp
```

The `--include` option does not implicitly select a `_full` partition. For example:

```bash
influx-download-synth \
    --partitions indoors \
    --include depth
```

downloads only RGB images and camera metadata because depth is not available in `indoors/`.

For the complete command reference:

```bash
influx-download-synth --help
```

## Output Structure

Before extraction, a selected `_full` scene containing all available modalities has the following structure:

```text
influx_synth_data/
└── nature_full/
    └── nature_000508/
        ├── Image.tar.gz
        ├── camview.tar.gz
        ├── Depth.tar.gz
        ├── DepthSharp.tar.gz
        ├── SurfaceNormal/
        │   ├── SurfaceNormal_1_0.mkv
        │   └── SurfaceNormal_1_0_visual_maps.tar.gz
        └── SurfaceNormalSharp/
            ├── SurfaceNormalSharp_1_0.mkv
            └── SurfaceNormalSharp_1_0_visual_maps.tar.gz
```

Only modalities selected by the command will be present.

After running with `--extract`, the selected scene has the following logical structure:

```text
influx_synth_data/
└── nature_full/
    └── nature_000508/
        ├── Image/                  # 240 RGB .png files
        ├── camview/                # 240 camera metadata .npz files
        ├── Depth/                  # 240 .npy files and 240 .png previews
        ├── DepthSharp/             # 240 .npy files and 240 .png previews
        ├── SurfaceNormal/          # 240 .npy files and 240 .png previews
        └── SurfaceNormalSharp/     # 240 .npy files and 240 .png previews
```

For depth and surface normals, use the `.npy` files for numerical analysis. The corresponding `.png` files are intended only for visualization.

Successfully processed compressed files are removed after extraction.

For complete modality descriptions, array shapes, and coordinate conventions, see the [InFlux-Synth dataset card](https://huggingface.co/datasets/princeton-vl/InFlux-Synth).

## Verify a Fully Extracted Release

After extracting the complete release, generate a completeness report using:

```bash
influx-verify-synth
```

By default, the command examines:

```text
<repository-root>/influx_synth_data/
```

To inspect a custom output directory, pass it as a positional argument:

```bash
influx-verify-synth /path/to/InFlux-Synth
```

The report checks the expected scene counts and verifies that each required file type contains 240 files per scene.

The current verifier is designed for a fully extracted release. In the `_full` partitions, it expects RGB images, camera metadata, both depth variants, and both surface normal variants. Intentionally partial or sampled downloads will therefore be reported as incomplete.

## Repeated or Interrupted Downloads

To retry a download, rerun the same command with the same output directory.

The dataset can also be assembled incrementally. For example, users may download RGB images and camera metadata first, then rerun the utility with additional `--include` values later.

Because successfully extracted compressed files are removed, rerunning a download after extraction may download missing archives again. For large downloads, select all desired modalities before extraction when practical.

To reduce download concurrency:

```bash
influx-download-synth \
    --max-workers 4 \
    --sample
```

If Xet-related download errors occur, retry with Xet disabled:

```bash
HF_HUB_DISABLE_XET=1 influx-download-synth \
    --sample
```

### Recovering from a Failed Extraction

A failed extraction may leave an affected scene partially extracted. Remove the affected scene directory before retrying the same command.

For example:

```bash
rm -rf influx_synth_data/nature_full/nature_000508
```

Then rerun the original command.
# Downloading and Extracting InFlux-Real

[InFlux-Real](https://huggingface.co/datasets/princeton-vl/InFlux-Real) is the unified real-world benchmark release for the InFlux project. It contains:

- **`influx/`**, the original InFlux benchmark
- **`influx_pp_real/`**, InFlux++ Real, a real-world benchmark extension of InFlux

The `influx-download-real` utility can download either partition independently or the complete release. It can also decode the distributed `.mp4` videos into per-frame `.tiff` images.

Complete the [base installation instructions](README_download.md#base-installation) before continuing.

## Benchmark Overview

| Partition | Videos | Frames | Validation videos / frames | Test videos / frames | Avg. frames/video |
|---|---:|---:|---:|---:|---:|
| **`influx/`** | 386 | 143,513 | 70 / 21,546 | 316 / 121,967 | ~372 |
| **`influx_pp_real/`** | 334 | 514,135 | 50 / 77,449 | 284 / 436,686 | ~1,539 |
| **Combined** | **720** | **657,648** | **120 / 98,995** | **600 / 558,653** | **~913** |

Ground truth camera intrinsics are included for the validation splits. Ground truth for the test splits is withheld for evaluation through the submission server.

## Storage Requirements

Review the storage requirements before beginning a download or TIFF extraction:

| Partition | Compressed `.mp4` videos | Decoded `.tiff` frames |
|---|---:|---:|
| **`influx/`** | 124 GiB | 3.0 TiB |
| **`influx_pp_real/`** | 537 GiB | 7.0 TiB |
| **Complete release** | **661 GiB** | **10.0 TiB** |

The compressed-video column reports the approximate size of the `.mp4` files as distributed through Hugging Face. The decoded-frame column reports the approximate disk space required after converting all videos in the corresponding partition into `.tiff` frames.

The downloaded `.mp4` files are retained after TIFF extraction. If retaining both representations, ensure that enough storage is available for their combined size.

Actual disk usage may vary slightly with filesystem overhead.

## Quick Start

### Download Both Partitions and Extract TIFF Frames

This is the typical workflow for users preparing the complete real-world benchmark for evaluation:

```bash
influx-download-real \
    --extract-frames
```

By default, both benchmark partitions are downloaded. The original `.mp4` videos are retained after the frames are extracted.

Data is stored under:

```text
<repository-root>/influx_real_data/
```

### Download Videos Without Extracting Frames

```bash
influx-download-real
```

This downloads both benchmark partitions as `.mp4` videos together with their benchmark JSON files.

### Download One Benchmark Partition

For example, download only InFlux++ Real:

```bash
influx-download-real \
    --partitions influx_pp_real
```

### Use a Custom Output Directory

```bash
influx-download-real \
    --output-dir /path/to/InFlux-Real
```

### Combine Options

```bash
influx-download-real \
    --partitions influx \
    --extract-frames \
    --output-dir /path/to/InFlux-Real
```

## Command-Line Options

| Option | Description | Default |
|---|---|---|
| `--output-dir PATH` | Directory in which to store the benchmark | `<repository-root>/influx_real_data` |
| `--partitions PARTITION [...]` | Partitions to download; accepted values are `influx` and `influx_pp_real` | Both |
| `--max-workers N` | Number of concurrent Hugging Face file downloads | `8` |
| `--extract-frames` | Decode downloaded `.mp4` videos into per-frame `.tiff` images | Disabled |

Supply multiple partitions after one `--partitions` option:

```bash
influx-download-real \
    --partitions influx influx_pp_real
```

For the complete command reference:

```bash
influx-download-real --help
```

## Video Playback

The `.mp4` files use YUV 4:4:4 chroma sampling, which may not be supported by every browser or default system video player.

For local playback, we recommend [VLC](https://www.videolan.org/).

## TIFF Frame Extraction

When `--extract-frames` is supplied, every video in each selected partition is decoded into:

```text
<output-dir>/<partition>/frames/<video-name>/
```

The corresponding `.mp4` file remains under the partition's `videos/` directory.

## Output Structure

After downloading both benchmark partitions:

```text
influx_real_data/
├── influx/
│   ├── videos/
│   │   └── *.mp4
│   ├── video_frame_count_and_split_v1.json
│   └── gt_validation_dict_v1.json
└── influx_pp_real/
    ├── videos/
    │   └── *.mp4
    ├── video_frame_count_and_split_v2.json
    └── gt_validation_dict_v2.json
```

After running with `--extract-frames`, the selected partitions additionally contain:

```text
influx_real_data/
├── influx/
│   ├── videos/
│   │   └── *.mp4
│   └── frames/
│       └── <video-name>/
│           └── *.tiff
└── influx_pp_real/
    ├── videos/
    │   └── *.mp4
    └── frames/
        └── <video-name>/
            └── *.tiff
```

The benchmark JSON files remain under their corresponding partition directories.

For benchmark details and the ground truth annotation schema, see the [InFlux-Real dataset card](https://huggingface.co/datasets/princeton-vl/InFlux-Real).

## Repeated or Interrupted Downloads

To retry a download, rerun the same command with the same output directory:

```bash
influx-download-real \
    --partitions influx_pp_real \
    --output-dir /path/to/InFlux-Real
```

The utility can also be used incrementally. For example, users may download `influx/` first and add `influx_pp_real/` later using the same output directory.

To reduce download concurrency:

```bash
influx-download-real \
    --max-workers 4
```

If Xet-related download errors occur, retry with Xet disabled:

```bash
HF_HUB_DISABLE_XET=1 influx-download-real
```

## Submit and Evaluate Results

After downloading InFlux-Real, follow the [Submit and Evaluate Results](README_evaluation.md) guide to generate, validate, and upload test-set predictions.

Public results are displayed on the [live InFlux leaderboard](https://influx.cs.princeton.edu/leaderboard).
# Submit and Evaluate Results

InFlux-Real includes public ground truth camera intrinsics for its validation splits. Ground truth for the test splits is withheld for evaluation through the InFlux submission server.

The submission system supports three benchmark targets:

| Target | Evaluation |
|---|---|
| `influx` | Original InFlux test split |
| `influx_pp_real` | InFlux++ Real test split |
| `all` | Both test splits, with InFlux, InFlux++ Real, and aggregate statistics |

Evaluation results are returned by email. Results that are made public are displayed on the [live InFlux leaderboard](https://influx.cs.princeton.edu/leaderboard).

## Installation

Complete the [base installation instructions](README_download.md#base-installation):

```bash
conda create --name influx python=3.11
conda activate influx
pip install -e .
```

Confirm that the upload command is available:

```bash
influx-upload --help
```

## Required Benchmark Metadata

Before uploading, the submission client validates the submitted videos and frames using the InFlux-Real split JSON files.

By default, it expects the files at:

```text
<repository-root>/influx_real_data/influx/video_frame_count_and_split_v1.json
<repository-root>/influx_real_data/influx_pp_real/video_frame_count_and_split_v2.json
```

These are the default locations created by the InFlux-Real download utility.

The required manifest depends on the selected target:

| Target | Required split manifest |
|---|---|
| `influx` | `video_frame_count_and_split_v1.json` |
| `influx_pp_real` | `video_frame_count_and_split_v2.json` |
| `all` | Both files |

If the files are stored elsewhere, pass their paths explicitly using:

```text
--influx-split-json-path
--influx-pp-real-split-json-path
```

The upload client requires the split manifests for local validation but does not read the video files during upload.

## Submission Format

A submission is a single JSON file containing metadata followed by per-frame predictions for every required test video.

The following example uses the radial-tangential Brown–Conrady camera model:

```json
{
  "submission_metadata": {
    "method_name": "your_method_name",
    "intrinsics_type": "rad-tan",
    "version": "influx"
  },
  "test_video1": {
    "0": {
      "fx": 0.0,
      "fy": 0.0,
      "cx": 0.0,
      "cy": 0.0,
      "k1": 0.0,
      "k2": 0.0,
      "p1": 0.0,
      "p2": 0.0
    },
    "1": {
      "fx": 0.0,
      "fy": 0.0,
      "cx": 0.0,
      "cy": 0.0,
      "k1": 0.0,
      "k2": 0.0,
      "p1": 0.0,
      "p2": 0.0
    }
  }
}
```

Each top-level video key must match the stem of a required test-video filename. Frame indices are represented as strings:

```text
"0"
"1"
"2"
```

Do not add leading zeros to frame indices.

### Submission Metadata

| Field | Accepted values |
|---|---|
| `method_name` | Name used to identify the submitted method |
| `intrinsics_type` | `"rad-tan"` or `"mei"` |
| `version` | `"influx"`, `"influx_pp_real"`, or `"all"` |

The value of `submission_metadata.version` must match the value passed to `influx-upload --version`.

### Required Intrinsics Parameters

For `rad-tan` submissions, every frame must contain:

```text
fx, fy, cx, cy, k1, k2, p1, p2
```

For `mei` submissions, every frame must contain:

```text
fx, fy, cx, cy, xi
```

Predictions should be finite numeric values.

If your method uses a different camera model, contact:

`influxbenchmark@gmail.com`

## Generate a Submission Template

The base package includes the `influx-generate-sample` utility for creating a submission template with the required test videos and frame indices.

View the available options using:

```bash
influx-generate-sample --help
```

Fill in every required prediction value before uploading the generated JSON file.

## Upload a Submission

Use:

```bash
influx-upload \
    --email your_email@example.com \
    --path path/to/submission.json \
    --method-name your_method_name \
    --version influx
```

The method name passed to `--method-name` must exactly match:

```json
"submission_metadata": {
  "method_name": "your_method_name"
}
```

### Submit to InFlux

```bash
influx-upload \
    --email your_email@example.com \
    --path path/to/influx_submission.json \
    --method-name your_method_name \
    --version influx
```

The JSON metadata must contain:

```json
"version": "influx"
```

### Submit to InFlux++ Real

```bash
influx-upload \
    --email your_email@example.com \
    --path path/to/influx_pp_real_submission.json \
    --method-name your_method_name \
    --version influx_pp_real
```

The JSON metadata must contain:

```json
"version": "influx_pp_real"
```

### Submit to Both Benchmarks

```bash
influx-upload \
    --email your_email@example.com \
    --path path/to/all_submission.json \
    --method-name your_method_name \
    --version all
```

The JSON metadata must contain:

```json
"version": "all"
```

A submission targeting `all` must contain every required video and frame from both real-world benchmark test splits.

## Custom Split-Manifest Paths

If InFlux-Real was downloaded outside the default repository directory, pass the corresponding manifest path.

For the original InFlux benchmark:

```bash
influx-upload \
    --email your_email@example.com \
    --path path/to/submission.json \
    --method-name your_method_name \
    --version influx \
    --influx-split-json-path /path/to/video_frame_count_and_split_v1.json
```

For InFlux++ Real:

```bash
influx-upload \
    --email your_email@example.com \
    --path path/to/submission.json \
    --method-name your_method_name \
    --version influx_pp_real \
    --influx-pp-real-split-json-path /path/to/video_frame_count_and_split_v2.json
```

For `all`, provide both paths when neither file is stored in its default location.

## Local Validation

Before connecting to the evaluation server, `influx-upload` validates the submission locally.

The client checks:

- The submission is a `.json` file
- The file does not exceed 512 MiB
- The JSON contains `submission_metadata`
- `method_name`, `intrinsics_type`, and `version` are present
- The method name is at most 100 characters
- The method name contains only letters, numbers, underscores, and dashes
- The selected benchmark target is valid
- The JSON target matches the value passed to `--version`
- Every required test video is present
- Every required frame is present
- Every required intrinsics parameter is present
- Numeric predictions are finite
- The command-line method name matches the method name in the JSON

Extra videos, frames, and parameters are ignored.

The submission filename may contain letters, numbers, underscores, dots, and dashes. It must begin with a letter, number, or underscore and end in `.json`.

## Verification and Upload Flow

After the file passes local validation:

1. The client contacts the InFlux submission server.
2. A verification code is sent to the supplied email address.
3. The server creates a submission ID and the client displays it.
4. Enter the verification code when prompted.
5. The JSON file is uploaded.
6. The server schedules the evaluation.
7. Results are returned by email.

Save the submission ID. It is used to identify the result and to publish or modify its leaderboard metadata.

Results are typically returned within a few hours.

Each email address may upload at most **three submissions every seven days**.

## Live Leaderboard

Public benchmark results are displayed on the:

[InFlux Live Leaderboard](https://influx.cs.princeton.edu/leaderboard)

## Command-Line Reference

View all upload options using:

```bash
influx-upload --help
```

The normal submission workflow uses:

```text
--email
--path
--method-name
--version
```

Additional options are available for:

- Using a different submission-server URL
- Supplying custom locations for the InFlux split manifest
- Supplying custom locations for the InFlux++ Real split manifest

## Related Documentation

- [Installation and Data Downloads](README_download.md)
- [Download and extract InFlux-Real](README_download_real.md)
- [InFlux-Real dataset card](https://huggingface.co/datasets/princeton-vl/InFlux-Real)
- [Live leaderboard](https://influx.cs.princeton.edu/leaderboard)
- [Main project README](../README.md)

## Support

For questions about submission formatting, evaluation, or the leaderboard, contact:

`influxbenchmark@gmail.com`
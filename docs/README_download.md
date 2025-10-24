# Download from HuggingFace


## Requirements
Please install the influx package and ffmpeg.

```bash
pip install .

# ffmeg required for extracting frames from video files
sudo apt-get install ffmpeg  # Ubuntu/Debian
brew install ffmpeg          # macOS
```

To view the videos locally, we also recommend using VLC Media Viewer, which can be downloaded [here](https://www.videolan.org/).

## ⚡ Quick Start

```bash
# Download videos, but do not extract video frames
python scripts/download_influx.py

# Or Download and extract frames in one command  
python scripts/download_influx.py --extract-frames

# By default, your data will be ready in influx_data/


# Specifying custom output directory
python scripts/download_influx.py --extract-frames --output-dir my_directory
```

## 📁 Dataset Contents

The dataset includes 386 `.mp4` videos and 2 `.json` files in the root directory:

- **Dynamic Intrinsics Videos (`.mp4`)**  
  Videos with dynamic intrinsics, moving objects, and camera motion.  

- **Frame Counts and Split (`video_frame_count_and_split.json`)**  
  Maps each video to its number of frames and whether it belongs to the validation or test split.  

- **Validation Ground Truth (`gt_validation_dict.json`)**  
  Maps validation video frames to ground truth intrinsics values.

---

### JSON File Structures

#### `video_frame_count_and_split.json`

```json
{
    "video_shot_1": {
        "frame_count": 1234,
        "split": "val"
    }
}
```

- `frame_count` – Number of frames in the video.

- `split` – Denotes which split the video belongs in. The value will either be "val" or "test".

#### `gt_validation_dict.json`

```json
{
    "video_shot_1": {
        "0": {
            "intrinsics_gt": {
                "fx": ..., "fy": ..., "cx": ..., "cy": ...,
                "k1": ..., "k2": ..., "p1": ..., "p2": ...
            },
            "intrinsics_gt_extrapolated": { ... },
            "lens_metadata": {
                "focal_length_mm": ...,
                "focus_distance_m": ...
            }
        },
        "1": { ... },
        ...
    }
}
```

**Per-frame keys:**
- `intrinsics_gt` – Ground truth intrinsics from look-up table (LUT) interpolation.
    - `fx, fy, cx, cy, k1, k2, p1, p2` denote the intrinsics parameters as specified by the rad-tan Brown-Conrady distortion model.

- `intrinsics_gt_extrapolated` – The same as `intrinsics_gt`, but also provides extrapolated intrinsics if lens metadata is outside of LUT bounds. It contains the same fields as `intrinsics_gt`.

- `lens_metadata` – Raw physical lens parameters `focal_length_mm`, `focus_distance_m`

## File Structure

Once all frames are extracted, the expected file structure is:

```
influx_data/
└── dataset/                             # Raw dataset downloaded
    ├── video1.mp4
    ├── video2.mp4
    ├── ...                              # More video files
    ├── gt_validation_dict.json          # Validation ground truth
    └── video_frame_count_and_split.json # Frame counts and val/test split

frames/                                  # Extracted frames per video
└── video1/
    ├── 0000000.tiff
    ├── 0000001.tiff
    ├── 0000002.tiff
    └── ...                              # Remaining frames
└── video2/
    ├── 0000000.tiff
    ├── 0000001.tiff
    └── ...                              # Remaining frames

```

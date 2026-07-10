import argparse
import json
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parent.parent
DEFAULT_ROOT = f"{REPO_ROOT}/influx_real_data"
SEPARATOR_WIDTH = 88
FRAMES_FOLDER_NAME = "frames"
FRAME_SUFFIX = ".tiff"
DATASETS = (
    ("InFlux", "influx"),
    ("InFlux++ Real", "influx_pp_real"),
)
METADATA_FILENAMES = {
    "influx": "video_frame_count_and_split_v1.json",
    "influx_pp_real": "video_frame_count_and_split_v2.json",
}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Report frame-count completeness for InFlux real-data extraction."
    )
    parser.add_argument(
        "root",
        nargs="?",
        default=DEFAULT_ROOT,
        help=(
            "Path to the root folder containing influx and influx_pp_real. "
            f"Default: {DEFAULT_ROOT}"
        ),
    )
    return parser.parse_args()


def format_ratio(numerator, denominator):
    if denominator == 0:
        return "n/a"
    return f"{numerator}/{denominator} ({100.0 * numerator / denominator:.2f}%)"


def list_immediate_dirs(path):
    if not path.is_dir():
        return []
    return sorted((child for child in path.iterdir() if child.is_dir()), key=lambda p: p.name)


def count_files_with_suffix(path, suffix):
    if not path.is_dir():
        return 0

    suffix = suffix.lower()
    return sum(
        1
        for child in path.iterdir()
        if child.is_file() and child.suffix.lower() == suffix
    )


def load_metadata(json_path):
    if not json_path.is_file():
        return None, f"metadata file is missing: {json_path}"

    try:
        with json_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        return None, f"metadata file could not be parsed as JSON: {exc}"
    except OSError as exc:
        return None, f"metadata file could not be read: {exc}"

    if not isinstance(data, dict):
        return None, "metadata file root must be a JSON object"

    return data, None


def get_expected_frame_count(video_metadata):
    if not isinstance(video_metadata, dict):
        return None

    frame_count = video_metadata.get("frame_count")
    if isinstance(frame_count, bool) or not isinstance(frame_count, int):
        return None

    if frame_count < 0:
        return None

    return frame_count


def print_frame_count_summary(matches, denominator):
    print("\nFrame-count matches, using JSON video count as denominator:")
    print(
        f"  - frames/<video>/*{FRAME_SUFFIX} == frame_count: "
        f"{format_ratio(matches, denominator)}"
    )


def report_dataset(root, display_name, folder_name):
    dataset_path = root / folder_name
    metadata_path = dataset_path / METADATA_FILENAMES[folder_name]
    frames_path = dataset_path / FRAMES_FOLDER_NAME

    print("=" * SEPARATOR_WIDTH)
    print(f"Dataset: {display_name}")
    print(f"Path:    {dataset_path}")
    print(f"Metadata JSON: {metadata_path}")
    print(f"Frames path:   {frames_path}")

    if not dataset_path.is_dir():
        print(f"WARNING: dataset folder is missing: {dataset_path}")
        print("Expected videos from JSON: n/a")
        print("Actual immediate frame directories: n/a")
        print_frame_count_summary(0, 0)
        return

    metadata, metadata_error = load_metadata(metadata_path)
    frame_dirs = list_immediate_dirs(frames_path)
    actual_frame_dir_count = len(frame_dirs)

    if metadata_error is not None:
        print(f"WARNING: {metadata_error}")
        print("Expected videos from JSON: n/a")
        print(f"Actual immediate frame directories: {actual_frame_dir_count}")
        if not frames_path.is_dir():
            print(f"WARNING: frames folder is missing: {frames_path}")
        print_frame_count_summary(0, 0)
        return

    expected_video_count = len(metadata)
    expected_video_names = set(metadata.keys())
    actual_frame_dir_names = {path.name for path in frame_dirs}
    missing_frame_dir_count = len(expected_video_names - actual_frame_dir_names)
    extra_frame_dir_count = len(actual_frame_dir_names - expected_video_names)

    print(f"Expected videos from JSON: {expected_video_count}")
    print(f"Actual immediate frame directories: {actual_frame_dir_count}")

    if not frames_path.is_dir():
        print(f"WARNING: frames folder is missing: {frames_path}")

    print(f"Missing frame directories by JSON count: {missing_frame_dir_count}")
    print(f"Extra frame directories not listed in JSON: {extra_frame_dir_count}")

    matching_frame_count_entries = 0
    valid_frame_count_entries = 0

    for video_name, video_metadata in metadata.items():
        expected_frame_count = get_expected_frame_count(video_metadata)
        if expected_frame_count is None:
            continue

        valid_frame_count_entries += 1
        video_frames_path = frames_path / video_name
        actual_frame_count = count_files_with_suffix(video_frames_path, FRAME_SUFFIX)

        if video_frames_path.is_dir() and actual_frame_count == expected_frame_count:
            matching_frame_count_entries += 1

    invalid_frame_count_entries = expected_video_count - valid_frame_count_entries
    if invalid_frame_count_entries:
        print(f"Invalid frame_count entries in JSON: {invalid_frame_count_entries}")

    print_frame_count_summary(matching_frame_count_entries, expected_video_count)


def main():
    args = parse_args()
    root = Path(args.root).expanduser().resolve()

    print(f"Extraction status report for root: {root}")
    print("Expected frame files per video: value from dataset-specific metadata JSON")

    if not root.is_dir():
        print(f"WARNING: root path is not a directory: {root}")

    for display_name, folder_name in DATASETS:
        report_dataset(root, display_name, folder_name)


if __name__ == "__main__":
    main()
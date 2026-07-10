import argparse
from collections import Counter
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parent.parent
DEFAULT_ROOT = f"{REPO_ROOT}/influx_synth_data"
EXPECTED_FRAMES_PER_VIDEO = 240
SEPARATOR_WIDTH = 88
BASE_CHECKS = (
    ("camview", ".npz"),
    ("Image", ".png"),
)
FULL_EXTRA_CHECKS = (
    ("Depth", ".npy"),
    ("Depth", ".png"),
    ("DepthSharp", ".npy"),
    ("DepthSharp", ".png"),
    ("SurfaceNormal", ".npy"),
    ("SurfaceNormal", ".png"),
    ("SurfaceNormalSharp", ".npy"),
    ("SurfaceNormalSharp", ".png"),
)
DATASETS = (
    ("indoors", 515, BASE_CHECKS),
    ("indoors_full", 525, BASE_CHECKS + FULL_EXTRA_CHECKS),
    ("nature", 508, BASE_CHECKS),
    ("nature_full", 293, BASE_CHECKS + FULL_EXTRA_CHECKS),
)


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Report extraction completeness for indoors, indoors_full, "
            "nature, and nature_full dataset folders."
        )
    )
    parser.add_argument(
        "root",
        nargs="?",
        default=DEFAULT_ROOT,
        help=(
            "Path to the root folder containing the dataset folders. "
            f"Default: {DEFAULT_ROOT}"
        ),
    )
    return parser.parse_args()


def list_immediate_dirs(path):
    """Return immediate child directories only, sorted by name."""
    if not path.is_dir():
        return []
    return sorted((child for child in path.iterdir() if child.is_dir()), key=lambda p: p.name)


def suffix_counts(folder):
    """Count file suffixes in one folder, non-recursively."""
    if not folder.is_dir():
        return Counter()

    counts = Counter()
    for child in folder.iterdir():
        if child.is_file():
            counts[child.suffix] += 1
    return counts


def check_label(subfolder, suffix):
    return f"{subfolder}/*{suffix} == {EXPECTED_FRAMES_PER_VIDEO}"


def format_ratio(numerator, denominator):
    if denominator == 0:
        return "n/a"
    return f"{numerator}/{denominator} ({100.0 * numerator / denominator:.2f}%)"


def evaluate_video_dir(video_dir, checks):
    """Return {check_label: bool} for one actual immediate video directory."""
    counts_by_subfolder = {}
    results = {}

    for subfolder, suffix in checks:
        if subfolder not in counts_by_subfolder:
            counts_by_subfolder[subfolder] = suffix_counts(video_dir / subfolder)

        actual_count = counts_by_subfolder[subfolder].get(suffix, 0)
        results[check_label(subfolder, suffix)] = actual_count == EXPECTED_FRAMES_PER_VIDEO

    return results


def report_dataset(root, dataset_name, expected_videos, checks):
    dataset_path = root / dataset_name
    video_dirs = list_immediate_dirs(dataset_path)
    actual_count = len(video_dirs)

    print("=" * SEPARATOR_WIDTH)
    print(f"Dataset: {dataset_name}")
    print(f"Path:    {dataset_path}")
    print(f"Expected video folders: {expected_videos}")
    print(f"Actual immediate directories: {actual_count}")

    if not dataset_path.is_dir():
        print(f"WARNING: dataset folder is missing: {dataset_path}")
    elif actual_count < expected_videos:
        print(f"Missing video folders by count: {expected_videos - actual_count}")
    elif actual_count > expected_videos:
        print(f"Extra immediate directories by count: {actual_count - expected_videos}")

    per_check_passes = {check_label(subfolder, suffix): 0 for subfolder, suffix in checks}
    complete_video_dirs = 0

    for video_dir in video_dirs:
        results = evaluate_video_dir(video_dir, checks)
        if all(results.values()):
            complete_video_dirs += 1

        for label, passed in results.items():
            if passed:
                per_check_passes[label] += 1

    print("\nPer-check pass counts, using expected video count as denominator:")
    for subfolder, suffix in checks:
        label = check_label(subfolder, suffix)
        print(f"  - {label}: {format_ratio(per_check_passes[label], expected_videos)}")

    print(f"\nVideo folders with all required counts: {format_ratio(complete_video_dirs, expected_videos)}")


def main():
    args = parse_args()
    root = Path(args.root).expanduser().resolve()

    print(f"Extraction status report for root: {root}")
    print(f"Expected frames per required file type per video: {EXPECTED_FRAMES_PER_VIDEO}")

    if not root.is_dir():
        print(f"WARNING: root path is not a directory: {root}")

    for dataset_name, expected_videos, checks in DATASETS:
        report_dataset(root, dataset_name, expected_videos, checks)

    return 0


if __name__ == "__main__":
    main()
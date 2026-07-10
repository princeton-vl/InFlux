import argparse
import glob
import os

# Disable hf-xet by default. Must happen before importing huggingface_hub.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "60")

from extract_tiffs import extract_tiffs
from huggingface_hub import snapshot_download
from pathlib import Path
from tqdm import tqdm


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parent.parent
PARTITIONS = ("influx", "influx_pp_real")


def build_allow_patterns(partitions):
    return [f"{partition}/**" for partition in partitions]


def download_dataset(local_dir=f"{REPO_ROOT}/influx_real_data", partitions=PARTITIONS, max_workers=8):
    """Download selected partitions of the InFlux dataset from Hugging Face Hub."""
    snapshot_download(
        repo_id="erichliang/InFlux-Real",
        repo_type="dataset",
        local_dir=local_dir,
        allow_patterns=build_allow_patterns(partitions),
        max_workers=max_workers,
    )
    print(f"Dataset downloaded to {local_dir}")


def main(args):
    output_dir = args.output_dir
    download_dataset(output_dir, args.partitions, max_workers=args.max_workers)

    if args.extract_frames:
        for partition in args.partitions:
            video_paths = []

            pattern = os.path.join(output_dir, partition, "videos", "*.mp4")
            video_paths.extend(glob.glob(pattern))
            video_paths = sorted(video_paths)

            for video_path in tqdm(video_paths, desc="Extracting frames from videos..."):
                video_name = os.path.splitext(os.path.basename(video_path))[0]
                frame_dest = os.path.join(output_dir, partition, "frames", video_name)
                print(f"Extracting frames from {video_name}...")
                extract_tiffs(video_path, frame_dest)

        print("Frame extraction completed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Download the InFlux dataset and optionally extract frames."
    )
    parser.add_argument(
        "--output-dir",
        default=f"{REPO_ROOT}/influx_real_data",
    )
    parser.add_argument(
        "--partitions",
        nargs="+",
        choices=["influx", "influx_pp_real"],
        default=["influx", "influx_pp_real"],
        metavar="PARTITION",
        help="Partitions to download. Choices: influx, influx_pp_real. Defaults to both.",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=8,
        help="Number of concurrent Hugging Face file downloads. Default: 8.",
    )
    parser.add_argument(
        "--extract-frames",
        action="store_true",
        help="Extract frames using extract_tiffs after downloading the dataset.",
    )
    args = parser.parse_args()

    main(args)

import argparse
import os
import shutil

os.environ.setdefault("HF_XET_HIGH_PERFORMANCE", "1")
os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "60")

from extract_files import extract_files
from huggingface_hub import snapshot_download
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parent.parent
CONFIG_NAME = "influx_pp_synth_unpack.json"
PARTITIONS = ("indoors", "indoors_full", "nature", "nature_full")

SAMPLE_COUNT = 1
SAMPLE_STARTS = {
    "indoors": 0,
    "indoors_full": 515,
    "nature": 0,
    "nature_full": 508,
}

BASE_MODALITIES = {
    "image": "Image.tar.gz",
    "camview": "camview.tar.gz",
}


def build_allow_patterns(partitions, extras=(), sample=False):
    extras = set(extras)

    patterns = set()
    for partition in partitions:
        for modality in BASE_MODALITIES.values():
            patterns.add(f"{partition}/*/{modality}")

    if "depth" in extras:
        for partition in partitions:
            if partition.endswith("_full"):
                patterns.add(f"{partition}/*/Depth.tar.gz")
    
    if "depth_sharp" in extras:
        for partition in partitions:
            if partition.endswith("_full"):
                patterns.add(f"{partition}/*/DepthSharp.tar.gz")

    if "surface_normals" in extras:
        for partition in partitions:
            if partition.endswith("_full"):
                patterns.add(f"{partition}/*/SurfaceNormal/SurfaceNormal_1_0.mkv")
                patterns.add(f"{partition}/*/SurfaceNormal/SurfaceNormal_1_0_visual_maps.tar.gz")
    
    if "surface_normals_sharp" in extras:
        for partition in partitions:
            if partition.endswith("_full"):
                patterns.add(f"{partition}/*/SurfaceNormalSharp/SurfaceNormalSharp_1_0.mkv")
                patterns.add(f"{partition}/*/SurfaceNormalSharp/SurfaceNormalSharp_1_0_visual_maps.tar.gz")

    if sample:
        sample_patterns = set()
        for pattern in patterns:
            split, rest = pattern.split("/*/", 1)
            scene = split.removesuffix("_full")
            start = SAMPLE_STARTS[split]
            for index in range(start, start + SAMPLE_COUNT):
                sample_patterns.add(f"{split}/{scene}_{index:06d}/{rest}")
        patterns = sample_patterns

    return sorted(patterns)


def download_dataset(local_dir=f"{REPO_ROOT}/influx_synth_data", partitions=PARTITIONS, extras=(), max_workers=8, sample=False):
    """Download selected partitions/modalities of the InFlux-Synth dataset from Hugging Face Hub."""
    print(f"Downloading InFlux-Synth ({', '.join(partitions)}) with extras ({', '.join(extras)}) to {local_dir}")
    snapshot_download(
        repo_id="princeton-vl/InFlux-Synth",
        repo_type="dataset",
        local_dir=local_dir,
        allow_patterns=build_allow_patterns(partitions, extras, sample),
        max_workers=max_workers,
    )
    print(f"Dataset downloaded to {local_dir}")


def main(args):
    output_dir = args.output_dir
    download_dataset(output_dir, args.partitions, args.include, max_workers=args.max_workers, sample=args.sample)

    if args.extract:
        config_path = SCRIPT_PATH.parent / CONFIG_NAME
        tmp_dir = os.path.join(output_dir, "tmp")
        try:
            shutil.rmtree(tmp_dir)
        except FileNotFoundError:
            pass
        os.makedirs(tmp_dir, exist_ok=True)

        try:
            for split_name in args.partitions:
                split_dir = os.path.join(output_dir, split_name)
                if not os.path.isdir(split_dir):
                    print(f"Skipping missing split: {split_dir}")
                    continue

                scene_dirs = sorted(
                    os.path.join(split_dir, name)
                    for name in os.listdir(split_dir)
                    if os.path.isdir(os.path.join(split_dir, name))
                )

                for scene_dir in scene_dirs:
                    extract_files(scene_dir, split_dir, config_path, tmp_dir)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            for split_name in args.partitions:
                cvdpack_json = os.path.join(output_dir, split_name, "cvdpack.json")
                try:
                    os.remove(cvdpack_json)
                except FileNotFoundError:
                    pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Download the InFlux-Synth dataset from Hugging Face Hub."
    )
    parser.add_argument(
        "--output-dir",
        default=f"{REPO_ROOT}/influx_synth_data",
    )
    parser.add_argument(
        "--partitions",
        nargs="+",
        choices=["indoors", "indoors_full", "nature", "nature_full"],
        default=["indoors", "indoors_full", "nature", "nature_full"],
        metavar="PARTITION",
        help="Partitions to download. Choices: indoors, indoors_full, nature, nature_full. Defaults to all four.",
    )
    parser.add_argument(
        "--include",
        nargs="*",
        choices=["depth", "depth_sharp", "surface_normals", "surface_normals_sharp"],
        default=[],
        metavar="EXTRA",
        help="Optional full-split extras: depth, depth_sharp, surface_normals, surface_normals_sharp. Defaults to none.",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=8,
        help="Number of concurrent Hugging Face file downloads. Default: 8.",
    )
    parser.add_argument(
        "--sample",
        action="store_true",
        help="Download only a small sample from each split.",
    )
    parser.add_argument(
        "--extract",
        action="store_true",
        help="Extract archives after download (Image/camview for all splits; depth/normals for *_full).",
    )
    args = parser.parse_args()

    main(args)
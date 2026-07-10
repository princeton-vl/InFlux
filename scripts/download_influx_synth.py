import argparse
import os
import shutil

# Disable hf-xet by default. Must happen before importing huggingface_hub.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "60")

from extract_files import extract_files
from huggingface_hub import snapshot_download
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parent.parent
CONFIG_NAME = "influx_pp_synth_unpack.json"
SCENES = ("indoors", "nature")

BASE_MODALITIES = {
    "image": "Image/*",
    "camview": "camview/*",
}


def build_allow_patterns(scenes, extras=()):
    extras = set(extras)

    patterns = set()
    for scene in scenes:
        for modality in BASE_MODALITIES.values():
            patterns.add(f"{scene}/*/{modality}")
            patterns.add(f"{scene}_full/*/{modality}")

    if "depth" in extras:
        for scene in scenes:
            patterns.add(f"{scene}_full/*/Depth.tar.gz")
            patterns.add(f"{scene}_full/*/DepthSharp.tar.gz")

    if "surface_normals" in extras:
        for scene in scenes:
            patterns.add(f"{scene}_full/*/SurfaceNormal/*.mkv")
            patterns.add(f"{scene}_full/*/SurfaceNormalSharp/*.mkv")

    return sorted(patterns)


def download_dataset(local_dir=f"{REPO_ROOT}/influx_synth_data", scenes=SCENES, extras=(), max_workers=8):
    """Download selected scenes/modalities of the InFlux-Synth dataset from Hugging Face Hub."""
    snapshot_download(
        repo_id="erichliang/InFlux-Synth",
        repo_type="dataset",
        local_dir=local_dir,
        allow_patterns=build_allow_patterns(scenes, extras),
        max_workers=max_workers,
    )
    print(f"Dataset downloaded to {local_dir}")


def main(args):
    output_dir = args.output_dir
    download_dataset(output_dir, args.categories, args.include, max_workers=args.max_workers)

    if args.extract:
        config_path = SCRIPT_PATH.parent / CONFIG_NAME
        tmp_dir = os.path.join(output_dir, "tmp")
        os.makedirs(tmp_dir, exist_ok=True)

        for category in args.categories:
            for split_name in (category, f"{category}_full"):
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

        shutil.rmtree(tmp_dir, ignore_errors=True)
        for category in args.categories:
            for split_name in (category, f"{category}_full"):
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
        "--categories",
        nargs="+",
        choices=["indoors", "nature"],
        default=["indoors", "nature"],
        metavar="CATEGORY",
        help="Scenes to download. Choices: indoors, nature. Defaults to both.",
    )
    parser.add_argument(
        "--include",
        nargs="*",
        choices=["depth", "surface_normals"],
        default=[],
        metavar="EXTRA",
        help="Optional full-split extras: depth, surface_normals",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=8,
        help="Number of concurrent Hugging Face file downloads. Default: 8.",
    )
    parser.add_argument(
        "--extract",
        action="store_true",
        help="Extract archives after download (Image/camview for all splits; depth/normals for *_full).",
    )
    args = parser.parse_args()

    main(args)
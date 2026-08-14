"""Script to create a dataset from images."""

import hashlib
import logging
from math import acos, cos, hypot, pi, sin, sqrt, tan
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import h5py
import hydra
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import scipy
import torch
import torch.nn.functional as F
from omegaconf import DictConfig, OmegaConf
from PIL import Image
from torch import Tensor
from tqdm import tqdm
import json

from siclib.utils.distortion_sampler import sample_distortion_coefs
from siclib.utils.distort_utils import get_distortion_remap

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# we disable the image-size safeguard that PIL has, since otherwise it will raise an error
# when saving images.
Image.MAX_IMAGE_PIXELS = None

class DatasetGenerator:
    """Dataset generator class to create datasets from images."""

    default_conf = {
        "name": "???",
        # paths
        "base_dir": "???",
        "im_dir": "${.base_dir}",
        "im_train": "${.im_dir}/train",
        "im_val": "${.im_dir}/val",
        "im_test": "${.im_dir}/test",
        "train_h5": "${.base_dir}/train.h5",
        "val_h5": "${.base_dir}/val.h5",
        "test_h5": "${.base_dir}/test.h5",
        # general
        "overwrite": False,
        "cam_id": "???",
        "distortion": {"profile": "influx_pp"},
        "workers": 8,
    }

    def __init__(self, conf):
        """Init the class by merging and storing the config."""
        self.conf = OmegaConf.merge(
            OmegaConf.create(self.default_conf),
            OmegaConf.create(conf),
        )
        logger.info(f"Config:\n{OmegaConf.to_yaml(self.conf)}")

        camera_modes = {
            "radial:2": False,
            "radtan:4": True,
        }
        self.cam_id = str(self.conf.cam_id)
        if self.cam_id not in camera_modes:
            raise ValueError(
                f"Unsupported cam_id {self.cam_id!r}. "
                f"Expected one of: {', '.join(camera_modes)}"
            )

        self.include_tangent_distortion = camera_modes[self.cam_id]

        distortion_profile = OmegaConf.to_container(
            self.conf.distortion, resolve=True
        )
        if not isinstance(distortion_profile, dict):
            raise TypeError("distortion configuration must resolve to a mapping")
        self.distortion_profile = distortion_profile

    def plot_distributions(self):
        """Plot parameter distributions."""
        rows = {"train": [], "val": [], "test": []}
        base_row = {
            "f": None,
            "cx": None,
            "cy": None,
            "k1": None,
            "k2": None,
        }
        if self.include_tangent_distortion:
            base_row.update({"p1": None, "p2": None})
        for split in ["train", "val", "test"]:
            rows_ = rows[split]
            with h5py.File(self.conf[f"{split}_h5"], "r") as h5_file:  # type:ignore
                for group in h5_file.values():
                    row_ = base_row.copy()
                    attrs = group.attrs
                    if self.include_tangent_distortion:
                        fx, fy, cx, cy, k1, k2, p1, p2 = attrs['params'].tolist()
                    else:
                        fx, fy, cx, cy, k1, k2 = attrs['params'].tolist()
                    row_["f"] = (fx + fy) / 2.0
                    row_["cx"] = cx / attrs["w"]
                    row_["cy"] = cy / attrs["h"]
                    row_["k1"] = k1
                    row_["k2"] = k2
                    if self.include_tangent_distortion:
                        row_["p1"] = p1
                        row_["p2"] = p2
                    rows_.append(row_)
        dfs = {}
        for split in ["train", "val", "test"]:
            df = pd.DataFrame(rows[split])
            dfs[split] = df

        nplots = max(len(df.columns) for df in dfs.values())
        fig, axs = plt.subplots(3, nplots, figsize=(5 * nplots, 15))
        for i, split in enumerate(["train", "val", "test"]):
            df = dfs[split]
            for j, param in enumerate(df.columns):
                if df[param].isnull().all():
                    continue
                axs[i, j].hist(df[param], bins=100)
                axs[i, j].set_xlabel(param)
                axs[i, j].set_ylabel(f"Count {split}")
        fig.tight_layout()
        fig.savefig(Path(self.conf.im_dir) / "distributions.png", bbox_inches="tight")

    def compute_frame(self, img_path: Path, metadata_path: Path, frame_idx: int, video_id: str):
        """Compute frame data in a worker thread. No h5 writes here."""
        fname = img_path.name
        cam_id = self.cam_id

        with Image.open(img_path) as img:
            w, h = img.size

        with open(metadata_path, "r") as f:
            gt_data = json.load(f)

        intrinsics = gt_data["intrinsics_gt"]
        distortion = gt_data["lens_metadata"]

        fx, fy = intrinsics["fx"], intrinsics["fy"]
        cx, cy = intrinsics["cx"], intrinsics["cy"]
        fd_m, lfl_mm = distortion["fd_m"], distortion["lfl_mm"]
        lfl_m = lfl_mm / 1000
        dist_coefs = sample_distortion_coefs(
            h, w, lfl_m, fd_m, profile=self.distortion_profile
        )
        k1, k2, p1, p2 = dist_coefs
        if self.include_tangent_distortion:
            params = np.array([fx, fy, cx, cy, k1, k2, p1, p2], dtype=np.float64)
            dist_for_map = np.array([k1, k2, p1, p2], dtype=np.float64)
        else:
            params = np.array([fx, fy, cx, cy, k1, k2], dtype=np.float64)
            dist_for_map = np.array([k1, k2, 0.0, 0.0], dtype=np.float64)

        map_x, map_y = get_distortion_remap(params[:4], dist_for_map, h, w)

        return {
            "group_key": f"{video_id}_{fname}",
            "h": h, "w": w,
            "cam_id": str(cam_id),
            "params": params,
            "image_path": str(img_path),
            "frame_idx": frame_idx,
            "video_id": video_id,
            "map_x": map_x,
            "map_y": map_y,
        }

    def write_frame(self, h5_file: h5py.File, result: dict):
        """Write a computed frame result to h5. Called from main thread only."""
        grp = h5_file.create_group(result["group_key"])
        grp.attrs["h"] = result["h"]
        grp.attrs["w"] = result["w"]
        grp.attrs["cam_id"] = result["cam_id"]
        grp.attrs["params"] = result["params"]
        grp.attrs["image_path"] = result["image_path"]
        grp.attrs["frame_idx"] = result["frame_idx"]
        grp.attrs["video_id"] = result["video_id"]
        grp.create_dataset("dist_map_x", data=result["map_x"], dtype=np.float32)
        grp.create_dataset("dist_map_y", data=result["map_y"], dtype=np.float32)

    def generate_split(self, split: str):
        """Generate a single split of a dataset."""
        h5_path = Path(self.conf[f"{split}_h5"])  # type: ignore
        split_dir = Path(self.conf[f"im_{split}"])

        video_folders = sorted(
            [
                path
                for path in split_dir.glob("*")
                if path.is_dir() and not path.name.startswith(".")
            ]
        )
        logger.info(f"Processing {len(video_folders)} videos for {split} split")

        n_videos_processed = 0

        with h5py.File(h5_path, "a") as h5_file:
            with ThreadPoolExecutor(max_workers=self.conf.workers) as executor:
                for video_folder in video_folders:
                    image_paths = sorted(
                        [
                            path
                            for path in video_folder.glob("*")
                            if not path.name.startswith(".") and path.suffix in [".png", ".tiff", ".tif"]
                        ]
                    )
                    logger.info(f"\tProcessing {len(image_paths)} images for {split} split {video_folder.name} video ({n_videos_processed + 1}/{len(video_folders)})...")

                    # filter out already-processed frames before submitting
                    pending = [
                        (frame_idx, img_path)
                        for frame_idx, img_path in enumerate(image_paths)
                        if f"{video_folder.name}_{img_path.name}" not in h5_file
                        or self.conf.overwrite
                    ]

                    if self.conf.overwrite:
                        for _, img_path in pending:
                            key = f"{video_folder.name}_{img_path.name}"
                            if key in h5_file:
                                del h5_file[key]

                    futures = {
                        executor.submit(
                            self.compute_frame,
                            img_path,
                            video_folder / f"{img_path.stem}.json",
                            frame_idx,
                            video_folder.name,
                        ): img_path
                        for frame_idx, img_path in pending
                    }

                    for future in tqdm(as_completed(futures), total=len(futures), desc=video_folder.name):
                        try:
                            result = future.result()
                            self.write_frame(h5_file, result)
                        except Exception as e:
                            logger.warning(f"Failed to process {futures[future]}: {e}")

                    n_videos_processed += 1

    def generate_dataset(self):
        """Generate all splits of a dataset."""
        out_dir = Path(self.conf.im_dir)
        if not out_dir.exists():
            logger.error(f"Image directory does not exist: {out_dir}")
            return
        OmegaConf.save(self.conf, out_dir / "config.yaml")

        for split in ["train", "val", "test"]:
            self.generate_split(split=split)

        for split in ["train", "val", "test"]:
            with h5py.File(self.conf[f"{split}_h5"], "r") as h5_file:  # type:ignore
                total = sum(1 for _ in h5_file)
            logger.info(f"Generated {total} {split} images.")

        self.plot_distributions()


@hydra.main(version_base=None, config_path="configs", config_name="influx_synth_radtan")
def main(cfg: DictConfig) -> None:
    """Run dataset generation."""
    generator = DatasetGenerator(conf=cfg)
    generator.generate_dataset()


if __name__ == "__main__":
    main()
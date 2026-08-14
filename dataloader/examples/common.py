"""Shared helpers for the public InFlux-Synth examples."""

from __future__ import annotations

import random
from pathlib import Path
from typing import Iterable, Sequence

import h5py
import numpy as np
import torch
from hydra import compose, initialize_config_dir
from omegaconf import DictConfig, OmegaConf


SUPPORTED_CAMERA_MODES = {"radial:2", "radtan:4"}


class ExampleError(RuntimeError):
    """Expected example failure with an actionable message."""


def config_dir() -> Path:
    import siclib

    path = Path(siclib.__file__).resolve().parent / "configs"
    if not path.is_dir():
        raise FileNotFoundError(f"Could not find packaged config directory: {path}")
    return path


def compose_example_config(
    config_name: str,
    overrides: Sequence[str] = (),
) -> DictConfig:
    """Compose one public example configuration with Hydra overrides."""
    with initialize_config_dir(version_base=None, config_dir=str(config_dir())):
        return compose(config_name=config_name, overrides=list(overrides))


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def dataset_dir_from_conf(conf: DictConfig) -> Path:
    try:
        dataset_dir = Path(str(conf.dataset_dir)).expanduser().resolve()
    except Exception as exc:  # OmegaConf may raise a missing-value error.
        raise ExampleError(
            "Set data.dataset_dir to the prepared directory containing the H5 "
            "files and train/val/test image trees."
        ) from exc
    if dataset_dir.name != "influx_synth":
        raise ExampleError(
            "The current InFluxSynthDataset requires data.dataset_dir to end in "
            f"'influx_synth'; received: {dataset_dir}"
        )
    return dataset_dir


def split_h5_path(dataset_dir: Path, split: str) -> Path:
    if split not in {"train", "val", "test"}:
        raise ExampleError(f"Unsupported split {split!r}")
    path = dataset_dir / f"{split}.h5"
    if not path.is_file():
        raise FileNotFoundError(f"Missing H5 file: {path}")
    return path


def read_h5_camera_modes(
    h5_path: Path,
    max_groups: int = 64,
) -> tuple[str, ...]:
    """Read and validate camera IDs from the first H5 frame groups."""
    modes: set[str] = set()
    with h5py.File(h5_path, "r") as handle:
        group_names = list(handle.keys())
        if not group_names:
            raise ExampleError(f"H5 file contains no frame groups: {h5_path}")
        for name in group_names[:max_groups]:
            raw_cam_id = handle[name].attrs["cam_id"]
            if isinstance(raw_cam_id, (bytes, np.bytes_)):
                cam_id = raw_cam_id.decode("utf-8")
            else:
                cam_id = str(raw_cam_id)
            modes.add(cam_id)
    unsupported = modes - SUPPORTED_CAMERA_MODES
    if unsupported:
        raise ExampleError(
            "Unsupported camera mode(s) in H5: " + ", ".join(sorted(unsupported))
        )
    return tuple(sorted(modes))


def validate_ray_support(
    camera_modes: Iterable[str],
    produce_rays: bool,
) -> None:
    if produce_rays and "radtan:4" in set(camera_modes):
        raise ExampleError(
            "Ray-grid generation is not implemented for radtan:4. Use "
            "radial:2 H5 files or select a data config with produce_rays=false."
        )


def prepare_data_config(data_conf: DictConfig, *, seed: int) -> DictConfig:
    """Clone and normalize a composed data config before dataset creation."""
    conf = OmegaConf.create(OmegaConf.to_container(data_conf, resolve=True))
    OmegaConf.set_struct(conf, False)
    dataset_dir = dataset_dir_from_conf(conf)
    conf.dataset_dir = str(dataset_dir)
    conf.seed = int(seed)

    if bool(conf.get("reseed", False)):
        raise ExampleError(
            "The released InFlux-Synth example path requires reseed=false. "
            "BatchedRandomSampler supplies tuple indices for geometric sampling."
        )
    conf.reseed = False

    num_workers = int(conf.num_workers)
    if num_workers < 0:
        raise ExampleError("data.num_workers must be nonnegative")
    if num_workers == 0:
        conf.prefetch_factor = None
    elif conf.get("prefetch_factor") is None:
        raise ExampleError(
            "data.prefetch_factor must be set when data.num_workers is positive"
        )

    for split in ("train", "val", "test"):
        key = f"{split}_batch_size"
        if int(conf[key]) <= 0:
            raise ExampleError(f"data.{key} must be positive")
    return conf


def create_loader(
    data_conf: DictConfig,
    split: str,
    *,
    pinned: bool,
):
    """Instantiate the public dataset and preserve its sampler policy."""
    from siclib.datasets.influx_synth_dataset import InFluxSynthDataset

    dataset = InFluxSynthDataset(data_conf)
    return dataset, dataset.get_data_loader(split, pinned=pinned)


def intrinsics_output_dim(camera_modes: Iterable[str]) -> int:
    """Return the raw camera-parameter count for one homogeneous H5 split."""
    modes = tuple(sorted(set(camera_modes)))
    if modes == ("radial:2",):
        return 6
    if modes == ("radtan:4",):
        return 8
    if not modes:
        raise ExampleError("No camera mode was found in the selected H5 split")
    raise ExampleError(
        "The tiny intrinsics example requires one camera mode per H5 split; "
        f"found: {', '.join(modes)}"
    )


def raw_intrinsics_targets(
    intrinsics: torch.Tensor,
    output_dim: int,
    device: torch.device,
) -> torch.Tensor:
    """Select raw pixel-valued camera targets without normalization."""
    if output_dim not in (6, 8):
        raise ExampleError(f"Expected 6 or 8 output parameters, got {output_dim}")
    if intrinsics.ndim != 2 or intrinsics.shape[1] < output_dim:
        raise ExampleError(
            f"Expected intrinsics with shape [B, >={output_dim}], got "
            f"{tuple(intrinsics.shape)}"
        )
    return intrinsics[:, :output_dim].to(device)


def intrinsics_target_description(output_dim: int) -> str:
    if output_dim == 6:
        return "raw intrinsics [fx, fy, cx, cy, k1, k2]"
    if output_dim == 8:
        return "raw intrinsics [fx, fy, cx, cy, k1, k2, p1, p2]"
    raise ExampleError(f"Expected 6 or 8 output parameters, got {output_dim}")


def ray_targets(
    batch: dict,
    image: torch.Tensor,
    device: torch.device,
) -> tuple[torch.Tensor, torch.Tensor]:
    rays = batch.get("rays")
    rays_mask = batch.get("rays_mask")
    if rays is None or rays_mask is None:
        raise ExampleError(
            "The ray model requires batch['rays'] and batch['rays_mask']. "
            "Use radial:2 H5 files with data.produce_rays=true."
        )
    batch_size, _, height, width = image.shape
    expected = height * width
    if rays.ndim != 3 or rays.shape != (batch_size, expected, 3):
        raise ExampleError(
            f"Expected rays with shape {(batch_size, expected, 3)}, got "
            f"{tuple(rays.shape)}"
        )
    if rays_mask.shape != (batch_size, expected):
        raise ExampleError(
            f"Expected rays_mask with shape {(batch_size, expected)}, got "
            f"{tuple(rays_mask.shape)}"
        )
    # Preserve the exact unit bearings returned by the retained AnyCalib
    # camera implementation. Only reshape/permute for the dense CNN loss.
    target = (
        rays.to(device)
        .reshape(batch_size, height, width, 3)
        .permute(0, 3, 1, 2)
    )
    mask = rays_mask.to(device).reshape(batch_size, 1, height, width)
    return target, mask


def masked_cosine_loss(
    prediction: torch.Tensor,
    target: torch.Tensor,
    mask: torch.Tensor,
) -> torch.Tensor:
    if prediction.shape != target.shape:
        raise ExampleError(
            f"Ray prediction/target shape mismatch: {tuple(prediction.shape)} "
            f"versus {tuple(target.shape)}"
        )
    if mask.shape != (prediction.shape[0], 1, prediction.shape[2], prediction.shape[3]):
        raise ExampleError(f"Unexpected ray mask shape: {tuple(mask.shape)}")
    cosine = (prediction * target).sum(dim=1, keepdim=True)
    valid = mask.to(dtype=prediction.dtype)
    return ((1.0 - cosine) * valid).sum() / valid.sum().clamp_min(1.0)

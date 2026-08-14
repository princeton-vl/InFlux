#!/usr/bin/env python3
"""Run one of two small, model-agnostic InFlux-Synth training examples.

The public examples demonstrate how to consume the released data loader. They
are not the AnyCalib architecture, loss, optimizer, schedule, or fine-tuning
recipe used in the InFlux++ experiments.

Examples from the ``dataloader/`` directory::

    python examples/train.py \
      --config-name example_train_intrinsics \
      data.dataset_dir=/absolute/path/to/influx_synth

    python examples/train.py \
      --config-name example_train_rays \
      data.dataset_dir=/absolute/path/to/influx_synth

Additional arguments are Hydra overrides.
"""

from __future__ import annotations

import argparse
import json
import math
from typing import Sequence

import torch
from omegaconf import DictConfig, OmegaConf
from torch import nn
from torch.nn import functional as F

try:
    from .common import (
        ExampleError,
        compose_example_config,
        create_loader,
        dataset_dir_from_conf,
        intrinsics_output_dim,
        intrinsics_target_description,
        masked_cosine_loss,
        prepare_data_config,
        raw_intrinsics_targets,
        ray_targets,
        read_h5_camera_modes,
        seed_everything,
        split_h5_path,
        validate_ray_support,
    )
except ImportError:  # Direct execution: python examples/train.py
    from common import (  # type: ignore
        ExampleError,
        compose_example_config,
        create_loader,
        dataset_dir_from_conf,
        intrinsics_output_dim,
        intrinsics_target_description,
        masked_cosine_loss,
        prepare_data_config,
        raw_intrinsics_targets,
        ray_targets,
        read_h5_camera_modes,
        seed_everything,
        split_h5_path,
        validate_ray_support,
    )


class TinyIntrinsicsRegressor(nn.Module):
    """Naive RGB-to-camera-parameters regressor used only as a loader example."""

    def __init__(
        self,
        hidden_channels: int,
        output_dim: int,
        focal_prior_multiplier: float = 1.5,
    ) -> None:
        super().__init__()
        if hidden_channels <= 0:
            raise ValueError("hidden_channels must be positive")
        if output_dim not in (6, 8):
            raise ValueError("output_dim must be 6 for radial:2 or 8 for radtan:4")
        if (
            not math.isfinite(focal_prior_multiplier)
            or focal_prior_multiplier <= 0
        ):
            raise ValueError(
                "focal_prior_multiplier must be finite and positive"
            )
        self.output_dim = output_dim
        self.focal_prior_multiplier = float(focal_prior_multiplier)
        self.encoder = nn.Sequential(
            nn.Conv2d(3, hidden_channels, kernel_size=5, stride=4, padding=2),
            nn.ReLU(inplace=True),
            nn.Conv2d(
                hidden_channels,
                hidden_channels * 2,
                kernel_size=3,
                stride=2,
                padding=1,
            ),
            nn.ReLU(inplace=True),
            nn.AdaptiveAvgPool2d(1),
            nn.Flatten(),
        )
        self.head = nn.Linear(hidden_channels * 2, output_dim)
        nn.init.zeros_(self.head.weight)
        nn.init.zeros_(self.head.bias)

    def camera_prior(self, image: torch.Tensor) -> torch.Tensor:
        """Return a raw camera prior matching the current input image shape."""

        batch_size, _, height, width = image.shape
        focal = image.new_full(
            (batch_size, 1),
            self.focal_prior_multiplier * max(height, width),
        )
        center_x = image.new_full((batch_size, 1), width / 2.0)
        center_y = image.new_full((batch_size, 1), height / 2.0)
        distortion = image.new_zeros((batch_size, self.output_dim - 4))
        return torch.cat(
            (focal, focal, center_x, center_y, distortion),
            dim=1,
        )

    def forward(self, image: torch.Tensor) -> torch.Tensor:
        residual = self.head(self.encoder(image))
        return self.camera_prior(image) + residual


class TinyRayPredictor(nn.Module):
    """Small RGB-plus-pixel-coordinate ray predictor for radial data."""

    def __init__(self, hidden_channels: int = 8) -> None:
        super().__init__()
        if hidden_channels <= 0:
            raise ValueError("hidden_channels must be positive")
        self.features = nn.Sequential(
            nn.Conv2d(5, hidden_channels, kernel_size=3, padding=1),
            nn.ReLU(inplace=True),
            nn.Conv2d(hidden_channels, hidden_channels, kernel_size=3, padding=1),
            nn.ReLU(inplace=True),
        )
        self.head = nn.Conv2d(hidden_channels, 3, kernel_size=1)
        nn.init.zeros_(self.head.weight)
        with torch.no_grad():
            self.head.bias.copy_(torch.tensor([0.0, 0.0, 1.0]))

    def forward(self, image: torch.Tensor) -> torch.Tensor:
        batch_size, _, height, width = image.shape
        y = torch.linspace(-1.0, 1.0, height, device=image.device, dtype=image.dtype)
        x = torch.linspace(-1.0, 1.0, width, device=image.device, dtype=image.dtype)
        yy, xx = torch.meshgrid(y, x, indexing="ij")
        coords = torch.stack((xx, yy), dim=0).expand(batch_size, -1, -1, -1)
        features = torch.cat((image, coords), dim=1)
        return F.normalize(self.head(self.features(features)), dim=1, eps=1e-6)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a public InFlux-Synth toy training configuration."
    )
    parser.add_argument(
        "--config-name",
        default="example_train_intrinsics",
        choices=("example_train_intrinsics", "example_train_rays"),
    )
    parser.add_argument(
        "--print-config",
        action="store_true",
        help="Print the resolved configuration before training.",
    )
    parser.add_argument(
        "overrides",
        nargs="*",
        help="Hydra overrides, for example data.dataset_dir=/path/to/influx_synth",
    )
    return parser.parse_args(argv)


def build_model(
    model_conf: DictConfig,
    camera_modes: tuple[str, ...],
) -> nn.Module:
    hidden_channels = int(model_conf.hidden_channels)
    if model_conf.name == "tiny_intrinsics":
        output_dim = intrinsics_output_dim(camera_modes)
        focal_prior_multiplier = float(model_conf.focal_prior_multiplier)
        return TinyIntrinsicsRegressor(
            hidden_channels,
            output_dim,
            focal_prior_multiplier,
        )
    if model_conf.name == "tiny_rays":
        return TinyRayPredictor(hidden_channels)
    raise ExampleError(f"Unsupported toy model: {model_conf.name!r}")


def validate_model_and_data(
    model_name: str,
    camera_modes: tuple[str, ...],
    produce_rays: bool,
) -> None:
    validate_ray_support(camera_modes, produce_rays)
    if model_name == "tiny_rays":
        if set(camera_modes) != {"radial:2"}:
            raise ExampleError(
                "tiny_rays supports radial:2 H5 files only; found "
                + ", ".join(camera_modes)
            )
        if not produce_rays:
            raise ExampleError(
                "tiny_rays requires a data config with produce_rays=true"
            )
    elif model_name == "tiny_intrinsics":
        intrinsics_output_dim(camera_modes)
    else:
        raise ExampleError(f"Unsupported toy model: {model_name!r}")


def train_from_config(
    conf: DictConfig,
    *,
    config_name: str = "",
) -> dict[str, object]:
    split = str(conf.train.split)
    steps = int(conf.train.steps)
    learning_rate = float(conf.train.learning_rate)
    weight_decay = float(conf.train.weight_decay)
    log_every = int(conf.train.log_every)
    seed = int(conf.train.seed)
    if steps <= 0:
        raise ExampleError("train.steps must be positive")
    if learning_rate <= 0:
        raise ExampleError("train.learning_rate must be positive")
    if weight_decay < 0:
        raise ExampleError("train.weight_decay cannot be negative")
    if log_every <= 0:
        raise ExampleError("train.log_every must be positive")

    seed_everything(seed)
    data_conf = prepare_data_config(conf.data, seed=seed)
    dataset_dir = dataset_dir_from_conf(data_conf)
    camera_modes = read_h5_camera_modes(split_h5_path(dataset_dir, split))
    model_name = str(conf.model.name)
    validate_model_and_data(model_name, camera_modes, bool(data_conf.produce_rays))
    intrinsics_dim = (
        intrinsics_output_dim(camera_modes)
        if model_name == "tiny_intrinsics"
        else None
    )

    device = torch.device(str(conf.train.device))
    _, loader = create_loader(data_conf, split, pinned=device.type == "cuda")
    model = build_model(conf.model, camera_modes).to(device)
    optimizer = torch.optim.Adam(
        model.parameters(),
        lr=learning_rate,
        weight_decay=weight_decay,
    )

    losses: list[float] = []
    completed_steps = 0
    image_shape: list[int] | None = None
    prediction_shape: list[int] | None = None
    rays_shape: list[int] | None = None

    while completed_steps < steps:
        batches_this_pass = 0
        for batch in loader:
            batches_this_pass += 1
            image = batch["image"].to(device, non_blocking=True)
            prediction = model(image)

            if model_name == "tiny_intrinsics":
                assert intrinsics_dim is not None
                target = raw_intrinsics_targets(
                    batch["intrinsics"], intrinsics_dim, device
                )
                if prediction.shape != target.shape:
                    raise ExampleError(
                        "Intrinsics prediction/target shape mismatch: "
                        f"{tuple(prediction.shape)} versus {tuple(target.shape)}"
                    )
                loss = F.mse_loss(prediction, target)
                target_description = intrinsics_target_description(intrinsics_dim)
            else:
                target, mask = ray_targets(batch, image, device)
                loss = masked_cosine_loss(prediction, target, mask)
                target_description = "per-pixel unit ray directions"

            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            optimizer.step()

            completed_steps += 1
            loss_value = float(loss.detach().cpu())
            losses.append(loss_value)
            image_shape = list(image.shape)
            prediction_shape = list(prediction.shape)
            rays = batch.get("rays")
            rays_shape = list(rays.shape) if rays is not None else None
            if completed_steps == 1 or completed_steps % log_every == 0 or completed_steps == steps:
                print(
                    f"step={completed_steps} loss={loss_value:.8f} "
                    f"model={model_name} camera_modes={','.join(camera_modes)} "
                    f"image_shape={image_shape} prediction_shape={prediction_shape}"
                )
            if completed_steps >= steps:
                break
        if batches_this_pass == 0:
            raise ExampleError(f"No batches were produced for split {split!r}")

    return {
        "status": "ok",
        "config_name": config_name,
        "dataset_dir": str(dataset_dir),
        "split": split,
        "steps": completed_steps,
        "model": model_name,
        "camera_modes": list(camera_modes),
        "produce_rays": bool(data_conf.produce_rays),
        "initial_loss": losses[0],
        "final_loss": losses[-1],
        "best_loss": min(losses),
        "losses": losses,
        "image_shape": image_shape,
        "prediction_shape": prediction_shape,
        "intrinsics_output_dim": intrinsics_dim,
        "rays_shape": rays_shape,
        "target": target_description,
        "note": "Toy loader example; not the AnyCalib training recipe.",
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        conf = compose_example_config(args.config_name, args.overrides)
        if args.print_config:
            print(OmegaConf.to_yaml(conf, resolve=True))
        result = train_from_config(conf, config_name=args.config_name)
    except (ExampleError, FileNotFoundError, RuntimeError, ValueError) as exc:
        raise SystemExit(f"error: {exc}") from exc
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Prepare extracted InFlux-Synth data for H5 generation.

The released Hugging Face layout stores each scene as paired ``Image/*.png``
and ``camview/*.npz`` directories. ``create_dataset_from_images.py`` expects a
split-aware tree with paired image/JSON files:

    <output_dir>/<split>/<video>/<frame>.png
    <output_dir>/<split>/<video>/<frame>.json

This utility scans every present InFlux-Synth partition, validates scene-level
RGB/camview pairing, assigns complete scenes to train/validation/test splits,
and creates that intermediate tree without modifying the extracted source data.

InFlux-Synth does not define an official train/validation/test split. By default,
this utility creates a deterministic 80/10/10 scene-level split. Users may
customize the ratios and seed or supply an explicit split manifest instead.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import shutil
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from PIL import Image


EXPECTED_PARTITIONS = ("indoors", "indoors_full", "nature", "nature_full")
SPLITS = ("train", "val", "test")
IMAGE_SUFFIXES = {".png"}
CAMVIEW_SUFFIXES = {".npz"}
MARKER_NAME = ".influx_synth_prepared.json"
DEFAULT_SPLIT_RATIOS = {"train": 0.8, "val": 0.1, "test": 0.1}
SPLIT_MANIFEST_NAME = "split_manifest.json"
SPLIT_ALGORITHM = "sha256_order_largest_remainder_v1"


class PreparationError(RuntimeError):
    """Expected preparation failure with an actionable message."""


@dataclass(frozen=True)
class PairRecord:
    key: str
    image: str
    camview: str


@dataclass
class SceneRecord:
    partition: str
    scene: str
    scene_path: str
    image_count: int = 0
    camview_count: int = 0
    paired_count: int = 0
    complete: bool = False
    errors: list[str] = field(default_factory=list)
    pairs: list[PairRecord] = field(default_factory=list)

    @property
    def scene_id(self) -> str:
        return f"{self.partition}/{self.scene}"


def natural_key(value: str) -> list[Any]:
    """Return a key that sorts embedded integer substrings numerically."""
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", value)]


def canonical_frame_key(path: Path, modality: str) -> str:
    """Normalize common Image/camview prefixes before pairing filenames."""
    stem = path.stem
    prefix = "image" if modality == "image" else "camview"
    if stem.lower().startswith(prefix):
        stem = stem[len(prefix) :]
    return stem.lstrip("_.-")


def build_unique_map(paths: Iterable[Path], modality: str) -> tuple[dict[str, Path], list[str]]:
    result: dict[str, Path] = {}
    errors: list[str] = []
    for path in paths:
        key = canonical_frame_key(path, modality)
        if not key:
            errors.append(f"Could not derive a frame key from {path.name}")
            continue
        if key in result:
            errors.append(
                f"Duplicate normalized {modality} key {key!r}: "
                f"{result[key].name!r} and {path.name!r}"
            )
            continue
        result[key] = path
    return result, errors


def scan_scene(
    partition: str,
    scene_dir: Path,
    expected_frames: int,
    *,
    keep_pairs: bool = False,
) -> SceneRecord:
    """Validate one extracted scene and optionally retain its RGB/camview pairs."""
    record = SceneRecord(
        partition=partition,
        scene=scene_dir.name,
        scene_path=str(scene_dir.resolve()),
    )
    image_dir = scene_dir / "Image"
    camview_dir = scene_dir / "camview"

    if not image_dir.is_dir():
        record.errors.append(f"Missing directory: {image_dir}")
    if not camview_dir.is_dir():
        record.errors.append(f"Missing directory: {camview_dir}")
    if record.errors:
        return record

    image_paths = sorted(
        (
            path
            for path in image_dir.iterdir()
            if path.is_file()
            and not path.name.startswith(".")
            and path.suffix.lower() in IMAGE_SUFFIXES
        ),
        key=lambda path: natural_key(path.name),
    )
    camview_paths = sorted(
        (
            path
            for path in camview_dir.iterdir()
            if path.is_file()
            and not path.name.startswith(".")
            and path.suffix.lower() in CAMVIEW_SUFFIXES
        ),
        key=lambda path: natural_key(path.name),
    )
    record.image_count = len(image_paths)
    record.camview_count = len(camview_paths)

    if record.image_count != expected_frames:
        record.errors.append(
            f"Expected {expected_frames} RGB PNGs, found {record.image_count} in {image_dir}"
        )
    if record.camview_count != expected_frames:
        record.errors.append(
            f"Expected {expected_frames} camview NPZs, found {record.camview_count} in {camview_dir}"
        )

    image_map, image_errors = build_unique_map(image_paths, "image")
    camview_map, camview_errors = build_unique_map(camview_paths, "camview")
    record.errors.extend(image_errors)
    record.errors.extend(camview_errors)

    image_only = sorted(set(image_map) - set(camview_map), key=natural_key)
    camview_only = sorted(set(camview_map) - set(image_map), key=natural_key)
    if image_only:
        preview = ", ".join(image_only[:8])
        record.errors.append(
            f"{len(image_only)} RGB frame keys have no camview match; first keys: {preview}"
        )
    if camview_only:
        preview = ", ".join(camview_only[:8])
        record.errors.append(
            f"{len(camview_only)} camview frame keys have no RGB match; first keys: {preview}"
        )

    paired_keys = sorted(set(image_map) & set(camview_map), key=natural_key)
    record.paired_count = len(paired_keys)
    if record.paired_count != expected_frames:
        record.errors.append(
            f"Expected {expected_frames} one-to-one RGB/camview pairs, found {record.paired_count}"
        )

    if keep_pairs:
        record.pairs = [
            PairRecord(key=key, image=str(image_map[key]), camview=str(camview_map[key]))
            for key in paired_keys
        ]

    record.complete = not record.errors
    return record


def scan_source(
    source_dir: Path,
    expected_frames: int,
) -> tuple[list[str], list[SceneRecord], list[str]]:
    """Scan all present known partitions; absent partitions are allowed."""
    if not source_dir.is_dir():
        raise PreparationError(f"Extracted source directory does not exist: {source_dir}")

    present_partitions = [name for name in EXPECTED_PARTITIONS if (source_dir / name).is_dir()]
    if not present_partitions:
        raise PreparationError(
            f"None of the expected partitions are present under {source_dir}: "
            + ", ".join(EXPECTED_PARTITIONS)
        )

    warnings: list[str] = []
    unknown_dirs = sorted(
        path.name
        for path in source_dir.iterdir()
        if path.is_dir() and path.name not in EXPECTED_PARTITIONS
    )
    if unknown_dirs:
        warnings.append("Ignoring unrecognized top-level directories: " + ", ".join(unknown_dirs))

    records: list[SceneRecord] = []
    for partition in present_partitions:
        partition_dir = source_dir / partition
        scene_dirs = sorted(
            (
                path
                for path in partition_dir.iterdir()
                if path.is_dir() and not path.name.startswith(".")
            ),
            key=lambda path: natural_key(path.name),
        )
        print(f"[scan] {partition}: {len(scene_dirs)} scene directories", flush=True)
        if not scene_dirs:
            records.append(
                SceneRecord(
                    partition=partition,
                    scene="<none>",
                    scene_path=str(partition_dir.resolve()),
                    errors=[f"No scene directories found in {partition_dir}"],
                )
            )
            continue
        for index, scene_dir in enumerate(scene_dirs, start=1):
            records.append(scan_scene(partition, scene_dir, expected_frames))
            if index % 100 == 0 or index == len(scene_dirs):
                print(f"[scan] {partition}: inspected {index}/{len(scene_dirs)}", flush=True)

    return present_partitions, records, warnings


def write_scan_reports(
    report_dir: Path,
    source_dir: Path,
    present_partitions: list[str],
    records: list[SceneRecord],
    warnings: list[str],
    expected_frames: int,
) -> tuple[Path, Path]:
    """Write machine-readable scene inventory reports."""
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / "scene_inventory.json"
    tsv_path = report_dir / "scene_inventory.tsv"

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_dir": str(source_dir.resolve()),
        "present_partitions": present_partitions,
        "expected_frames_per_scene": expected_frames,
        "warnings": warnings,
        "scenes": [
            {
                **asdict(record),
                "scene_id": record.scene_id,
                "pairs": [],
            }
            for record in records
        ],
    }
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    with tsv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(
            [
                "scene_id",
                "partition",
                "scene",
                "scene_path",
                "image_count",
                "camview_count",
                "paired_count",
                "complete",
                "errors",
            ]
        )
        for record in records:
            writer.writerow(
                [
                    record.scene_id,
                    record.partition,
                    record.scene,
                    record.scene_path,
                    record.image_count,
                    record.camview_count,
                    record.paired_count,
                    str(record.complete).lower(),
                    " | ".join(record.errors),
                ]
            )

    return json_path, tsv_path


def validate_split_ratios(
    train_ratio: float,
    val_ratio: float,
    test_ratio: float,
) -> dict[str, float]:
    """Validate user-supplied split ratios and preserve train/val/test order."""
    ratios = {
        "train": float(train_ratio),
        "val": float(val_ratio),
        "test": float(test_ratio),
    }
    for split, ratio in ratios.items():
        if not math.isfinite(ratio):
            raise PreparationError(f"--{split}-ratio must be finite, found {ratio}")
        if ratio < 0:
            raise PreparationError(f"--{split}-ratio must be nonnegative, found {ratio}")

    total = sum(ratios.values())
    if not math.isclose(total, 1.0, rel_tol=0.0, abs_tol=1e-9):
        raise PreparationError(
            "Train/validation/test ratios must sum to 1.0; "
            f"received {train_ratio} + {val_ratio} + {test_ratio} = {total}"
        )
    return ratios


def allocate_split_counts(
    scene_count: int,
    ratios: dict[str, float],
) -> dict[str, int]:
    """Convert ratios into exact scene counts using largest remainders."""
    if scene_count < 0:
        raise PreparationError(f"scene_count must be nonnegative, found {scene_count}")

    raw_counts = {split: scene_count * ratios[split] for split in SPLITS}
    counts = {split: int(math.floor(raw_counts[split])) for split in SPLITS}
    remainder = scene_count - sum(counts.values())

    split_priority = {split: index for index, split in enumerate(SPLITS)}
    ranked = sorted(
        SPLITS,
        key=lambda split: (
            -(raw_counts[split] - counts[split]),
            split_priority[split],
        ),
    )
    for split in ranked[:remainder]:
        counts[split] += 1

    if sum(counts.values()) != scene_count:
        raise PreparationError(
            f"Internal split allocation error: {counts} does not sum to {scene_count}"
        )
    return counts


def deterministic_scene_order(scene_ids: Iterable[str], seed: int) -> list[str]:
    """Return a cross-platform deterministic pseudo-random scene ordering."""

    def key(scene_id: str) -> tuple[bytes, str]:
        payload = f"influx-synth-split-v1\0{seed}\0{scene_id}".encode("utf-8")
        return hashlib.sha256(payload).digest(), scene_id

    return sorted(scene_ids, key=key)


def generate_ratio_split(
    records: list[SceneRecord],
    *,
    ratios: dict[str, float],
    seed: int,
) -> tuple[dict[str, list[str]], dict[str, int]]:
    """Assign every complete scene exactly once using deterministic ratios."""
    scene_ids = [record.scene_id for record in records if record.complete]
    if not scene_ids:
        raise PreparationError("No complete scenes are available for automatic splitting")

    ordered = deterministic_scene_order(scene_ids, seed)
    counts = allocate_split_counts(len(ordered), ratios)
    assignments: dict[str, list[str]] = {split: [] for split in SPLITS}

    offset = 0
    for split in SPLITS:
        next_offset = offset + counts[split]
        assignments[split] = sorted(ordered[offset:next_offset], key=natural_key)
        offset = next_offset

    if offset != len(ordered):
        raise PreparationError(
            f"Internal split assignment error: assigned {offset} of {len(ordered)} scenes"
        )
    return assignments, counts


def write_split_manifest(path: Path, assignments: dict[str, list[str]]) -> Path:
    """Atomically write a normalized split manifest for reproducibility."""
    normalized = {split: list(assignments[split]) for split in SPLITS}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(json.dumps(normalized, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return path


def validate_existing_split_locations(
    assignments: dict[str, list[str]],
    output_dir: Path,
) -> None:
    """Reject stale prepared scenes that already exist under a different split."""
    for expected_split in SPLITS:
        for scene_id in assignments[expected_split]:
            partition, scene = scene_id.split("/", 1)
            video_name = f"{partition}__{scene}"
            for other_split in SPLITS:
                if other_split == expected_split:
                    continue
                conflicting = output_dir / other_split / video_name
                if conflicting.exists():
                    raise PreparationError(
                        f"Scene {scene_id!r} is assigned to {expected_split!r}, but a "
                        f"prepared directory already exists under {other_split!r}: "
                        f"{conflicting}. Use a fresh output directory or remove the stale "
                        "prepared scene before changing split assignments."
                    )


def load_split_manifest(path: Path) -> dict[str, list[str]]:
    """Load ``{"train": [...], "val": [...], "test": [...]}`` assignments."""
    if not path.is_file():
        raise PreparationError(f"Split manifest does not exist: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PreparationError(f"Invalid JSON in split manifest {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise PreparationError("Split manifest must be a JSON object")

    unknown = sorted(set(raw) - set(SPLITS))
    if unknown:
        raise PreparationError(
            "Split manifest contains unsupported keys: " + ", ".join(unknown)
        )

    assignments: dict[str, list[str]] = {}
    seen: dict[str, str] = {}
    for split in SPLITS:
        values = raw.get(split, [])
        if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
            raise PreparationError(f"Manifest field {split!r} must be a list of scene IDs")
        normalized: list[str] = []
        for value in values:
            scene_id = value.strip().strip("/")
            if scene_id.count("/") != 1:
                raise PreparationError(
                    f"Scene ID {value!r} must have the form '<partition>/<scene>'"
                )
            if scene_id in seen:
                raise PreparationError(
                    f"Scene {scene_id!r} is assigned to both {seen[scene_id]!r} and {split!r}"
                )
            seen[scene_id] = split
            normalized.append(scene_id)
        assignments[split] = normalized
    return assignments


def validate_split_manifest(
    assignments: dict[str, list[str]],
    records: list[SceneRecord],
) -> tuple[dict[str, SceneRecord], list[str]]:
    complete = {record.scene_id: record for record in records if record.complete}
    requested = [scene_id for split in SPLITS for scene_id in assignments[split]]
    unknown = sorted(set(requested) - set(complete), key=natural_key)
    if unknown:
        raise PreparationError(
            "Split manifest references missing or incomplete scenes: " + ", ".join(unknown)
        )
    unassigned = sorted(set(complete) - set(requested), key=natural_key)
    return complete, unassigned


def scalar_float(value: Any, name: str, path: Path) -> float:
    array = np.asarray(value)
    if array.size != 1:
        raise PreparationError(f"Expected scalar {name} in {path}, found shape {array.shape}")
    result = float(array.reshape(-1)[0])
    if not math.isfinite(result):
        raise PreparationError(f"Non-finite {name} in {path}: {result}")
    return result


def scene_environment(partition: str) -> str:
    if partition.startswith("indoors"):
        return "indoors"
    if partition.startswith("nature"):
        return "nature"
    return partition


def read_pair_metadata(
    pair: PairRecord,
    *,
    partition: str,
    scene: str,
) -> dict[str, Any]:
    """Validate one real pair and build the JSON consumed by the H5 generator."""
    source_image = Path(pair.image)
    source_camview = Path(pair.camview)

    with Image.open(source_image) as image:
        width, height = image.size
        image_mode = image.mode

    with np.load(source_camview, allow_pickle=False) as data:
        required = {"K", "HW", "focus_distance", "LFL"}
        missing = sorted(required - set(data.files))
        if missing:
            raise PreparationError(
                f"Missing required camview keys in {source_camview}: {', '.join(missing)}"
            )

        K = np.asarray(data["K"], dtype=np.float64)
        if K.shape != (3, 3):
            raise PreparationError(f"Expected K shape (3, 3) in {source_camview}, found {K.shape}")
        if not np.isfinite(K).all():
            raise PreparationError(f"Non-finite K in {source_camview}")
        if float(K[0, 0]) <= 0 or float(K[1, 1]) <= 0:
            raise PreparationError(f"Expected positive fx/fy in {source_camview}")

        hw_array = np.asarray(data["HW"]).reshape(-1)
        if hw_array.size != 2:
            raise PreparationError(f"Expected HW with two entries in {source_camview}")
        hw = [int(hw_array[0]), int(hw_array[1])]
        if hw != [height, width]:
            raise PreparationError(
                f"HW/image-size mismatch for {source_image}: camview={hw}, image={[height, width]}"
            )

        focus_distance = scalar_float(data["focus_distance"], "focus_distance", source_camview)
        lfl_mm = scalar_float(data["LFL"], "LFL", source_camview)
        if focus_distance <= 0:
            raise PreparationError(f"focus_distance must be positive in {source_camview}")
        if lfl_mm <= 0:
            raise PreparationError(f"LFL must be positive in {source_camview}")

        focal_length_mm: float | None = None
        if "focal_length" in data.files:
            focal_length_mm = scalar_float(data["focal_length"], "focal_length", source_camview)
            if not np.isclose(focal_length_mm, lfl_mm, rtol=0, atol=1e-6):
                raise PreparationError(
                    f"focal_length and LFL differ in {source_camview}: "
                    f"{focal_length_mm} vs {lfl_mm}"
                )

    return {
        "intrinsics_gt": {
            "fx": float(K[0, 0]),
            "fy": float(K[1, 1]),
            "cx": float(K[0, 2]),
            "cy": float(K[1, 2]),
            "k1": 0.0,
            "k2": 0.0,
            "p1": 0.0,
            "p2": 0.0,
        },
        "lens_metadata": {
            # Historical key expected by create_dataset_from_images.py. In the
            # InFlux-Synth release, focus_distance represents lens to object.
            "fd_m": focus_distance,
            "lfl_mm": lfl_mm,
        },
        "scene_metadata": {
            "env": scene_environment(partition),
        },
        "source_metadata": {
            "partition": partition,
            "scene": scene,
            "frame_key": pair.key,
            "source_image": str(source_image.resolve()),
            "source_camview": str(source_camview.resolve()),
            "image_mode": image_mode,
            "image_hw": [height, width],
            "focal_length_mm": focal_length_mm,
            "focus_distance_semantics": "lens_to_object_m",
        },
    }


def materialize_image(source: Path, destination: Path, mode: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if mode == "copy":
        shutil.copy2(source, destination)
        return
    if mode == "symlink":
        destination.symlink_to(source.resolve())
        return
    if mode == "hardlink":
        try:
            os.link(source, destination)
        except OSError as exc:
            raise PreparationError(
                f"Could not hard-link {source} to {destination}: {exc}. "
                "Use --mode symlink or --mode copy when source and output are on different filesystems."
            ) from exc
        return
    raise PreparationError(f"Unsupported materialization mode: {mode}")


def verify_completed_scene(
    destination: Path,
    *,
    source_scene_id: str,
    split: str,
    expected_frames: int,
) -> bool:
    marker = destination / MARKER_NAME
    if not marker.is_file():
        return False
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if payload.get("source_scene_id") != source_scene_id or payload.get("split") != split:
        return False
    png_count = len(list(destination.glob("*.png")))
    json_count = len([path for path in destination.glob("*.json") if not path.name.startswith(".")])
    return png_count == expected_frames and json_count == expected_frames


def prepare_scene(
    record: SceneRecord,
    *,
    split: str,
    output_dir: Path,
    expected_frames: int,
    mode: str,
    overwrite_existing: bool,
) -> dict[str, Any]:
    """Prepare one complete scene atomically and return its summary."""
    rescanned = scan_scene(
        record.partition,
        Path(record.scene_path),
        expected_frames,
        keep_pairs=True,
    )
    if not rescanned.complete:
        raise PreparationError(
            f"Scene became incomplete while preparing {record.scene_id}: "
            + " | ".join(rescanned.errors)
        )

    video_name = f"{record.partition}__{record.scene}"
    split_dir = output_dir / split
    destination = split_dir / video_name
    split_dir.mkdir(parents=True, exist_ok=True)

    if destination.exists():
        if verify_completed_scene(
            destination,
            source_scene_id=record.scene_id,
            split=split,
            expected_frames=expected_frames,
        ) and not overwrite_existing:
            return {
                "scene_id": record.scene_id,
                "split": split,
                "destination": str(destination.resolve()),
                "status": "skipped_complete",
                "frames": expected_frames,
                "mode": mode,
            }
        if not overwrite_existing:
            raise PreparationError(
                f"Destination already exists but is not a verified completed scene: {destination}. "
                "Use --overwrite-existing-scenes to replace it."
            )
        shutil.rmtree(destination)

    temp_destination = split_dir / f".{video_name}.tmp-{os.getpid()}"
    if temp_destination.exists():
        shutil.rmtree(temp_destination)
    temp_destination.mkdir(parents=True)

    frame_records: list[dict[str, Any]] = []
    try:
        for frame_index, pair in enumerate(rescanned.pairs):
            frame_name = f"{frame_index:07d}"
            destination_image = temp_destination / f"{frame_name}.png"
            destination_json = temp_destination / f"{frame_name}.json"

            materialize_image(Path(pair.image), destination_image, mode)
            metadata = read_pair_metadata(
                pair,
                partition=record.partition,
                scene=record.scene,
            )
            destination_json.write_text(
                json.dumps(metadata, indent=2) + "\n",
                encoding="utf-8",
            )
            frame_records.append(
                {
                    "frame_index": frame_index,
                    "frame_key": pair.key,
                    "source_image": str(Path(pair.image).resolve()),
                    "source_camview": str(Path(pair.camview).resolve()),
                    "prepared_image": f"{frame_name}.png",
                    "prepared_json": f"{frame_name}.json",
                }
            )

        marker_payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source_scene_id": record.scene_id,
            "source_scene_path": record.scene_path,
            "split": split,
            "video_name": video_name,
            "mode": mode,
            "frames": len(frame_records),
            "frame_mapping": frame_records,
        }
        (temp_destination / MARKER_NAME).write_text(
            json.dumps(marker_payload, indent=2) + "\n",
            encoding="utf-8",
        )
        temp_destination.rename(destination)
    except Exception:
        shutil.rmtree(temp_destination, ignore_errors=True)
        raise

    return {
        "scene_id": record.scene_id,
        "split": split,
        "destination": str(destination.resolve()),
        "status": "prepared",
        "frames": len(frame_records),
        "mode": mode,
    }


def ensure_safe_roots(source_dir: Path, output_dir: Path) -> None:
    source = source_dir.resolve()
    output = output_dir.resolve()
    if source == output:
        raise PreparationError("Source and output directories must differ")
    if source in output.parents:
        raise PreparationError("Output directory must not be nested inside the extracted source directory")
    if output in source.parents:
        raise PreparationError("Extracted source directory must not be nested inside the output directory")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare extracted InFlux-Synth Image/camview data for H5 generation."
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        required=True,
        help="Extracted InFlux-Synth root containing any subset of the four partitions.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Destination root for train/val/test image+JSON directories and reports.",
    )
    parser.add_argument(
        "--split-manifest",
        type=Path,
        help=(
            "Optional JSON file with train/val/test scene-ID lists. Scene IDs have "
            "the form 'partition/scene'. When omitted, all complete scenes are split "
            "deterministically using --train-ratio, --val-ratio, --test-ratio, and "
            "--split-seed."
        ),
    )
    parser.add_argument(
        "--train-ratio",
        type=float,
        default=DEFAULT_SPLIT_RATIOS["train"],
        help="Automatic scene-level training ratio (default: 0.8).",
    )
    parser.add_argument(
        "--val-ratio",
        type=float,
        default=DEFAULT_SPLIT_RATIOS["val"],
        help="Automatic scene-level validation ratio (default: 0.1).",
    )
    parser.add_argument(
        "--test-ratio",
        type=float,
        default=DEFAULT_SPLIT_RATIOS["test"],
        help="Automatic scene-level test ratio (default: 0.1).",
    )
    parser.add_argument(
        "--split-seed",
        type=int,
        default=42,
        help=(
            "Seed used to deterministically order scenes for automatic splitting "
            "(default: 42)."
        ),
    )
    parser.add_argument(
        "--scan-only",
        action="store_true",
        help="Validate extracted scenes and write inventory reports without preparing files.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate the source and split manifest and print the plan without preparing files.",
    )
    parser.add_argument(
        "--expected-frames",
        type=int,
        default=240,
        help="Expected RGB/camview pairs per scene (default: 240).",
    )
    parser.add_argument(
        "--mode",
        choices=("hardlink", "symlink", "copy"),
        default="hardlink",
        help="How to materialize RGB files in the prepared tree (default: hardlink).",
    )
    parser.add_argument(
        "--overwrite-existing-scenes",
        action="store_true",
        help="Replace selected output scene directories instead of resuming/skipping verified scenes.",
    )
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    source_dir = args.source_dir.resolve()
    output_dir = args.output_dir.resolve()
    if args.expected_frames <= 0:
        raise PreparationError("--expected-frames must be positive")
    ensure_safe_roots(source_dir, output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    present_partitions, records, warnings = scan_source(source_dir, args.expected_frames)
    inventory_json, inventory_tsv = write_scan_reports(
        output_dir,
        source_dir,
        present_partitions,
        records,
        warnings,
        args.expected_frames,
    )
    print(f"[report] inventory JSON: {inventory_json}")
    print(f"[report] inventory TSV:  {inventory_tsv}")
    for warning in warnings:
        print(f"[warning] {warning}", file=sys.stderr)

    incomplete = [record for record in records if not record.complete]
    if incomplete:
        preview = "; ".join(
            f"{record.scene_id}: {' | '.join(record.errors)}" for record in incomplete[:5]
        )
        raise PreparationError(
            f"Found {len(incomplete)} incomplete scene(s). See the inventory reports. "
            f"First errors: {preview}"
        )

    if args.scan_only:
        print(
            f"[scan] PASS: {len(records)} complete scene(s) across "
            f"{', '.join(present_partitions)}"
        )
        return 0

    manifest_source: str | None
    split_method: str
    split_ratios: dict[str, float] | None
    split_seed: int | None
    split_counts: dict[str, int]

    if args.split_manifest is not None:
        source_manifest = args.split_manifest.resolve()
        assignments = load_split_manifest(source_manifest)
        manifest_source = str(source_manifest)
        split_method = "manifest"
        split_ratios = None
        split_seed = None
        split_counts = {split: len(assignments[split]) for split in SPLITS}
    else:
        split_ratios = validate_split_ratios(
            getattr(args, "train_ratio", DEFAULT_SPLIT_RATIOS["train"]),
            getattr(args, "val_ratio", DEFAULT_SPLIT_RATIOS["val"]),
            getattr(args, "test_ratio", DEFAULT_SPLIT_RATIOS["test"]),
        )
        split_seed = int(getattr(args, "split_seed", 42))
        assignments, split_counts = generate_ratio_split(
            records,
            ratios=split_ratios,
            seed=split_seed,
        )
        manifest_source = None
        split_method = "ratios"

    complete, unassigned = validate_split_manifest(assignments, records)
    selected_count = sum(len(assignments[split]) for split in SPLITS)
    if selected_count == 0:
        raise PreparationError("Split assignment does not select any scenes")

    validate_existing_split_locations(assignments, output_dir)
    normalized_manifest = write_split_manifest(
        output_dir / SPLIT_MANIFEST_NAME,
        assignments,
    )

    print(f"[plan] split method: {split_method}")
    if split_method == "ratios":
        print(
            "[plan] ratios: "
            + ", ".join(f"{split}={split_ratios[split]:.6g}" for split in SPLITS)
        )
        print(f"[plan] split seed: {split_seed}")
        print(f"[plan] algorithm: {SPLIT_ALGORITHM}")
    else:
        print(f"[plan] source manifest: {manifest_source}")
        print("[plan] ratio and seed options are ignored when --split-manifest is supplied")
    print(f"[plan] normalized manifest: {normalized_manifest}")
    print(f"[plan] selected scenes: {selected_count}")
    for split in SPLITS:
        print(f"[plan] {split}: {len(assignments[split])} scene(s)")
    if unassigned:
        print(f"[plan] unassigned complete scenes will be skipped: {len(unassigned)}")

    if args.dry_run:
        print(
            "[dry-run] Validation passed; inventory and split-manifest reports were "
            "written, but no prepared scene directories were created."
        )
        return 0

    for split in SPLITS:
        (output_dir / split).mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    for split in SPLITS:
        for scene_id in assignments[split]:
            print(f"[prepare] {split}: {scene_id}", flush=True)
            results.append(
                prepare_scene(
                    complete[scene_id],
                    split=split,
                    output_dir=output_dir,
                    expected_frames=args.expected_frames,
                    mode=args.mode,
                    overwrite_existing=args.overwrite_existing_scenes,
                )
            )

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_dir": str(source_dir),
        "output_dir": str(output_dir),
        "split_manifest": str(normalized_manifest),
        "split_assignment": {
            "method": split_method,
            "source_manifest": manifest_source,
            "ratios": split_ratios,
            "seed": split_seed,
            "algorithm": SPLIT_ALGORITHM if split_method == "ratios" else None,
            "counts": split_counts,
        },
        "present_partitions": present_partitions,
        "expected_frames_per_scene": args.expected_frames,
        "mode": args.mode,
        "selected_scene_count": selected_count,
        "unassigned_complete_scenes": unassigned,
        "results": results,
        "path_note": (
            "The H5 generator stores prepared image paths directly. Place this prepared tree at "
            "its final location before H5 generation and do not move it afterward."
        ),
    }
    report_path = output_dir / "preparation_report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"[prepare] PASS: {sum(item['frames'] for item in results)} frame records")
    print(f"[report] preparation: {report_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return run(args)
    except PreparationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

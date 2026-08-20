import argparse
import json
import numpy as np
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_VAL_TEST_SPLIT_DIR = os.path.join(SCRIPT_DIR, "data", "val_test_split")

if __name__ == "__main__":
    sys.path.append(os.path.dirname(SCRIPT_DIR))

from common_utils import config
from LUT import LUT
from real_world.utils import PER_FRAME_METADATA, RAW_DATA
from utils import GT_PARAMS


def get_exp_name(zoom_idx, focus_distance_idx):
    return f"zoom_{int(zoom_idx)}_focus_distance_{int(focus_distance_idx)}"


def get_vertex_id(lens, zoom_idx, focus_distance_idx):
    return f"{lens}:{get_exp_name(zoom_idx, focus_distance_idx)}"


def get_vertex_record(lens, vertex):
    zoom_idx, focus_distance_idx = map(int, vertex)
    exp_name = get_exp_name(zoom_idx, focus_distance_idx)

    return {
        "zoom_idx": zoom_idx,
        "focus_distance_idx": focus_distance_idx,
        "exp_name": exp_name,
        "vertex_id": get_vertex_id(lens, zoom_idx, focus_distance_idx),
    }


def make_empty_lut_provenance(lens, reason="no_normal_interpolation_region"):
    return {
        "lens": lens,
        "is_within_lut": False,
        "region_type": None,
        "vertex_ids": [],
        "vertices": [],
        "weights": [],
        "reason": reason,
    }


def make_region_lut_provenance(lut, region, region_type, weights):
    vertices = [get_vertex_record(lut.lens, vertex) for vertex in region]
    vertex_ids = [vertex["vertex_id"] for vertex in vertices]

    return {
        "lens": lut.lens,
        "is_within_lut": True,
        "region_type": region_type,
        "vertex_ids": vertex_ids,
        "vertices": vertices,
        "weights": [float(weight) for weight in weights],
        "reason": "normal_interpolation_region",
    }


def compute_trapezoidal_weights(lut, input_points, quad):
    zoom_0, fdist_0, zoom_1, fdist_1, zoom_2, fdist_2, zoom_3, fdist_3 = lut.get_point_values(quad)

    assert zoom_0 - zoom_2 == zoom_1 - zoom_3

    def upper_line(x):
        m = (fdist_3 - fdist_1) / (zoom_3 - zoom_1)
        b = fdist_3 - m * zoom_3
        return m * x + b

    def lower_line(x):
        m = (fdist_2 - fdist_0) / (zoom_2 - zoom_0)
        b = fdist_2 - m * zoom_2
        return m * x + b

    fx = (input_points[:, 0] - zoom_0) / (zoom_2 - zoom_0)
    fy = (input_points[:, 1] - lower_line(input_points[:, 0])) / (
        upper_line(input_points[:, 0]) - lower_line(input_points[:, 0])
    )

    weights = np.vstack(
        (
            (1 - fx) * (1 - fy),
            (1 - fx) * fy,
            fx * (1 - fy),
            fx * fy,
        )
    ).T

    return weights


def compute_triangular_weights(lut, input_points, tri):
    x_0, y_0, x_1, y_1, x_2, y_2 = lut.get_point_values(tri)

    v0 = np.array([x_1 - x_0, y_1 - y_0])
    v1 = np.array([x_2 - x_0, y_2 - y_0])
    v2s = input_points - np.array([[x_0, y_0]])

    d00 = np.dot(v0, v0)
    d01 = np.dot(v0, v1)
    d11 = np.dot(v1, v1)
    d20s = np.dot(v2s, v0)
    d21s = np.dot(v2s, v1)

    denom = d00 * d11 - d01 * d01

    vs = (d11 * d20s - d01 * d21s) / denom
    us = (d00 * d21s - d01 * d20s) / denom
    ws = 1.0 - vs - us

    weights = np.vstack((ws, vs, us)).T

    return weights


def get_lut_provenance_for_inputs(lut, input_points):
    provenance = [
        make_empty_lut_provenance(lut.lens)
        for _ in range(input_points.shape[0])
    ]

    assigned = np.zeros(input_points.shape[0], dtype=bool)

    for quad in lut.grid_regions:
        mask = lut.region_mask(input_points, quad) & ~assigned

        if mask.sum() > 0:
            weights = compute_trapezoidal_weights(lut, input_points[mask], quad)
            global_indices = np.where(mask)[0]

            for local_idx, global_idx in enumerate(global_indices):
                provenance[global_idx] = make_region_lut_provenance(
                    lut,
                    quad,
                    "quadrilateral",
                    weights[local_idx],
                )

            assigned[mask] = True

    for tri in lut.drone_regions:
        mask = lut.region_mask(input_points, tri) & ~assigned

        if mask.sum() > 0:
            weights = compute_triangular_weights(lut, input_points[mask], tri)
            global_indices = np.where(mask)[0]

            for local_idx, global_idx in enumerate(global_indices):
                provenance[global_idx] = make_region_lut_provenance(
                    lut,
                    tri,
                    "triangular",
                    weights[local_idx],
                )

            assigned[mask] = True

    return provenance


def threshold_key(threshold):
    threshold = float(threshold)
    if threshold.is_integer():
        return str(int(threshold))
    return f"{threshold:g}"


def add_coverage_fractions(record):
    total = record["num_total_frames"]
    normal = record["num_frames_with_normal_lut_provenance"]
    valid = record["num_reliability_valid_frames"]

    record["reliability_valid_frame_fraction_of_total"] = (
        float(valid / total) if total > 0 else None
    )
    record["reliability_valid_frame_fraction_of_normal_lut_provenance"] = (
        float(valid / normal) if normal > 0 else None
    )

    return record


def make_empty_coverage_record():
    return {
        "num_total_frames": 0,
        "num_frames_with_normal_lut_provenance": 0,
        "num_reliability_valid_frames": 0,
        "num_frames_without_normal_lut_provenance": 0,
        "num_frames_with_untrusted_vertices": 0,
        "invalid_reason_counts": {},
    }


def increment_reason_count(record, reason):
    if reason is None:
        reason = "unknown"

    if reason not in record["invalid_reason_counts"]:
        record["invalid_reason_counts"][reason] = 0

    record["invalid_reason_counts"][reason] += 1


def update_coverage_record_for_frame(record, provenance, trusted_vertices):
    record["num_total_frames"] += 1

    vertex_ids = provenance.get("vertex_ids", [])
    is_within_lut = provenance.get("is_within_lut", False)

    if is_within_lut and len(vertex_ids) > 0:
        record["num_frames_with_normal_lut_provenance"] += 1

        all_vertices_trusted = all(
            vertex_id in trusted_vertices
            for vertex_id in vertex_ids
        )

        if all_vertices_trusted:
            record["num_reliability_valid_frames"] += 1
        else:
            record["num_frames_with_untrusted_vertices"] += 1
            increment_reason_count(record, "has_untrusted_lut_vertex")
    else:
        record["num_frames_without_normal_lut_provenance"] += 1
        increment_reason_count(record, provenance.get("reason"))


def load_split_file(path):
    if not os.path.exists(path):
        return set(), False

    values = np.load(path)
    return set(str(value) for value in values), True


def load_val_test_split_sets(val_test_split_dir):
    split_sets = {
        "v1": {
            "val": set(),
            "test": set(),
        },
        "v2": {
            "val": set(),
            "test": set(),
        },
    }

    split_metadata = {
        "split_dir": val_test_split_dir,
        "files": {},
        "warnings": [],
    }

    for version in ["v1", "v2"]:
        for split_name in ["val", "test"]:
            filename = f"{split_name}_split_{version}.npy"
            path = os.path.join(val_test_split_dir, filename)

            names, found = load_split_file(path)
            split_sets[version][split_name] = names

            split_metadata["files"][f"{version}_{split_name}"] = {
                "path": path,
                "found": bool(found),
                "num_videos": int(len(names)),
            }

            if not found:
                split_metadata["warnings"].append(f"Missing split file: {path}")

        overlap = split_sets[version]["val"] & split_sets[version]["test"]
        if len(overlap) > 0:
            split_metadata["warnings"].append(
                f"{version} val/test split overlap contains {len(overlap)} videos. "
                f"Preview: {sorted(overlap)[:20]}"
            )

    return split_sets, split_metadata


def get_video_split_memberships(video_name, split_sets):
    """
    Return all version/split memberships for a video.

    A video may be counted once for v1 and once for v2 if it appears in both
    version-specific split files.
    """
    memberships = []

    for version in ["v1", "v2"]:
        for split_name in ["val", "test"]:
            if video_name in split_sets[version][split_name]:
                memberships.append((version, split_name))

    if len(memberships) == 0:
        memberships.append(("unassigned", "unassigned"))

    return memberships


def make_empty_version_split_summary():
    return {
        "v1": {
            "val": make_empty_coverage_record(),
            "test": make_empty_coverage_record(),
        },
        "v2": {
            "val": make_empty_coverage_record(),
            "test": make_empty_coverage_record(),
        },
        "unassigned": make_empty_coverage_record(),
    }


def finalize_version_split_summary(version_split_summary):
    for version in ["v1", "v2"]:
        for split_name in ["val", "test"]:
            add_coverage_fractions(version_split_summary[version][split_name])

    add_coverage_fractions(version_split_summary["unassigned"])

    return version_split_summary


def update_version_split_summary(version_split_summary, video_name, provenance, trusted_vertices, split_sets):
    memberships = get_video_split_memberships(video_name, split_sets)

    for version, split_name in memberships:
        if version == "unassigned":
            update_coverage_record_for_frame(
                version_split_summary["unassigned"],
                provenance,
                trusted_vertices,
            )
        else:
            update_coverage_record_for_frame(
                version_split_summary[version][split_name],
                provenance,
                trusted_vertices,
            )


def compute_frame_reliability_coverage_report(
    video_frame_provenance_by_lens,
    video_frame_names_by_lens,
    trusted_lut_vertices_json,
    val_test_split_dir,
):
    with open(trusted_lut_vertices_json, "r") as f:
        trusted_artifact = json.load(f)

    split_sets, split_metadata = load_val_test_split_sets(val_test_split_dir)

    trusted_vertices_by_threshold_px = trusted_artifact["trusted_vertices_by_threshold_px"]
    thresholds = trusted_artifact.get(
        "epe_thresholds_px",
        sorted(trusted_vertices_by_threshold_px.keys(), key=lambda x: float(x)),
    )

    report = {
        "trusted_lut_vertices_json": trusted_lut_vertices_json,
        "trusted_lut_vertices_policy": trusted_artifact.get("policy", {}),
        "val_test_split_metadata": split_metadata,
        "split_accounting_note": (
            "summary_by_threshold_px is de-duplicated over all frames. "
            "summary_by_version_split_and_threshold_px counts frames separately for each "
            "evaluation version split. A video can contribute to v1 and v2 counts if it "
            "appears in both version-specific split files."
        ),
        "thresholds_px": thresholds,
        "summary_by_threshold_px": {},
        "summary_by_lens_and_threshold_px": {},
        "summary_by_version_split_and_threshold_px": {},
        "summary_by_lens_version_split_and_threshold_px": {},
    }

    for threshold in thresholds:
        key = threshold_key(threshold)

        aggregate_record = make_empty_coverage_record()
        version_split_record = make_empty_version_split_summary()

        report["summary_by_threshold_px"][key] = aggregate_record
        report["summary_by_lens_and_threshold_px"][key] = {}
        report["summary_by_version_split_and_threshold_px"][key] = version_split_record
        report["summary_by_lens_version_split_and_threshold_px"][key] = {}

        for lens, provenance_list in video_frame_provenance_by_lens.items():
            frame_names = video_frame_names_by_lens.get(lens, [])

            if len(frame_names) != len(provenance_list):
                raise ValueError(
                    f"Frame name/provenance length mismatch for lens {lens}: "
                    f"{len(frame_names)} names vs {len(provenance_list)} provenance records"
                )

            lens_record = make_empty_coverage_record()
            lens_version_split_record = make_empty_version_split_summary()

            trusted_vertices = set(
                trusted_vertices_by_threshold_px.get(key, {}).get(lens, [])
            )

            for video_name, provenance in zip(frame_names, provenance_list):
                update_coverage_record_for_frame(
                    aggregate_record,
                    provenance,
                    trusted_vertices,
                )
                update_coverage_record_for_frame(
                    lens_record,
                    provenance,
                    trusted_vertices,
                )
                update_version_split_summary(
                    version_split_record,
                    video_name,
                    provenance,
                    trusted_vertices,
                    split_sets,
                )
                update_version_split_summary(
                    lens_version_split_record,
                    video_name,
                    provenance,
                    trusted_vertices,
                    split_sets,
                )

            report["summary_by_lens_and_threshold_px"][key][lens] = add_coverage_fractions(lens_record)
            report["summary_by_lens_version_split_and_threshold_px"][key][lens] = finalize_version_split_summary(lens_version_split_record)

        report["summary_by_threshold_px"][key] = add_coverage_fractions(aggregate_record)
        report["summary_by_version_split_and_threshold_px"][key] = finalize_version_split_summary(version_split_record)

    return report


def get_default_reliability_report_path(trusted_lut_vertices_json):
    policy_dir_name = os.path.basename(os.path.dirname(os.path.abspath(trusted_lut_vertices_json)))

    return os.path.join(
        SCRIPT_DIR,
        "artifacts",
        "frame_lut_reliability",
        "real_world",
        policy_dir_name,
        "frame_coverage_by_threshold.json",
    )


def write_reliability_coverage_report(
    video_frame_provenance_by_lens,
    video_frame_names_by_lens,
    trusted_lut_vertices_json,
    reliability_report_path,
    val_test_split_dir,
):
    if reliability_report_path is None:
        reliability_report_path = get_default_reliability_report_path(trusted_lut_vertices_json)

    report = compute_frame_reliability_coverage_report(
        video_frame_provenance_by_lens,
        video_frame_names_by_lens,
        trusted_lut_vertices_json,
        val_test_split_dir,
    )

    os.makedirs(os.path.dirname(reliability_report_path), exist_ok=True)

    with open(reliability_report_path, "w") as f:
        json.dump(report, f, indent=4)

    print(f"Wrote LUT reliability frame coverage report to {reliability_report_path}")


def interpolate_all_frames(
    video_root,
    selected_trials_dir,
    dry_run=False,
    trusted_lut_vertices_json=None,
    reliability_report_path=None,
    val_test_split_dir=DEFAULT_VAL_TEST_SPLIT_DIR,
):
    # Generate all LUTs for each lens type
    lenses = list(config['lenses'].keys())
    luts = {lens: LUT(f'{selected_trials_dir}/{lens}_selected_trials.json', lens) for lens in lenses}

    # Create per-lens data structures
    video_names_and_frame_counts_by_lens = {lens: [] for lens in lenses}
    video_frame_metadata_by_lens = {lens: [] for lens in lenses}
    video_frame_names_by_lens = {lens: [] for lens in lenses}
    video_frame_intrinsics_by_lens = {}
    video_frame_provenance_by_lens = {lens: [] for lens in lenses}

    for subdir in sorted(os.listdir(video_root)):
        # Check that item is a video directory, and metadata file exists
        if os.path.isdir(os.path.join(video_root, subdir)):
            metadata_path = os.path.join(video_root, subdir, PER_FRAME_METADATA)
            if os.path.exists(metadata_path):
                with open(metadata_path, "r") as f:
                    metadata = json.load(f)

                # Extract needed info from each metadata file
                lens = metadata["lens"]
                if lens not in lenses:
                    print(f"WARNING: Lens {lens} not recognized, skipping video {subdir}...")
                    continue

                video_name = subdir
                num_frames = len(metadata["frames"])
                video_names_and_frame_counts_by_lens[lens].append((video_name, num_frames))

                for frame in metadata["frames"]:
                    focus_distance = metadata["frames"][frame]["focus_distance_m"] * 1000  # Store in mm for LUT lookup
                    focal_length = metadata["frames"][frame]["focal_length_mm"]

                    video_frame_metadata_by_lens[lens].append([focal_length, focus_distance])
                    video_frame_names_by_lens[lens].append(video_name)
            else:
                print(f'WARNING: No {PER_FRAME_METADATA} found in', os.path.join(video_root, subdir) + ', skipping...')

    # Run LUT interpolation for all frames, by lens
    intr_keys_to_retrieve = ['fx', 'fy', 'cx', 'cy', 'k1', 'k2', 'p1', 'p2']
    lens_metadata_to_retrieve = ['focal_length_mm', 'focus_distance_m']

    for lens in video_frame_metadata_by_lens.keys():
        frame_metadata = np.array(video_frame_metadata_by_lens[lens])
        if frame_metadata.shape[0] == 0:
            print(f"WARNING: No frames found for lens {lens}, skipping...")
            continue

        intrinsics = []

        # Get ground truth intrinsics, no extrapolation
        for intr_key in intr_keys_to_retrieve:
            result, _, _ = luts[lens].interpolate_all(frame_metadata, intr_key, extrapolate=False)
            intrinsics.append(result)

        # Get ground truth intrinsics, with extrapolation
        for intr_key in intr_keys_to_retrieve:
            result, _, _ = luts[lens].interpolate_all(frame_metadata, intr_key, extrapolate=True)
            intrinsics.append(result)

        # Report lens metadata as well
        intrinsics.append(frame_metadata)

        video_frame_intrinsics_by_lens[lens] = np.hstack(intrinsics)
        video_frame_provenance_by_lens[lens] = get_lut_provenance_for_inputs(luts[lens], frame_metadata)

    # Print statistics
    for lens in video_names_and_frame_counts_by_lens.keys():
        print(f"Found {len(video_names_and_frame_counts_by_lens[lens])} videos for lens {lens}")
        print(f"\tFound {len(video_frame_metadata_by_lens[lens])} total frames for lens {lens}")

        # Compute number of frames with non-nan intrinsics, if any intrinsics exist
        if lens in video_frame_intrinsics_by_lens:
            n_nan_frames = np.isnan(video_frame_intrinsics_by_lens[lens][:, :8]).any(axis=-1).sum()
            n_nan_extrapolated_frames = np.isnan(video_frame_intrinsics_by_lens[lens][:, 8:16]).any(axis=-1).sum()
            n_total_frames = video_frame_intrinsics_by_lens[lens].shape[0]
            n_normal_lut_provenance_frames = sum(
                provenance.get("is_within_lut", False)
                for provenance in video_frame_provenance_by_lens[lens]
            )

            print(f"\tFound {n_nan_frames} frames with NaN intrinsics for lens {lens} (outside of LUT bounds)")
            print(f"\tFound {n_nan_extrapolated_frames} frames with NaN intrinsics after extrapolation for lens {lens}")
            print(f"\tFound {n_total_frames - n_nan_frames} frames with non-NaN normal intrinsics for lens {lens}")
            print(f"\tFound {n_normal_lut_provenance_frames} frames with normal LUT provenance for lens {lens}")
            print(f"\tPercent of frames with non-NaN extrapolated intrinsics: {(n_total_frames - n_nan_extrapolated_frames) / n_total_frames * 100:.2f}%")

    if trusted_lut_vertices_json is not None and not dry_run:
        write_reliability_coverage_report(
            video_frame_provenance_by_lens,
            video_frame_names_by_lens,
            trusted_lut_vertices_json,
            reliability_report_path,
            val_test_split_dir,
        )
    elif trusted_lut_vertices_json is not None and dry_run:
        print("Dry run enabled; skipping LUT reliability frame coverage report write.")

    if not dry_run:
        print("Writing ground truth json to disk...")

        # Write results to json files
        for lens in video_frame_intrinsics_by_lens.keys():
            intrinsics = video_frame_intrinsics_by_lens[lens]
            provenance = video_frame_provenance_by_lens[lens]
            video_names_and_frame_counts = video_names_and_frame_counts_by_lens[lens]

            curr_intrinsics_idx = 0
            for video_name, num_frames in video_names_and_frame_counts:
                start_idx = curr_intrinsics_idx
                end_idx = curr_intrinsics_idx + num_frames
                intrinsics_slice = intrinsics[start_idx:end_idx, :]
                provenance_slice = provenance[start_idx:end_idx]

                gt_intrinsics_dict = {
                    str(i): {
                        "intrinsics_gt": {
                            key: float(val) for key, val in zip(intr_keys_to_retrieve, row[:8])
                        },
                        "intrinsics_gt_extrapolated": {
                            key: float(val) for key, val in zip(intr_keys_to_retrieve, row[8:16])
                        },
                        "lens_metadata": {
                            key: float(val / 1000.0 if key == "focus_distance_m" else val) for key, val in zip(lens_metadata_to_retrieve, row[16:])
                            # key: float(val) for key, val in zip(lens_metadata_to_retrieve, row[16:])
                        },
                        "lut_provenance": provenance_slice[i],
                    }
                    for i, row in enumerate(intrinsics_slice)
                }

                gt_params_path = os.path.join(video_root, video_name, RAW_DATA, GT_PARAMS)

                with open(gt_params_path, "w") as f:
                    json.dump(gt_intrinsics_dict, f, indent=4)

                # Update index for next video
                curr_intrinsics_idx += num_frames

    return video_frame_intrinsics_by_lens


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate per-frame ground truth intrinsics for all real world videos using LUT interpolation.")
    parser.add_argument("--video-root", type=str, help="Specify path to folder containing all of the video subfolders with frame metadata.", default=config['lut_creation']['VIDEO_ROOT'])
    parser.add_argument("--selected-trials-dir", type=str, help="Specify path to folder containing all of the selected trials .json files.", default=config['lut_creation']['SELECTED_TRIALS_DIR'])
    parser.add_argument("--dry-run", action='store_true', help="If set, will not write to disk, but will return the interpolated results.")
    parser.add_argument(
        "--trusted-lut-vertices-json",
        "--trusted_lut_vertices_json",
        type=str,
        default=None,
        help="Optional path to trusted_lut_vertices_by_threshold.json. If provided, writes a frame coverage report.",
    )
    parser.add_argument(
        "--reliability-report-path",
        "--reliability_report_path",
        type=str,
        default=None,
        help="Optional explicit output path for the LUT reliability frame coverage report.",
    )
    parser.add_argument(
        "--val-test-split-dir",
        "--val_test_split_dir",
        type=str,
        default=DEFAULT_VAL_TEST_SPLIT_DIR,
        help="Directory containing val_split_v1.npy, test_split_v1.npy, val_split_v2.npy, and test_split_v2.npy.",
    )
    args = parser.parse_args()

    video_root = args.video_root
    selected_trials_dir = args.selected_trials_dir
    dry_run = args.dry_run
    trusted_lut_vertices_json = args.trusted_lut_vertices_json
    reliability_report_path = args.reliability_report_path
    val_test_split_dir = args.val_test_split_dir

    interpolate_all_frames(
        video_root,
        selected_trials_dir,
        dry_run=dry_run,
        trusted_lut_vertices_json=trusted_lut_vertices_json,
        reliability_report_path=reliability_report_path,
        val_test_split_dir=val_test_split_dir,
    )
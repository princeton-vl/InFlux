#!/usr/bin/env python3
"""
process_video_by_detections.py

Run the Kalibr pipeline on an MXF video. Requires the InFlux utility environment.

Steps:
 1. Extract metadata and TIFF frames from ARRIRAW MXF/MP4/MOV file.
 2. Write simplified metadata, experiment metadata, and target.yaml based on board size.
 3. Calculate detections per frame in TIFF files.
 4. Select frames using ANMS by detections.
 5. Create bag with these frames.
 6. Run Kalibr on the bag.

"""

import argparse
import csv
import cv2
import json
import math
import numpy as np
import os
import psutil
import resource
import sys
import time

if __name__ == "__main__":
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    sys.path.append(os.path.dirname(SCRIPT_DIR))

from pathlib import Path

if __name__ == "__main__":
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    sys.path.append(os.path.dirname(SCRIPT_DIR))

from common_utils import config, get_settings_by_exp_name, ensure_folders_exist, read_kalibr_result_file, flag_missing, create_flag_file, normalize_drone_coordinates, get_camera_info, read_flag_file, create_per_frame_meta_from_metadata_export
from hue_calib import hue_calib
from select_frames_by_anms import select_and_copy_frames as select_frames_by_anms
from utils import *
from write_aprilgrid_config import write_config as write_aprilgrid_config

def parse_bool(value):
    """Parse an explicit True/False command-line value."""
    if isinstance(value, bool):
        return value

    normalized = value.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise argparse.ArgumentTypeError("Expected either True or False")

def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Process video (ARRIRAW MXF/MP4/MOV) using Kalibr corner detections and frame culling.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--root-folder", type=str, help="Directory to place all experiments in", default=config['real_calib']['EXP_ROOT'])
    parser.add_argument("--lens", type=str, choices=config['lenses'].keys(), help="Lens type for placing in the right directory", required=True)
    parser.add_argument("--lens-name-suffix", type=str, default='', help="Suffix to lens metadata name for specifying which version of lens")
    parser.add_argument("--exp_name", type=str, help="Name of experiment. If not provided, will take the name of the video file")
    parser.add_argument("--video", type=str,help="Absolute path to a single MXF/MP4/MOV file. If not provided, will look inside `--exp_name` folder (which must be provided).")
    parser.add_argument("--board_size", type=str, help="AprilGrid board size (e.g., 0.1, 0.2, 0.4, 0.8), or 'drone'. If not provided, will be determined through focal length/focus distance metadata.")
    parser.add_argument("--focal_length_guess", type=float, help="[Optional if metadata exists] Guess for focal length value to give to Kalibr, in px. This will only be used when no metadata exists")
    parser.add_argument("--start_end_idx", type=int, nargs=2, help="Start and end indices to extract from video, inclusive (non-negative integer)")
    parser.add_argument("--allow_duplicates", type=parse_bool, default=True, help="Allow multiple videos to contribute to each experiment; only works if gathering all videos in a experiment folder")
    parser.add_argument("--settings_path", type=str, help="Custom settings path. Overrides {lens}.json")

    anms_grp = parser.add_argument_group('ANMS')
    anms_grp.add_argument("--min_supp_r", type=float, help="Threshold minimum suppression radius for frames to be selected. Lower means more frames will be selected. If not provided, will be calculated automatically.")
    anms_grp.add_argument("--c_robust", type=float, help="c_robust (as defined in ANMS paper)", default=1)
    anms_grp.add_argument('--include_consecutive', action="store_true", help="Include strings of consecutive & identical frames. Default is to exclude all but one")

    parser.add_argument("--overwrite", action="store_true", help="If set, rerun steps even if flags exist")
    parser.add_argument("--pause", action="store_true", help="Wait for enter to be hit between steps. (For manual testing)")
    parser.add_argument("--num_trials", type=int, help="Number of calibration trials to run", default=17)

    args = parser.parse_args()

    # Additional validations (if any)
    if args.start_end_idx is not None:
        if any([x < 0 for x in args.start_end_idx]):
            parser.error("start and end idx must be non-negative integers")

    assert args.c_robust > 0 and args.c_robust <= 1, "C_robust should be > 0 and <= 1"

    assert (args.exp_name is not None) or (args.video is not None), "Please provide at least one of `--exp_name` or `--video`."

    if args.board_size:
        try:
            args.board_size = float(args.board_size)
        except ValueError:
            assert args.board_size == "drone", "Board size must be a float or 'drone'"

    return args

def main(args):
    # Unpack arguments
    camera = 'arri'
    root_folder_base = args.root_folder
    lens = args.lens
    lens_name_suffix = args.lens_name_suffix
    root_folder = f"{root_folder_base}/{lens}"
    settings_path = args.settings_path # none by default
    videofiles = [args.video]
    focal_length_guess = args.focal_length_guess

    exp_name = args.exp_name
    if exp_name: # experiment folder provided; use that if video is not provided
        if not args.video:  # use videos found inside experiment folder instead
            raw_data_dir = f"{root_folder}/{exp_name}/{RAW_DATA}"
            # find all videos in the raw data folder for this exp setting (copy from camera card should have put them there)
            videofiles = sorted([f"{raw_data_dir}/{f}" for f in os.listdir(raw_data_dir) if os.path.isfile(f"{raw_data_dir}/{f}") and os.path.splitext(f)[1] in ['.mxf', '.mov', '.mp4']])
            if not args.allow_duplicates:
                assert len(videofiles) == 1, f"Cannot find unique video file within {exp_name} experiment folder ({len(videofiles)} videos found) (are there two videos with the same experiment settings?)"

        _, _, board_size, _ = get_settings_by_exp_name(exp_name, settings_path=settings_path)
    else:
        # exp name not provided; rely on video name
        assert args.video
        exp_name = Path(args.video).stem
        board_size = args.board_size
        assert board_size, "Please provide board size if not providing experiment name"

    start_idx, end_idx = args.start_end_idx or [None, None]
    pause = input if args.pause else (lambda *args: None)
    skip_if_exists = not args.overwrite
    c_robust = args.c_robust
    min_supp_r = args.min_supp_r
    num_trials = args.num_trials
    exclude_consecutive = not args.include_consecutive

    # define experiment folders
    exp_folder = os.path.join(root_folder, exp_name)

    calib_result_filepaths = []
    for i in range(num_trials):
        calib_result_filepaths.append(f'{exp_folder}/{RESULTS}/trial_{i}_calib_result.json')
    # note: these are relative to the exp_folder
    calib_folders = []
    for i in range(num_trials):
        calib_folders.append(f'{exp_folder}/trial_{i}/calibration')

    ensure_folders_exist([FLAGS, KALIBR_COMMON_CACHE, RAW_DATA, SELECTED_FRAMES, RESULTS, RUN_METADATA], root_dir=exp_folder)
    ensure_folders_exist(calib_folders)

    pause("Directories created. Press Enter to continue...")

    # validate that video files exist
    for video in videofiles:
        if not os.path.isfile(video):
            print(f"File {video} does not exist. Exiting.")
            sys.exit(1)

    start_time = time.time()
    times = []

    # extract metadata and TIFF frames from MXF
    if flag_missing(EXTRACT_META_AND_FRAMES_COMPLETE, exp_folder, skip_if_exists):
        print("=== Extracting metadata and TIFF frames from MXF/MP4/MOV ===")
        # function extracts the tiff for a single video into a folder named raw_data/{counter}
        def extract(video, counter, start_idx, end_idx):
            ext = os.path.splitext(video)[1].lower()

            extract_folder_target = f"{exp_folder}/{RAW_DATA}/{counter}"
            ensure_folders_exist(extract_folder_target)

            if ext in (".mp4", ".mov"):
                print("From", ext)
                # TODO parallelize?
                vidcap = cv2.VideoCapture(video)
                frame_num = 0
                while (ret := vidcap.read())[0]:
                    cv2.imwrite(f"{extract_folder_target}/{frame_num:07d}.tiff", ret[1])  # save frame as TIFF file
                    frame_num += 1
            elif ext == ".mxf":
                # start extract based on how many frames are already there (if we were interrupted)
                if start_idx is not None and end_idx is not None:
                    cmd_extract = f'./process_mxf.sh "{os.path.realpath(video)}" "{extract_folder_target}" "{exp_folder}/{METADATA_EXPORT}" {start_idx} {end_idx}'
                else:
                    # check if frames already exist in raw_data; if so, get the one with the highest number (filenames are of the form <0-padded number>.tiff. use that as the start index)
                    existing_frames = [f for f in os.listdir(f"{extract_folder_target}") if f.endswith(".tiff")]
                    if existing_frames:
                        start_idx = max([int(f.split(".")[0]) for f in existing_frames]) + 1
                        print(f"Found {len(existing_frames)} existing frames. Starting extraction from frame {start_idx}.")
                        cmd_extract = f'./process_mxf.sh "{os.path.realpath(video)}" "{extract_folder_target}" "{exp_folder}/{METADATA_EXPORT}" {start_idx}'
                    else: # just do all of them
                        cmd_extract = f'./process_mxf.sh "{os.path.realpath(video)}" "{extract_folder_target}" "{exp_folder}/{METADATA_EXPORT}"'
                if not run_bash_command(cmd_extract, verbose=True):
                    sys.exit(1)
            else:
                print("Invalid video format. Only allows mxf/mov/mp4")
                sys.exit(1)

        for i, video_path in enumerate(videofiles):
            extract(video_path, i, start_idx, end_idx)

        # moving tiffs outside their respective subfolders into the rawdata folder and renaming them
        total_tiffs = 0
        video_dir = f"{exp_folder}/{RAW_DATA}"
        folder_list = sorted([f for f in os.listdir(video_dir) if os.path.isdir(os.path.join(video_dir, f))])
        for folder in folder_list:
            print("MOVING IMAGES FROM FOLDER: ", f"{video_dir}/{folder}")
            folder_dir = f"{video_dir}/{folder}"
            all_tiffs = sorted([
                t for t in os.listdir(folder_dir)
                if os.path.isfile(os.path.join(folder_dir, t)) and t.lower().endswith((".tiff", ".tif"))
            ])
            for tiff in all_tiffs:
                new_name = f"{total_tiffs:07d}.tiff"

                os.chdir(video_dir)

                if os.path.islink(f"{new_name}"):
                    os.unlink(f"{new_name}")
                    print(f"[WARNING] Image symlink already exists! Overriding")

                # os.symlink(f"{folder_dir}/{tiff}", f"{new_name}")
                os.link(f"{folder_dir}/{tiff}", f"{new_name}")

                total_tiffs += 1
            print(f"DONE WITH {folder} FOLDER")

        create_flag_file(EXTRACT_META_AND_FRAMES_COMPLETE, exp_folder)
        times.append(("Extract metadata & frames", time.time() - start_time))
        print(times)
        pause("Press Enter to continue...")
        start_time = time.time()
    else:
        print("===> Reusing extracted metadata and TIFF frames from MXF/MP4/MOV...")

    # also write json of just focal lengths and focus distances for each frame and some extra meta, for easier access
    if flag_missing(WRITE_PER_FRAME_AND_RUN_METADATA_COMPLETE, exp_folder, skip_if_exists):
        ext = os.path.splitext(videofiles[0])[1].lower()

        if ext == ".mxf":
            if not os.path.exists(f"{exp_folder}/{TARGET_PARAMETERS}"):
                print(f"=== Writing {TARGET_PARAMETERS} (hasn't been written yet by UI?...) ===")
                with open(f"{exp_folder}/{TARGET_PARAMETERS}", "w") as f:
                    zoom, focus_distance_mm, _, _ = get_settings_by_exp_name(exp_name, settings_path=settings_path)
                    obj = {
                        "focal_length": zoom,
                        "focus_distance": focus_distance_mm,
                        "board_size": board_size,
                    }
                    json.dump(obj, f, indent=4)
            else:
                print("===> Reusing target parameters written from UI...")

            if os.path.exists(f"{exp_folder}/{METADATA_EXPORT}"):
                print("=== Writing simplified per-frame metadata ===")
                per_frame_meta = create_per_frame_meta_from_metadata_export(f"{exp_folder}/{METADATA_EXPORT}", lens_name_suffix)
                with open(f"{exp_folder}/{PER_FRAME_METADATA}", "w") as f:
                    json.dump(per_frame_meta, f, indent=4)

                print(f"=== Writing {ACTUAL_PARAMETERS} ===")
                with open(f"{exp_folder}/{ACTUAL_PARAMETERS}", "w") as f:
                    obj = {
                        "focal_length": per_frame_meta["frames"][0]["focal_length_mm"],
                        "focus_distance": per_frame_meta["frames"][0]["focus_distance_m"] * 1000,
                        "board_size": board_size, # note: we already got this from the exp name before
                    }
                    json.dump(obj, f, indent=4)
            else:
                print("===> No metadata export file found (not an MXF file?). Skipping writing simplified per-frame metadata and actual parameters...")
        elif ext in (".mp4", ".mov"):
            pass  # there is no metadata or target parameters to extract for these videos
        else:
            print("Invalid video format. Only allows mxf/mov/mp4")
            sys.exit(1)


        create_flag_file(WRITE_PER_FRAME_AND_RUN_METADATA_COMPLETE, exp_folder)
        times.append(("Write simplified per-frame metadata", time.time() - start_time))
        print(times)
        pause("Press Enter to continue...")
        start_time = time.time()
    else:
        print("===> Reusing simplified per-frame metadata...")

    # get number of frames
    num_frames = 0
    for i in os.listdir(f"{exp_folder}/{RAW_DATA}"):
        if os.path.splitext(i)[1].lower() == '.tiff':
            num_frames += 1
    print("NUM_FRAMES", num_frames)

    # increase the number of open files at once (temporary)
    soft_limit, hard_limit = resource.getrlimit(resource.RLIMIT_NOFILE)
    try:
        resource.setrlimit(resource.RLIMIT_NOFILE, (16384, hard_limit))
    except ValueError as e:
        print(f"Could not set file descriptor limit: {e}")

    if board_size == "drone":
        points_2d, points_2d_successes = None, None
        if flag_missing(DETECT_CORNERS_COMPLETE, exp_folder, skip_if_exists): # here, "corners" are just the drone detections in the video
            print("=== Detecting drone locations ===")
            # GENERATE 2D detections! we dont have them yet. only the raw tiffs from the video
            # read 2D detections
            points_2d, points_2d_successes = hue_calib(
                src=f"{exp_folder}/{RAW_DATA}",
                frames_dest=f"{exp_folder}/{DETECTION_FRAMES}",
                overwrite=not skip_if_exists,
            )
            # save the full versions in case they're needed
            np.savetxt(f"{exp_folder}/{COORDS_2D_FULL}", points_2d, delimiter=',')
            np.savetxt(f"{exp_folder}/{COORDS_2D_SUCCESSES_FULL}", points_2d_successes, delimiter=',')
            create_flag_file(DETECT_CORNERS_COMPLETE, exp_folder)

        if flag_missing(SELECT_FRAMES_COMPLETE, exp_folder, skip_if_exists): # selecting frames = choosing the first detection from each consecutive group of frames

            if points_2d is None or points_2d_successes is None:
                points_2d = np.loadtxt(f"{exp_folder}/{COORDS_2D_FULL}", delimiter=',')
                points_2d_successes = np.loadtxt(f"{exp_folder}/{COORDS_2D_SUCCESSES_FULL}", delimiter=',')

            points_2d_successes = points_2d_successes.astype(int)

            # on first detected flash, record the position
            flash_centers = []
            for i in range(1, points_2d.shape[0]):
                if points_2d_successes[i-1, 1] == 0 and points_2d_successes[i, 1] == 1:
                    flash_centers.append(points_2d[i])

            points_2d = np.array(flash_centers)
            points_2d[:, 0] = np.arange(len(points_2d)) # reindex
            points_2d_successes = np.ones((points_2d.shape[0], 2)).astype(int)
            points_2d_successes[:, 0] = np.arange(len(points_2d_successes)) # reindex

            # offset by 0.5 to match kalibr convention
            points_2d[:, 1:] -= np.full_like(points_2d[:, 1:], 0.5)

            # save using csv writer
            with open(f"{exp_folder}/{COORDS_2D}", "w") as f:
                writer = csv.writer(f)
                for p in points_2d:
                    p0 = int(p[0])
                    writer.writerow([p0, *p[1:]]) # first col needs to be int
            with open(f"{exp_folder}/{COORDS_2D_SUCCESSES}", "w") as f:
                writer = csv.writer(f)
                for p in points_2d_successes:
                    writer.writerow(p)

            create_flag_file(SELECT_FRAMES_COMPLETE, exp_folder, data=str(len(points_2d)))


        if os.path.exists(f"{exp_folder}/{RTK_POSITIONS}"):
            # drone process: read RTK & detections --> massage & transform & put in kalibr_common_cache
            # TODO refine when rtk data and detections are ready
            if flag_missing(WRITE_TARGET_COMPLETE, exp_folder, skip_if_exists):
                print("=== Transforming drone data for Kalibr ===")
                with open(f"{exp_folder}/{RTK_POSITIONS}", "r") as f:
                    flashes = json.load(f) # list of objs with 'x', 'y', 'alt', and 'timestamp'
                    points_3d = np.zeros((len(flashes), 4))
                    points_3d[:, 0] = np.arange(len(flashes)) # index
                    for i, flash in enumerate(flashes):
                        points_3d[i, 1:] = [flash['x'], flash['y'], flash['alt']]
                    points_3d_normalized = normalize_drone_coordinates(points_3d)

                # yaml file should contain normalized coords
                with open(f'{exp_folder}/{TARGET_YAML}', mode='w', newline='') as file:
                    file.write("target_type: pointcloud\npoints:\n")
                    for point in points_3d_normalized:
                        file.write(f"- [{point[1]}, {point[2]}, {point[3]}]\n")

                create_flag_file(WRITE_TARGET_COMPLETE, exp_folder)
            else:
                print("===> Reusing transformed drone data for Kalibr...")
        else:
            print(f"[WARNING] Could not find RTK positions for {exp_name}. Exiting with status 0 to continue pipeline.")
            sys.exit(0)


        # end drone process
    else:
        # write target.yaml
        if flag_missing(WRITE_TARGET_COMPLETE, exp_folder, skip_if_exists):
            print("=== Writing target.yaml ===")
            write_aprilgrid_config(f"{exp_folder}/{TARGET_YAML}", board_size)

            create_flag_file(WRITE_TARGET_COMPLETE, exp_folder)
            times.append(("Write target.yaml", time.time() - start_time))
            print(times)
            pause("Press Enter to continue...")
            start_time = time.time()
        else:
            print("===> Reusing target.yaml...")

        # calculate detections per frame in TIFF files
        if flag_missing(DETECT_CORNERS_COMPLETE, exp_folder, skip_if_exists):
            if start_idx is not None and end_idx is not None:
                print(f"=== Getting num detections in frames {start_idx} to {end_idx} ===")
            else:
                print(f"=== Getting num detections in all frames ===")

            # run batches sequentially and combine results at the end
            batch_size = 400
            num_batches = (num_frames + batch_size - 1) // batch_size
            starts = []
            ends = []
            for i in range(num_batches):
                start = i * batch_size
                end = min((i + 1) * batch_size, num_frames) - 1 # end is inclusive so subtract one
                starts.append(start)
                ends.append(end)
                # note: path is hardcoded here. it has to match what kalibr_detect_corners does
                if not os.path.exists(f"{exp_folder}/{RAW_DATA}/detections_per_frame_{start:05d}_{end:05d}.json"):
                    print(f"=== Batch {i+1}: running Kalibr detect_corners on frames {start} to {end} ===")
                    cmd_detect = f''' \\
                        docker run --rm \\
                        --platform linux/amd64 \\
                        --name "kalibr-{exp_name}-detect-{i}" \\
                        -v "{exp_folder}:/data" \\
                        kalibr " \\
                        rosrun kalibr kalibr_detect_corners \\
                            --target /data/{TARGET_YAML} \\
                            --models pinhole-radtan \\
                            --topics /cam0/image_raw \\
                            --frames-dir /data/{RAW_DATA} \\
                            --output-dir /data/{RAW_DATA} \\
                            --from-to {start} {end} \\
                            --detection-coords /data/{COORDS_2D_FULL.replace('.csv', '')}_{start:05d}_{end:05d}.csv \\
                            --detection-successes /data/{COORDS_2D_SUCCESSES_FULL.replace('.csv', '')}_{start:05d}_{end:05d}.csv
                             " '''

                    if not run_bash_command(cmd_detect, verbose=True, cleanup_on_error_fn=kill_containers_matching_pattern(exp_name)): # outputs {RAW_DATA}/detections_per_frame.json
                        sys.exit(1)
                else:
                    print(f"=== Batch {i+1}: Reusing detections for frames {start} to {end}...")

            # combine results
            print("=== Combining results ===")
            coords_2d_str = ""
            coords_2d_successes_str = ""
            combined = {}
            batch_files = [f for f in os.listdir(f"{exp_folder}/{RAW_DATA}") if f.startswith("detections_per_frame_")]
            assert len(batch_files) == num_batches, f"Expected {num_batches} batch files, found {len(batch_files)}"
            for start, end in zip(starts, ends):
                with open(f"{exp_folder}/{COORDS_2D_FULL.replace('.csv', '')}_{start:05d}_{end:05d}.csv", "r") as f:
                    coords_2d_str += f.read()
                with open(f"{exp_folder}/{COORDS_2D_SUCCESSES_FULL.replace('.csv', '')}_{start:05d}_{end:05d}.csv", "r") as f:
                    coords_2d_successes_str += f.read()
            for batch_file in batch_files:
                with open(f"{exp_folder}/{RAW_DATA}/{batch_file}", "r") as f:
                    combined |= json.load(f)
            with open(f"{exp_folder}/{COORDS_2D_FULL}", "w") as f:
                f.write(coords_2d_str)
            with open(f"{exp_folder}/{COORDS_2D_SUCCESSES_FULL}", "w") as f:
                f.write(coords_2d_successes_str)
            with open(f"{exp_folder}/{DETECTIONS_PER_FRAME}", "w") as f:
                json.dump(combined, f)

            create_flag_file(DETECT_CORNERS_COMPLETE, exp_folder)
            times.append(("kalibr_detect_corners", time.time() - start_time))
            print(times)
            pause("Press Enter to continue...")
            start_time = time.time()
        else:
            print("===> Reusing detections...")

        # select frames using ANMS by detections
        if flag_missing(SELECT_FRAMES_COMPLETE, exp_folder, skip_if_exists):
            print("=== Selecting/copying best frames via ANMS & rewriting coords files ===")
            selected_indices = select_frames_by_anms(
                f"{exp_folder}/{RAW_DATA}",
                f"{exp_folder}/{SELECTED_FRAMES}",
                f"{exp_folder}/{DETECTIONS_PER_FRAME}",
                c_robust=c_robust,
                min_supp_r=min_supp_r,
                n_workers=os.cpu_count() - 1,
                exclude_consecutive=exclude_consecutive,
            )
            # rewrite coords files
            rewrite_coords_files(exp_folder, set(selected_indices))

            create_flag_file(SELECT_FRAMES_COMPLETE, exp_folder, data=str(len(selected_indices)))
            times.append(("ANMS", time.time() - start_time))
            print(times)
            pause("\nPress Enter to continue...")
            start_time = time.time()
        else:
            print("===> Reusing selected frames...")

        # end board section

    # focal length guess
    ext = os.path.splitext(videofiles[0])[1].lower()

    if ext == ".mxf":
        # Determine + log focal length guess
        sensor_width_mm, _, sensor_resolution_x, _, _ = get_camera_info(camera)
        with open(f"{exp_folder}/{ACTUAL_PARAMETERS}", "r") as f:
            obj = json.load(f)
            focal_length_mm = obj["focal_length"]
            focus_distance_m = obj["focus_distance"] / 1000
        pinhole_to_obj_in_m = focus_distance_m - focal_length_mm / 1000
        # use thin lens equation to approximate lens focal length (px) from camera focal length (mm) and focus distance (m)
        lens_focal_length_guess_mm = 1 / (1 / focal_length_mm + 1 / (pinhole_to_obj_in_m * 1000))
        focal_length_guess = lens_focal_length_guess_mm * sensor_resolution_x / sensor_width_mm # in px
    elif ext in (".mp4", ".mov"):
        assert focal_length_guess is not None and isinstance(focal_length_guess, float)  # No calulation from metadata possible; manual initilaization needs to exist
    else:
        print("Invalid video format. Only allows mxf/mov/mp4")
        sys.exit(1)

    print(f"=====> Focal length guess: {focal_length_guess} px")

    # read num datapoints from SELECT_FRAMES_COMPLETE - its either num ANMS frames (board) or num waypoints (drone)
    num_selected_frames = int(read_flag_file(SELECT_FRAMES_COMPLETE, exp_folder))
    # run Kalibr calibration
    if flag_missing(CALIB_COMPLETE, exp_folder, skip_if_exists):
        image_width, image_height = get_image_size(exp_folder)
        trials_to_run = [not os.path.exists(f"{calib_folder_path}/{REPORT_CAM}") for calib_folder_path in calib_folders]
        print(f"=== Running Kalibr calibration for {exp_name} (trials needed: {trials_to_run.count(True)}) ===")
        cmd_calibs = [f''' \\
            docker run --rm \\
            --platform linux/amd64 \\
            -e "DISPLAY" -e "QT_X11_NO_MITSHM=1" \\
            --name "kalibr-{exp_name}-calib-trial-{pid}" \\
            -v "/tmp/.X11-unix:/tmp/.X11-unix:rw" \\
            -v "{exp_folder}/{KALIBR_COMMON_CACHE}:/data" \\
            -v "{calib_folder}:/report" \\
            kalibr " \\
            FOCAL_LENGTH_GUESS={focal_length_guess} rosrun kalibr kalibr_calibrate_cameras \\
                --dont-show-report \\
                --topics /cam0/image_raw \\
                --models pinhole-radtan \\
                --detection-coords /data/{Path(COORDS_2D).name} \\
                --detection-successes /data/{Path(COORDS_2D_SUCCESSES).name} \\
                --image-width {image_width} --image-height {image_height} \\
                --report-dir /report \\
                --init-mode fixed_point \\
                --target /data/{Path(TARGET_YAML).name} ;"  '''
                for pid, (calib_folder, to_run) in enumerate(zip(calib_folders, trials_to_run)) if to_run]
        log_filepaths = [f'{calib_folder}/{KALIBR_CALIB_LOG}' for calib_folder, to_run in zip(calib_folders, trials_to_run) if to_run]

        # be smart about memory based on num frames - 1 worker takes abt 0.041358% of total computer mem per 1 frame (from testing)
        # AKA 0.01323456 GB
        avail_ram = psutil.virtual_memory().available / 1024**3 # in GB
        worker_frames = math.floor(avail_ram / 0.01323456) * 0.98 # to give a buffer
        # 1690 / 32 * (num GB RAM)
        print("Workerframes available:", worker_frames)
        # if we allocate abt 70% memory to these processes (so we don't max out memory; seems like the baseline computer memory usage is around 25%)
        # we have ~1690 worker-frames at our disposal. so we can do floor(1690 / num_frames) at a time, (if memory is the constraint)
        cpu_constrained_num_workers = os.cpu_count() - 3
        mem_constrained_num_workers = math.floor(worker_frames / num_selected_frames)
        if mem_constrained_num_workers < cpu_constrained_num_workers:
            # make smarter batch sizes, spreading out the work
            batches = math.ceil(num_trials / mem_constrained_num_workers)
            num_workers = math.ceil(num_trials / batches)
            print(f"NOTE: Too many frames to use {cpu_constrained_num_workers} parallel processes. Using {num_workers} instead")
        else:
            num_workers = cpu_constrained_num_workers
        if not run_bash_commands(cmd_calibs, log_filepaths, batch_size=num_workers, verbose=True, cleanup_on_error_fn=kill_containers_matching_pattern(exp_name)):
            sys.exit(1)

        # Read and record Kalibr calibration results
        all_calib_files_found = True
        for calib_folder_path, calib_result_filepath in zip(calib_folders, calib_result_filepaths):
            try:
                calib_result_dict = read_kalibr_result_file(f'{calib_folder_path}/{RESULTS_CAM}')
                calib_result_dict['coordinate_convention'] = 'normal' # keep track of convention going forward
            except:
                all_calib_files_found = False
                continue

            with open(calib_result_filepath, 'w') as file:
                json.dump(calib_result_dict, file, indent=4)

        if all_calib_files_found:
            create_flag_file(CALIB_COMPLETE, exp_folder)
            times.append(("Kalibr calibration", time.time() - start_time))
        else:
            print(f"Kalibr calibration failed on some trials of {calib_folder_path}. No results found. Continuing")
            print("Exiting with status 1")
            sys.exit(1) # will either retry or skip & put it in onhold
    else:
        print("===> Reusing calibration...")

    print("TIMINGS")
    print(times)

if __name__ == "__main__":
    args = parse_arguments()
    main(args)

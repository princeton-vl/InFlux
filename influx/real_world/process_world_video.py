import argparse
import cv2
import json
import os
import sys
import time

if __name__ == "__main__":
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    sys.path.append(os.path.dirname(SCRIPT_DIR))

from utils import *
from common_utils import config, ensure_folders_exist, flag_missing, create_flag_file, create_per_frame_meta_from_metadata_export

def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Process real-world (benchmark) video (ARRIRAW MXF/MP4/MOV).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--root-folder", type=str, help="Directory to place all experiments in", default=config['real_world']['VIDEO_ROOT'])
    parser.add_argument("--lens-name-suffix", type=str, default='', help="Suffix to lens metadata name for specifying which version of lens")
    parser.add_argument("--exp_name", type=str, help="Name of the benchmark video folder under --root-folder", required=True)
    parser.add_argument("--start_end_idx", type=int, nargs=2, help="Start and end indices to extract from video, inclusive (non-negative integer)")

    parser.add_argument("--overwrite", action="store_true", help="If set, rerun steps even if flags exist")
    parser.add_argument("--pause", action="store_true", help="Wait for enter to be hit between steps. (For manual testing)")

    args = parser.parse_args()

    # Additional validations (if any)
    if args.start_end_idx:
        if any([x < 0 for x in args.start_end_idx]):
            parser.error("start and end idx must be non-negative integers")

    return args

def main(args):
    # Unpack arguments
    root_folder = args.root_folder # root folder is actually whats provided, doesn't have lens in it
    lens_name_suffix = args.lens_name_suffix

    exp_name = args.exp_name
    raw_data_dir = f"{root_folder}/{exp_name}/{RAW_DATA}"
    videofiles = sorted([f for f in os.listdir(raw_data_dir) if os.path.isfile(f"{raw_data_dir}/{f}") and os.path.splitext(f)[1].lower() in ['.mxf', '.mov', '.mp4']])
    assert len(videofiles) == 1, f"Cannot find unique video file within {exp_name} experiment folder ({len(videofiles)} videos found) (are there two videos with the same experiment settings?)"
    video = f"{raw_data_dir}/{videofiles[0]}"

    start_idx, end_idx = args.start_end_idx or [None, None]
    pause = input if args.pause else (lambda *args: None)
    skip_if_exists = not args.overwrite

    # define experiment folders
    exp_folder = os.path.join(root_folder, exp_name)

    ensure_folders_exist([FLAGS, RAW_DATA], root_dir=exp_folder)

    pause("Directories created. Press Enter to continue...")

    # validate that MXF file exists
    if not os.path.isfile(video):
        print(f"File {video} does not exist. Exiting.")
        sys.exit(1)

    start_time = time.time()
    times = []

    # extract metadata and TIFF frames from MXF
    if flag_missing(EXTRACT_META_AND_FRAMES_COMPLETE, exp_folder, skip_if_exists):
        print("=== Extracting metadata and TIFF frames from MXF/MP4/MOV ===")
        ext = os.path.splitext(video)[1].lower()
        if ext in (".mp4", ".mov"):
            print("From", ext)
            # TODO parallelize?
            vidcap = cv2.VideoCapture(video)
            frame_num = 0
            while (ret := vidcap.read())[0]:
                cv2.imwrite(f"{exp_folder}/{RAW_DATA}/{frame_num:07d}.tiff", ret[1])  # save frame as TIFF file
                frame_num += 1
        elif ext == ".mxf":
            # start extract based on how many frames are already there (if we were interrupted)
            if start_idx is not None and end_idx is not None:
                # TODO maybe move process_mxf out of real_calib?
                cmd_extract = f'../real_calib/process_mxf.sh "{os.path.realpath(video)}" "{exp_folder}/{RAW_DATA}" "{exp_folder}/{METADATA_EXPORT}" {start_idx} {end_idx}'
            else:
                # check if frames already exist in raw_data; if so, get the one with the highest number (filenames are of the form <0-padded number>.tiff. use that as the start index)
                existing_frames = [f for f in os.listdir(f"{exp_folder}/{RAW_DATA}") if f.endswith(".tiff")]
                if existing_frames:
                    start_idx = max([int(f.split(".")[0]) for f in existing_frames])
                    print(f"Found {len(existing_frames)} existing frames. Starting extraction from frame {start_idx}.")
                    cmd_extract = f'../real_calib/process_mxf.sh "{os.path.realpath(video)}" "{exp_folder}/{RAW_DATA}" "{exp_folder}/{METADATA_EXPORT}" {start_idx}'
                else: # just do all of them
                    cmd_extract = f'../real_calib/process_mxf.sh "{os.path.realpath(video)}" "{exp_folder}/{RAW_DATA}" "{exp_folder}/{METADATA_EXPORT}"'
            if not run_bash_command(cmd_extract, verbose=True):
                sys.exit(1)
        else:
            print("Invalid video format. Only allows mxf/mov/mp4")
            sys.exit(1)

        create_flag_file(EXTRACT_META_AND_FRAMES_COMPLETE, exp_folder)
        times.append(("Extract metadata & frames", time.time() - start_time))
        print(times)
        pause("Press Enter to continue...")
        start_time = time.time()
    else:
        print("===> Reusing extracted metadata and TIFF frames from MXF/MP4/MOV...")

    # also write json of just focal lengths and focus distances for each frame and some extra meta, for easier access
    if flag_missing(WRITE_PER_FRAME_AND_RUN_METADATA_COMPLETE, exp_folder, skip_if_exists):
        if os.path.exists(f"{exp_folder}/{METADATA_EXPORT}"):
            print("=== Writing simplified per-frame metadata ===")
            per_frame_meta = create_per_frame_meta_from_metadata_export(f"{exp_folder}/{METADATA_EXPORT}", lens_name_suffix)
            with open(f"{exp_folder}/{PER_FRAME_METADATA}", "w") as f:
                json.dump(per_frame_meta, f, indent=4)

        else:
            print("===> No metadata export file found (not an MXF file?). Skipping writing simplified per-frame metadata and actual parameters...")

        create_flag_file(WRITE_PER_FRAME_AND_RUN_METADATA_COMPLETE, exp_folder)
        times.append(("Write simplified per-frame metadata", time.time() - start_time))
        print(times)
        pause("Press Enter to continue...")
        start_time = time.time()
    else:
        print("===> Reusing simplified per-frame metadata...")

    print("TIMINGS")
    print(times)

if __name__ == "__main__":
    args = parse_arguments()
    main(args)

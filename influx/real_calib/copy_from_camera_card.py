import argparse
import os
import sys
import time

if __name__ == "__main__":
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    sys.path.append(os.path.dirname(SCRIPT_DIR))

from collections import defaultdict
from utils import *
from common_utils import config, get_real_exp_name, ensure_folders_exist, create_per_frame_meta_from_metadata_export

def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Batch copy ARRIRAW MXF videos (.mxf) from camera card to local storage",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--src", type=str, help="Directory where camera card mounts. Required if not requeuing")
    parser.add_argument("--dest", type=str, help="Directory to copy to (i.e. on desktop)", default=config['real_calib']['VIDEO_DEST_DIR'])
    parser.add_argument("--exp-root", type=str, help="Root directory of experiments", default=config['real_calib']['EXP_ROOT'])

    parser.add_argument("--timestamp", type=str, help="If provided, override the timestamp (to continue resync from a previous run)", default=None)
    parser.add_argument("--no-rsync", action="store_true", help="If provided, don't rsync, just skip to (re)queuing all the videos from a given timestamp. Must provide timestamp")
    parser.add_argument("--no-hardlink", action="store_true", help="If provided, will skip hardlinking videos to their experiment folders. Useful if you only want to view video --> experiment name mappings")
    parser.add_argument("--lens-name-suffix", type=str, default='', help="Suffix to lens metadata name for specifying which version of lens")

    parser.add_argument("--wipe", action="store_true", help="Wipe the source directory after copying")
    parser.add_argument("--skip", type=int, nargs="+", help="List of (1-indexed) video indices to skip copying, sorted by name ascending", default=[])

    parser.add_argument("--settings-path", type=str, help="Custom settings path to add to each pipeline invocation. Overrides {lens}.json")
    parser.add_argument("--queue-path", type=str, help="Path to queue file to store pipeline running commands", default=config['real_calib']['QUEUE_FILE'])
    parser.add_argument("--allow-dup-settings", action="store_true", help="If set, allow videos with duplicate settings. They'll be created in folders with '(<n>)' at the end of the foldername")
    parser.add_argument("--merge-same-setting-videos", action="store_true", help="If set, bulk process all input videos with the same calibration settings by combining their frames together")

    parser.add_argument("--num_trials", type=int, help="Number of calibration trials to run", default=100)

    args = parser.parse_args()

    if args.no_rsync:
        assert args.timestamp is not None, "Must provide timestamp if skipping rsync"
    else:
        assert args.src is not None, "Must provide camera card directory if rsyncing"

    return args

def main(args):
    src_dir = args.src
    dest_dir = args.dest
    lens_name_suffix = args.lens_name_suffix
    skip = args.skip
    queue_path = args.queue_path
    settings_path = args.settings_path
    wipe = args.wipe
    timestamp = args.timestamp or time.strftime('%Y-%m-%d_%H:%M')
    no_rsync = args.no_rsync
    no_hardlink = args.no_hardlink
    allow_dup_settings = args.allow_dup_settings
    merge_same_setting_videos = args.merge_same_setting_videos

    num_trials = args.num_trials

    if not no_rsync:
        # timestamp the destination directory
        dest_dir = f"{dest_dir}/{timestamp}"

        ensure_folders_exist(dest_dir)

        # get all ARRIRAW MXF videos in the camera-card root
        videofiles = sorted([f for f in sorted(os.listdir(src_dir)) if os.path.isfile(os.path.join(src_dir, f)) and os.path.splitext(f)[1].lower() == ".mxf"])
        # exclude videos in skip list
        excludes = [f for i, f in enumerate(videofiles) if i+1 in skip]
        excludes_str = "".join([f" --exclude '{f}'" for f in excludes])

        print(f"=====> rsync {src_dir} to {dest_dir}...")
        start_time = time.time()
        cmd_copy = f'rsync -rltDhuP{excludes_str} --include "*.mxf" --exclude "*" "{src_dir}"/ "{dest_dir}"'
        if not run_bash_command(cmd_copy, verbose=True):
            sys.exit(1)
        elapsed = time.time() - start_time
        print(f"=====> rsync complete (took {elapsed:.2f}s)")
    else:
        dest_dir = f"{dest_dir}/{timestamp}"
        assert os.path.isdir(dest_dir), "Timestamp directory does not exist!"
        # get all copied ARRIRAW MXF videos when requeuing
        videofiles = sorted([f for f in sorted(os.listdir(dest_dir)) if os.path.isfile(os.path.join(dest_dir, f)) and os.path.splitext(f)[1].lower() == ".mxf"])
        excludes = [f for i, f in enumerate(videofiles) if i+1 in skip]

    # for each video, run process_mxf for one frame, get metadata (zoom & focus), lookup indices in lens metadata file, and create an invocation with the correct exp name (add to list of commadns to add)
    videofiles = sorted(set(videofiles) - set(excludes))

    invocations = []

    seen_experiments = defaultdict(list)  # experiment name to folder name mapping
    experiment_to_videos_mapping = defaultdict(list)  # expname to list of videofiles
    experiment_to_folders_mapping = defaultdict(list)  # expname to list of new folder names to create; should track experiment_to_videos_mapping

    # find all experiment directories that exist already
    for lens in config['lenses'].keys():
        exp_root = os.path.join(args.exp_root, lens)
        ensure_folders_exist(exp_root)

        for exp_name in os.listdir(exp_root):
            i = exp_name.find('_additional_trial_')
            i = i if i != -1 else len(exp_name)
            exp_name_no_extension = exp_name[:i]
            seen_experiments[exp_name_no_extension].append(exp_name)

    temp_metadata_path = f"{dest_dir}/{TEMP_METADATA}"
    print(f"=====> Creating hardlinks to videos inside each experiment dir")
    # sort all the videos into experiment_to_videos_mapping dict based off of which experiment setting they are
    for videofile in videofiles:
        video_path = os.path.join(dest_dir, videofile)
        print(f"\n\n====== {video_path} ======")

        cmd_extract = f'art-cmd export --input "{video_path}" --output "{temp_metadata_path}" --start 1 --duration 1'
        if not run_bash_command(cmd_extract, print_command=False):
            sys.exit(1)

        # get focal length and focus distance
        obj = create_per_frame_meta_from_metadata_export(temp_metadata_path, lens_name_suffix)
        focal_length_mm = obj["frames"][0]["focal_length_mm"]
        focus_distance_m = obj["frames"][0]["focus_distance_m"] # NOTE : this is the sensor to object distance, not the pinhole_to_obj
        lens = obj["lens"]

        exp_root = f"{args.exp_root}/{lens}"
        ensure_folders_exist(exp_root)
        exp_name = get_real_exp_name(focal_length_mm, focus_distance_m, lens, settings_path=settings_path)
        exp_folder = os.path.join(exp_root, exp_name)

        print(f"{videofile} --> {exp_name}")

        # Determine number of times experiment has been performed (both in the past, and in this batch)
        n_times_seen_previously = 0
        n_times_seen_total = 0
        if exp_name in seen_experiments:
            n_times_seen_previously += len(seen_experiments[exp_name])
            n_times_seen_total += len(seen_experiments[exp_name])
        if exp_name in experiment_to_videos_mapping:
            n_times_seen_total += len(experiment_to_videos_mapping[exp_name])

        if n_times_seen_total > 0:
            if allow_dup_settings:
                print(f"[WARNING] VIDEO {videofile} and {seen_experiments[exp_name]} all MAP TO {exp_name}, but allowing duplicate settings. Creating another folder.")

                if not merge_same_setting_videos:
                    folder_name = f"{exp_name}_additional_trial_{n_times_seen_total}"
                else:
                    if n_times_seen_previously != 0:
                        folder_name = f"{exp_name}_additional_trial_{n_times_seen_previously}"
                    else:
                        folder_name = f"{exp_name}"

                exp_folder = os.path.join(exp_root, folder_name)
                print(f"---> New folder name: {folder_name}")
            else:
                print(f"[ERROR] VIDEO {videofile} MAPS TO {exp_name}, but so do previous videos ({seen_experiments[exp_name]}). This shouldn't happen! Ensure camera settings are unique. Skipping creating symlink.")
                continue
        else:
            folder_name = exp_name
            exp_folder = os.path.join(exp_root, folder_name)

        experiment_to_videos_mapping[exp_name].append(videofile)
        experiment_to_folders_mapping[exp_name].append(exp_folder)

    # for each experiment, hardlink all the videos that are mapped to it to the experiment's rawdata folder
    for exp_name in experiment_to_videos_mapping:
        lens = exp_name.split('_')[-1]
        videos = experiment_to_videos_mapping[exp_name]
        exp_folders = experiment_to_folders_mapping[exp_name]

        if no_hardlink:
            continue

        # Create folders and invocations
        for exp_folder in exp_folders:
            ensure_folders_exist(exp_folder)
            ensure_folders_exist([RAW_DATA], root_dir=exp_folder)

            # Extract folder exp_folder_name
            exp_folder_name = exp_folder.split('/')[-1]

            settings_path_flag = f' --settings_path {settings_path}' if settings_path else ''
            invocations.append(
                f'python process_video_by_detections.py --lens {lens} --lens-name-suffix "{lens_name_suffix}" --exp_name "{exp_folder_name}"{settings_path_flag} --allow_duplicates {allow_dup_settings} --num_trials {num_trials}'
            )

            if merge_same_setting_videos:
                break

        for videofile, exp_folder in zip(videos, exp_folders):
            dest_path = os.path.join(exp_root, exp_folder, RAW_DATA, videofile)
            src_video_path = os.path.join(dest_dir, videofile)

            if not os.path.isfile(dest_path):
                # create the hardlink
                os.link(src_video_path, dest_path)
            else:
                print(f"[WARNING] Symlink already exists for {videofile} in {exp_name}. Skipping adding hardlink.")

    if os.path.exists(temp_metadata_path):
        os.remove(temp_metadata_path)

    print(f"\n\n=====> Batch adding {len(invocations)} commands to queue...")
    with open(queue_path, "a") as f:
        if len(invocations):
            print("\n".join(invocations))
            f.write("\n" + "\n".join(invocations))

    if wipe:
        ans = input("=====> Wipe source directory?... [y/n]")
        if ans.lower() != "y":
            print("=====> Skipping wipe")
            return
        cmd_wipe = f'rm -rf {src_dir}/*'
        if not run_bash_command(cmd_wipe, verbose=True):
            sys.exit(1)


if __name__ == "__main__":
    args = parse_arguments()
    main(args)

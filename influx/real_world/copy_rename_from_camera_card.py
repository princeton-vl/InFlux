import argparse
import os
import pandas as pd
import sys

from pathlib import Path

if __name__ == "__main__":
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    sys.path.append(os.path.dirname(SCRIPT_DIR))

from common_utils import config, ensure_folders_exist
from real_calib.utils import run_bash_command
from utils import *


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Batch copy all videos (.mxf, .mp4, .mov) from camera card to local storage and rename based on mapping",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--src", type=str, help="Directory where camera card mounts.", required=True)
    parser.add_argument("--video-root", type=str, help="Root directory of videos", default=config['real_world']['VIDEO_ROOT'])
    parser.add_argument("--name-mapping", type=str, help="File where names are provided", required=True)
    parser.add_argument("--card", type=str, choices=["a", "b", "c", "d", "e", "f", "g"], help="Camera card label that we want to copy (for lookup into the name mapping file)", required=True)
    parser.add_argument("--no-rsync", action="store_true", help="Don't rsync (just show the name mappings). Kinda like dryrun")
    parser.add_argument("--skip", type=int, nargs="+", help="List of (1-indexed) video indices to skip copying, sorted by name ascending", default=[])
    parser.add_argument("--queue-path", type=str, help="Path to queue file to store pipeline running commands", default=config['real_world']['QUEUE_FILE'])
    parser.add_argument("--lens-name-suffix", type=str, default='', help="Suffix to lens metadata name for specifying which version of lens")

    args = parser.parse_args()

    return args

def main(args):
    src_dir = args.src
    video_root = args.video_root
    skip = args.skip
    queue_path = args.queue_path
    name_mapping_file = args.name_mapping
    card = args.card
    no_rsync = args.no_rsync
    lens_name_suffix = args.lens_name_suffix

    # get filename mapping
    df = pd.read_csv(name_mapping_file)


    newnames = df[df['Camera Card'] == card]['Target Filename']

    # get all videos (.mxf, .mov, .mp4) in root_folder
    videofiles = sorted([f for f in sorted(os.listdir(src_dir)) if os.path.isfile(os.path.join(src_dir, f)) and os.path.splitext(f)[1].lower() in [".mxf", ".mov", ".mp4"]])
    # exclude videos in skip list
    videofiles = [f for i, f in enumerate(videofiles) if i+1 not in skip]

    assert len(videofiles) == len(newnames), f"Number of videos to copy does not match the number of rows for card {card} in the name mapping file"

    invocations = []
    temp_metadata_path = f"{video_root}/{TEMP_METADATA}"

    video_stems = []
    video_paths = []
    if not no_rsync:
        for videofile, newname in zip(videofiles, newnames):
            vid_stem = Path(newname).stem
            video_dir = os.path.join(video_root, vid_stem, RAW_DATA)
            ensure_folders_exist(video_dir) # create the video root

            src_video_path = os.path.join(src_dir, videofile)
            dest_video_path = os.path.join(video_dir, newname)

            print(f"{src_video_path} --> {dest_video_path}")

            video_stems.append(vid_stem)
            video_paths.append(dest_video_path)

            # rsync
            cmd_copy = f'rsync -rltDhuP "{src_video_path}" "{dest_video_path}"' # no trailing slashes to copy files
            if not run_bash_command(cmd_copy, verbose=True): # no trailing slashes to copy files
                sys.exit(1)
        print("====> All rsyncs done")

    for video_stem, video_path in zip(video_stems, video_paths):
        # extract 1  frame of metadata to get the lens (for use in LUT)
        cmd_extract = f'art-cmd export --input "{video_path}" --output "{temp_metadata_path}" --start 1 --duration 1'
        if not run_bash_command(cmd_extract, print_command=False):
            sys.exit(1)

        invocations.append(f'python process_world_video.py --lens-name-suffix "{lens_name_suffix}" --exp_name "{video_stem}"')

    # batch add to queue
    # NOTE this will just add everything even if its been queued before. in practice thats fine
    print(f"\n\n=====> Batch adding {len(invocations)} (out of {len(videofiles)} videos) commands to queue...")
    with open(queue_path, "a") as f:
        if len(invocations):
            print("\n".join(invocations))
            f.write("\n" + "\n".join(invocations))


if __name__ == "__main__":
    args = parse_arguments()
    main(args)

import argparse
import glob
import os
from extract_tiffs import extract_tiffs
from huggingface_hub import snapshot_download
from tqdm import tqdm


def download_dataset(local_dir="influx_data/dataset"):
    """
    Download the InFlux dataset from Hugging Face Hub.
    """
    snapshot_download(
        repo_id="princeton-vl/InFlux",
        repo_type="dataset",
        local_dir=local_dir,
        allow_patterns="*",
        ignore_patterns=None,
    )
    print(f"Dataset downloaded to {local_dir}")


def main(args):
    output_dir = args.output_dir
    extract_frames = args.extract_frames
    
    # download dataset
    dataset_dir = f"{output_dir}/dataset"
    download_dataset(dataset_dir)

    # optionally extract frames
    if extract_frames:
        # Find all .mp4 videos
        pattern = os.path.join(dataset_dir, "*.mp4")
        video_paths = sorted(glob.glob(pattern))
        
        for video_path in tqdm(video_paths, desc="Extracting frames from videos..."):
            video_name = video_path.split('/')[-1].split('.')[0]
            
            frame_dest = f'{output_dir}/frames/{video_name}'
            
            print(f"Extracting frames from {video_name}...")
            extract_tiffs(video_path, frame_dest)
            
        print("Frame extraction completed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Download the InFlux dataset and optionally extract frames."
    )
    parser.add_argument(
        "--extract-frames",
        action="store_true",
        help="Extract frames using extract_tiffs after downloading the dataset.",
    )
    parser.add_argument("--output-dir", type=str, default='influx_data')
    args = parser.parse_args()
    
    main(args)

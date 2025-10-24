import argparse
import json
from pathlib import Path


def generate_empty_submission(path_to_split_json, intr_type, file_path):
    with open(path_to_split_json, 'r') as f:
        split_info = json.load(f)

    empty_submission = {
        'submission_metadata': {
            'method_name': 'empty_submission',
            'intrinsics_type': intr_type
        }
    }

    for video, info in split_info.items():
        if info['split'] == 'test':
            empty_submission[video] = {}
            num_frames = info['frame_count']

            for frame_idx in range(num_frames):
                if intr_type == 'rad-tan':
                    empty_submission[video][str(frame_idx)] = {
                        'fx': None,
                        'fy': None,
                        'cx': None,
                        'cy': None,
                        'k1': None,
                        'k2': None,
                        'p1': None,
                        'p2': None
                    }
                elif intr_type == 'mei':
                    empty_submission[video][str(frame_idx)] = {
                        'fx': None,
                        'fy': None,
                        'cx': None,
                        'cy': None,
                        'xi': None,
                    }
                else:
                    raise NotImplementedError(f"Unsupported intrinsics type: {intr_type}")

    with open(file_path, 'w') as f:
        json.dump(empty_submission, f, indent=4)

    print(f"Generated empty submission file: {file_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Generate an empty submission JSON for InFlux benchmark."
    )
    parser.add_argument(
        '--split-json-path', type=str, default='influx_data/dataset/video_frame_count_and_split.json',
        help="Path to the split JSON file (default: influx_data/dataset/video_frame_count_and_split.json)"
    )
    parser.add_argument(
        '--intr-type', type=str, choices=['rad-tan', 'mei'], default='rad-tan',
        help="Type of intrinsics (default: rad-tan)"
    )
    parser.add_argument(
        '--output', type=str, default='empty_submission.json',
        help="Path to save the generated empty submission JSON (default: empty_submission.json)"
    )

    args = parser.parse_args()
    generate_empty_submission(args.split_json_path, args.intr_type, args.output)


if __name__ == "__main__":
    main()

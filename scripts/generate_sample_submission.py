import argparse
import json
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parent.parent

DEFAULT_INFLUX_SPLIT_JSON_PATH = (
    REPO_ROOT
    / 'influx_real_data'
    / 'influx'
    / 'video_frame_count_and_split_v1.json'
)
DEFAULT_INFLUX_PP_REAL_SPLIT_JSON_PATH = (
    REPO_ROOT
    / 'influx_real_data'
    / 'influx_pp_real'
    / 'video_frame_count_and_split_v2.json'
)


def get_selected_split_paths(
    version,
    influx_split_json_path,
    influx_pp_real_split_json_path,
):
    if version == 'influx':
        return [Path(influx_split_json_path)]
    if version == 'influx_pp_real':
        return [Path(influx_pp_real_split_json_path)]
    if version == 'all':
        return [
            Path(influx_split_json_path),
            Path(influx_pp_real_split_json_path),
        ]
    raise ValueError(f"Unsupported version: {version}")


def generate_empty_submission(
    version,
    influx_split_json_path,
    influx_pp_real_split_json_path,
    intr_type,
    method_name,
    file_path,
):
    empty_submission = {
        'submission_metadata': {
            'method_name': method_name,
            'intrinsics_type': intr_type,
            'version': version,
        }
    }

    test_video_count = 0
    test_frame_count = 0

    for path_to_split_json in get_selected_split_paths(
        version,
        influx_split_json_path,
        influx_pp_real_split_json_path,
    ):
        if not path_to_split_json.is_file():
            raise ValueError(
                f"Split JSON file not found: {path_to_split_json}"
            )

        with path_to_split_json.open('r', encoding='utf-8') as f:
            split_info = json.load(f)

        for video, info in split_info.items():
            if info['split'] == 'test':
                if video in empty_submission:
                    raise ValueError(
                        f"Video {video!r} appears in more than one selected "
                        "split JSON file"
                    )

                empty_submission[video] = {}
                num_frames = info['frame_count']
                test_video_count += 1
                test_frame_count += num_frames

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
                            'p2': None,
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
                        raise NotImplementedError(
                            f"Unsupported intrinsics type: {intr_type}"
                        )

    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(empty_submission, f, indent=4)

    print(f"Generated empty submission file: {file_path}")
    print(f"  version: {version}")
    print(f"  intrinsics type: {intr_type}")
    print(f"  method name: {method_name}")
    print(f"  test videos: {test_video_count}")
    print(f"  test frames: {test_frame_count}")
    print(f"  output: {file_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Generate an empty submission JSON for InFlux benchmark."
    )
    parser.add_argument(
        '--version',
        type=str,
        choices=['influx', 'influx_pp_real', 'all'],
        required=True,
        help=(
            "Benchmark track to generate: influx, influx_pp_real, or all"
        ),
    )
    parser.add_argument(
        '--influx-split-json-path',
        type=str,
        default=str(DEFAULT_INFLUX_SPLIT_JSON_PATH),
        help=(
            "Path to the influx split JSON file "
            f"(default: {DEFAULT_INFLUX_SPLIT_JSON_PATH})"
        ),
    )
    parser.add_argument(
        '--influx-pp-real-split-json-path',
        type=str,
        default=str(DEFAULT_INFLUX_PP_REAL_SPLIT_JSON_PATH),
        help=(
            "Path to the influx_pp_real split JSON file "
            f"(default: {DEFAULT_INFLUX_PP_REAL_SPLIT_JSON_PATH})"
        ),
    )
    parser.add_argument(
        '--intr-type',
        type=str,
        choices=['rad-tan', 'mei'],
        default='rad-tan',
        help="Type of intrinsics (default: rad-tan)",
    )
    parser.add_argument(
        '--method-name',
        type=str,
        default='empty_submission',
        help=(
            "Method name stored in submission_metadata "
            "(default: empty_submission)"
        ),
    )
    parser.add_argument(
        '--output',
        type=str,
        default='empty_submission.json',
        help=(
            "Path to save the generated empty submission JSON "
            "(default: empty_submission.json)"
        ),
    )

    args = parser.parse_args()

    for path in get_selected_split_paths(
        args.version,
        args.influx_split_json_path,
        args.influx_pp_real_split_json_path,
    ):
        if not path.is_file():
            parser.error(f"Split JSON file not found: {path}")

    generate_empty_submission(
        args.version,
        args.influx_split_json_path,
        args.influx_pp_real_split_json_path,
        args.intr_type,
        args.method_name,
        args.output,
    )


if __name__ == "__main__":
    main()

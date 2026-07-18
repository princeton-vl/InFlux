import requests
import argparse
from requests_toolbelt.multipart.encoder import MultipartEncoder, MultipartEncoderMonitor
from tqdm import tqdm
import os
import json
import math
import re
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

DEFAULT_WEBSITE = 'https://influx.cs.princeton.edu'
MAX_FILE_SIZE = 512 * 1024 * 1024  # 512MB
MAX_JSON_DEPTH = 10

website = DEFAULT_WEBSITE
session = None
headers = None


def initialize_session(website_url):
    global website, session, headers

    website = website_url.rstrip('/')
    session = requests.Session()

    response = session.get(f'{website}/request_submit/')
    if response.status_code != 200:
        raise RuntimeError(
            f"Failed to load submission page: HTTP {response.status_code}: "
            f"{response.text}"
        )

    csrf_token = (
        session.cookies.get('csrftoken')
        or session.cookies.get('influx_dev_csrftoken')
    )
    if not csrf_token:
        raise RuntimeError("Could not obtain a CSRF token from the website")

    headers = {
        'X-CSRFToken': csrf_token,
        'Referer': f'{website}/request_submit/',
    }


def request_verification(args, url=None):
    if url is None:
        url = f"{website}/request_submit/"

    data = {
        'email': args.email,
        'method_name': args.method_name,
        'version': args.version,
    }

    response = session.post(url, data=data, headers=headers)

    if response.status_code == 200:
        upload_id = response.json()['upload_id']
        print(f"Verification code sent to {args.email}.")
        print(f"Your submission id is {upload_id}.")
        return upload_id

    print("Failed to request verification:", response.text)
    raise SystemExit(1)


def verify_code(upload_id, code, url=None):
    if url is None:
        url = f"{website}/verify"

    data = {
        'code': code,
    }
    response = session.post(f"{url}/{upload_id}/", data=data, headers=headers)
    if response.status_code == 200:
        return True

    print("Verification failed:", response.text)
    raise SystemExit(1)


def check_json_depth(obj, current_depth=0, max_depth=MAX_JSON_DEPTH):
    """Recursively check JSON depth to prevent deeply nested attacks."""
    if current_depth > max_depth:
        raise ValueError(
            f"JSON is too deeply nested (max depth: {max_depth})"
        )

    if isinstance(obj, dict):
        for value in obj.values():
            check_json_depth(value, current_depth + 1, max_depth)
    elif isinstance(obj, list):
        for item in obj:
            check_json_depth(item, current_depth + 1, max_depth)


def upload_file(upload_id, file_path, url=None):
    if url is None:
        url = f"{website}/upload"

    # Check that file_path points to one JSON file.
    if not os.path.isfile(file_path):
        raise ValueError(f"{file_path} is not a valid file path.")
    if not file_path.endswith(".json"):
        raise ValueError("Only JSON files are allowed.")

    total_size = os.path.getsize(file_path)
    if total_size > MAX_FILE_SIZE:
        raise ValueError(
            f"File size ({total_size} bytes) exceeds maximum allowed size "
            f"({MAX_FILE_SIZE} bytes)"
        )

    progress_bar = tqdm(
        total=total_size,
        unit='B',
        unit_scale=True,
        desc="Uploading",
    )

    def progress_callback(monitor):
        progress_bar.update(monitor.bytes_read - progress_bar.n)

    try:
        with open(file_path, 'rb') as f:
            encoder = MultipartEncoder(
                fields={
                    'file': (
                        os.path.basename(file_path),
                        f,
                        'application/json',
                    )
                }
            )
            monitor = MultipartEncoderMonitor(encoder, progress_callback)
            new_headers = headers.copy()
            new_headers['Content-Type'] = monitor.content_type

            response = session.post(
                f"{url}/{upload_id}/",
                data=monitor,
                headers=new_headers,
            )
    finally:
        progress_bar.close()

    if response.status_code != 200:
        print("Failed to upload file:", response.text)
        raise SystemExit(1)

    print("File uploaded successfully.")

    # Finish upload.
    response = session.post(
        f"{website}/finish_upload/{upload_id}/",
        headers=headers,
    )
    if response.status_code != 200:
        print("Failed to finish upload:", response.text)
        raise SystemExit(1)

    try:
        result = response.json()
    except ValueError:
        result = {}

    print(result.get('message', 'Successfully uploaded your submission.'))
    if result.get('state'):
        print(f"Submission state: {result['state']}")


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
        return [Path(influx_split_json_path), Path(influx_pp_real_split_json_path)]
    raise ValueError(f"Unsupported version: {version}")


def load_required_test_videos(
    version,
    influx_split_json_path,
    influx_pp_real_split_json_path,
):
    required_videos = {}

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
            if info['split'] != 'test':
                continue

            if video in required_videos:
                raise ValueError(
                    f"Video {video!r} appears in more than one selected "
                    "split JSON file"
                )

            required_videos[video] = info['frame_count']

    return required_videos


def check_submission_validity(
    submission_file_path,
    submission_method_name,
    version,
    influx_split_json_path,
    influx_pp_real_split_json_path,
):
    json_name = os.path.basename(submission_file_path)

    if not re.match(r'^[a-zA-Z0-9_][a-zA-Z0-9_.-]*\.json$', json_name):
        raise ValueError(
            "Filename contains invalid characters. Only letters, numbers, "
            "underscores, dots, and dashes allowed."
        )

    file_size = os.path.getsize(submission_file_path)
    if file_size > MAX_FILE_SIZE:
        raise ValueError(
            f"Submission file is too large ({file_size} bytes). "
            f"Maximum size is {MAX_FILE_SIZE} bytes."
        )

    with open(submission_file_path, 'r', encoding='utf-8') as f:
        submission = json.load(f)

    check_json_depth(submission)

    if 'submission_metadata' not in submission:
        raise ValueError(
            "Submission is missing 'submission_metadata' key"
        )

    metadata = submission['submission_metadata']
    if not isinstance(metadata, dict):
        raise ValueError("submission_metadata must be a JSON object")

    if 'method_name' not in metadata:
        raise ValueError("submission_metadata is missing 'method_name'")
    if 'intrinsics_type' not in metadata:
        raise ValueError("submission_metadata is missing 'intrinsics_type'")
    if 'version' not in metadata:
        raise ValueError("submission_metadata is missing 'version'")

    method_name = metadata['method_name']
    intr_type = metadata['intrinsics_type']
    metadata_version = metadata['version']

    if not method_name or not isinstance(method_name, str):
        raise ValueError("Method name must be a non-empty string")

    if len(method_name) > 100:
        raise ValueError("Method name too long (max 100 characters)")

    # Only allow alphanumeric, underscore, and dash (not at start).
    if not re.match(r'^[a-zA-Z0-9_][a-zA-Z0-9_-]*$', method_name):
        raise ValueError(
            "Method name contains invalid characters. Only letters, numbers, "
            "underscores, and dashes allowed. Please rename the method."
        )

    if intr_type not in ['rad-tan', 'mei']:
        raise ValueError(
            "Intrinsics type must be either 'rad-tan' or 'mei'. "
            "Please email influxbenchmark@gmail.com if your method uses a "
            "different intrinsics model."
        )

    if metadata_version not in ['influx', 'influx_pp_real', 'all']:
        raise ValueError(
            "submission_metadata.version must be 'influx', 'influx_pp_real', or 'all'"
        )

    if metadata_version != version:
        raise ValueError(
            f"Version in submission metadata '{metadata_version}' does not "
            f"match requested version '{version}'"
        )

    required_videos = load_required_test_videos(
        version,
        influx_split_json_path,
        influx_pp_real_split_json_path,
    )

    if intr_type == 'rad-tan':
        required_keys = ['fx', 'fy', 'cx', 'cy', 'k1', 'k2', 'p1', 'p2']
    else:
        required_keys = ['fx', 'fy', 'cx', 'cy', 'xi']

    for video, num_frames in required_videos.items():
        if video not in submission:
            raise ValueError(
                f"Submission is missing data for test video: {video}"
            )

        video_data = submission[video]
        if not isinstance(video_data, dict):
            raise ValueError(
                f"Submission data for video {video} must be a JSON object"
            )

        for frame_idx in range(num_frames):
            frame_key = str(frame_idx)
            if frame_key not in video_data:
                raise ValueError(
                    f"Submission is missing data for frame {frame_idx} "
                    f"of video {video}"
                )

            frame_data = video_data[frame_key]
            if not isinstance(frame_data, dict):
                raise ValueError(
                    f"Frame {frame_idx} of video {video} must be a JSON object"
                )

            for key in required_keys:
                if key not in frame_data:
                    raise ValueError(
                        f"Missing key '{key}' in frame {frame_idx} "
                        f"of video {video}"
                    )

                value = frame_data[key]
                if value is None:
                    continue

                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError(
                        f"Invalid type for '{key}' in frame {frame_idx} "
                        f"of video {video}: {value}"
                    )

                try:
                    numeric_value = float(value)
                except (OverflowError, TypeError, ValueError) as exc:
                    raise ValueError(
                        f"Value for '{key}' in frame {frame_idx} of video "
                        f"{video} cannot be represented as float64: {value}"
                    ) from exc

                if not math.isfinite(numeric_value):
                    raise ValueError(
                        f"Non-finite value for '{key}' in frame {frame_idx} "
                        f"of video {video}: {value}"
                    )

    # Extra videos, frames, and parameters are intentionally ignored.

    # Check that supplied method name matches submission metadata.
    if method_name != submission_method_name:
        raise ValueError(
            f"Method name in submission metadata '{method_name}' does not "
            f"match passed in submission method name '{submission_method_name}'"
        )

    print("Submission file is valid.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--website",
        default=DEFAULT_WEBSITE,
        help=f"Submission website (default: {DEFAULT_WEBSITE})",
    )
    parser.add_argument(
        "--email",
        help="Email address to send verification code to",
        required=True,
    )
    parser.add_argument(
        "--path",
        help="Path to submission JSON",
        required=True,
    )
    parser.add_argument(
        "--method_name",
        "--method-name",
        dest="method_name",
        help="Method name that will be displayed in the leaderboard",
        default='my_submission',
    )
    parser.add_argument(
        "--version",
        choices=['influx', 'influx_pp_real', 'all'],
        required=True,
        help="Benchmark version for this submission: influx, influx_pp_real, or all",
    )
    parser.add_argument(
        "--influx-split-json-path",
        default=str(DEFAULT_INFLUX_SPLIT_JSON_PATH),
        help=(
            "Path to the influx split JSON file "
            f"(default: {DEFAULT_INFLUX_SPLIT_JSON_PATH})"
        ),
    )
    parser.add_argument(
        "--influx-pp-real-split-json-path",
        default=str(DEFAULT_INFLUX_PP_REAL_SPLIT_JSON_PATH),
        help=(
            "Path to the influx_pp_real split JSON file "
            f"(default: {DEFAULT_INFLUX_PP_REAL_SPLIT_JSON_PATH})"
        ),
    )

    args = parser.parse_args()
    upload_path = args.path

    for path in get_selected_split_paths(
        args.version,
        args.influx_split_json_path,
        args.influx_pp_real_split_json_path,
    ):
        if not path.is_file():
            parser.error(f"Split JSON file not found: {path}")

    check_submission_validity(
        upload_path,
        args.method_name,
        args.version,
        args.influx_split_json_path,
        args.influx_pp_real_split_json_path,
    )

    initialize_session(args.website)
    upload_id = request_verification(args)

    if upload_id:
        code = input(
            "Please enter the verification code sent to your email: "
        )

        if verify_code(upload_id, code):
            upload_file(upload_id, upload_path)
        else:
            print("Verification failed. Upload not allowed.")


if __name__ == "__main__":
    main()

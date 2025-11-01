import requests
import argparse
from requests_toolbelt.multipart.encoder import MultipartEncoder, MultipartEncoderMonitor
from tqdm import tqdm
import os
import json
import re

website = 'https://influx.cs.princeton.edu'

MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB
MAX_JSON_DEPTH = 10

session = requests.Session()    
response = session.get(f'{website}/request_submit/')
csrf_token = session.cookies.get('csrftoken')
headers = {
    'X-CSRFToken': csrf_token,
    'Referer': f'{website}/request_submit/'
}

def request_verification(args, url=f"{website}/request_submit/"):
    data = {
        'email': args.email,
        'method_name': args.method_name,
    }

    response = session.post(url, data=data, headers=headers)

    if response.status_code == 200:
        upload_id = response.json()['upload_id']
        print(f"Verification code sent to {args.email}.")
        print(f"Your submission id is {upload_id}.")
        return upload_id
    else:
        print("Failed to request verification:", response.text)
        exit(1)

def verify_code(upload_id, code, url=f"{website}/verify"):
    data = {
        'code': code,
    }
    response = session.post(f"{url}/{upload_id}/", data=data, headers=headers)
    if response.status_code == 200:
        return True
    else:
        print(response)
        exit(1)

def check_json_depth(obj, current_depth=0, max_depth=MAX_JSON_DEPTH):
    """Recursively check JSON depth to prevent deeply nested attacks."""
    if current_depth > max_depth:
        raise ValueError(f"JSON is too deeply nested (max depth: {max_depth})")
    
    if isinstance(obj, dict):
        for value in obj.values():
            check_json_depth(value, current_depth + 1, max_depth)
    elif isinstance(obj, list):
        for item in obj:
            check_json_depth(item, current_depth + 1, max_depth)

def upload_file(upload_id, file_path, url=f"{website}/upload"):
    # Check that file_path points to one JSON file
    if not os.path.isfile(file_path):
        raise ValueError(f"{file_path} is not a valid file path.")
    if not file_path.endswith(".json"):
        raise ValueError("Only JSON files are allowed.")

    total_size = os.path.getsize(file_path)
    if total_size > MAX_FILE_SIZE:
        raise ValueError(f"File size ({total_size} bytes) exceeds maximum allowed size ({MAX_FILE_SIZE} bytes)")

    progress_bar = tqdm(total=total_size, unit='B', unit_scale=True, desc="Uploading")

    def progress_callback(monitor):
        progress_bar.update(monitor.bytes_read - progress_bar.n)

    with open(file_path, 'rb') as f:
        encoder = MultipartEncoder(
            fields={'file': (os.path.basename(file_path), f, 'application/json')}
        )
        monitor = MultipartEncoderMonitor(encoder, progress_callback)
        new_headers = headers.copy()
        new_headers['Content-Type'] = monitor.content_type

        response = session.post(f"{url}/{upload_id}/", data=monitor, headers=new_headers)
        progress_bar.close()

        if response.status_code != 200:
            print("Failed to upload file:", response.text)
            raise SystemExit(1)
        else:
            print("File uploaded successfully.")

    # Finish upload
    response = session.post(f"{website}/finish_upload/{upload_id}/", headers=headers)
    if response.status_code != 200:
        print("Failed to finish upload:", response.text)
        raise SystemExit(1)
    else:
        print("Successfully uploaded your submission. Evaluation will start soon and results will be sent to your email.")


def check_submission_validity(submission_file_path, submission_method_name, path_to_split_json='influx_data/dataset/video_frame_count_and_split.json'):
    json_name = os.path.basename(submission_file_path)
    
    if not re.match(r'^[a-zA-Z0-9_][a-zA-Z0-9_.-]*\.json$', json_name):
        raise ValueError("Filename contains invalid characters. Only letters, numbers, underscores, dots, and dashes allowed.")

    file_size = os.path.getsize(submission_file_path)
    if file_size > MAX_FILE_SIZE:
        raise ValueError(f"Submission file is too large ({file_size} bytes). Maximum size is {MAX_FILE_SIZE} bytes.")

    if not os.path.isfile(path_to_split_json):
        raise ValueError(f"Split JSON file not found: {path_to_split_json}")

    with open(submission_file_path, 'r') as f:
        submission = json.load(f) 

    check_json_depth(submission)

    if 'submission_metadata' not in submission:
        raise ValueError("Submission is missing 'submission_metadata' key")

    method_name = submission['submission_metadata']['method_name']
    intr_type = submission['submission_metadata']['intrinsics_type']

    if not method_name or not isinstance(method_name, str):
        raise ValueError("Method name must be a non-empty string")
    
    if len(method_name) > 100:
        raise ValueError("Method name too long (max 100 characters)")
    
    # Only allow alphanumeric, underscore, and dash (not at start)
    if not re.match(r'^[a-zA-Z0-9_][a-zA-Z0-9_-]*$', method_name):
        raise ValueError("Method name contains invalid characters. Only letters, numbers, underscores, and dashes allowed. Please rename the method.")

    if intr_type not in ['rad-tan', 'mei']:
        raise ValueError("Intrinsics type must be either 'rad-tan' or 'mei'. Please email influxbenchmark@gmail.com if your method uses a different intrinsics model.")

    with open(path_to_split_json, 'r') as f:
        split_info = json.load(f)

    for video, info in split_info.items():
        if info['split'] == 'test':
            if video not in submission:
                raise ValueError(f"Submission is missing data for test video: {video}")

            num_frames = info['frame_count']
            video_data = submission[video]

            for frame_idx in range(num_frames):
                frame_key = str(frame_idx)
                if frame_key not in video_data:
                    raise ValueError(f"Submission is missing data for frame {frame_idx} of video {video}")

                frame_data = video_data[frame_key]
                if intr_type == 'rad-tan':
                    required_keys = ['fx', 'fy', 'cx', 'cy', 'k1', 'k2', 'p1', 'p2']
                elif intr_type == 'mei':
                    required_keys = ['fx', 'fy', 'cx', 'cy', 'xi']

                for key in required_keys:
                    if key not in frame_data:
                        raise ValueError(f"Missing key '{key}' in frame {frame_idx} of video {video}")

                    value = frame_data[key]
                    if not (isinstance(value, (int, float)) or value is None):
                        raise ValueError(f"Invalid type for '{key}' in frame {frame_idx} of video {video}: {value}")
                    if key in ['fx', 'fy', 'cx', 'cy'] and value < 0:
                        raise ValueError(f"Negative value for '{key}' in frame {frame_idx} of video {video}: {value}")

    # Check that supplied method name matches submission metadata
    if submission['submission_metadata']['method_name'] != submission_method_name:
        raise ValueError(f"Method name in submission metadata \'{submission['submission_metadata']['method_name']}\' does not match passed in submission method name \'{submission_method_name}\'")
    
    print("Submission file is valid.")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", help="Email address to send verification code to", required=True)
    parser.add_argument("--path", help="Path to submission json", required=True)
    parser.add_argument("--method_name", help="Method name that will be displayed in the leaderboard", default='my_submission')
    parser.add_argument("--split-json-path", help="Path to the split JSON file (default: influx_data/dataset/video_frame_count_and_split.json)", default='influx_data/dataset/video_frame_count_and_split.json')
                        
    args = parser.parse_args()
    
    upload_path = args.path

    check_submission_validity(upload_path, args.method_name, args.split_json_path)

    upload_id = request_verification(args)

    if upload_id:
        code = input("Please enter the verification code sent to your email: ")

        if verify_code(upload_id, code):
            upload_file(upload_id, upload_path)
        else:
            print("Verification failed. Upload not allowed.")

if __name__ == "__main__":
    main()
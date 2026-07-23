#!/usr/bin/env python3
"""Validate and upload an InFlux benchmark submission.

The client performs the same strict local payload checks as the server before
requesting a verification email. Network and HTTP failures are translated into
bounded, actionable messages rather than dumping HTML error pages.
"""

from __future__ import annotations

import argparse
import html
import json
import math
import os
import re
import sys
import time
import traceback
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import requests
from requests_toolbelt.multipart.encoder import (
    MultipartEncoder,
    MultipartEncoderMonitor,
)
from tqdm import tqdm


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parent.parent

DEFAULT_INFLUX_SPLIT_JSON_PATH = (
    REPO_ROOT
    / "influx_real_data"
    / "influx"
    / "video_frame_count_and_split_v1.json"
)
DEFAULT_INFLUX_PP_REAL_SPLIT_JSON_PATH = (
    REPO_ROOT
    / "influx_real_data"
    / "influx_pp_real"
    / "video_frame_count_and_split_v2.json"
)

DEFAULT_WEBSITE = "https://influx.cs.princeton.edu"
MAX_FILE_SIZE = 200 * 1024 * 1024  # 200 MiB
MAX_JSON_DEPTH = 10
REQUEST_TIMEOUT_SECONDS = 60
UPLOAD_TIMEOUT_SECONDS = 15 * 60
MAX_ERROR_DETAIL_CHARS = 320
MAX_VALIDATION_DETAIL_ITEMS = 8
SUPPORT_EMAIL = "influxbenchmark@gmail.com"
CSRF_COOKIE_NAMES = ("csrftoken", "influx_dev_csrftoken")

website = DEFAULT_WEBSITE
session: requests.Session | None = None
headers: dict[str, str] | None = None
verbose = False


class UploadSubmissionError(RuntimeError):
    """Expected, user-facing upload-client failure."""


STAGE_BOOTSTRAP = "bootstrap"
STAGE_REQUEST = "request_verification"
STAGE_VERIFY = "verify_code"
STAGE_UPLOAD = "upload_file"
STAGE_FINISH = "finish_upload"
STAGE_STATUS = "submission_status"


def human_bytes(value: int) -> str:
    number = float(value)
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    for unit in units:
        if number < 1024.0 or unit == units[-1]:
            if unit == "B":
                return f"{int(number)} {unit}"
            return f"{number:.2f} {unit}"
        number /= 1024.0
    return f"{value} B"


def compact_response_text(
    value: str,
    *,
    limit: int = MAX_ERROR_DETAIL_CHARS,
) -> str:
    """Convert HTML/plain response content into a bounded one-line summary."""

    text = html.unescape(value or "")
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = " ".join(text.split())
    if len(text) > limit:
        return text[: limit - 1].rstrip() + "…"
    return text


def response_json_or_none(
    response: requests.Response,
) -> dict[str, Any] | None:
    try:
        payload = response.json()
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def server_error_detail(response: requests.Response) -> str | None:
    payload = response_json_or_none(response)
    if payload is not None:
        for key in ("error", "message", "detail"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    detail = compact_response_text(response.text)
    return detail or None


def _collect_validation_messages(
    value: Any,
    *,
    path: str = "validation",
    output: list[str] | None = None,
) -> list[str]:
    """Best-effort extraction of useful messages from a server report."""

    if output is None:
        output = []
    if len(output) >= MAX_VALIDATION_DETAIL_ITEMS:
        return output

    if isinstance(value, str):
        text = " ".join(value.split())
        if text:
            output.append(f"{path}: {text}")
        return output

    if isinstance(value, list):
        for index, item in enumerate(value):
            _collect_validation_messages(
                item,
                path=f"{path}[{index}]",
                output=output,
            )
            if len(output) >= MAX_VALIDATION_DETAIL_ITEMS:
                break
        return output

    if isinstance(value, dict):
        # Prefer likely issue containers before counters and metadata.
        preferred = (
            "errors",
            "error",
            "issues",
            "items",
            "messages",
            "missing",
            "invalid",
        )
        keys = list(value)
        ordered = [key for key in preferred if key in value]
        ordered.extend(key for key in keys if key not in ordered)
        for key in ordered:
            child = value[key]
            if key in {"count", "valid", "is_valid"}:
                continue
            _collect_validation_messages(
                child,
                path=f"{path}.{key}",
                output=output,
            )
            if len(output) >= MAX_VALIDATION_DETAIL_ITEMS:
                break
    return output


def validation_detail(response: requests.Response) -> str | None:
    payload = response_json_or_none(response)
    if payload is None or "validation" not in payload:
        return None
    messages = _collect_validation_messages(payload["validation"])
    if not messages:
        return None
    return " | ".join(messages)


def stage_label(stage: str) -> str:
    return {
        STAGE_BOOTSTRAP: "loading the InFlux submission page",
        STAGE_REQUEST: "requesting a verification code",
        STAGE_VERIFY: "verifying the code",
        STAGE_UPLOAD: "uploading the JSON file",
        STAGE_FINISH: "queueing the validated submission",
        STAGE_STATUS: "checking submission status",
    }.get(stage, "contacting InFlux")


def friendly_http_error(
    response: requests.Response,
    *,
    stage: str,
    website_url: str,
    upload_id: str | None = None,
) -> UploadSubmissionError:
    status = int(response.status_code)
    detail = server_error_detail(response)
    validation = validation_detail(response)
    identifier = upload_id or "the submission"

    if status == 400:
        if stage == STAGE_VERIFY:
            message = "The verification code was not accepted."
            payload = response_json_or_none(response) or {}
            remaining = payload.get("attempts_remaining")
            if isinstance(remaining, int):
                message += f" Attempts remaining: {remaining}."
        elif stage == STAGE_UPLOAD:
            message = (
                "The server rejected the uploaded JSON. Local validation passed, "
                "so review the server detail below for a stricter runtime check."
            )
        else:
            message = "The server rejected the request."
    elif status == 401:
        message = "The InFlux service rejected authentication for this request."
    elif status == 403:
        if stage in {STAGE_UPLOAD, STAGE_FINISH, STAGE_STATUS}:
            message = (
                "This client session is no longer authorized for the submission. "
                "Rerun the command to request and verify a new submission."
            )
        else:
            message = "The InFlux service refused this request."
    elif status == 404:
        if stage == STAGE_BOOTSTRAP:
            message = (
                f"The submission page was not found at {website_url!r}. Check "
                "--website and pass the site root, not an endpoint path."
            )
        else:
            message = (
                f"Submission {identifier} or the requested endpoint was not found. "
                "Check --website and the submission ID."
            )
    elif status == 409:
        if stage == STAGE_UPLOAD:
            message = (
                "The submission is already queued or is otherwise no longer "
                "replaceable. Do not create a duplicate until its current state is "
                "understood."
            )
        elif stage == STAGE_FINISH:
            message = (
                "The server could not queue the submission from its current state. "
                "The file may not have been committed, or it may already be queued."
            )
        else:
            message = "The request conflicts with the submission's current state."
    elif status == 410:
        message = (
            "The verification code has expired. Rerun the command to create a new "
            "submission and request a fresh code."
        )
    elif status == 413:
        message = (
            f"The server rejected the file as too large. This client allows at most "
            f"{human_bytes(MAX_FILE_SIZE)}. Confirm that client and server limits "
            "match, or upload a compact JSON representation."
        )
    elif status == 429:
        payload = response_json_or_none(response) or {}
        if payload.get("code") == "SUBMISSION_RATE_LIMIT":
            limit = payload.get("limit")
            window_days = payload.get("window_days")
            next_eligible_at = payload.get("next_eligible_at")
            support_email = payload.get("support_email") or SUPPORT_EMAIL
            if isinstance(limit, int) and isinstance(window_days, int):
                message = (
                    f"This email address has reached the InFlux limit of {limit} "
                    f"queued submissions in a rolling {window_days}-day window."
                )
            else:
                message = "This email address has reached the InFlux submission limit."
            if isinstance(next_eligible_at, str) and next_eligible_at.strip():
                message += (
                    " The next submission may be queued after "
                    f"{next_eligible_at.strip()}."
                )
            message += (
                " Keep the existing submission IDs and do not create duplicates. "
                f"If this seems incorrect, email {support_email}."
            )
        else:
            message = (
                "Too many verification attempts or requests were made. Wait "
                "briefly, then rerun the command for a fresh submission."
            )
    elif status == 503:
        message = (
            "The InFlux submission service is temporarily unavailable or in "
            f"maintenance while {stage_label(stage)}. No successful queueing was "
            "confirmed by this client."
        )
    elif status >= 500:
        message = (
            "The InFlux service encountered a server-side problem while "
            f"{stage_label(stage)}. No successful queueing was confirmed by this "
            "client."
        )
    else:
        message = f"The server returned HTTP {status} while {stage_label(stage)}."

    additions: list[str] = []
    if detail and detail.casefold() not in message.casefold():
        additions.append(f"Server detail: {detail}")
    if validation:
        additions.append(f"Validation detail: {validation}")
    if additions:
        message += " " + " ".join(additions)
    return UploadSubmissionError(message)


def validate_website(value: str) -> str:
    if value != value.strip():
        raise UploadSubmissionError(
            "--website contains leading or trailing whitespace."
        )
    parsed = urlsplit(value)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise UploadSubmissionError(
            "--website must be an absolute http or https URL, for example "
            f"{DEFAULT_WEBSITE!r}."
        )
    if parsed.username or parsed.password:
        raise UploadSubmissionError(
            "--website must not embed a username or password."
        )
    if parsed.query or parsed.fragment:
        raise UploadSubmissionError(
            "--website must be the site root and must not include a query or fragment."
        )
    path = parsed.path.rstrip("/")
    if path:
        raise UploadSubmissionError(
            "--website must point to the site root, not an endpoint path. "
            f"Received path {parsed.path!r}."
        )
    return value.rstrip("/")


def validate_email_argument(value: str) -> str:
    if value != value.strip():
        raise UploadSubmissionError(
            "--email contains leading or trailing whitespace."
        )
    if any(character.isspace() or ord(character) < 32 for character in value):
        raise UploadSubmissionError("--email must not contain whitespace.")
    if value.count("@") != 1:
        raise UploadSubmissionError(
            "--email must contain one @ separator."
        )
    local, domain = value.rsplit("@", 1)
    if not local or not domain or "." not in domain:
        raise UploadSubmissionError(
            "--email does not look like a complete email address."
        )
    return value


def csrf_token_from_session(item: requests.Session) -> str | None:
    for cookie in item.cookies:
        if cookie.name in CSRF_COOKIE_NAMES and cookie.value:
            return str(cookie.value)
    return None


def request_with_friendly_errors(
    item: requests.Session,
    method: str,
    url: str,
    *,
    stage: str,
    data: Any = None,
    request_headers: dict[str, str] | None = None,
    timeout_seconds: int = REQUEST_TIMEOUT_SECONDS,
    upload_id: str | None = None,
) -> requests.Response:
    if verbose:
        print(f"[verbose] {method} {url}", file=sys.stderr)
    try:
        response = item.request(
            method,
            url,
            data=data,
            headers=request_headers,
            timeout=timeout_seconds,
        )
    except requests.Timeout as exc:
        ambiguity = (
            " Because the request may have reached the server, do not assume it "
            "failed safely. Check the submission state before creating a duplicate."
            if stage in {STAGE_UPLOAD, STAGE_FINISH}
            else ""
        )
        raise UploadSubmissionError(
            f"Timed out after {timeout_seconds} seconds while "
            f"{stage_label(stage)}.{ambiguity}"
        ) from exc
    except requests.exceptions.SSLError as exc:
        raise UploadSubmissionError(
            f"TLS certificate verification failed while {stage_label(stage)}. "
            "Check --website and the local certificate configuration."
        ) from exc
    except requests.ConnectionError as exc:
        ambiguity = (
            " The server may still have received some or all of the request; check "
            "the submission state before creating a duplicate."
            if stage in {STAGE_UPLOAD, STAGE_FINISH}
            else ""
        )
        raise UploadSubmissionError(
            f"Could not connect to {website!r} while {stage_label(stage)}. Check "
            f"network access, DNS, and --website.{ambiguity}"
        ) from exc
    except requests.RequestException as exc:
        raise UploadSubmissionError(
            f"Network request failed while {stage_label(stage)}: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    if verbose:
        summary = compact_response_text(response.text, limit=180)
        print(
            f"[verbose] HTTP {response.status_code}"
            + (f" — {summary}" if summary else ""),
            file=sys.stderr,
        )
    if response.status_code >= 400:
        raise friendly_http_error(
            response,
            stage=stage,
            website_url=website,
            upload_id=upload_id,
        )
    return response


def require_json_object(
    response: requests.Response,
    *,
    stage: str,
) -> dict[str, Any]:
    payload = response_json_or_none(response)
    if payload is None:
        detail = compact_response_text(response.text)
        suffix = f" Response summary: {detail}" if detail else ""
        raise UploadSubmissionError(
            "The server returned an unexpected non-JSON success response while "
            f"{stage_label(stage)}.{suffix}"
        )
    return payload


def initialize_session(website_url: str) -> None:
    global website, session, headers

    website = validate_website(website_url)
    session = requests.Session()

    response = request_with_friendly_errors(
        session,
        "GET",
        f"{website}/request_submit/",
        stage=STAGE_BOOTSTRAP,
    )
    csrf_token = csrf_token_from_session(session)
    if not csrf_token:
        raise UploadSubmissionError(
            "The submission page loaded, but no recognized CSRF cookie was set. "
            "The website may be misconfigured or an intermediary may have removed "
            "cookies."
        )

    headers = {
        "X-CSRFToken": csrf_token,
        "Referer": f"{website}/request_submit/",
    }
    if verbose:
        print(
            f"[verbose] submission page ready; CSRF cookie acquired; "
            f"content-type={response.headers.get('content-type', '<unknown>')}",
            file=sys.stderr,
        )


def _require_runtime_session() -> tuple[requests.Session, dict[str, str]]:
    if session is None or headers is None:
        raise UploadSubmissionError("The upload session was not initialized.")
    return session, headers


def request_verification(args: argparse.Namespace, url: str | None = None) -> str:
    item, request_headers = _require_runtime_session()
    if url is None:
        url = f"{website}/request_submit/"

    response = request_with_friendly_errors(
        item,
        "POST",
        url,
        stage=STAGE_REQUEST,
        data={
            "email": args.email,
            "method_name": args.method_name,
            "version": args.version,
        },
        request_headers=request_headers,
    )
    payload = require_json_object(response, stage=STAGE_REQUEST)
    upload_id = payload.get("upload_id")
    try:
        upload_id = str(UUID(str(upload_id)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise UploadSubmissionError(
            "The server reported success but did not return a valid submission UUID."
        ) from exc

    print(f"Verification code sent to {args.email}.")
    print(f"Your submission id is {upload_id}.")
    return upload_id


def verify_code(upload_id: str, code: str, url: str | None = None) -> bool:
    item, request_headers = _require_runtime_session()
    code = code.strip()
    if not re.fullmatch(r"\d{6}", code):
        raise UploadSubmissionError(
            "Verification code must contain exactly six digits. No verification "
            "request was sent."
        )
    if url is None:
        url = f"{website}/verify"

    response = request_with_friendly_errors(
        item,
        "POST",
        f"{url}/{upload_id}/",
        stage=STAGE_VERIFY,
        data={"code": code},
        request_headers=request_headers,
        upload_id=upload_id,
    )
    require_json_object(response, stage=STAGE_VERIFY)
    print("Verification successful.")
    return True


def check_json_depth(
    obj: Any,
    current_depth: int = 0,
    max_depth: int = MAX_JSON_DEPTH,
) -> None:
    """Recursively check JSON depth to prevent deeply nested inputs."""

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


def get_selected_split_paths(
    version: str,
    influx_split_json_path: str | os.PathLike[str],
    influx_pp_real_split_json_path: str | os.PathLike[str],
) -> list[Path]:
    if version == "influx":
        return [Path(influx_split_json_path)]
    if version == "influx_pp_real":
        return [Path(influx_pp_real_split_json_path)]
    if version == "all":
        return [
            Path(influx_split_json_path),
            Path(influx_pp_real_split_json_path),
        ]
    raise ValueError(f"Unsupported version: {version}")


def _load_standard_json(path: Path) -> Any:
    def reject_constant(value: str) -> None:
        raise ValueError(f"Non-standard JSON constant is not allowed: {value}")

    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle, parse_constant=reject_constant)
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"{path} is not valid UTF-8 JSON: {exc}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{path} is not valid JSON at line {exc.lineno}, column "
            f"{exc.colno}: {exc.msg}"
        ) from exc


def load_required_test_videos(
    version: str,
    influx_split_json_path: str | os.PathLike[str],
    influx_pp_real_split_json_path: str | os.PathLike[str],
) -> dict[str, int]:
    required_videos: dict[str, int] = {}

    for path_to_split_json in get_selected_split_paths(
        version,
        influx_split_json_path,
        influx_pp_real_split_json_path,
    ):
        if not path_to_split_json.is_file():
            raise ValueError(f"Split JSON file not found: {path_to_split_json}")
        split_info = _load_standard_json(path_to_split_json)
        if not isinstance(split_info, dict):
            raise ValueError(
                f"Split JSON root must be an object: {path_to_split_json}"
            )

        for video, info in split_info.items():
            if not isinstance(video, str) or not video:
                raise ValueError(
                    f"Split JSON contains an invalid video identifier: "
                    f"{path_to_split_json}"
                )
            if not isinstance(info, dict):
                raise ValueError(
                    f"Split metadata for {video!r} must be an object in "
                    f"{path_to_split_json}"
                )
            split = info.get("split")
            frame_count = info.get("frame_count")
            if split not in {"test", "val"}:
                raise ValueError(
                    f"Split metadata for {video!r} has unsupported split "
                    f"{split!r} in {path_to_split_json}"
                )
            if (
                isinstance(frame_count, bool)
                or not isinstance(frame_count, int)
                or frame_count < 0
            ):
                raise ValueError(
                    f"Split metadata for {video!r} has invalid frame_count "
                    f"{frame_count!r} in {path_to_split_json}"
                )
            if split != "test":
                continue
            if video in required_videos:
                raise ValueError(
                    f"Video {video!r} appears in more than one selected split "
                    "JSON file"
                )
            required_videos[video] = frame_count

    if not required_videos:
        raise ValueError("Selected split JSON files contain no test videos")
    return required_videos


def check_submission_validity(
    submission_file_path: str | os.PathLike[str],
    submission_method_name: str,
    version: str,
    influx_split_json_path: str | os.PathLike[str],
    influx_pp_real_split_json_path: str | os.PathLike[str],
) -> None:
    path = Path(submission_file_path)
    if not path.is_file():
        raise ValueError(f"Submission JSON file not found: {path}")

    json_name = path.name
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*\.json", json_name):
        raise ValueError(
            "Filename must end in .json and may contain only letters, numbers, "
            "underscores, dots, and dashes."
        )

    file_size = path.stat().st_size
    if file_size > MAX_FILE_SIZE:
        raise ValueError(
            f"Submission file is {human_bytes(file_size)}, exceeding the "
            f"{human_bytes(MAX_FILE_SIZE)} client limit. Compact JSON is accepted; "
            "whitespace is not required."
        )
    if file_size == 0:
        raise ValueError("Submission JSON file is empty")

    submission = _load_standard_json(path)
    check_json_depth(submission)
    if not isinstance(submission, dict):
        raise ValueError("Submission JSON root must be an object")

    metadata = submission.get("submission_metadata")
    if not isinstance(metadata, dict):
        raise ValueError(
            "Submission must contain a 'submission_metadata' JSON object"
        )
    for key in ("method_name", "intrinsics_type", "version"):
        if key not in metadata:
            raise ValueError(f"submission_metadata is missing {key!r}")

    method_name = metadata["method_name"]
    intr_type = metadata["intrinsics_type"]
    metadata_version = metadata["version"]

    if not isinstance(method_name, str) or not method_name:
        raise ValueError("submission_metadata.method_name must be non-empty text")
    if len(method_name) > 100:
        raise ValueError(
            "submission_metadata.method_name exceeds 100 characters"
        )
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_-]*", method_name):
        raise ValueError(
            "submission_metadata.method_name may contain only letters, numbers, "
            "underscores, and dashes. Use modify_submission.py after evaluation "
            "to set a more presentation-friendly display name."
        )
    if method_name != submission_method_name:
        raise ValueError(
            f"--method-name is {submission_method_name!r}, but "
            f"submission_metadata.method_name is {method_name!r}. The upload-time "
            "name must match exactly."
        )

    if intr_type not in {"rad-tan", "mei"}:
        raise ValueError(
            "submission_metadata.intrinsics_type must be 'rad-tan' or 'mei'. "
            "Email influxbenchmark@gmail.com for another intrinsics model."
        )
    if metadata_version not in {"influx", "influx_pp_real", "all"}:
        raise ValueError(
            "submission_metadata.version must be 'influx', 'influx_pp_real', or "
            "'all'"
        )
    if metadata_version != version:
        raise ValueError(
            f"--version is {version!r}, but submission_metadata.version is "
            f"{metadata_version!r}. They must match exactly."
        )

    required_videos = load_required_test_videos(
        version,
        influx_split_json_path,
        influx_pp_real_split_json_path,
    )
    required_keys = (
        ("fx", "fy", "cx", "cy", "k1", "k2", "p1", "p2")
        if intr_type == "rad-tan"
        else ("fx", "fy", "cx", "cy", "xi")
    )

    checked_frames = 0
    null_values = 0
    for video, num_frames in required_videos.items():
        if video not in submission:
            raise ValueError(f"Submission is missing test video {video!r}")
        video_data = submission[video]
        if not isinstance(video_data, dict):
            raise ValueError(
                f"Submission data for video {video!r} must be an object"
            )

        for frame_idx in range(num_frames):
            frame_key = str(frame_idx)
            if frame_key not in video_data:
                raise ValueError(
                    f"Submission is missing frame {frame_idx} of video {video!r}"
                )
            frame_data = video_data[frame_key]
            if not isinstance(frame_data, dict):
                raise ValueError(
                    f"Frame {frame_idx} of video {video!r} must be an object"
                )

            for key in required_keys:
                if key not in frame_data:
                    raise ValueError(
                        f"Frame {frame_idx} of video {video!r} is missing {key!r}"
                    )
                value = frame_data[key]
                if value is None:
                    null_values += 1
                    continue
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError(
                        f"Frame {frame_idx} of video {video!r} has non-numeric "
                        f"{key!r}: {value!r}"
                    )
                try:
                    numeric_value = float(value)
                except (OverflowError, TypeError, ValueError) as exc:
                    raise ValueError(
                        f"Frame {frame_idx} of video {video!r} has {key!r} that "
                        f"cannot be represented as float64: {value!r}"
                    ) from exc
                if not math.isfinite(numeric_value):
                    raise ValueError(
                        f"Frame {frame_idx} of video {video!r} has non-finite "
                        f"{key!r}: {value!r}"
                    )
            checked_frames += 1

    print("Submission file is valid.")
    if verbose:
        print(
            f"[verbose] local validation: version={version} "
            f"videos={len(required_videos)} frames={checked_frames} "
            f"null_values={null_values} size={human_bytes(file_size)}",
            file=sys.stderr,
        )


def _upload_post(
    upload_id: str,
    file_path: Path,
    *,
    url: str,
) -> dict[str, Any]:
    item, base_headers = _require_runtime_session()
    total_size = file_path.stat().st_size
    progress_bar = tqdm(
        total=total_size,
        unit="B",
        unit_scale=True,
        desc="Uploading",
    )

    def progress_callback(monitor: MultipartEncoderMonitor) -> None:
        progress_bar.update(monitor.bytes_read - progress_bar.n)

    try:
        with file_path.open("rb") as handle:
            encoder = MultipartEncoder(
                fields={
                    "file": (
                        file_path.name,
                        handle,
                        "application/json",
                    )
                }
            )
            monitor = MultipartEncoderMonitor(encoder, progress_callback)
            request_headers = dict(base_headers)
            request_headers["Content-Type"] = monitor.content_type
            response = request_with_friendly_errors(
                item,
                "POST",
                f"{url}/{upload_id}/",
                stage=STAGE_UPLOAD,
                data=monitor,
                request_headers=request_headers,
                timeout_seconds=UPLOAD_TIMEOUT_SECONDS,
                upload_id=upload_id,
            )
    finally:
        progress_bar.close()

    return require_json_object(response, stage=STAGE_UPLOAD)


def get_submission_status(upload_id: str) -> dict[str, Any]:
    item, request_headers = _require_runtime_session()
    response = request_with_friendly_errors(
        item,
        "GET",
        f"{website}/submission/{upload_id}/status/",
        stage=STAGE_STATUS,
        request_headers=request_headers,
        upload_id=upload_id,
    )
    return require_json_object(response, stage=STAGE_STATUS)


def finish_upload(upload_id: str) -> dict[str, Any]:
    item, request_headers = _require_runtime_session()
    last_error: UploadSubmissionError | None = None

    # finish_upload is idempotent. One bounded retry handles a transient reverse
    # proxy or network interruption without creating another submission record.
    for attempt in range(1, 3):
        try:
            response = request_with_friendly_errors(
                item,
                "POST",
                f"{website}/finish_upload/{upload_id}/",
                stage=STAGE_FINISH,
                request_headers=request_headers,
                upload_id=upload_id,
            )
            return require_json_object(response, stage=STAGE_FINISH)
        except UploadSubmissionError as exc:
            last_error = exc
            try:
                status = get_submission_status(upload_id)
            except UploadSubmissionError:
                status = {}
            if status.get("state") == "QUEUED":
                print(
                    "Queueing response was interrupted, but the server reports "
                    "that the submission is QUEUED."
                )
                return status
            if attempt == 1 and status.get("state") == "FILE_RECEIVED":
                print(
                    "Queueing was not confirmed; retrying the idempotent "
                    "finish step once.",
                    file=sys.stderr,
                )
                time.sleep(2)
                continue
            break

    assert last_error is not None
    raise last_error


def upload_file(
    upload_id: str,
    file_path: str | os.PathLike[str],
    url: str | None = None,
) -> None:
    path = Path(file_path)
    if not path.is_file():
        raise UploadSubmissionError(f"Submission JSON file not found: {path}")
    if path.suffix.lower() != ".json":
        raise UploadSubmissionError("Only .json submission files are allowed.")
    total_size = path.stat().st_size
    if total_size > MAX_FILE_SIZE:
        raise UploadSubmissionError(
            f"File is {human_bytes(total_size)}, exceeding the "
            f"{human_bytes(MAX_FILE_SIZE)} client limit."
        )
    if url is None:
        url = f"{website}/upload"

    upload_payload = _upload_post(upload_id, path, url=url)
    print(upload_payload.get("message", "File uploaded successfully."))
    state = upload_payload.get("state")
    if state:
        print(f"Submission state after upload: {state}")

    result = finish_upload(upload_id)
    print(result.get("message", "Submission was queued successfully."))
    if result.get("state"):
        print(f"Submission state: {result['state']}")
    if result.get("needs_cache") is not None and verbose:
        print(
            f"[verbose] needs_cache={result.get('needs_cache')}",
            file=sys.stderr,
        )


def print_evaluation_next_steps(
    upload_id: str,
    *,
    email: str,
    method_name: str,
    version: str,
) -> None:
    """Explain what happens after queueing and how to request support."""

    print()
    print("Your submission is queued for evaluation.")
    print(f"Submission ID: {upload_id}")
    print(f"Evaluation results will be sent to: {email}")
    print(
        "Most submissions receive a result email within a few hours, although "
        "a busy queue or ground-truth cache staging can take longer."
    )
    print(
        "If no result email arrives within 1-2 days, check your spam or junk "
        f"folder, then email {SUPPORT_EMAIL} and include:"
    )
    print(f"  - submission ID: {upload_id}")
    print(f"  - method name: {method_name}")
    print(f"  - benchmark version: {version}")
    print(f"  - submitter email: {email}")
    print(
        "Keep the submission ID. It is the primary identifier for this "
        "evaluation and is needed for support or later publication changes."
    )
    print(
        "Do not create a duplicate submission unless support asks you to; the "
        "existing evaluation may still be queued or running."
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate a prediction JSON locally, verify ownership by email, and "
            "queue it for InFlux evaluation."
        )
    )
    parser.add_argument(
        "--website",
        default=DEFAULT_WEBSITE,
        help=f"Submission website root (default: {DEFAULT_WEBSITE})",
    )
    parser.add_argument(
        "--email",
        help="Email address that receives the verification code",
        required=True,
    )
    parser.add_argument(
        "--path",
        help="Path to the submission JSON",
        required=True,
    )
    parser.add_argument(
        "--method-name",
        dest="method_name",
        help="Exact method_name stored in submission_metadata",
        required=True,
    )
    parser.add_argument(
        "--version",
        choices=["influx", "influx_pp_real", "all"],
        required=True,
        help="Benchmark version: influx, influx_pp_real, or all",
    )
    parser.add_argument(
        "--influx-split-json-path",
        default=str(DEFAULT_INFLUX_SPLIT_JSON_PATH),
        help=(
            "Path to the InFlux split JSON file "
            f"(default: {DEFAULT_INFLUX_SPLIT_JSON_PATH})"
        ),
    )
    parser.add_argument(
        "--influx-pp-real-split-json-path",
        default=str(DEFAULT_INFLUX_PP_REAL_SPLIT_JSON_PATH),
        help=(
            "Path to the InFlux++ Real split JSON file "
            f"(default: {DEFAULT_INFLUX_PP_REAL_SPLIT_JSON_PATH})"
        ),
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print bounded HTTP and validation diagnostics to stderr",
    )
    return parser


def run(args: argparse.Namespace) -> int:
    global verbose
    verbose = bool(args.verbose)

    args.website = validate_website(args.website)
    args.email = validate_email_argument(args.email)
    upload_path = Path(args.path)

    try:
        check_submission_validity(
            upload_path,
            args.method_name,
            args.version,
            args.influx_split_json_path,
            args.influx_pp_real_split_json_path,
        )
    except (OSError, ValueError) as exc:
        raise UploadSubmissionError(f"Local submission validation failed: {exc}") from exc

    initialize_session(args.website)
    upload_id = request_verification(args)
    code = input("Please enter the verification code sent to your email: ")
    verify_code(upload_id, code)
    upload_file(upload_id, upload_path)
    print_evaluation_next_steps(
        upload_id,
        email=args.email,
        method_name=args.method_name,
        version=args.version,
    )
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return run(args)
    except KeyboardInterrupt:
        print("\nCancelled by user. No successful queueing was confirmed.", file=sys.stderr)
        return 130
    except UploadSubmissionError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        if getattr(args, "verbose", False):
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

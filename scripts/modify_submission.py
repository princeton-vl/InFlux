#!/usr/bin/env python3
"""Verify ownership and update an evaluated InFlux submission's publication metadata."""

from __future__ import annotations

import argparse
import getpass
import html
import re
import sys
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import requests


DEFAULT_WEBSITE = "https://influx.cs.princeton.edu"
REQUEST_TIMEOUT_SECONDS = 60
MAX_ERROR_DETAIL_CHARS = 240


class ModifySubmissionError(RuntimeError):
    """Expected, user-facing failure from the modification client."""


CSRF_COOKIE_NAMES = ("csrftoken", "influx_dev_csrftoken")


STAGE_BOOTSTRAP = "bootstrap"
STAGE_REQUEST = "request_challenge"
STAGE_VERIFY = "verify_challenge"
STAGE_UPDATE = "apply_update"


def csrf_token_from_session(session: requests.Session) -> str | None:
    """Return the first recognized Django CSRF cookie without name conflicts."""

    for cookie in session.cookies:
        if cookie.name in CSRF_COOKIE_NAMES and cookie.value:
            return str(cookie.value)
    return None


def compact_response_text(value: str, *, limit: int = MAX_ERROR_DETAIL_CHARS) -> str:
    """Turn an HTML/plain response body into a bounded one-line diagnostic."""

    text = html.unescape(value or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = " ".join(text.split())
    if len(text) > limit:
        return text[: limit - 1].rstrip() + "…"
    return text


def response_json_or_none(response: requests.Response) -> dict[str, Any] | None:
    try:
        payload = response.json()
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def server_error_detail(response: requests.Response) -> str | None:
    payload = response_json_or_none(response)
    if payload is not None:
        error = payload.get("error")
        if isinstance(error, str) and error.strip():
            return error.strip()
        message = payload.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()

    detail = compact_response_text(response.text)
    return detail or None


def stage_label(stage: str) -> str:
    return {
        STAGE_BOOTSTRAP: "loading the InFlux submission page",
        STAGE_REQUEST: "requesting modification verification",
        STAGE_VERIFY: "verifying the modification code",
        STAGE_UPDATE: "applying the submission update",
    }.get(stage, "contacting InFlux")


def friendly_http_error(
    response: requests.Response,
    *,
    stage: str,
    website: str,
    submission_id: str | None = None,
) -> ModifySubmissionError:
    """Translate HTTP/API failures without dumping an HTML error page."""

    status = int(response.status_code)
    detail = server_error_detail(response)
    identifier = submission_id or "the requested submission"

    if status == 400:
        message = "The server rejected the request."
    elif status == 401:
        message = "The modification service rejected authentication."
    elif status == 403:
        if stage == STAGE_REQUEST:
            message = (
                "The server would not start ownership verification. Confirm that "
                "--email exactly matches the original submitter email."
            )
        elif stage == STAGE_VERIFY:
            message = (
                "The verification code was not accepted. Check the six-digit code "
                "and request a new challenge if it has expired."
            )
        else:
            message = (
                "The verified modification session is no longer authorized. Rerun "
                "the command to request a new verification code."
            )
    elif status == 404:
        if stage == STAGE_BOOTSTRAP:
            message = (
                f"The InFlux submission page was not found at {website!r}. Check "
                "--website and make sure it points to the site root."
            )
        elif stage == STAGE_REQUEST:
            message = (
                f"Submission {identifier} was not found at {website}. Check the UUID "
                "and --website. The live record may also have been removed during an "
                "administrative or test-data reset."
            )
        elif stage == STAGE_VERIFY:
            message = (
                "The short-lived modification challenge was not found or is no longer "
                "valid. Rerun the command to request a new verification code."
            )
        else:
            message = (
                f"Submission {identifier} was no longer available when the update was "
                "applied. Check the UUID and rerun ownership verification."
            )
    elif status == 409:
        message = (
            "The submission is not currently in a modifiable state. Publication "
            "metadata can normally be changed only after evaluation is finalized."
        )
    elif status == 410:
        message = (
            "The verification challenge has expired. Rerun the command to request a "
            "new code."
        )
    elif status == 429:
        message = (
            "Too many verification attempts or requests were made. Wait briefly, then "
            "rerun the command to request a new challenge."
        )
    elif status >= 500:
        message = (
            "The InFlux service encountered a temporary server-side problem while "
            f"{stage_label(stage)}. No local retry was attempted."
        )
    else:
        message = (
            f"The server returned HTTP {status} while {stage_label(stage)}."
        )

    if detail and detail.casefold() not in message.casefold():
        message += f" Server detail: {detail}"

    return ModifySubmissionError(message)


def request_with_friendly_errors(
    session: requests.Session,
    method: str,
    url: str,
    *,
    stage: str,
    website: str,
    submission_id: str | None = None,
    data: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> requests.Response:
    try:
        response = session.request(
            method,
            url,
            data=data,
            headers=headers,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.Timeout as exc:
        raise ModifySubmissionError(
            f"Timed out after {REQUEST_TIMEOUT_SECONDS} seconds while "
            f"{stage_label(stage)}. Check connectivity and retry; no update was "
            "confirmed by this client."
        ) from exc
    except requests.exceptions.SSLError as exc:
        raise ModifySubmissionError(
            f"TLS certificate verification failed while {stage_label(stage)}. "
            "Check the --website URL and local certificate configuration."
        ) from exc
    except requests.ConnectionError as exc:
        raise ModifySubmissionError(
            f"Could not connect to {website!r} while {stage_label(stage)}. Check "
            "network access, DNS, and --website."
        ) from exc
    except requests.RequestException as exc:
        raise ModifySubmissionError(
            f"Network request failed while {stage_label(stage)}: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    if response.status_code >= 400:
        raise friendly_http_error(
            response,
            stage=stage,
            website=website,
            submission_id=submission_id,
        )
    return response


def checked_json_post(
    session: requests.Session,
    url: str,
    *,
    data: dict[str, Any],
    headers: dict[str, str],
    stage: str,
    website: str,
    submission_id: str,
) -> dict[str, Any]:
    response = request_with_friendly_errors(
        session,
        "POST",
        url,
        stage=stage,
        website=website,
        submission_id=submission_id,
        data=data,
        headers=headers,
    )
    payload = response_json_or_none(response)
    if payload is None:
        detail = compact_response_text(response.text)
        suffix = f" Response summary: {detail}" if detail else ""
        raise ModifySubmissionError(
            f"The server returned an unexpected non-JSON success response while "
            f"{stage_label(stage)}.{suffix}"
        )
    return payload


def validate_optional_http_url(
    value: str | None,
    *,
    option_name: str,
) -> None:
    """Validate an optional public link before requesting email verification."""

    if value is None or value == "":
        return

    if value != value.strip():
        raise ModifySubmissionError(
            f"{option_name} contains leading or trailing whitespace. "
            "Remove the whitespace and try again. No verification email was requested."
        )

    if any(character.isspace() or ord(character) < 32 for character in value):
        raise ModifySubmissionError(
            f"{option_name} must not contain whitespace or control characters. "
            "No verification email was requested."
        )

    parsed = urlsplit(value)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or not parsed.netloc:
        if not parsed.scheme:
            example = f"https://{value.lstrip('/')}"
            raise ModifySubmissionError(
                f"{option_name} must be an absolute http or https URL. "
                f"Received {value!r}. Add an explicit scheme, for example "
                f"{example!r}. No verification email was requested."
            )
        raise ModifySubmissionError(
            f"{option_name} must be an absolute http or https URL with a host. "
            f"Received {value!r}. No verification email was requested."
        )

    if parsed.username or parsed.password:
        raise ModifySubmissionError(
            f"{option_name} must not embed a username or password. "
            "No verification email was requested."
        )


def validate_website(value: str) -> str:
    if value != value.strip():
        raise ModifySubmissionError("--website contains leading or trailing whitespace.")
    parsed = urlsplit(value)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise ModifySubmissionError(
            "--website must be an absolute http or https URL, for example "
            f"{DEFAULT_WEBSITE!r}."
        )
    if parsed.username or parsed.password:
        raise ModifySubmissionError("--website must not embed credentials.")
    if parsed.query or parsed.fragment:
        raise ModifySubmissionError("--website must not contain a query string or fragment.")
    path = parsed.path.rstrip("/")
    if path:
        raise ModifySubmissionError(
            "--website must point to the site root, without an endpoint path. "
            f"Received path {parsed.path!r}."
        )
    return value.rstrip("/")


def validate_submission_id(value: str) -> str:
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ModifySubmissionError(
            f"--id must be a valid submission UUID. Received {value!r}. "
            "No verification email was requested."
        ) from exc
    return str(parsed)


def validate_email_address(value: str) -> str:
    if value != value.strip():
        raise ModifySubmissionError(
            "--email contains leading or trailing whitespace. "
            "No verification email was requested."
        )
    if any(character.isspace() or ord(character) < 32 for character in value):
        raise ModifySubmissionError(
            "--email must not contain whitespace or control characters. "
            "No verification email was requested."
        )
    if value.count("@") != 1:
        raise ModifySubmissionError(
            f"--email must be a valid address. Received {value!r}. "
            "No verification email was requested."
        )
    local, domain = value.rsplit("@", 1)
    if not local or not domain or domain.startswith(".") or domain.endswith("."):
        raise ModifySubmissionError(
            f"--email must be a valid address. Received {value!r}. "
            "No verification email was requested."
        )
    return value


def validate_optional_display_text(
    value: str | None,
    *,
    option_name: str,
    maximum_length: int,
) -> None:
    if value is None:
        return
    if len(value) > maximum_length:
        raise ModifySubmissionError(
            f"{option_name} is {len(value)} characters long; the maximum is "
            f"{maximum_length}. No verification email was requested."
        )
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ModifySubmissionError(
            f"{option_name} must not contain control characters or newlines. "
            "No verification email was requested."
        )


def validate_verification_code(value: str) -> str:
    if not re.fullmatch(r"\d{6}", value):
        raise ModifySubmissionError(
            "Verification code must contain exactly six digits. Rerun the command "
            "and enter the code from the newest modification email."
        )
    return value


def validate_metadata(args: argparse.Namespace) -> None:
    validate_optional_http_url(
        args.url_publication,
        option_name="--url-publication",
    )
    validate_optional_http_url(
        args.url_code,
        option_name="--url-code",
    )
    validate_optional_display_text(
        args.method_name,
        option_name="--method-name",
        maximum_length=100,
    )
    validate_optional_display_text(
        args.publication,
        option_name="--publication",
        maximum_length=200,
    )


def build_modification_data(args: argparse.Namespace) -> dict[str, Any]:
    data: dict[str, Any] = {}
    if args.method_name is not None:
        data["method_name"] = args.method_name
    if args.publication is not None:
        data["publication"] = args.publication
    if args.url_publication is not None:
        data["url_publication"] = args.url_publication
    if args.url_code is not None:
        data["url_code"] = args.url_code
    if args.publish:
        data["anonymous"] = "false"
    elif args.hide:
        data["anonymous"] = "true"
    return data


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Email-verify ownership of an evaluated InFlux submission, then "
            "update its display metadata or public/private intent."
        )
    )
    parser.add_argument("--id", required=True, help="Submission UUID")
    parser.add_argument(
        "--email",
        required=True,
        help="Exact original submitter email address",
    )
    parser.add_argument(
        "--method-name",
        default=None,
        help=(
            "Public display method name. This does not alter the immutable "
            "method name stored in the submitted JSON. Pass an empty string "
            "to return to the original name."
        ),
    )
    parser.add_argument("--publication", default=None)
    parser.add_argument("--url-publication", default=None)
    parser.add_argument("--url-code", default=None)
    visibility = parser.add_mutually_exclusive_group()
    visibility.add_argument(
        "--publish",
        action="store_true",
        help="Request public leaderboard visibility.",
    )
    visibility.add_argument(
        "--hide",
        action="store_true",
        help="Hide or re-hide the result from the public leaderboard.",
    )
    parser.add_argument(
        "--website",
        default=DEFAULT_WEBSITE,
        help=f"Website base URL (default: {DEFAULT_WEBSITE})",
    )
    parser.add_argument(
        "--code",
        default=None,
        help="Six-digit verification code; omitted means prompt securely.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help=(
            "Show diagnostic details such as endpoint stages and the "
            "short-lived modification challenge ID."
        ),
    )
    args = parser.parse_args()

    args.id = validate_submission_id(args.id)
    args.email = validate_email_address(args.email)
    website = validate_website(args.website)
    validate_metadata(args)
    if args.code is not None:
        args.code = validate_verification_code(args.code.strip())

    modification_data = build_modification_data(args)
    if not modification_data:
        parser.error(
            "Specify at least one metadata option, --publish, or --hide."
        )

    session = requests.Session()

    if args.verbose:
        print(f"Website: {website}")
        print(f"Submission ID: {args.id}")
        print("Stage: bootstrap CSRF session")

    bootstrap = request_with_friendly_errors(
        session,
        "GET",
        f"{website}/request_submit/",
        stage=STAGE_BOOTSTRAP,
        website=website,
        submission_id=args.id,
    )
    del bootstrap

    csrf_token = csrf_token_from_session(session)
    if not csrf_token:
        observed = sorted({cookie.name for cookie in session.cookies})
        observed_text = ", ".join(observed) if observed else "none"
        raise ModifySubmissionError(
            "The website did not set a recognized CSRF cookie. "
            f"Expected one of {CSRF_COOKIE_NAMES!r}; observed: {observed_text}. "
            "Check --website and whether the site is under maintenance."
        )

    headers = {
        "X-CSRFToken": csrf_token,
        "Referer": f"{website}/request_submit/",
        "Accept": "application/json",
    }

    if args.verbose:
        print("Stage: request ownership-verification email")

    challenge = checked_json_post(
        session,
        f"{website}/request_modify/{args.id}/",
        data={"email": args.email},
        headers=headers,
        stage=STAGE_REQUEST,
        website=website,
        submission_id=args.id,
    )
    challenge_id = str(challenge.get("challenge_id") or "")
    try:
        challenge_id = str(UUID(challenge_id))
    except (ValueError, AttributeError) as exc:
        raise ModifySubmissionError(
            "The website did not return a valid modification challenge ID."
        ) from exc

    print(challenge.get("message", "Verification code requested."))
    if args.verbose:
        print(f"Challenge ID: {challenge_id}")

    code = args.code
    if code is None:
        code = validate_verification_code(
            getpass.getpass("Verification code: ").strip()
        )

    if args.verbose:
        print("Stage: verify ownership code")

    verified = checked_json_post(
        session,
        f"{website}/verify_modify/{challenge_id}/",
        data={"code": code},
        headers=headers,
        stage=STAGE_VERIFY,
        website=website,
        submission_id=args.id,
    )
    print(verified.get("message", "Modification verification successful."))

    if args.verbose:
        print("Stage: apply metadata/visibility update")

    updated = checked_json_post(
        session,
        f"{website}/modify/{args.id}/",
        data=modification_data,
        headers=headers,
        stage=STAGE_UPDATE,
        website=website,
        submission_id=args.id,
    )
    print(updated.get("message", "Submission result metadata updated."))
    print(f"Submission ID: {updated.get('submission_id', args.id)}")
    print(f"Display method: {updated.get('display_method_name', '')}")
    print(f"Owner private flag: {updated.get('anonymous')}")
    print(f"Administrator hidden: {updated.get('admin_hidden')}")
    print(f"Publicly visible: {updated.get('public_visible')}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ModifySubmissionError, requests.RequestException) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)

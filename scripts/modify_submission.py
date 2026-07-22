#!/usr/bin/env python3
"""Verify ownership and update an evaluated InFlux submission's publication metadata."""

from __future__ import annotations

import argparse
import getpass
import sys
from typing import Any
from urllib.parse import urlsplit

import requests


DEFAULT_WEBSITE = "https://influx.cs.princeton.edu"
REQUEST_TIMEOUT_SECONDS = 60


class ModifySubmissionError(RuntimeError):
    pass


CSRF_COOKIE_NAMES = ("csrftoken", "influx_dev_csrftoken")


def csrf_token_from_session(session: requests.Session) -> str | None:
    """Return the first recognized Django CSRF cookie without name conflicts."""

    for cookie in session.cookies:
        if cookie.name in CSRF_COOKIE_NAMES and cookie.value:
            return str(cookie.value)
    return None


def response_json(response: requests.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise ModifySubmissionError(
            f"Server returned HTTP {response.status_code} with non-JSON data: "
            f"{response.text[:500]}"
        ) from exc
    if not isinstance(payload, dict):
        raise ModifySubmissionError("Server returned a non-object JSON response.")
    return payload


def checked_post(
    session: requests.Session,
    url: str,
    *,
    data: dict[str, Any],
    headers: dict[str, str],
) -> dict[str, Any]:
    response = session.post(
        url,
        data=data,
        headers=headers,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    payload = response_json(response)
    if response.status_code >= 400:
        raise ModifySubmissionError(
            f"HTTP {response.status_code}: {payload.get('error', payload)}"
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


def validate_metadata_urls(args: argparse.Namespace) -> None:
    validate_optional_http_url(
        args.url_publication,
        option_name="--url-publication",
    )
    validate_optional_http_url(
        args.url_code,
        option_name="--url-code",
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
            "Show diagnostic details such as the short-lived modification "
            "challenge ID."
        ),
    )
    args = parser.parse_args()

    validate_metadata_urls(args)

    modification_data = build_modification_data(args)
    if not modification_data:
        parser.error(
            "Specify at least one metadata option, --publish, or --hide."
        )

    website = args.website.rstrip("/")
    session = requests.Session()

    bootstrap = session.get(
        f"{website}/request_submit/",
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    bootstrap.raise_for_status()
    csrf_token = csrf_token_from_session(session)
    if not csrf_token:
        observed = sorted({cookie.name for cookie in session.cookies})
        observed_text = ", ".join(observed) if observed else "none"
        raise ModifySubmissionError(
            "The website did not set a recognized CSRF cookie. "
            f"Expected one of {CSRF_COOKIE_NAMES!r}; observed: {observed_text}."
        )

    headers = {
        "X-CSRFToken": csrf_token,
        "Referer": f"{website}/request_submit/",
        "Accept": "application/json",
    }

    challenge = checked_post(
        session,
        f"{website}/request_modify/{args.id}/",
        data={"email": args.email},
        headers=headers,
    )
    challenge_id = str(challenge.get("challenge_id") or "")
    if not challenge_id:
        raise ModifySubmissionError(
            "The website did not return a modification challenge ID."
        )
    print(challenge.get("message", "Verification code requested."))
    if args.verbose:
        print(f"Challenge ID: {challenge_id}")

    code = args.code
    if code is None:
        code = getpass.getpass("Verification code: ").strip()

    verified = checked_post(
        session,
        f"{website}/verify_modify/{challenge_id}/",
        data={"code": code},
        headers=headers,
    )
    print(verified.get("message", "Modification verification successful."))

    updated = checked_post(
        session,
        f"{website}/modify/{args.id}/",
        data=modification_data,
        headers=headers,
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

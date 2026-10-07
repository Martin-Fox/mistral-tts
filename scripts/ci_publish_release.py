#!/usr/bin/env python3
"""
CI Release Publisher for Gitea.
Uploads binary release assets (e.g., mistral-tts-windows-x64.zip) to Gitea Releases
via the REST API using Python's standard library (urllib).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any


class GiteaAPIError(Exception):
    """Exception raised when a Gitea REST API request fails."""

    def __init__(self, status_code: int, reason: str, body: str = ""):
        message = f"HTTP {status_code} ({reason}): {body}" if body else f"HTTP {status_code} ({reason})"
        super().__init__(message)
        self.status_code = status_code
        self.reason = reason
        self.body = body


def api_request(
    url: str,
    token: str,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
    timeout: float = 120.0,
) -> tuple[int, Any]:
    """
    Executes an HTTP request against the Gitea API.
    Returns (status_code, parsed_json_or_none).
    """
    req_headers = {
        "Authorization": f"token {token}",
        "Accept": "application/json",
        "User-Agent": "mistral-tts-ci/1.0",
    }
    if headers:
        req_headers.update(headers)

    req = urllib.request.Request(url=url, data=data, headers=req_headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            content = resp.read()
            if content:
                try:
                    return status, json.loads(content.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    return status, content
            return status, None
    except urllib.error.HTTPError as exc:
        err_body = ""
        try:
            err_body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        raise GiteaAPIError(exc.code, exc.reason, err_body) from exc


def determine_release_metadata(ref_name: str, ref_type: str) -> tuple[str, str, bool, str]:
    """
    Determines release tag, title, prerelease flag, and description based on git ref.
    """
    ref_name = ref_name.strip()
    ref_type = ref_type.strip().lower()

    if ref_type == "tag" or ref_name.startswith("v"):
        tag = ref_name if ref_name else "v-preview"
        title = f"Mistral-TTS {tag}"
        is_prerelease = any(p in tag.lower() for p in ["preview", "rc", "beta", "alpha"])
        description = f"Release {tag} of Mistral-TTS Booksmith standalone Windows executable."
    else:
        tag = "v-preview"
        title = "Mistral-TTS Windows Build (Preview)"
        is_prerelease = True
        branch_info = f"branch '{ref_name}'" if ref_name else "latest commit"
        description = (
            f"Automated preview build of Mistral-TTS Booksmith standalone Windows executable ({branch_info})."
        )

    return tag, title, is_prerelease, description


def build_multipart_payload(field_name: str, filename: str, file_bytes: bytes, boundary: str) -> bytes:
    """
    Encodes file bytes into multipart/form-data payload.
    """
    content_type = "application/zip" if filename.lower().endswith(".zip") else "application/octet-stream"
    header = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode("utf-8")
    footer = f"\r\n--{boundary}--\r\n".encode("utf-8")
    return header + file_bytes + footer


def get_or_create_release(
    api_base: str,
    repo: str,
    token: str,
    tag: str,
    title: str,
    is_prerelease: bool,
    description: str,
) -> dict[str, Any]:
    """
    Finds an existing release by tag or creates a new one.
    """
    tag_url = f"{api_base}/repos/{repo}/releases/tags/{urllib.parse.quote(tag)}"
    print(f"[Release] Checking release for tag '{tag}' at {tag_url}...", flush=True)

    try:
        _, release_data = api_request(tag_url, token, method="GET")
        print(f"[Release] Found existing release '{release_data.get('name')}' (ID: {release_data.get('id')}).", flush=True)
        return release_data
    except GiteaAPIError as exc:
        if exc.status_code != 404:
            raise

    # Not found -> Create release
    print(f"[Release] Tag '{tag}' not found. Creating new release '{title}'...", flush=True)
    create_url = f"{api_base}/repos/{repo}/releases"
    payload = {
        "tag_name": tag,
        "name": title,
        "body": description,
        "prerelease": is_prerelease,
        "draft": False,
    }
    json_bytes = json.dumps(payload).encode("utf-8")
    _, release_data = api_request(
        create_url,
        token,
        method="POST",
        headers={"Content-Type": "application/json"},
        data=json_bytes,
    )
    print(f"[Release] Created release successfully (ID: {release_data.get('id')}).", flush=True)
    return release_data


def delete_existing_asset_if_present(
    api_base: str,
    repo: str,
    token: str,
    release_id: int,
    filename: str,
    release_data: dict[str, Any],
) -> None:
    """
    Finds and deletes any existing asset matching filename in the given release.
    """
    assets = release_data.get("assets")
    if assets is None:
        assets_url = f"{api_base}/repos/{repo}/releases/{release_id}/assets"
        _, assets = api_request(assets_url, token, method="GET")

    if not isinstance(assets, list):
        return

    for asset in assets:
        if isinstance(asset, dict) and asset.get("name") == filename:
            asset_id = asset.get("id")
            print(f"[Release] Found existing asset '{filename}' (ID: {asset_id}). Deleting...", flush=True)
            del_url = f"{api_base}/repos/{repo}/releases/{release_id}/assets/{asset_id}"
            api_request(del_url, token, method="DELETE")
            print(f"[Release] Deleted asset ID {asset_id} successfully.", flush=True)


def upload_release_asset(
    api_base: str,
    repo: str,
    token: str,
    release_id: int,
    file_path: str,
) -> dict[str, Any]:
    """
    Uploads file as an attachment to the specified Gitea release.
    """
    filename = os.path.basename(file_path)
    file_size = os.path.getsize(file_path)
    print(f"[Release] Reading {file_path} ({file_size / (1024 * 1024):.2f} MB)...", flush=True)

    with open(file_path, "rb") as f:
        file_bytes = f.read()

    boundary = f"----GiteaReleaseBoundary{uuid.uuid4().hex}"
    payload = build_multipart_payload(field_name="attachment", filename=filename, file_bytes=file_bytes, boundary=boundary)

    upload_url = f"{api_base}/repos/{repo}/releases/{release_id}/assets?name={urllib.parse.quote(filename)}"
    print(f"[Release] Uploading asset to {upload_url}...", flush=True)

    status, resp_data = api_request(
        upload_url,
        token,
        method="POST",
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(payload)),
        },
        data=payload,
        timeout=300.0,
    )
    print(f"[Release] Asset '{filename}' uploaded successfully (Status: {status})!", flush=True)
    return resp_data


def publish_release(
    file_path: str,
    token: str,
    repo: str = "fox/mistral-tts",
    api_base: str = "https://gitea.marcin-lis.pl/api/v1",
    ref_name: str = "",
    ref_type: str = "",
    tag_override: str | None = None,
) -> None:
    """
    Orchestrates the entire release publication process.
    """
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    if not token or not token.strip():
        raise ValueError("Gitea API token is missing or empty.")

    api_base = api_base.rstrip("/")
    if not api_base.endswith("/api/v1"):
        api_base = f"{api_base}/api/v1"

    if tag_override:
        tag = tag_override.strip()
        title = f"Mistral-TTS {tag}"
        is_prerelease = any(p in tag.lower() for p in ["preview", "rc", "beta", "alpha"])
        description = f"Release {tag} of Mistral-TTS Booksmith standalone Windows executable."
    else:
        tag, title, is_prerelease, description = determine_release_metadata(ref_name, ref_type)

    print(f"[Release] Target repository: {repo}", flush=True)
    print(f"[Release] Target tag: {tag} (prerelease: {is_prerelease})", flush=True)
    print(f"[Release] Release title: {title}", flush=True)

    release_data = get_or_create_release(
        api_base=api_base,
        repo=repo,
        token=token,
        tag=tag,
        title=title,
        is_prerelease=is_prerelease,
        description=description,
    )
    release_id = release_data["id"]

    filename = os.path.basename(file_path)
    delete_existing_asset_if_present(
        api_base=api_base,
        repo=repo,
        token=token,
        release_id=release_id,
        filename=filename,
        release_data=release_data,
    )

    upload_release_asset(
        api_base=api_base,
        repo=repo,
        token=token,
        release_id=release_id,
        file_path=file_path,
    )
    print(f"[Release] Successfully published '{filename}' to release '{title}' ({tag}).", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Publish binary assets to Gitea Releases.")
    parser.add_argument("file", help="Path to the binary file / zip archive to upload")
    parser.add_argument("--token", default=None, help="Gitea API token (or GITEA_TOKEN/GITHUB_TOKEN env)")
    parser.add_argument("--repo", default=None, help="Gitea repository 'owner/repo' (default: fox/mistral-tts)")
    parser.add_argument("--api-base", default=None, help="Gitea base URL or API URL (default: https://gitea.marcin-lis.pl)")
    parser.add_argument("--ref-name", default=None, help="Git ref name (or REF_NAME env)")
    parser.add_argument("--ref-type", default=None, help="Git ref type (or REF_TYPE env)")
    parser.add_argument("--tag", default=None, help="Explicit release tag override")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    token = (
        args.token
        or os.getenv("GITEA_TOKEN")
        or os.getenv("GITHUB_TOKEN")
        or ""
    ).strip()

    if not token:
        print("Error: Gitea API token must be provided via --token, GITEA_TOKEN, or GITHUB_TOKEN.", file=sys.stderr)
        sys.exit(1)

    repo = (
        args.repo
        or os.getenv("GITEA_REPO")
        or os.getenv("GITHUB_REPOSITORY")
        or "fox/mistral-tts"
    ).strip()

    api_base = (
        args.api_base
        or os.getenv("GITEA_API_URL")
        or os.getenv("GITEA_BASE_URL")
        or os.getenv("GITEA_SERVER_URL")
        or "https://gitea.marcin-lis.pl"
    ).strip()

    ref_name = (
        args.ref_name
        or os.getenv("REF_NAME")
        or os.getenv("GITHUB_REF_NAME")
        or ""
    ).strip()

    ref_type = (
        args.ref_type
        or os.getenv("REF_TYPE")
        or os.getenv("GITHUB_REF_TYPE")
        or ""
    ).strip()

    try:
        publish_release(
            file_path=args.file,
            token=token,
            repo=repo,
            api_base=api_base,
            ref_name=ref_name,
            ref_type=ref_type,
            tag_override=args.tag,
        )
    except Exception as exc:
        print(f"[Release] Error publishing release: {exc}", file=sys.stderr, flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()

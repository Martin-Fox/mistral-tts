import json
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from scripts.ci_publish_release import (
    GiteaAPIError,
    api_request,
    build_multipart_payload,
    delete_existing_asset_if_present,
    determine_release_metadata,
    get_or_create_release,
    publish_release,
    upload_release_asset,
)


def test_determine_release_metadata():
    # Tag release - stable
    tag, title, prerelease, desc = determine_release_metadata("v1.0.0", "tag")
    assert tag == "v1.0.0"
    assert title == "Mistral-TTS v1.0.0"
    assert prerelease is False
    assert "Release v1.0.0" in desc

    # Tag release - preview / rc
    tag, title, prerelease, desc = determine_release_metadata("v1.1.0-preview", "tag")
    assert tag == "v1.1.0-preview"
    assert prerelease is True

    # Branch release - main
    tag, title, prerelease, desc = determine_release_metadata("main", "branch")
    assert tag == "v-preview"
    assert title == "Mistral-TTS Windows Build (Preview)"
    assert prerelease is True
    assert "branch 'main'" in desc

    # Empty ref
    tag, title, prerelease, desc = determine_release_metadata("", "")
    assert tag == "v-preview"
    assert prerelease is True


def test_build_multipart_payload():
    boundary = "testboundary123"
    filename = "bundle.zip"
    file_bytes = b"PK\x03\x04testdata"

    payload = build_multipart_payload("attachment", filename, file_bytes, boundary)
    assert f"--{boundary}\r\n".encode("utf-8") in payload
    assert b'name="attachment"; filename="bundle.zip"' in payload
    assert b"Content-Type: application/zip" in payload
    assert file_bytes in payload
    assert f"\r\n--{boundary}--\r\n".encode("utf-8") in payload


def test_api_request_success():
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = json.dumps({"id": 42, "name": "v1.0.0"}).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        status, data = api_request("https://test.gitea/api/v1/test", token="token123")
        assert status == 200
        assert data == {"id": 42, "name": "v1.0.0"}


def test_api_request_error():
    mock_fp = MagicMock()
    mock_fp.read.return_value = b'{"message": "not found"}'
    http_err = urllib.error.HTTPError(
        url="https://test.gitea/api/v1/test",
        code=404,
        msg="Not Found",
        hdrs={},  # type: ignore[arg-type]
        fp=mock_fp,
    )

    with patch("urllib.request.urlopen", side_effect=http_err):
        with pytest.raises(GiteaAPIError) as exc_info:
            api_request("https://test.gitea/api/v1/test", token="token123")
        assert exc_info.value.status_code == 404
        assert '{"message": "not found"}' in exc_info.value.body


def test_get_or_create_release_existing():
    with patch("scripts.ci_publish_release.api_request") as mock_req:
        mock_req.return_value = (200, {"id": 99, "name": "Existing", "tag_name": "v-preview"})
        res = get_or_create_release(
            "https://test.gitea/api/v1", "fox/test", "tok", "v-preview", "Title", True, "Desc"
        )
        assert res["id"] == 99
        assert mock_req.call_count == 1
        assert mock_req.call_args[1]["method"] == "GET"


def test_get_or_create_release_creates_new():
    with patch("scripts.ci_publish_release.api_request") as mock_req:
        mock_req.side_effect = [
            GiteaAPIError(404, "Not Found", ""),
            (201, {"id": 100, "name": "Title", "tag_name": "v-preview"}),
        ]
        res = get_or_create_release(
            "https://test.gitea/api/v1", "fox/test", "tok", "v-preview", "Title", True, "Desc"
        )
        assert res["id"] == 100
        assert mock_req.call_count == 2
        assert mock_req.call_args_list[1][1]["method"] == "POST"


def test_delete_existing_asset_if_present():
    with patch("scripts.ci_publish_release.api_request") as mock_req:
        release_data = {
            "id": 10,
            "assets": [
                {"id": 1, "name": "other.zip"},
                {"id": 2, "name": "mistral-tts-windows-x64.zip"},
            ],
        }
        mock_req.return_value = (204, None)
        delete_existing_asset_if_present(
            "https://test.gitea/api/v1",
            "fox/test",
            "tok",
            release_id=10,
            filename="mistral-tts-windows-x64.zip",
            release_data=release_data,
        )
        assert mock_req.call_count == 1
        assert mock_req.call_args[0][0] == "https://test.gitea/api/v1/repos/fox/test/releases/10/assets/2"
        assert mock_req.call_args[1]["method"] == "DELETE"


def test_upload_release_asset(tmp_path):
    test_file = tmp_path / "mistral-tts-windows-x64.zip"
    test_file.write_bytes(b"PKzipcontent")

    with patch("scripts.ci_publish_release.api_request") as mock_req:
        mock_req.return_value = (201, {"id": 55, "name": "mistral-tts-windows-x64.zip"})
        res = upload_release_asset(
            "https://test.gitea/api/v1",
            "fox/test",
            "tok",
            release_id=10,
            file_path=str(test_file),
        )
        assert res["id"] == 55
        assert mock_req.call_count == 1
        assert mock_req.call_args[1]["method"] == "POST"


def test_publish_release_integration(tmp_path):
    test_file = tmp_path / "mistral-tts-windows-x64.zip"
    test_file.write_bytes(b"dummy zip data")

    with patch("scripts.ci_publish_release.get_or_create_release") as mock_get_or_create, \
         patch("scripts.ci_publish_release.delete_existing_asset_if_present") as mock_delete, \
         patch("scripts.ci_publish_release.upload_release_asset") as mock_upload:

        mock_get_or_create.return_value = {"id": 12, "assets": []}
        publish_release(
            file_path=str(test_file),
            token="test-token",
            repo="fox/mistral-tts",
            api_base="https://gitea.marcin-lis.pl",
            ref_name="main",
            ref_type="branch",
        )

        mock_get_or_create.assert_called_once()
        mock_delete.assert_called_once()
        mock_upload.assert_called_once()


def test_publish_release_file_not_found():
    with pytest.raises(FileNotFoundError):
        publish_release("nonexistent.zip", token="test-token")


def test_publish_release_empty_token(tmp_path):
    test_file = tmp_path / "test.zip"
    test_file.write_bytes(b"abc")
    with pytest.raises(ValueError):
        publish_release(str(test_file), token="")

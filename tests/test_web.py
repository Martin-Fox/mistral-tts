import json
from unittest.mock import patch
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from src.web import app, progress_store, get_audio

client = TestClient(app)

def test_read_root():
    """Assert that the root route responds with 200 and contains 'Mistral-TTS-Booksmith'."""
    response = client.get("/")
    assert response.status_code == 200
    assert "Mistral-TTS-Booksmith" in response.text

def test_get_audio_not_found():
    """Assert that requesting a non-existent file returns status code 404."""
    response = client.get("/api/audio/non_existent_file.mp3")
    assert response.status_code == 404
    assert "Audio file not found" in response.json()["detail"]

def test_get_audio_path_traversal_direct():
    """Assert that the path traversal check directly rejects traversal paths with 400."""
    for traversal_path in ["../../etc/passwd", "../styles.css", "storage/../../../etc/passwd"]:
        with pytest.raises(HTTPException) as exc_info:
            get_audio(traversal_path)
        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "Invalid filename"

def test_get_audio_path_traversal_client():
    """Assert that client requests attempting path traversal do not succeed, returning 400 or 404."""
    response1 = client.get("/api/audio/..%2F..%2Fetc%2Fpasswd")
    assert response1.status_code in (400, 404)

    response2 = client.get("/api/audio/..%2Fstyles.css")
    assert response2.status_code in (400, 404)

def test_get_progress_not_found():
    """Assert that an invalid task_id returns 404."""
    response = client.get("/api/progress?task_id=non-existent-task-id")
    assert response.status_code == 404
    assert "Task not found" in response.json()["detail"]

def test_get_progress_success():
    """Assert that a valid task_id registered in progress_store returns an SSE stream containing task status JSON."""
    task_id = "test-task-success"
    task_state = {
        "percentage": 100,
        "status": "Completed",
        "logs": ["Done"],
        "completed": True,
        "audio_file": "audiobook.mp3",
        "error": None,
        "created_at": 1719222222.0
    }
    progress_store[task_id] = task_state

    try:
        response = client.get(f"/api/progress?task_id={task_id}")
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]

        # Verify the yielded SSE event content
        content = response.text
        expected_event = f"data: {json.dumps(task_state)}\n\n"
        assert expected_event in content
    finally:
        if task_id in progress_store:
            del progress_store[task_id]

@patch("src.web.run_generation_pipeline")
def test_generate_success(mock_run_pipeline):
    """Assert that a valid generation request triggers the pipeline and registers the task."""
    data = {
        "api_key": "test_api_key",
        "text_content": "This is some test content for audiobook generation.",
        "voice_preset": "en_paul_neutral",
        "output_filename": "audiobook.mp3"
    }
    response = client.post("/api/generate", data=data)
    assert response.status_code == 200
    json_data = response.json()
    assert "task_id" in json_data
    task_id = json_data["task_id"]

    # Verify that the task_id is registered in progress_store with initial pending state
    assert task_id in progress_store
    assert progress_store[task_id]["status"] == "Pending"
    assert progress_store[task_id]["percentage"] == 0
    assert progress_store[task_id]["completed"] is False

    # Verify that the background pipeline function is called exactly once with correct parameters
    mock_run_pipeline.assert_called_once_with(
        task_id=task_id,
        api_key="test_api_key",
        text_content="This is some test content for audiobook generation.",
        text_file_data=None,
        voice_file_data=None,
        voice_preset="en_paul_neutral",
        voice_manual_id=None,
        source_lang=None,
        target_lang=None,
        output_filename="audiobook.mp3"
    )

    # Clean up progress_store
    if task_id in progress_store:
        del progress_store[task_id]

def test_generate_missing_text():
    """Assert that omitting text_file and text_content returns a client error status code 400."""
    data = {
        "api_key": "test_api_key",
        "voice_preset": "en_paul_neutral",
        "output_filename": "audiobook.mp3"
    }
    response = client.post("/api/generate", data=data)
    assert response.status_code == 400
    assert "Either text_file or text_content must be provided." in response.json()["detail"]

@patch("os.getenv", return_value=None)
def test_generate_missing_api_key(mock_getenv):
    """Assert that omitting or providing an empty API key returns a client error status code 400 when not in env."""
    data = {
        "api_key": "   ",
        "text_content": "Hello",
        "voice_preset": "en_paul_neutral",
        "output_filename": "audiobook.mp3"
    }
    response = client.post("/api/generate", data=data)
    assert response.status_code == 400
    assert "API key is required." in response.json()["detail"]


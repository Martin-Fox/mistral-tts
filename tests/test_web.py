import json
from unittest.mock import patch
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from src.web import app, progress_store, get_audio, verify_session

# Bypass authentication by default in tests
app.dependency_overrides[verify_session] = lambda: "session-id"

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


def test_authentication_status_unauthenticated():
    """Assert that checking status without a session cookie returns authenticated: False."""
    app.dependency_overrides.clear()
    try:
        response = client.get("/api/auth/status")
        assert response.status_code == 200
        assert response.json()["authenticated"] is False
    finally:
        app.dependency_overrides[verify_session] = lambda: "session-id"


def test_login_success():
    """Assert that a login request with correct credentials returns 200 and sets the session cookie."""
    with patch("src.web.APP_USERNAME", "admin"), \
         patch("src.web.APP_PASSWORD", "admin"):
        app.dependency_overrides.clear()
        try:
            payload = {"username": "admin", "password": "admin"}
            response = client.post("/api/auth/login", json=payload)
            assert response.status_code == 200
            assert "Login successful" in response.json()["message"]
            # Check that session_id cookie is set
            assert "session_id" in response.cookies
        finally:
            app.dependency_overrides[verify_session] = lambda: "session-id"


def test_login_failure():
    """Assert that a login request with incorrect credentials returns 401."""
    with patch("src.web.APP_USERNAME", "admin"), \
         patch("src.web.APP_PASSWORD", "admin"):
        app.dependency_overrides.clear()
        try:
            payload = {"username": "admin", "password": "wrong_password"}
            response = client.post("/api/auth/login", json=payload)
            assert response.status_code == 401
            assert "Incorrect username or password" in response.json()["detail"]
        finally:
            app.dependency_overrides[verify_session] = lambda: "session-id"


def test_logout_success():
    """Assert that a logout request clears the session and cookie."""
    with patch("src.web.APP_USERNAME", "admin"), \
         patch("src.web.APP_PASSWORD", "admin"):
        app.dependency_overrides.clear()
        try:
            # First login to establish session
            login_response = client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
            assert login_response.status_code == 200
            assert "session_id" in login_response.cookies
            
            # Then logout
            logout_response = client.post("/api/auth/logout")
            assert logout_response.status_code == 200
            
            # Verify status is now unauthenticated
            status_response = client.get("/api/auth/status")
            assert status_response.json()["authenticated"] is False
        finally:
            app.dependency_overrides[verify_session] = lambda: "session-id"


def test_api_endpoint_requires_session():
    """Assert that accessing a protected API endpoint without a session cookie returns 401."""
    app.dependency_overrides.clear()
    try:
        response = client.get("/api/progress?task_id=some_id")
        assert response.status_code == 401
        assert "Not authenticated" in response.json()["detail"]
    finally:
        app.dependency_overrides[verify_session] = lambda: "session-id"


def test_change_password_unauthorized():
    """Assert that changing the password without a session returns 401."""
    app.dependency_overrides.clear()
    try:
        payload = {"current_password": "admin", "new_password": "newpassword"}
        response = client.post("/api/auth/change-password", json=payload)
        assert response.status_code == 401
    finally:
        app.dependency_overrides[verify_session] = lambda: "session-id"


def test_change_password_success(tmp_path):
    """Assert that a valid change-password request updates the password and writes to auth.json."""
    temp_auth_file = tmp_path / "auth.json"
    
    with patch("src.web.AUTH_FILE", temp_auth_file), \
         patch("src.web.APP_PASSWORD", "admin"):
        
        app.dependency_overrides.clear()
        try:
            # Login first to get session
            login_res = client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
            assert login_res.status_code == 200
            
            # Change password
            payload = {
                "current_password": "admin",
                "new_password": "new_secure_password"
            }
            response = client.post("/api/auth/change-password", json=payload)
            assert response.status_code == 200
            assert "Password updated successfully" in response.json()["message"]
            
            # Verify file was written
            assert temp_auth_file.exists()
            with open(temp_auth_file, "r") as f:
                saved_data = json.load(f)
                assert saved_data["password"] == "new_secure_password"
        finally:
            app.dependency_overrides[verify_session] = lambda: "session-id"


def test_change_password_wrong_current(tmp_path):
    """Assert that providing a wrong current password returns 400."""
    temp_auth_file = tmp_path / "auth.json"
    
    with patch("src.web.AUTH_FILE", temp_auth_file), \
         patch("src.web.APP_PASSWORD", "admin"):
        
        app.dependency_overrides.clear()
        try:
            # Login first
            client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
            
            payload = {
                "current_password": "wrong_current_password",
                "new_password": "new_secure_password"
            }
            response = client.post("/api/auth/change-password", json=payload)
            assert response.status_code == 400
            assert "Incorrect current password" in response.json()["detail"]
        finally:
            app.dependency_overrides[verify_session] = lambda: "session-id"


def test_change_password_too_short():
    """Assert that a new password shorter than 4 characters is rejected with 400."""
    with patch("src.web.APP_PASSWORD", "admin"):
        app.dependency_overrides.clear()
        try:
            # Login first
            client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
            
            payload = {
                "current_password": "admin",
                "new_password": "abc"
            }
            response = client.post("/api/auth/change-password", json=payload)
            assert response.status_code == 400
            assert "New password must be at least 4 characters long" in response.json()["detail"]
        finally:
            app.dependency_overrides[verify_session] = lambda: "session-id"


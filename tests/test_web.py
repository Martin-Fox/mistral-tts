import json
import time
from unittest.mock import patch
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from src.web import app, db, get_audio, verify_session

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
    """Assert that a valid task_id registered in db returns an SSE stream containing task status JSON."""
    task_id = "test-task-success"
    db.create_task(task_id)
    db.update_task(
        task_id=task_id,
        percentage=100,
        status="Completed",
        completed=True,
        audio_file="audiobook.mp3",
        error=None
    )
    db.add_log(task_id, "Done")

    try:
        response = client.get(f"/api/progress?task_id={task_id}")
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]

        # Verify the yielded SSE event content
        content = response.text
        assert content.startswith("data: ")
        data_json = json.loads(content.split("\n\n")[0].replace("data: ", ""))
        assert data_json["percentage"] == 100
        assert data_json["status"] == "Completed"
        assert data_json["completed"] is True
        assert data_json["audio_file"] == "audiobook.mp3"
        assert data_json["error"] is None
        assert data_json["logs"] == ["Done"]
        assert "last_log_id" in data_json
    finally:
        conn = db._get_connection()
        try:
            with conn:
                conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        finally:
            conn.close()

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



    # Verify that the task_id is registered in db
    task_db_state = db.get_task(task_id)
    assert task_db_state is not None
    assert task_db_state["status"] == "Pending"
    assert task_db_state["percentage"] == 0
    assert task_db_state["completed"] is False

    # Verify that the background pipeline function is called exactly once with correct parameters
    mock_run_pipeline.assert_called_once_with(
        task_id=task_id,
        api_key="test_api_key",
        openai_key="",
        text_content="This is some test content for audiobook generation.",
        text_file_data=None,
        voice_file_data=None,
        voice_preset="en_paul_neutral",
        voice_manual_id=None,
        source_lang=None,
        target_lang=None,
        output_filename="audiobook.mp3",
        engine="mistral"
    )

    # Clean up db
    conn = db._get_connection()
    try:
        with conn:
            conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    finally:
        conn.close()

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


def test_generate_openai_voice_cloning_error():
    """Assert that requesting OpenAI TTS with an uploaded voice_file returns status code 400."""
    data = {
        "engine": "openai",
        "voice_preset": "alloy",
        "text_content": "Hello",
        "output_filename": "audiobook.mp3",
        "openai_key": "test_openai_key"
    }
    files = {
        "voice_file": ("voice.wav", b"fake-audio")
    }
    response = client.post("/api/generate", data=data, files=files)
    assert response.status_code == 400
    assert "does not support voice cloning" in response.json()["detail"]


@patch("os.getenv", return_value=None)
def test_generate_openai_missing_key_error(mock_getenv):
    """Assert that omitting or providing an empty OpenAI API key returns status code 400 when not in env."""
    data = {
        "engine": "openai",
        "text_content": "Hello",
        "voice_preset": "alloy",
        "output_filename": "audiobook.mp3",
        "openai_key": "   "
    }
    response = client.post("/api/generate", data=data)
    assert response.status_code == 400
    assert "OpenAI API key is required" in response.json()["detail"]



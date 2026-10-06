import json
import time
from unittest.mock import patch
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from src.web import app, db, get_audio, verify_session, get_cache_key, run_generation_pipeline

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


@pytest.mark.anyio
async def test_background_purger():
    # 1. Create a task
    task_id = "old-task-999"
    db.create_task(task_id)
    db.add_log(task_id, "Old task log")
    
    # 2. Modify created_at timestamp in SQLite to be older than 24 hours (e.g., 90000 seconds ago)
    conn = db._get_connection()
    try:
        with conn:
            conn.execute("UPDATE tasks SET created_at = ? WHERE id = ?", (time.time() - 90000, task_id))
    finally:
        conn.close()
        
    # 3. Call delete_old_tasks with cutoff 24 hours ago
    cutoff = time.time() - 86400
    purged = db.delete_old_tasks(cutoff)
    assert purged == 1
    
    # 4. Assert task is deleted and logs cascaded
    assert db.get_task(task_id) is None
    assert len(db.get_logs(task_id)) == 0


def test_config_endpoints_require_session():
    """Assert that accessing /api/config without a valid session cookie returns 401."""
    app.dependency_overrides.clear()
    unauthed_client = TestClient(app)
    try:
        get_res = unauthed_client.get("/api/config")
        assert get_res.status_code == 401
        assert "Not authenticated" in get_res.json()["detail"]

        post_res = unauthed_client.post("/api/config", json={"translation_model": "mistral-large-latest"})
        assert post_res.status_code == 401
        assert "Not authenticated" in post_res.json()["detail"]
    finally:
        app.dependency_overrides[verify_session] = lambda: "session-id"


def test_config_endpoints_with_session_cookie():
    """Assert that accessing /api/config with a valid session cookie succeeds."""
    from src.web import active_sessions
    app.dependency_overrides.clear()
    valid_sid = "test-session-config-123"
    active_sessions.add(valid_sid)
    session_client = TestClient(app)
    session_client.cookies.set("session_id", valid_sid)
    try:
        get_res = session_client.get("/api/config")
        assert get_res.status_code == 200
        assert "translation_model" in get_res.json()

        with patch("src.web.save_translation_model") as mock_save, \
             patch("src.web.get_translation_model", return_value="mistral-large-latest"):
            post_res = session_client.post(
                "/api/config",
                json={"translation_model": "mistral-large-latest"}
            )
            assert post_res.status_code == 200
            assert post_res.json()["translation_model"] == "mistral-large-latest"
            mock_save.assert_called_once_with("mistral-large-latest")
    finally:
        active_sessions.discard(valid_sid)
        app.dependency_overrides[verify_session] = lambda: "session-id"


def test_post_config_injection_rejected():
    """Assert that CRLF or invalid characters in translation_model are rejected by POST /api/config with 400."""
    response = client.post("/api/config", json={"translation_model": "ministral\r\nEVIL=1"})
    assert response.status_code == 400
    assert "Invalid model name format" in response.json()["detail"]


def test_get_config():
    """Assert that GET /api/config returns 200 and the current translation model."""
    response = client.get("/api/config")
    assert response.status_code == 200
    data = response.json()
    assert "translation_model" in data
    assert isinstance(data["translation_model"], str)
    assert len(data["translation_model"]) > 0


def test_post_config_json_success():
    """Assert that POST /api/config updates translation model via JSON body."""
    with patch("src.web.save_translation_model") as mock_save, \
         patch("src.web.get_translation_model", return_value="mistral-large-latest"):
        response = client.post("/api/config", json={"translation_model": "mistral-large-latest"})
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["translation_model"] == "mistral-large-latest"
        mock_save.assert_called_once_with("mistral-large-latest")


def test_post_config_form_success():
    """Assert that POST /api/config updates translation model via form data."""
    with patch("src.web.save_translation_model") as mock_save, \
         patch("src.web.get_translation_model", return_value="ministral-3b-latest"):
        response = client.post(
            "/api/config",
            data={"translation_model": "ministral-3b-latest"},
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["translation_model"] == "ministral-3b-latest"
        mock_save.assert_called_once_with("ministral-3b-latest")


def test_post_config_invalid_json():
    """Assert that sending malformed JSON to POST /api/config returns 400."""
    response = client.post(
        "/api/config",
        content=b"{malformed_json: true",
        headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 400
    assert "Invalid JSON body" in response.json()["detail"]


@pytest.mark.parametrize("invalid_payload", [
    {"translation_model": ""},
    {"translation_model": "   "},
    {"translation_model": 12345},
    {"translation_model": None},
    {},
    {"other_field": "model"}
])
def test_post_config_validation_failures(invalid_payload):
    """Assert that missing, empty, or non-string translation_model returns 400."""
    response = client.post("/api/config", json=invalid_payload)
    assert response.status_code == 400
    assert "translation_model is required and must be a non-empty string" in response.json()["detail"]


def test_get_cache_key_includes_translation_model():
    """Assert that differing translation_model values result in unique cache keys."""
    key1 = get_cache_key("text", "preset", None, None, "English", "Spanish", translation_model="ministral-8b-latest")
    key2 = get_cache_key("text", "preset", None, None, "English", "Spanish", translation_model="mistral-large-latest")
    key_none = get_cache_key("text", "preset", None, None, "English", "Spanish", translation_model=None)

    assert key1 != key2
    assert key1 != key_none
    assert key2 != key_none

    # Identical inputs yield identical cache keys
    key1_repeat = get_cache_key("text", "preset", None, None, "English", "Spanish", translation_model="ministral-8b-latest")
    assert key1 == key1_repeat


@patch("src.web.run_generation_pipeline")
def test_generate_with_translation_model(mock_run_pipeline):
    """Assert that passing translation_model to /api/generate forwards it to run_generation_pipeline."""
    data = {
        "api_key": "test_api_key",
        "text_content": "This is test content.",
        "voice_preset": "en_paul_neutral",
        "output_filename": "audiobook.mp3",
        "source_lang": "English",
        "target_lang": "Polish",
        "translation_model": "mistral-large-latest"
    }
    response = client.post("/api/generate", data=data)
    assert response.status_code == 200
    task_id = response.json()["task_id"]

    mock_run_pipeline.assert_called_once_with(
        task_id=task_id,
        api_key="test_api_key",
        openai_key="",
        text_content="This is test content.",
        text_file_data=None,
        voice_file_data=None,
        voice_preset="en_paul_neutral",
        voice_manual_id=None,
        source_lang="English",
        target_lang="Polish",
        output_filename="audiobook.mp3",
        engine="mistral",
        translation_model="mistral-large-latest"
    )

    # Clean up db
    conn = db._get_connection()
    try:
        with conn:
            conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    finally:
        conn.close()


@pytest.mark.anyio
async def test_run_generation_pipeline_translation_model(tmp_path):
    """Verify run_generation_pipeline initializes MistralTTSClient with translation_model."""
    from unittest.mock import AsyncMock, MagicMock
    task_id = "test-pipeline-trans-model"
    db.create_task(task_id)

    dummy_input = tmp_path / f"input_{task_id}.txt"
    dummy_input.write_text("Hello world", encoding="utf-8")
    dummy_trans = tmp_path / f"translated_{task_id}.txt"
    dummy_trans.write_text("Hola mundo", encoding="utf-8")

    with patch("src.web.MistralTTSClient") as mock_client_cls, \
         patch("src.web.get_tts_client") as mock_get_tts, \
         patch("src.web.AudioCompiler"), \
         patch("src.core.epub_parser.read_input_text", return_value="Hello world"), \
         patch("src.web.save_manifest"), \
         patch("src.web.load_manifest", return_value={"chunks": [], "completed": []}), \
         patch("src.web.TextSplitter") as mock_splitter:

        mock_client = MagicMock()
        mock_client.translate_file = AsyncMock(return_value=dummy_trans)
        mock_client_cls.return_value = mock_client

        mock_tts = MagicMock()
        mock_tts.generate_audio = AsyncMock()
        mock_get_tts.return_value = mock_tts

        mock_splitter.return_value.split.return_value = ["Hola mundo"]

        try:
            await run_generation_pipeline(
                task_id=task_id,
                api_key="mistral_api_key",
                text_content="Hello world",
                text_file_data=None,
                voice_file_data=None,
                voice_preset="en_paul_neutral",
                voice_manual_id=None,
                source_lang="English",
                target_lang="Spanish",
                output_filename="audiobook.mp3",
                engine="mistral",
                translation_model="mistral-large-latest"
            )
            mock_client_cls.assert_any_call(api_key="mistral_api_key", translation_model="mistral-large-latest")
        finally:
            conn = db._get_connection()
            try:
                with conn:
                    conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            finally:
                conn.close()


@pytest.mark.anyio
async def test_run_generation_pipeline_with_text_file_data():
    """Verify run_generation_pipeline succeeds without crashing when text_file_data is provided."""
    from pathlib import Path
    from unittest.mock import AsyncMock, MagicMock

    task_id = "test-pipeline-text-file-upload"
    db.create_task(task_id)

    chunk_text = "Test content"

    async def fake_generate_audio(chunk, chunk_path):
        chunk_path.write_bytes(b"0" * 150)

    with patch("src.web.get_tts_client") as mock_get_tts, \
         patch("src.web.AudioCompiler") as mock_compiler_cls, \
         patch("src.core.epub_parser.read_input_text", return_value=chunk_text), \
         patch("src.web.save_manifest"), \
         patch("src.web.load_manifest", return_value={"chunks": [], "completed": []}), \
         patch("src.web.TextSplitter") as mock_splitter:

        mock_tts = MagicMock()
        mock_tts.generate_audio = AsyncMock(side_effect=fake_generate_audio)
        mock_get_tts.return_value = mock_tts

        mock_compiler = MagicMock()
        mock_compiler.compile.return_value = {
            "expected_duration": 1.0,
            "output_duration": 1.0,
            "total_chunks": 1,
            "output_path": Path("storage/output/audiobook.mp3")
        }
        mock_compiler_cls.return_value = mock_compiler

        mock_splitter.return_value.split.return_value = [chunk_text]

        try:
            await run_generation_pipeline(
                task_id=task_id,
                api_key="mistral_api_key",
                text_content=None,
                text_file_data=("chapter1.txt", b"Test content"),
                voice_file_data=None,
                voice_preset="en_paul_neutral",
                voice_manual_id=None,
                source_lang=None,
                target_lang=None,
                output_filename="audiobook.mp3",
                engine="mistral"
            )

            task = db.get_task(task_id)
            assert task["completed"] is True
            assert task["status"] == "Completed"
            assert task["error"] is None
            assert task["percentage"] == 100
            assert mock_compiler.compile.called
        finally:
            conn = db._get_connection()
            try:
                with conn:
                    conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            finally:
                conn.close()


def test_generate_invalid_source_lang():
    """Assert that /api/generate rejects invalid source_lang with HTTP 400."""
    data = {
        "api_key": "test_api_key",
        "text_content": "Valid text content",
        "source_lang": "invalid!@#$",
        "target_lang": "Spanish"
    }
    response = client.post("/api/generate", data=data)
    assert response.status_code == 400
    assert "Invalid source_lang" in response.json()["detail"]


def test_generate_invalid_target_lang():
    """Assert that /api/generate rejects invalid target_lang with HTTP 400."""
    data = {
        "api_key": "test_api_key",
        "text_content": "Valid text content",
        "source_lang": "English",
        "target_lang": "../../etc/passwd"
    }
    response = client.post("/api/generate", data=data)
    assert response.status_code == 400
    assert "Invalid target_lang" in response.json()["detail"]


def test_generate_valid_languages(monkeypatch):
    """Assert that /api/generate accepts valid source_lang and target_lang."""
    with patch("src.web.run_generation_pipeline"):
        data = {
            "api_key": "test_api_key",
            "text_content": "Valid text content",
            "source_lang": "English",
            "target_lang": "Latin American Spanish"
        }
        response = client.post("/api/generate", data=data)
        assert response.status_code == 200
        assert "task_id" in response.json()


@pytest.mark.parametrize("invalid_lang", [
    "a",                          # too short (< 2)
    "a" * 41,                     # too long (> 40)
    "../../etc/passwd",           # path traversal
    "../secret",                  # path traversal
    "en\nrm -rf /",               # CRLF / command injection
    "en\r\nHeader: Value",        # CRLF injection
    "en; DROP TABLE",             # SQL injection attempt
    "<script>alert(1)</script>",  # XSS attempt
    "en\x00es",                   # Null byte
    "1234",                       # Digits only
    "en_US",                      # Underscore not allowed by regex
    "en!es",                      # Exclamation mark
    "es@domain",                  # @ symbol
    "fr#test",                    # hash symbol
    "es$var",                     # dollar symbol
    "`whoami`",                   # backticks
])
def test_generate_malformed_and_malicious_languages_rejected(invalid_lang):
    """Assert that /api/generate rejects all malicious and malformed languages with HTTP 400."""
    # Test as source_lang
    data_source = {
        "api_key": "test_api_key",
        "text_content": "Valid content",
        "source_lang": invalid_lang,
        "target_lang": "Spanish"
    }
    res_source = client.post("/api/generate", data=data_source)
    assert res_source.status_code == 400
    assert "Invalid source_lang" in res_source.json()["detail"]

    # Test as target_lang
    data_target = {
        "api_key": "test_api_key",
        "text_content": "Valid content",
        "source_lang": "English",
        "target_lang": invalid_lang
    }
    res_target = client.post("/api/generate", data=data_target)
    assert res_target.status_code == 400
    assert "Invalid target_lang" in res_target.json()["detail"]


@pytest.mark.parametrize("valid_lang", [
    "en",
    "a" * 40,
    "English",
    "Latin American Spanish",
    "pt-BR",
    "zh-Hans",
    "  fr  ",  # Leading/trailing whitespace should be stripped and accepted
])
def test_generate_valid_language_variations(valid_lang):
    """Assert that /api/generate accepts valid language strings."""
    with patch("src.web.run_generation_pipeline"):
        data = {
            "api_key": "test_api_key",
            "text_content": "Valid text content",
            "source_lang": valid_lang,
            "target_lang": valid_lang
        }
        response = client.post("/api/generate", data=data)
        assert response.status_code == 200
        assert "task_id" in response.json()









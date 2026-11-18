import asyncio
import contextvars
import json
import logging
import os
import re
import sys
import time
import threading
import tempfile
import zipfile
import xml.etree.ElementTree as ET
import uuid
from pathlib import Path
from typing import Optional

import secrets
from fastapi import APIRouter, FastAPI, BackgroundTasks, File, Form, UploadFile, HTTPException, Query, Depends, status, Request, Response, Cookie
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator, ValidationError

from src.core.text_splitter import TextSplitter
from src.api.mistral_client import MistralTTSClient
from src.api.factory import get_tts_client
from src.core.resource_limits import ResourceLimits, ResourceLimitExceeded, check_text
from src.web_limits import JobController, GenerationRequestLimits, GenerationRoute
from src.core.audio_compiler import AudioCompiler
from src.core.cache_io import run_blocking_until_done
from src.core.pipeline import prepare_text, run_pipeline, VoiceInput
from src.core.auth import hash_password, verify_password, load_credentials, save_credentials, password_meets_policy
from src.web_security import WebSecurity
from src.core.login_limiter import LoginLimiter
from src.core.task_store import save_job, load_job, task_directory, load_translation, save_translation, validate_task_id, save_cache_reference
from src.core.storage_retention import StoragePolicy, StorageBudgetExceeded, check_storage_budget, sweep_storage
from src.core.process_runner import process_budget
from src.core.voice_reference import prepare_reference
from src.api.retry import validate_retry_settings
from src.core.task_db import TaskDatabase
from src.core.config import get_translation_model, save_translation_model, load_environment

# Load environment variables from .env
load_environment()

def get_static_dir() -> Path:
    """Resolves static assets directory for PyInstaller bundle or local development."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass) / "src" / "web" / "static"
    local_static = Path(__file__).resolve().parent / "web" / "static"
    if local_static.exists():
        return local_static
    return Path("src/web/static")

# Static assets can live in a read-only source or PyInstaller directory.
STATIC_DIRECTORY = get_static_dir()

# Only mutable storage is created at startup.
Path("storage/cache").mkdir(parents=True, exist_ok=True)
Path("storage/output").mkdir(parents=True, exist_ok=True)


# Set up logging
logger = logging.getLogger("booksmith")

LANG_REGEX = re.compile(r"^[a-zA-Z\s\-]{2,40}$")

# Authentication configuration (for HTTP Basic Auth)
AUTH_FILE = Path("storage/auth.json")
APP_USERNAME = os.getenv("APP_USERNAME", "admin")
APP_PASSWORD = os.getenv("APP_PASSWORD", "admin")

APP_PASSWORD_HASH = None

# Process-local sessions: run the WebUI with one worker.
active_sessions: dict[str, float] = {}
password_change_sessions: set[str] = set()
auth_lock = threading.RLock()
login_limiter = LoginLimiter()
SESSION_TTL_SECONDS = 28800
SESSION_COOKIE_SECURE = False


def configure_sessions():
    global SESSION_TTL_SECONDS, SESSION_COOKIE_SECURE
    try:
        ttl = int(os.getenv("SESSION_TTL_SECONDS", "28800"))
        workers = int(os.getenv("WEB_CONCURRENCY", "1"))
    except ValueError:
        raise RuntimeError("SESSION_TTL_SECONDS and WEB_CONCURRENCY must be positive integers") from None
    secure = os.getenv("SESSION_COOKIE_SECURE", "false").lower().strip()
    if ttl <= 0 or workers != 1 or secure not in ("true", "false"):
        raise RuntimeError(
            "Use SESSION_TTL_SECONDS > 0, SESSION_COOKIE_SECURE=true/false "
            "and a single WebUI worker (WEB_CONCURRENCY=1)."
        )
    SESSION_TTL_SECONDS = ttl
    SESSION_COOKIE_SECURE = secure == "true"


def session_is_valid(session_id: Optional[str]) -> bool:
    with auth_lock:
        now = time.monotonic()
        for expired in [sid for sid, expiry in active_sessions.items() if expiry <= now]:
            active_sessions.pop(expired, None)
            password_change_sessions.discard(expired)
        return bool(session_id and session_id in active_sessions)

def verify_login_session(session_id: Optional[str] = Cookie(None)):
    """
    Validates the session cookie.
    Designed as a pluggable dependency to allow easy transition to OIDC/Pocket-ID in the future.
    """
    if not session_is_valid(session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )
    return session_id


def verify_session(session_id: Optional[str] = Cookie(None)):
    with auth_lock:
        token = verify_login_session(session_id)
        if token in password_change_sessions:
            raise HTTPException(status_code=403, detail='Password change required before using the application')
        return token

app = FastAPI(
    title="Mistral TTS Booksmith API", docs_url=None, redoc_url=None
)

job_controller = JobController(running=2, queued=2)
app.add_middleware(GenerationRequestLimits, controller=lambda: job_controller,
                   storage_check=lambda: check_storage_budget(),
                   authenticated=lambda scope: verify_session(Request(scope).cookies.get('session_id')))
app.add_middleware(WebSecurity)


async def read_upload_bounded(upload: UploadFile, limit: int) -> bytes:
    content = bytearray()
    while True:
        chunk = await upload.read(min(65536, limit - len(content) + 1))
        if not chunk:
            return bytes(content)
        content.extend(chunk)
        if len(content) > limit:
            raise HTTPException(status_code=413, detail="Uploaded file exceeds its size limit")


def check_web_document(filename):
    if Path(filename or '').suffix.lower() == '.mobi':
        raise HTTPException(status_code=415, detail='MOBI uploads/resume are disabled in WebUI; convert to EPUB or TXT.')


# Mount static files directory
app.mount("/static", StaticFiles(directory=STATIC_DIRECTORY), name="static")



# Initialize database
db = TaskDatabase(Path("storage/state.db"))

# ContextVar to track the active task_id in each coroutine
current_task_id = contextvars.ContextVar("current_task_id", default=None)

class TaskLogHandler(logging.Handler):
    def __init__(self, database: TaskDatabase):
        super().__init__()
        self.database = database
        self.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s", datefmt="%H:%M:%S"))

    def emit(self, record):
        try:
            task_id = current_task_id.get()
            if task_id:
                log_entry = self.format(record)
                self.database.add_log(task_id, log_entry)
        except Exception:
            self.handleError(record)

# Register global logging handler at module level
global_log_handler = TaskLogHandler(db)
logging.getLogger("booksmith").addHandler(global_log_handler)
logging.getLogger("src").addHandler(global_log_handler)

async def run_generation_pipeline(
    task_id: str,
    api_key: str,
    text_content: Optional[str],
    text_file_data: Optional[tuple[str, bytes]],
    voice_file_data: Optional[tuple[str, bytes]],
    voice_preset: Optional[str],
    voice_manual_id: Optional[str],
    source_lang: Optional[str],
    target_lang: Optional[str],
    output_filename: str,
    engine: str = "mistral",
    openai_key: Optional[str] = None,
    translation_model: Optional[str] = None,
    input_encoding: Optional[str] = None
):
    """
    Asynchronous pipeline task that handles file translation, voice cloning,
    audio chunk generation, and final compilation.
    """
    saved_job = (task_directory(task_id) / "spec.json").exists()
    engine = engine.strip().lower()
    text_path = None
    voice_path = None
    task_temp_dir = None

    token = current_task_id.set(task_id)
    try:
        if saved_job:
            parameters = load_job(task_id)
            translation_model = parameters["translation_model"]
            input_encoding = parameters["input_encoding"]
        db.update_task(task_id, status="Preparing Files")
        logger.info(f"Starting audiobook generation task: {task_id}")

        # 1. Save uploaded text file or text content to a temporary task directory
        task_temp_dir = Path("storage/cache") / f"task_{task_id}"
        task_temp_dir.mkdir(parents=True, exist_ok=True)
        if text_file_data:
            filename, content = text_file_data
            suffix = Path(filename).suffix or ".txt"
            base_stem = Path(filename).stem
            safe_stem = re.sub(r'[^a-zA-Z0-9_-]', '_', base_stem) or "input"
            text_path = task_temp_dir / f"{safe_stem}{suffix}"
            with open(text_path, "wb") as f:
                f.write(content)
            logger.info(f"Saved uploaded text file to {text_path}")
        elif text_content is not None:
            input_encoding = "utf-8"
            text_path = task_temp_dir / "input.txt"
            with open(text_path, "w", encoding="utf-8") as f:
                f.write(text_content)
            logger.info(f"Saved text content to temporary file {text_path}")
        else:
            raise ValueError("No text input provided.")

        # 2. Save voice file to a temporary path if provided
        if voice_file_data:
            filename, content = voice_file_data
            suffix = Path(filename).suffix or ".mp3"
            voice_path = task_temp_dir / f"voice_{task_id}{suffix}"
            with open(voice_path, "wb") as f:
                f.write(content)
            logger.info(f"Saved uploaded voice file to {voice_path}")

        effective_translation_model = (translation_model or get_translation_model()) if target_lang else None

        async def translate(path, source, target, model):
            translation_client = MistralTTSClient(api_key=api_key, translation_model=model)
            translated = load_translation(task_id) if saved_job else None
            if translated is None:
                if saved_job:
                    translation_client.translation_cache_dir = task_directory(task_id) / "translation-cache"
                    translated = await translation_client.translate_file(
                        path, source, target,
                        output_filename=f"{task_id}_translated{'.srt' if path.suffix.lower() == '.srt' else '.txt'}",
                        input_encoding=input_encoding)
                    translated = save_translation(task_id, translated)
                else:
                    translated = await translation_client.translate_file(path, source, target, input_encoding=input_encoding)
            logger.info(f"Translation completed. Translated file: {translated}")
            return translated

        def report(event):
            if event.stage in ('Translating', 'Splitting Text', 'Configuring Voice', 'Waiting for Cache',
                               'Generating Audio', 'Compiling Audiobook'):
                db.update_task(task_id, status=event.stage)
            if event.stage == 'Text Ready':
                logger.info(f"Text split into {event.total} semantic chunks (total characters: {event.characters}).")
            elif event.stage == 'Translating':
                logger.info(f"Translating text from {source_lang or 'English'} to {target_lang}...")
            elif event.stage == 'Generating Chunk':
                action = 'Reusing cached audio' if event.cached else 'Generating audio'
                logger.info(f"{action} for chunk {event.current}/{event.total}...")
            elif event.stage == 'Chunk Ready':
                db.update_task(task_id, percentage=int(event.current / event.total * 90))
            elif event.stage == 'Compiling Audiobook':
                logger.info(f"Compiling final audiobook file from {event.total} chunks...")

        prepared = await prepare_text(
            text_path, splitter=TextSplitter(), source_lang=source_lang, target_lang=target_lang,
            translation_model=effective_translation_model, input_encoding=input_encoding,
            translate=translate, progress=report)
        tts_api_key = openai_key if engine == "openai" else api_key
        client = get_tts_client(engine, tts_api_key)
        requested_name = Path(output_filename)
        output_stem = requested_name.stem.encode("utf-8")[:180].decode("utf-8", errors="ignore")
        published_filename = f"{task_id}_{output_stem}{requested_name.suffix}"
        output_path = Path("storage/output") / published_filename

        def cache_ready(directory):
            if saved_job:
                save_cache_reference(task_id, directory.name)

        result = await run_pipeline(
            prepared, client=client, engine=engine,
            voice=VoiceInput(voice_preset or voice_manual_id, voice_path),
            output_path=output_path, compiler_factory=AudioCompiler, progress=report, cache_ready=cache_ready)
        logger.info(
            f"Audiobook compiled successfully. Saved to {output_path} "
            f"(verified duration: {result.compilation.get('output_duration', 0):.2f}s, "
            f"expected ~{result.compilation.get('expected_duration', 0):.2f}s across {result.chunk_count} chunks)")
        db.update_task(task_id, percentage=100, status="Completed", completed=True, audio_file=published_filename)

    except Exception as e:
        logger.error(f"Error in generation pipeline: {e}", exc_info=True)
        db.update_task(
            task_id,
            status="Failed",
            error=str(e)
        )
    finally:
        current_task_id.reset(token)

        # Clean up temporary uploaded text, voice, and task cache directory
        if text_path and text_path.exists():
            try:
                text_path.unlink()
            except Exception as e:
                logger.warning(f"Failed to delete temporary text file {text_path}: {e}")
        if voice_path and voice_path.exists():
            try:
                voice_path.unlink()
            except Exception as e:
                logger.warning(f"Failed to delete temporary voice file {voice_path}: {e}")
        if task_temp_dir and task_temp_dir.exists():
            try:
                task_temp_dir.rmdir()
            except Exception:
                pass

class ChangePasswordRequest(BaseModel):
    current_password: str = Field(max_length=1024)
    new_password: str = Field(max_length=1024)

@app.post("/api/auth/change-password")
def change_password(request: ChangePasswordRequest, session: str = Depends(verify_login_session)):
    # Serialize password verification/publication against concurrent logins.
    with auth_lock:
        return _change_password(request)


def _change_password(request: ChangePasswordRequest):
    """
    Endpoint to change the password for the current user.
    Persists the new password to storage/auth.json so it survives restarts.
    """
    global APP_PASSWORD_HASH
    
    # Verify current password
    if not verify_password(request.current_password, APP_PASSWORD_HASH):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Incorrect current password"
        )
    
    # Validate new password
    if not password_meets_policy(request.new_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must contain 12-1024 characters (at least 12 after trimming)"
        )
        
    # Persist the new credentials
    try:
        new_hash = hash_password(request.new_password)
        save_credentials(AUTH_FILE, APP_USERNAME, new_hash)
        
        # Update in-memory
        APP_PASSWORD_HASH = new_hash
        active_sessions.clear()
        password_change_sessions.clear()
        logger.info(f"Password successfully changed for user: {APP_USERNAME}")
        return {"message": "Password updated successfully. Please log in with your new credentials."}
    except Exception as e:
        logger.error(f"Failed to persist new password: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save new password to disk"
        )

class LoginRequest(BaseModel):
    username: str = Field(max_length=256)
    password: str = Field(max_length=1024)

@app.post("/api/auth/login")
def login(request: LoginRequest, response: Response, http_request: Request):
    source = http_request.client.host if http_request.client else "unknown"
    retry_after = login_limiter.consume(source, request.username)
    if retry_after is not None:
        raise HTTPException(
            status_code=429,
            detail="Too many login attempts. Please try again later.",
            headers={"Retry-After": str(retry_after)}
        )
    with auth_lock:
        return _login(request, response)


def _login(request: LoginRequest, response: Response):
    """
    Verifies credentials and sets a session cookie.
    """
    is_correct_username = secrets.compare_digest(request.username.encode("utf-8"), APP_USERNAME.encode("utf-8"))
    is_correct_password = verify_password(request.password, APP_PASSWORD_HASH)
    if not (is_correct_username and is_correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password"
        )
    
    session_id = str(uuid.uuid4())
    session_is_valid(None)  # Evict expired entries before adding a session.
    active_sessions[session_id] = time.monotonic() + SESSION_TTL_SECONDS
    requires_change = not password_meets_policy(request.password)
    if requires_change:
        password_change_sessions.add(session_id)
    response.set_cookie(
        key="session_id",
        value=session_id,
        httponly=True,
        samesite="lax",
        secure=SESSION_COOKIE_SECURE,
        max_age=SESSION_TTL_SECONDS
    )
    return {"message": "Login successful", "requires_password_change": requires_change}

@app.post("/api/auth/logout")
def logout(request: Request, response: Response):
    """
    Clears the session cookie and removes the session from memory.
    """
    session_id = request.cookies.get("session_id")
    with auth_lock:
        active_sessions.pop(session_id, None)
        password_change_sessions.discard(session_id)
    response.delete_cookie(key="session_id", httponly=True, samesite="lax", secure=SESSION_COOKIE_SECURE)
    return {"message": "Logged out successfully"}

@app.get("/api/auth/status")
def get_auth_status(request: Request):
    """
    Returns the current authentication status of the user.
    """
    session_id = request.cookies.get("session_id")
    if session_is_valid(session_id):
        return {"authenticated": True, "username": APP_USERNAME,
                "requires_password_change": session_id in password_change_sessions}
    return {"authenticated": False}

class ConfigUpdateRequest(BaseModel):
    translation_model: str = Field(max_length=100)

    @field_validator("translation_model", mode="before")
    @classmethod
    def validate_translation_model(cls, v):
        if not isinstance(v, str) or not v.strip():
            raise ValueError("translation_model is required and must be a non-empty string")
        return v.strip()

@app.get("/api/config")
def get_config(session: str = Depends(verify_session)):
    """
    Returns the current translation model configuration.

    Returns:
        dict: JSON object with 'translation_model' key.
    """
    return {"translation_model": get_translation_model()}

@app.post("/api/config")
async def update_config(
    request: Request,
    session: str = Depends(verify_session)
):
    """
    Updates the translation model configuration in .env and runtime environment.

    Accepts JSON body ({"translation_model": "..."}) or form-encoded data.

    Raises:
        HTTPException: 400 if payload is invalid or 'translation_model' is missing/empty.

    Returns:
        dict: JSON response containing status and updated 'translation_model'.
    """
    content_type = request.headers.get("content-type", "")
    data = {}
    if "application/json" in content_type:
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("JSON body must be an object")
            data = body
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON body")
    else:
        try:
            form = await request.form()
            data = dict(form)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid form data")

    try:
        req = ConfigUpdateRequest(**data)
        save_translation_model(req.translation_model)
    except ValidationError:
        raise HTTPException(
            status_code=400,
            detail="translation_model is required and must be a non-empty string"
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"status": "ok", "translation_model": get_translation_model()}

@app.get("/")
def read_root():
    """Serves the main frontend page."""
    return FileResponse(STATIC_DIRECTORY / "index.html")

@app.get("/api/audio/{filename}")
def get_audio(filename: str, session: str = Depends(verify_session)):
    """Serves the compiled audiobook file with protection against path traversal."""
    base_dir = Path("storage/output").resolve()
    file_path = (base_dir / filename).resolve()
    if not file_path.is_relative_to(base_dir):
        raise HTTPException(status_code=400, detail="Invalid filename")
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Audio file not found")
    return FileResponse(file_path, media_type="audio/mpeg")

@app.get("/api/progress")
async def get_progress(
    task_id: str = Query(...),
    last_log_id: int = Query(0),
    session: str = Depends(verify_session)
):
    """
    Returns an SSE stream yielding progress updates as JSON-encoded string events.
    """
    task_state = db.get_task(task_id)
    if not task_state:
        raise HTTPException(status_code=404, detail="Task not found")

    async def event_generator():
        current_last_id = last_log_id
        while True:
            if not session_is_valid(session):
                break
            task_state = db.get_task(task_id)
            if not task_state:
                break
            
            new_logs = db.get_logs(task_id, after_id=current_last_id)
            if new_logs:
                current_last_id = new_logs[-1]["id"]
            
            payload = {
                "percentage": task_state["percentage"],
                "status": task_state["status"],
                "completed": task_state["completed"],
                "audio_file": task_state["audio_file"],
                "error": task_state["error"],
                "logs": [log_item["message"] for log_item in new_logs],
                "last_log_id": current_last_id
            }
            
            yield f"data: {json.dumps(payload)}\n\n"
            if task_state["completed"] or task_state["status"] in ("Failed", "Interrupted"):
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

generation_router = APIRouter(route_class=GenerationRoute)


@generation_router.post("/api/generate")
async def generate_audiobook(
    background_tasks: BackgroundTasks,
    text_file: Optional[UploadFile] = File(None),
    text_content: Optional[str] = Form(None),
    voice_file: Optional[UploadFile] = File(None),
    voice_preset: Optional[str] = Form(None),
    voice_manual_id: Optional[str] = Form(None),
    source_lang: Optional[str] = Form(None),
    target_lang: Optional[str] = Form(None),
    translation_model: Optional[str] = Form(None),
    output_filename: str = Form("audiobook.mp3"),
    api_key: Optional[str] = Form(None),
    engine: str = Form("mistral"),
    openai_key: Optional[str] = Form(None),
    session: str = Depends(verify_session)
):
    """
    Triggers the background generation task and returns a unique task ID immediately.
    Storage retention runs separately and protects unfinished/resumable tasks.
    """
    engine = engine.strip().lower()
    if engine not in ("mistral", "openai"):
        raise HTTPException(status_code=400, detail="Unknown TTS engine")
    if not text_file and not text_content:
        raise HTTPException(status_code=400, detail="Either text_file or text_content must be provided.")

    # Validate OpenAI voice cloning limitation
    if engine == "openai":
        if voice_file is not None and voice_file.filename and voice_file.filename.strip():
            raise HTTPException(
                status_code=400,
                detail="OpenAI TTS does not support voice cloning. Please select an OpenAI preset voice instead."
            )

    # Resolve API keys
    resolved_mistral_key = (api_key or "").strip() or os.getenv("MISTRAL_API_KEY", "")
    resolved_openai_key = (openai_key or "").strip() or os.getenv("OPENAI_API_KEY", "")

    # Perform validation based on the selected engine and operations
    if engine == "openai":
        if not resolved_openai_key:
            raise HTTPException(
                status_code=400,
                detail="OpenAI API key is required when using the OpenAI engine. Please provide it or set OPENAI_API_KEY."
            )
    else:
        # engine == "mistral"
        if not resolved_mistral_key:
            raise HTTPException(
                status_code=400,
                detail="Mistral API key is required. Please enter it in the WebUI or set MISTRAL_API_KEY."
            )

    if target_lang and not resolved_mistral_key:
        raise HTTPException(
            status_code=400,
            detail="Mistral API key is required for translation. Please enter it in the WebUI or set MISTRAL_API_KEY."
        )

    # Validate languages if provided
    if source_lang is not None and source_lang.strip():
        if not LANG_REGEX.match(source_lang.strip()):
            raise HTTPException(
                status_code=400,
                detail="Invalid source_lang. Must be 2-40 characters containing only letters, spaces, or hyphens."
            )
        source_lang = source_lang.strip()
    else:
        source_lang = None

    if target_lang is not None and target_lang.strip():
        if not LANG_REGEX.match(target_lang.strip()):
            raise HTTPException(
                status_code=400,
                detail="Invalid target_lang. Must be 2-40 characters containing only letters, spaces, or hyphens."
            )
        target_lang = target_lang.strip()
    else:
        target_lang = None

    # Sanitize and validate the output audiobook filename to prevent path traversal
    safe_filename = Path(output_filename).name
    if not safe_filename or safe_filename.startswith(".") or Path(safe_filename).suffix.lower() not in (".mp3", ".m4b", ".wav"):
        raise HTTPException(status_code=400, detail="Invalid output filename. Must be a valid audio file name.")

    task_id = str(uuid.uuid4())

    limits = ResourceLimits.from_env()
    if text_content is not None:
        try:
            check_text(text_content)
        except ResourceLimitExceeded as error:
            raise HTTPException(status_code=413, detail=str(error)) from None

    # Read uploaded file contents in the request handler to prevent closed file descriptors in background task
    text_file_data = None
    if text_file:
        check_web_document(text_file.filename)
        text_bytes = await read_upload_bounded(text_file, limits.max_text_upload_bytes)
        text_file_data = (text_file.filename, text_bytes)

    voice_file_data = None
    if voice_file:
        voice_bytes = await read_upload_bounded(voice_file, limits.max_voice_upload_bytes)
        voice_file_data = (voice_file.filename, voice_bytes)

    # Validate parsed size (including EPUB expansion) before creating a task or
    # constructing an API client. Keep the original upload for the existing pipeline.
    if text_file_data:
        from src.core.epub_parser import read_input_text
        with tempfile.TemporaryDirectory(prefix="booksmith-preflight-") as directory:
            probe = Path(directory) / ("input" + Path(text_file_data[0] or "input.txt").suffix)
            probe.write_bytes(text_file_data[1])
            try:
                await run_blocking_until_done(read_input_text, probe)
            except ResourceLimitExceeded as error:
                raise HTTPException(status_code=413, detail=str(error)) from None
            except (ValueError, zipfile.BadZipFile, ET.ParseError):
                raise HTTPException(status_code=400, detail="Invalid input document") from None

    # Reject unsupported/overlong audio before a task can submit translation or
    # TTS work. Keep the original immutable snapshot for deterministic cache IDs.
    if voice_file_data:
        with tempfile.TemporaryDirectory(prefix='booksmith-voice-preflight-') as directory:
            probe = Path(directory) / ('input' + Path(voice_file_data[0] or '').suffix)
            probe.write_bytes(voice_file_data[1])
            try:
                await prepare_reference(probe)
            except ResourceLimitExceeded as error:
                raise HTTPException(status_code=413, detail=str(error)) from None
            except (ValueError, TimeoutError):
                raise HTTPException(status_code=400, detail='Invalid or unsupported voice reference') from None


    # Enqueue background execution task
    pipeline_kwargs = {
        "task_id": task_id,
        "api_key": resolved_mistral_key,
        "openai_key": resolved_openai_key,
        "text_content": text_content,
        "text_file_data": text_file_data,
        "voice_file_data": voice_file_data,
        "voice_preset": voice_preset,
        "voice_manual_id": voice_manual_id,
        "source_lang": source_lang,
        "target_lang": target_lang,
        "output_filename": safe_filename,
        "engine": engine,
    }
    if translation_model is not None:
        pipeline_kwargs["translation_model"] = translation_model

    incoming_size = sum(len(upload[1]) for upload in (text_file_data, voice_file_data) if upload)
    if text_file_data is None:
        incoming_size += len((text_content or '').encode('utf-8'))
    try:
        await asyncio.to_thread(check_storage_budget, additional_bytes=incoming_size * 2)
    except StorageBudgetExceeded as error:
        raise HTTPException(status_code=507, detail=str(error)) from None
    save_job(task_id, pipeline_kwargs)
    db.create_task(task_id)

    background_tasks.add_task(
        job_controller.run,
        run_generation_pipeline,
        **pipeline_kwargs
    )

    return {"task_id": task_id}


@app.get("/api/tasks")
def list_resumable_tasks(session: str = Depends(verify_session)):
    return {"tasks": [task for task in db.resumable_tasks()
                      if (task_directory(task['id']) / 'spec.json').exists()]}


@generation_router.post("/api/resume/{task_id}")
async def resume_task(task_id: str, background_tasks: BackgroundTasks,
                      api_key: Optional[str] = Form(None), openai_key: Optional[str] = Form(None),
                      session: str = Depends(verify_session)):
    try:
        task_id = validate_task_id(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task ID") from None
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task['status'] not in ('Interrupted', 'Failed') or task['completed']:
        raise HTTPException(status_code=409, detail="Task is not resumable")
    try:
        arguments = load_job(task_id)
    except (OSError, ValueError, KeyError, TypeError):
        raise HTTPException(status_code=409, detail="Saved task inputs are missing, changed or incompatible") from None
    if arguments['text_file_data']:
        check_web_document(arguments['text_file_data'][0])
    mistral = (api_key or '').strip() or os.getenv('MISTRAL_API_KEY', '')
    openai = (openai_key or '').strip() or os.getenv('OPENAI_API_KEY', '')
    if (arguments['engine'] == 'mistral' or arguments['target_lang']) and not mistral:
        raise HTTPException(status_code=400, detail="Mistral API key required to resume")
    if arguments['engine'] == 'openai' and not openai:
        raise HTTPException(status_code=400, detail="OpenAI API key required to resume")
    incoming_size = sum(len(upload[1]) for upload in (arguments['text_file_data'], arguments['voice_file_data']) if upload)
    try:
        await asyncio.to_thread(check_storage_budget, additional_bytes=incoming_size)
    except StorageBudgetExceeded as error:
        raise HTTPException(status_code=507, detail=str(error)) from None
    if not db.claim_resume(task_id):
        raise HTTPException(status_code=409, detail="Task was already resumed")
    background_tasks.add_task(job_controller.run, run_generation_pipeline,
                              task_id=task_id, api_key=mistral, openai_key=openai, **arguments)
    return {"task_id": task_id}


app.include_router(generation_router)


async def task_purger_loop():
    """Plan or apply state-aware retention without blocking the event loop."""
    while True:
        try:
            policy = StoragePolicy.from_env()
            report = await run_blocking_until_done(
                lambda: sweep_storage(Path('storage'), db.db_path, policy=policy,
                                      dry_run=not policy.storage_cleanup_enabled))
            if report['candidates'] or report['expired_tasks'] or report['skipped']:
                logger.info("Storage retention dry_run=%s: %d artifacts, %d completed tasks, %d skipped",
                            report['dry_run'], len(report['candidates']),
                            len(report['expired_tasks']), len(report['skipped']))
        except Exception as e:
            logger.error(f"Error in task_purger_loop: {e}", exc_info=True)
        await asyncio.sleep(1800)


@app.on_event("startup")
async def startup_event():
    global APP_USERNAME, APP_PASSWORD, APP_PASSWORD_HASH, job_controller
    validate_retry_settings()
    StoragePolicy.from_env()
    process_budget()
    process_budget(probe=True)
    limits = ResourceLimits.from_env()
    job_controller = JobController(limits.max_running_jobs, limits.max_queued_jobs)
    configure_sessions()
    APP_USERNAME, APP_PASSWORD_HASH = load_credentials(AUTH_FILE, APP_USERNAME, APP_PASSWORD)
    APP_PASSWORD = None
    db.interrupt_unfinished_tasks()
    asyncio.create_task(task_purger_loop())


import asyncio
import contextvars
import hashlib
import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Optional

import secrets
from dotenv import load_dotenv
from fastapi import FastAPI, BackgroundTasks, File, Form, UploadFile, HTTPException, Query, Depends, status, Request, Response, Cookie
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.core.text_splitter import TextSplitter
from src.api.mistral_client import MistralTTSClient
from src.api.factory import get_tts_client
from src.core.audio_compiler import AudioCompiler
from src.core.task_db import TaskDatabase

# Load environment variables from .env
load_dotenv()

# Ensure directories exist on startup
Path("src/web/static").mkdir(parents=True, exist_ok=True)
Path("storage/cache").mkdir(parents=True, exist_ok=True)
Path("storage/output").mkdir(parents=True, exist_ok=True)


# Set up logging
logger = logging.getLogger("booksmith")

# Authentication configuration (for HTTP Basic Auth)
AUTH_FILE = Path("storage/auth.json")
APP_USERNAME = os.getenv("APP_USERNAME", "admin")
APP_PASSWORD = os.getenv("APP_PASSWORD", "admin")

if AUTH_FILE.exists():
    try:
        with open(AUTH_FILE, "r") as f:
            auth_data = json.load(f)
            APP_USERNAME = auth_data.get("username", APP_USERNAME)
            APP_PASSWORD = auth_data.get("password", APP_PASSWORD)
        logger.info("Loaded persisted credentials from storage/auth.json")
    except Exception as e:
        logger.error(f"Failed to load persisted credentials: {e}")

if APP_USERNAME == "admin" and APP_PASSWORD == "admin":
    logger.warning("Using default credentials (admin/admin). Please set APP_USERNAME and APP_PASSWORD in your environment or .env file.")

# Active sessions store (in-memory)
active_sessions = set()

def verify_session(session_id: Optional[str] = Cookie(None)):
    """
    Validates the session cookie.
    Designed as a pluggable dependency to allow easy transition to OIDC/Pocket-ID in the future.
    """
    if not session_id or session_id not in active_sessions:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )
    return session_id

app = FastAPI(
    title="Mistral TTS Booksmith API"
)

# Mount static files directory
app.mount("/static", StaticFiles(directory="src/web/static"), name="static")

# Global progress store
progress_store = {}

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

def get_cache_key(
    text: str,
    voice_preset: Optional[str],
    voice_manual_id: Optional[str],
    voice_bytes: Optional[bytes],
    source_lang: Optional[str],
    target_lang: Optional[str]
) -> str:
    """
    Generates a unique cache key based on translation and voice parameters.
    """
    hasher = hashlib.sha256()
    hasher.update(text.encode("utf-8"))
    if voice_preset:
        hasher.update(voice_preset.encode("utf-8"))
    if voice_manual_id:
        hasher.update(voice_manual_id.encode("utf-8"))
    if voice_bytes:
        hasher.update(voice_bytes)
    if source_lang:
        hasher.update(source_lang.encode("utf-8"))
    if target_lang:
        hasher.update(target_lang.encode("utf-8"))
    return hasher.hexdigest()

def load_manifest(manifest_path: Path) -> dict:
    """Loads cache manifest file if it exists."""
    if manifest_path.exists():
        try:
            with open(manifest_path, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"chunks": [], "completed": []}

def save_manifest(manifest_path: Path, manifest: dict):
    """Saves cache manifest file atomically using a temporary file and replace."""
    temp_path = manifest_path.with_suffix(".tmp")
    try:
        with open(temp_path, "w") as f:
            json.dump(manifest, f, indent=4)
        temp_path.replace(manifest_path)
    except Exception as e:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass
        raise e

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
    openai_key: Optional[str] = None
):
    """
    Asynchronous pipeline task that handles file translation, voice cloning,
    audio chunk generation, and final compilation.
    """
    text_path = None
    voice_path = None
    translated_path = None

    token = current_task_id.set(task_id)
    try:
        progress_store[task_id]["status"] = "Preparing Files"
        logger.info(f"Starting audiobook generation task: {task_id}")

        # 1. Save uploaded text file or text content to a temporary file
        if text_file_data:
            filename, content = text_file_data
            suffix = Path(filename).suffix or ".txt"
            text_path = Path("storage/cache") / f"input_{task_id}{suffix}"
            with open(text_path, "wb") as f:
                f.write(content)
            logger.info(f"Saved uploaded text file to {text_path}")
        elif text_content is not None:
            text_path = Path("storage/cache") / f"input_{task_id}.txt"
            with open(text_path, "w", encoding="utf-8") as f:
                f.write(text_content)
            logger.info(f"Saved text content to temporary file {text_path}")
        else:
            raise ValueError("No text input provided.")

        # 2. Save voice file to a temporary path if provided
        voice_bytes = None
        if voice_file_data:
            filename, content = voice_file_data
            voice_bytes = content
            suffix = Path(filename).suffix or ".mp3"
            voice_path = Path("storage/cache") / f"voice_{task_id}{suffix}"
            with open(voice_path, "wb") as f:
                f.write(content)
            logger.info(f"Saved uploaded voice file to {voice_path}")

        # Read base text content
        from src.core.epub_parser import read_input_text
        text = read_input_text(text_path)

        # Generate cache key using parameters and inputs
        cache_key = get_cache_key(
            text=text,
            voice_preset=voice_preset,
            voice_manual_id=voice_manual_id,
            voice_bytes=voice_bytes,
            source_lang=source_lang,
            target_lang=target_lang
        )
        cache_dir = Path("storage/cache") / cache_key
        cache_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = cache_dir / "manifest.json"

        # 3. Translation step
        if target_lang:
            progress_store[task_id]["status"] = "Translating"
            source = source_lang or "English"
            logger.info(f"Translating text from {source} to {target_lang}...")
            translation_client = MistralTTSClient(api_key=api_key)
            translated_path = await translation_client.translate_file(text_path, source, target_lang)
            logger.info(f"Translation completed. Translated file: {translated_path}")
            with open(translated_path, "r", encoding="utf-8") as f:
                text = f.read()

        # 4. Split text into semantic chunks
        progress_store[task_id]["status"] = "Splitting Text"
        splitter = TextSplitter()
        chunks = splitter.split(text)
        total_chunks = len(chunks)
        logger.info(f"Text split into {total_chunks} semantic chunks.")
        if total_chunks == 0:
            raise ValueError("The split text has 0 chunks.")

        # Resolve correct TTS API key and client
        tts_api_key = openai_key if engine == "openai" else api_key
        client = get_tts_client(engine, tts_api_key)

        # 5. Clone or configure voice
        progress_store[task_id]["status"] = "Configuring Voice"
        if engine == "openai":
            voice_id = voice_preset or voice_manual_id or "alloy"
            logger.info(f"Setting OpenAI voice to: {voice_id}")
            client.set_voice_id(voice_id)
        else:
            # engine == "mistral"
            if voice_path:
                logger.info("Cloning voice profile from uploaded file...")
                await client.clone_voice(voice_path)
            elif voice_preset:
                logger.info(f"Setting voice preset to: {voice_preset}")
                client.set_voice_id(voice_preset)
            elif voice_manual_id:
                logger.info(f"Setting voice ID to: {voice_manual_id}")
                client.set_voice_id(voice_manual_id)
            else:
                logger.info("No voice specified. Defaulting to en_paul_neutral.")
                client.set_voice_id("en_paul_neutral")

        # 6. Load manifest and generate audio chunks
        progress_store[task_id]["status"] = "Generating Audio"
        manifest = load_manifest(manifest_path)
        manifest["chunks"] = chunks

        chunk_files = []
        for i, chunk in enumerate(chunks):
            chunk_filename = f"chunk_{i:04d}.mp3"
            chunk_path = cache_dir / chunk_filename
            chunk_files.append(chunk_path)

            if (
                chunk_filename in manifest.get("completed", [])
                and len(manifest.get("chunks", [])) > i
                and manifest["chunks"][i] == chunk
                and chunk_path.exists()
                and chunk_path.stat().st_size > 0
            ):
                logger.info(f"Chunk {i+1}/{total_chunks} already generated (cached).")
                percentage = int(((i + 1) / total_chunks) * 90)
                progress_store[task_id]["percentage"] = percentage
                continue

            logger.info(f"Generating audio for chunk {i+1}/{total_chunks}...")
            await client.generate_audio(chunk, chunk_path)

            if "completed" not in manifest:
                manifest["completed"] = []
            manifest["completed"].append(chunk_filename)
            save_manifest(manifest_path, manifest)

            percentage = int(((i + 1) / total_chunks) * 90)
            progress_store[task_id]["percentage"] = percentage

        # 7. Compile final audiobook
        progress_store[task_id]["status"] = "Compiling Audiobook"
        logger.info("Compiling final audiobook file...")
        compiler = AudioCompiler()
        output_path = Path("storage/output") / output_filename
        await asyncio.to_thread(compiler.compile, chunk_files, output_path)
        logger.info(f"Audiobook compiled successfully. Saved to {output_path}")

        # 8. Mark task as completed
        progress_store[task_id]["percentage"] = 100
        progress_store[task_id]["status"] = "Completed"
        progress_store[task_id]["completed"] = True
        progress_store[task_id]["audio_file"] = output_filename

    except Exception as e:
        logger.error(f"Error in generation pipeline: {e}", exc_info=True)
        if task_id in progress_store:
            progress_store[task_id]["status"] = "Failed"
            progress_store[task_id]["error"] = str(e)
    finally:
        current_task_id.reset(token)

        # Clean up temporary uploaded text, voice, and translated files
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
        if translated_path and translated_path.exists():
            try:
                translated_path.unlink()
            except Exception as e:
                logger.warning(f"Failed to delete temporary translated file {translated_path}: {e}")

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

@app.post("/api/auth/change-password")
def change_password(request: ChangePasswordRequest, session: str = Depends(verify_session)):
    """
    Endpoint to change the password for the current user.
    Persists the new password to storage/auth.json so it survives restarts.
    """
    global APP_PASSWORD
    
    # Verify current password
    if not secrets.compare_digest(request.current_password, APP_PASSWORD):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Incorrect current password"
        )
    
    # Validate new password
    if not request.new_password or len(request.new_password.strip()) < 4:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be at least 4 characters long"
        )
        
    # Persist the new credentials
    try:
        with open(AUTH_FILE, "w") as f:
            json.dump({"username": APP_USERNAME, "password": request.new_password}, f, indent=4)
        
        # Update in-memory
        APP_PASSWORD = request.new_password
        logger.info(f"Password successfully changed for user: {APP_USERNAME}")
        return {"message": "Password updated successfully. Please log in with your new credentials."}
    except Exception as e:
        logger.error(f"Failed to persist new password: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save new password to disk"
        )

class LoginRequest(BaseModel):
    username: str
    password: str

@app.post("/api/auth/login")
def login(request: LoginRequest, response: Response):
    """
    Verifies credentials and sets a session cookie.
    """
    is_correct_username = secrets.compare_digest(request.username, APP_USERNAME)
    is_correct_password = secrets.compare_digest(request.password, APP_PASSWORD)
    if not (is_correct_username and is_correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password"
        )
    
    session_id = str(uuid.uuid4())
    active_sessions.add(session_id)
    response.set_cookie(
        key="session_id",
        value=session_id,
        httponly=True,
        samesite="lax",
        secure=False
    )
    return {"message": "Login successful"}

@app.post("/api/auth/logout")
def logout(request: Request, response: Response):
    """
    Clears the session cookie and removes the session from memory.
    """
    session_id = request.cookies.get("session_id")
    if session_id in active_sessions:
        active_sessions.remove(session_id)
    response.delete_cookie(key="session_id")
    return {"message": "Logged out successfully"}

@app.get("/api/auth/status")
def get_auth_status(request: Request):
    """
    Returns the current authentication status of the user.
    """
    session_id = request.cookies.get("session_id")
    if session_id and session_id in active_sessions:
        return {"authenticated": True, "username": APP_USERNAME}
    return {"authenticated": False}

@app.get("/")
def read_root():
    """Serves the main frontend page."""
    return FileResponse("src/web/static/index.html")

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
async def get_progress(task_id: str = Query(...), session: str = Depends(verify_session)):
    """
    Returns an SSE stream yielding progress updates as JSON-encoded string events.
    """
    if task_id not in progress_store:
        raise HTTPException(status_code=404, detail="Task not found")

    async def event_generator():
        while True:
            task_state = progress_store.get(task_id)
            if not task_state:
                break
            yield f"data: {json.dumps(task_state)}\n\n"
            if task_state.get("completed") or task_state.get("error") or task_state.get("status") == "Failed":
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.post("/api/generate")
async def generate_audiobook(
    background_tasks: BackgroundTasks,
    text_file: Optional[UploadFile] = File(None),
    text_content: Optional[str] = Form(None),
    voice_file: Optional[UploadFile] = File(None),
    voice_preset: Optional[str] = Form(None),
    voice_manual_id: Optional[str] = Form(None),
    source_lang: Optional[str] = Form(None),
    target_lang: Optional[str] = Form(None),
    output_filename: str = Form("audiobook.mp3"),
    api_key: Optional[str] = Form(None),
    engine: str = Form("mistral"),
    openai_key: Optional[str] = Form(None),
    session: str = Depends(verify_session)
):
    """
    Triggers the background generation task and returns a unique task ID immediately.
    Includes eviction of tasks older than 24 hours to prevent memory leaks.
    """
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

    # Sanitize and validate the output audiobook filename to prevent path traversal
    safe_filename = Path(output_filename).name
    if not safe_filename or safe_filename.startswith(".") or Path(safe_filename).suffix.lower() not in (".mp3", ".m4b", ".wav"):
        raise HTTPException(status_code=400, detail="Invalid output filename. Must be a valid audio file name.")

    # Prevent memory leaks: evict progress store tasks older than 24 hours, but only if they are in terminal states
    now = time.time()
    expired_tasks = [
        tid for tid, state in progress_store.items()
        if now - state.get("created_at", 0) > 86400 and state.get("status") in ("Completed", "Failed")
    ]
    for tid in expired_tasks:
        try:
            del progress_store[tid]
        except KeyError:
            pass

    task_id = str(uuid.uuid4())

    # Read uploaded file contents in the request handler to prevent closed file descriptors in background task
    text_file_data = None
    if text_file:
        text_bytes = await text_file.read()
        text_file_data = (text_file.filename, text_bytes)

    voice_file_data = None
    if voice_file:
        voice_bytes = await voice_file.read()
        voice_file_data = (voice_file.filename, voice_bytes)

    # Initialize task state in progress store
    progress_store[task_id] = {
        "percentage": 0,
        "status": "Pending",
        "logs": [],
        "completed": False,
        "audio_file": None,
        "error": None,
        "created_at": now
    }

    # Enqueue background execution task
    background_tasks.add_task(
        run_generation_pipeline,
        task_id=task_id,
        api_key=resolved_mistral_key,
        openai_key=resolved_openai_key,
        text_content=text_content,
        text_file_data=text_file_data,
        voice_file_data=voice_file_data,
        voice_preset=voice_preset,
        voice_manual_id=voice_manual_id,
        source_lang=source_lang,
        target_lang=target_lang,
        output_filename=safe_filename,
        engine=engine
    )

    return {"task_id": task_id}

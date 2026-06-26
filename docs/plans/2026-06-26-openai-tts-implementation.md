# OpenAI TTS Support Implementation Plan

> **For Gemini:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Integrate the OpenAI TTS API alongside the existing Mistral Voxtral engine, enabling high-quality audio generation in languages not natively supported by Mistral (such as Polish), with full CLI, TUI, and WebUI support.

**Architecture:** We use a Unified Provider Interface (Factory Pattern) to decouple the caller code from specific API clients. The translation step is decoupled so that Mistral Large continues to handle translation using the Mistral key, while the TTS phase uses either Mistral or OpenAI depending on the selected engine.

**Tech Stack:** Python 3.11, FastAPI, Textual (TUI), HTML/CSS/JS (vanilla, glassmorphism), `httpx` (asynchronous HTTP requests for OpenAI TTS).

---

### Task 1: Create Unified TTS Interface & Factory

**Files:**
- Create: `src/api/base_client.py`
- Create: `src/api/factory.py`
- Create: `tests/test_factory.py`

**Step 1: Write the failing test**
Create `tests/test_factory.py`:
```python
import pytest
from src.api.factory import get_tts_client
from src.api.base_client import BaseTTSClient

def test_factory_returns_correct_clients():
    # Since we don't have mock keys, we just check instantiation or types
    with pytest.raises(ValueError):
        get_tts_client("invalid-engine", "dummy-key")
```

**Step 2: Run test to verify it fails**
Run: `PYTHONPATH=. pytest tests/test_factory.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.api.base_client'`

**Step 3: Write minimal implementation**
Create `src/api/base_client.py`:
```python
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Dict

class BaseTTSClient(ABC):
    def __init__(self, api_key: str):
        self.api_key = api_key.strip()

    @abstractmethod
    async def generate_audio(self, text: str, output_path: Path, retry_count: int = 3) -> None:
        pass

    @abstractmethod
    async def list_voices(self, retry_count: int = 3) -> List[Dict[str, str]]:
        pass

    @abstractmethod
    async def clone_voice(self, audio_path: Path) -> str:
        pass
```

Create `src/api/factory.py`:
```python
from src.api.base_client import BaseTTSClient
from src.api.mistral_client import MistralTTSClient

def get_tts_client(engine: str, api_key: str) -> BaseTTSClient:
    engine = engine.strip().lower()
    if engine == "mistral":
        return MistralTTSClient(api_key=api_key)
    elif engine == "openai":
        from src.api.openai_client import OpenAITTSClient
        return OpenAITTSClient(api_key=api_key)
    else:
        raise ValueError(f"Unknown TTS engine: {engine}")
```

**Step 4: Run test to verify it passes**
Run: `PYTHONPATH=. pytest tests/test_factory.py -v`
Expected: PASS

**Step 5: Commit**
```bash
git add src/api/base_client.py src/api/factory.py tests/test_factory.py
git commit -m "feat: add BaseTTSClient interface and get_tts_client factory"
```

---

### Task 2: Refactor MistralTTSClient to Inherit from BaseTTSClient

**Files:**
- Modify: `src/api/mistral_client.py:1-24`
- Test: `tests/test_epub.py` (ensure existing tests still pass)

**Step 1: Check existing tests**
Run: `PYTHONPATH=. pytest tests/test_epub.py -v`
Expected: PASS (current tests pass)

**Step 2: Modify MistralTTSClient to inherit from BaseTTSClient**
In `src/api/mistral_client.py`:
```python
from src.api.base_client import BaseTTSClient

class MistralTTSClient(BaseTTSClient):
    """
    Wrapper for Mistral AI Voxtral API interaction, including voice cloning
    and asynchronous text-to-speech generation.
    """

    def __init__(self, api_key: str):
        super().__init__(api_key)
        self.client = Mistral(api_key=self.api_key)
        self.model = "voxtral-mini-tts-2603"
        self.voice_sample_path: Optional[Path] = None
        self.voice_id: Optional[str] = None
```

**Step 3: Run tests to verify inheritance doesn't break behavior**
Run: `PYTHONPATH=. pytest tests/test_epub.py -v`
Expected: PASS

**Step 4: Commit**
```bash
git add src/api/mistral_client.py
git commit -m "refactor: make MistralTTSClient inherit from BaseTTSClient"
```

---

### Task 3: Implement OpenAITTSClient

**Files:**
- Create: `src/api/openai_client.py`
- Create: `tests/test_openai_client.py`

**Step 1: Write failing/mock tests for OpenAITTSClient**
Create `tests/test_openai_client.py`:
```python
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from src.api.openai_client import OpenAITTSClient

@pytest.mark.asyncio
async def test_openai_list_voices():
    client = OpenAITTSClient(api_key="dummy-key")
    voices = await client.list_voices()
    assert len(voices) == 6
    assert voices[0]["id"] == "alloy"

@pytest.mark.asyncio
async def test_openai_clone_voice_raises_error():
    client = OpenAITTSClient(api_key="dummy-key")
    with pytest.raises(NotImplementedError):
        await client.clone_voice(Path("dummy.mp3"))

@pytest.mark.asyncio
@patch("httpx.AsyncClient.post")
async def test_openai_generate_audio(mock_post):
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.content = b"fake-audio-bytes"
    mock_post.return_value = mock_response

    client = OpenAITTSClient(api_key="dummy-key")
    out_path = Path("storage/cache/test_openai.mp3")
    
    try:
        await client.generate_audio("Hello", out_path)
        assert out_path.exists()
        assert out_path.read_bytes() == b"fake-audio-bytes"
    finally:
        if out_path.exists():
            out_path.unlink()
```

**Step 2: Run tests to verify they fail**
Run: `PYTHONPATH=. pytest tests/test_openai_client.py -v`
Expected: FAIL (ModuleNotFoundError: No module named 'src.api.openai_client')

**Step 3: Write OpenAITTSClient implementation**
Create `src/api/openai_client.py`:
```python
import httpx
import logging
from pathlib import Path
from typing import List, Dict
from src.api.base_client import BaseTTSClient

logger = logging.getLogger(__name__)

class OpenAITTSClient(BaseTTSClient):
    """
    Asynchronous client for the OpenAI TTS API.
    Uses httpx for lightweight and robust API calls.
    """

    def __init__(self, api_key: str):
        super().__init__(api_key)
        self.api_url = "https://api.openai.com/v1/audio/speech"
        self.model = "tts-1"
        self.voice_id = "alloy"  # Default voice

    async def list_voices(self, retry_count: int = 3) -> List[Dict[str, str]]:
        """Returns the 6 standard OpenAI TTS voices."""
        return [
            {"id": "alloy", "name": "Alloy (Neutral)"},
            {"id": "echo", "name": "Echo (Balanced)"},
            {"id": "fable", "name": "Fable (Narrative)"},
            {"id": "onyx", "name": "Onyx (Deep/Male)"},
            {"id": "nova", "name": "Nova (Energetic/Female)"},
            {"id": "shimmer", "name": "Shimmer (Professional)"},
        ]

    def set_voice_id(self, voice_id: str):
        """Sets the selected preset voice ID."""
        self.voice_id = voice_id.strip().lower()

    async def clone_voice(self, audio_path: Path) -> str:
        """OpenAI TTS does not support voice cloning."""
        raise NotImplementedError("OpenAI TTS does not support zero-shot voice cloning.")

    async def generate_audio(self, text: str, output_path: Path, retry_count: int = 3) -> None:
        """Generates audio chunk using OpenAI TTS API with retry logic."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model,
            "input": text,
            "voice": self.voice_id,
            "response_format": "mp3"
        }

        for attempt in range(retry_count):
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    response = await client.post(self.api_url, headers=headers, json=payload)
                    
                    if response.status_code == 200:
                        output_path.write_bytes(response.content)
                        logger.info(f"Successfully generated OpenAI TTS audio for: {output_path}")
                        return
                    else:
                        error_detail = response.text
                        logger.warning(
                            f"OpenAI API returned status {response.status_code} on attempt {attempt + 1}: {error_detail}"
                        )
                        raise ValueError(f"OpenAI TTS API Error: Status {response.status_code} - {error_detail}")
            except Exception as e:
                logger.warning(f"Attempt {attempt + 1} failed for OpenAI TTS chunk {output_path}: {e}")
                if attempt < retry_count - 1:
                    import asyncio
                    await asyncio.sleep(2 ** attempt)
                else:
                    logger.error(f"Failed to generate OpenAI audio after {retry_count} attempts.")
                    raise
```

**Step 4: Run tests to verify they pass**
Run: `PYTHONPATH=. pytest tests/test_openai_client.py -v`
Expected: PASS

**Step 5: Commit**
```bash
git add src/api/openai_client.py tests/test_openai_client.py
git commit -m "feat: implement OpenAITTSClient using httpx"
```

---

### Task 4: Update CLI with Engine Selection and Validation

**Files:**
- Modify: `src/cli.py`
- Create: `tests/test_cli_integration.py`

**Step 1: Write integration tests for CLI validation**
Create `tests/test_cli_integration.py`:
```python
import pytest
from src.cli import BooksmithCLI
from pathlib import Path

def test_cli_validation_openai_cloning():
    # Verify that choosing openai engine and a voice path raises ValueError
    cli = BooksmithCLI(api_key="dummy-openai-key")
    with pytest.raises(ValueError, match="OpenAI TTS does not support voice cloning"):
        import asyncio
        asyncio.run(cli.run(
            text_path=Path("tests/data/sample.txt"),
            voice_path=Path("tests/data/sample.mp3"),
            output_path=Path("output.mp3"),
            engine="openai"
        ))
```

**Step 2: Run CLI tests to verify they fail**
Run: `PYTHONPATH=. pytest tests/test_cli_integration.py -v`
Expected: FAIL (TypeError or ValueError mismatch because `engine` is not yet supported in `cli.py`)

**Step 3: Modify `src/cli.py` to support engine selection and validation**
Modify `src/cli.py` to:
1. Accept `engine` in `BooksmithCLI` constructor or `run()` method.
2. Resolve correct API key depending on engine.
3. Use factory: `client = get_tts_client(engine, tts_api_key)`.
4. Validate that if `engine == "openai"`, `voice_path` is not passed for cloning.
5. Add `--engine` and `--openai-key` in `main()` parser.

**Step 4: Run tests to verify they pass**
Run: `PYTHONPATH=. pytest tests/test_cli_integration.py -v`
Expected: PASS

**Step 5: Commit**
```bash
git add src/cli.py tests/test_cli_integration.py
git commit -m "feat: add engine selection and validation to CLI"
```

---

### Task 5: Update TUI with Dynamic Engine & Voice Selection

**Files:**
- Modify: `src/tui.py`

**Step 1: Modify TUI class variables and compose()**
In `src/tui.py`:
- Add `OPENAI_VOICES` list.
- In `compose()`, add an **Engine** select menu and an **OpenAI API Key** input.
- Add event handler `on_select_changed` to update the voice select list and disable voice cloning input when engine is set to `openai`.
- Update `start_processing()` and `process_book()` to read these values and use the factory to get the client.

**Step 2: Verify TUI loads correctly**
Run: `PYTHONPATH=. python3 src/cli.py --tui`
Expected: TUI displays the new Engine select field and OpenAI Key field.

**Step 3: Commit**
```bash
git add src/tui.py
git commit -m "feat: add dynamic engine selection and voice list updates to TUI"
```

---

### Task 6: Update Web Backend with Engine Selection

**Files:**
- Modify: `src/web.py`
- Modify: `tests/test_web.py`

**Step 1: Write failing test in `tests/test_web.py`**
Modify `tests/test_web.py` to add a test validating the `/api/generate` endpoint for OpenAI validation:
```python
def test_generate_openai_voice_cloning_error(client):
    response = client.post(
        "/api/generate",
        data={
            "engine": "openai",
            "voice_preset": "alloy",
            "text_content": "Test text",
            "api_key": "dummy-key"
        },
        files={
            "voice_file": ("voice.mp3", b"fake-audio-data", "audio/mpeg")
        }
    )
    assert response.status_code == 400
    assert "does not support voice cloning" in response.json()["detail"]
```

**Step 2: Run web tests to verify they fail**
Run: `PYTHONPATH=. pytest tests/test_web.py -v`
Expected: FAIL

**Step 3: Modify `src/web.py` to support engine parameters**
In `src/web.py`:
- In `generate_audiobook` endpoint, accept `engine` and `openai_key`.
- Perform strict validation (error if `engine == "openai"` and `voice_file` is uploaded).
- Pass `engine` and `openai_key` down to `run_generation_pipeline()` in background tasks.
- In `run_generation_pipeline()`, retrieve the correct client using the factory: `client = get_tts_client(engine, api_key)`.

**Step 4: Run web tests to verify they pass**
Run: `PYTHONPATH=. pytest tests/test_web.py -v`
Expected: PASS

**Step 5: Commit**
```bash
git add src/web.py tests/test_web.py
git commit -m "feat: integrate OpenAI TTS engine support and validation in web backend"
```

---

### Task 7: Update Web Frontend (HTML, CSS, JS)

**Files:**
- Modify: `src/web/static/index.html`
- Modify: `src/web/static/app.js`
- Modify: `src/web/static/styles.css`

**Step 1: Modify `index.html`**
- Add Engine select dropdown.
- Add OpenAI API Key input field container.

**Step 2: Modify `app.js`**
- Listen for engine change to show/hide OpenAI Key field and update voice presets.
- Pack `engine` and `openai_key` in `FormData` sent to `/api/generate`.

**Step 3: Manually test WebUI in browser**
- Start the server: `python3 -m uvicorn src.web:app --host 0.0.0.0 --port 8000`
- Verify engine toggling works and generates speech correctly.

**Step 4: Commit**
```bash
git add src/web/static/index.html src/web/static/app.js src/web/static/styles.css
git commit -m "feat: add engine toggles, dynamic voice presets, and key inputs to WebUI frontend"
```

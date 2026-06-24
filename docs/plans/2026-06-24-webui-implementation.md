# WebUI MVP Implementation Plan

> **For Gemini:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create a simple, zero-setup, premium WebUI MVP for Mistral-TTS-Booksmith using FastAPI and a Vanilla HTML/CSS/JS Single-Page Application.

**Architecture:** Implement a FastAPI server in `src/web.py` that serves a Single-Page Application from `src/web/static/`. The server handles background TTS pipeline tasks, streams progress updates to the client via Server-Sent Events (SSE), and serves the compiled audiobooks.

**Tech Stack:** Python, FastAPI, Uvicorn, python-multipart, HTML5, CSS3, Vanilla JavaScript.

---

### Task 1: Add Dependencies

**Files:**
- Modify: `requirements.txt`

**Step 1: Add dependencies to requirements.txt**
Append `fastapi`, `uvicorn`, and `python-multipart` to `requirements.txt`:
```
fastapi
uvicorn
python-multipart
```

**Step 2: Install dependencies**
Run: `pip install -r requirements.txt`

**Step 3: Commit**
```bash
git add requirements.txt
git commit -m "chore: add fastapi, uvicorn, and python-multipart dependencies"
```

---

### Task 2: Implement FastAPI Backend

**Files:**
- Create: `src/web.py`

**Step 1: Write backend implementation**
Create `src/web.py` to:
- Serve the static frontend SPA (`/` and `/static`).
- Implement `POST /api/generate` to start background tasks and return a `task_id`.
- Implement `GET /api/progress` to stream progress and logs via SSE.
- Implement `GET /api/audio/{filename}` to serve output files.
- Integrate directly with `MistralTTSClient`, `TextSplitter`, and `AudioCompiler`.

**Step 2: Commit**
```bash
git add src/web.py
git commit -m "feat: implement FastAPI backend with background tasks and SSE"
```

---

### Task 3: Create Frontend HTML

**Files:**
- Create: `src/web/static/index.html`

**Step 1: Write index.html**
Create `src/web/static/index.html` with:
- Standard HTML5 semantic structure.
- Inter font from Google Fonts.
- Form inputs for text (file + textarea), voice (preset dropdown, manual ID, file upload), translation toggles, and output path.
- Real-time progress dashboard container (animated progress bar, active status, log console).
- Audio player card container.

**Step 2: Commit**
```bash
git add src/web/static/index.html
git commit -m "feat: create WebUI HTML5 single-page application structure"
```

---

### Task 4: Create Frontend CSS

**Files:**
- Create: `src/web/static/styles.css`

**Step 1: Write styles.css**
Create `src/web/static/styles.css` with:
- Deep slate-gray theme (`#0f172a`, `#1e293b`).
- Modern violet accents (`#6366f1`).
- Card layouts with glassmorphism borders and shadows.
- Micro-animations for button hovers, active progress bar gradients, and smooth transition states.

**Step 2: Commit**
```bash
git add src/web/static/styles.css
git commit -m "feat: design WebUI CSS with dark theme and glassmorphism cards"
```

---

### Task 5: Create Frontend JavaScript

**Files:**
- Create: `src/web/static/app.js`

**Step 1: Write app.js**
Create `src/web/static/app.js` to:
- Handle form submissions and asynchronous file uploads via `fetch` and `FormData`.
- Establish an `EventSource` connection to the SSE progress endpoint.
- Dynamically update the progress bar, status text, and console logs.
- Reveal the custom audio player on completion.

**Step 2: Commit**
```bash
git add src/web/static/app.js
git commit -m "feat: implement WebUI JavaScript for form handling and SSE progress tracking"
```

---

### Task 6: Implement Web Integration Tests

**Files:**
- Create: `tests/test_web.py`

**Step 1: Write test_web.py**
Create `tests/test_web.py` to:
- Test routing and static file rendering.
- Assert that `POST /api/generate` returns a `task_id` and registers background tasks correctly.
- Verify basic API error handling.

**Step 2: Run tests**
Run: `PYTHONPATH=. pytest tests/test_web.py -v`

**Step 3: Commit**
```bash
git add tests/test_web.py
git commit -m "test: add integration tests for FastAPI web server"
```

---

### Task 7: Update Dockerfile and README.md

**Files:**
- Modify: `Dockerfile`
- Modify: `README.md`

**Step 1: Update Dockerfile**
Expose port 8000 and document how to run the web server.

**Step 2: Update README.md**
Add instructions for running the WebUI locally (`python3 -m uvicorn src.web:app --reload`) and using Docker.

**Step 3: Commit**
```bash
git add Dockerfile README.md
git commit -m "docs: document WebUI usage and update Dockerfile to expose web service"
```

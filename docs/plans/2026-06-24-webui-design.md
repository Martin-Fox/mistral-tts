# WebUI MVP Design Document

**Date:** 2026-06-24  
**Feature:** WebUI MVP  
**Status:** Validated  

---

## 1. Architecture & Backend API

We will implement a lightweight, fast, and asynchronous web server using **FastAPI** and **uvicorn**. The server will be located in `src/web.py` and will serve both the static Single-Page Application (SPA) frontend and the required API endpoints.

### Endpoints
* `GET /`: Serves the Single-Page Application (`index.html`).
* `GET /static/{path:path}`: Serves static assets (HTML, CSS, JS) from the `src/web/static/` directory.
* `POST /api/generate`: Receives generation parameters as a multipart/form-data request (allowing raw text input or file uploads, preset voice or audio file uploads for cloning, optional translation, and output path). Initiates the audiobook generation as an asynchronous background task, returning a unique `task_id` immediately.
* `GET /api/progress`: A Server-Sent Events (SSE) endpoint (`text/event-stream`) that streams live status updates, chunk generation progress (percentages), and logs to the client based on the provided `task_id`.
* `GET /api/audio/{filename}`: Serves the final compiled audiobook file from `storage/output/` for in-browser playback.

### Code Reuse
The backend will directly import and utilize the existing business logic:
* `MistralTTSClient` (from `src/api/mistral_client.py`) for Voxtral API interaction and translation.
* `TextSplitter` (from `src/core/text_splitter.py`) for semantic paragraph chunking.
* `AudioCompiler` (from `src/core/audio_compiler.py`) for stitching chunks via FFmpeg.

---

## 2. Frontend & Design Aesthetics

The frontend is a single-page application built using vanilla HTML5, CSS3, and JavaScript, located in the `src/web/static/` directory.

### Visual Aesthetics
* **Theme:** Premium, dark-mode styling utilizing a deep space-gray background (`#0f172a`), dark slate cards (`#1e293b`), and vibrant indigo/violet accents (`#6366f1`).
* **Typography:** Modern, clean typography using Google Fonts (Inter).
* **Components:** Card-based layouts featuring subtle glassmorphic borders and shadows. Hover states and transition animations will make the interface feel alive and highly responsive.

### Components
1. **Configuration Form:**
   - **Text Input:** Drag-and-drop file upload area + collapsible textarea.
   - **Voice Configuration:** Toggle between preset voice dropdown, manual voice ID input, or audio file upload (`.mp3`/`.wav`) for zero-shot cloning.
   - **Translation Toggle:** Optional source and target language selectors.
   - **Start Button:** Prominent, styled action button to initiate generation.
2. **Real-time Progress Dashboard:** (Revealed smoothly on start)
   - **Progress Bar:** Smoothly animated gradient-filled progress bar showing percentage completion.
   - **Status Badge:** Dynamic status indicator (e.g., *Translating*, *Generating Chunks (5/10)*, *Compiling Audio*).
   - **Live Logs:** Scrollable terminal-style console log box streaming live execution logs.
3. **Audiobook Player Card:** (Revealed on completion)
   - A custom-styled HTML5 audio player containing the compiled audiobook with download option.

---

## 3. Data Flow & Error Handling

### Data Flow
1. User configures parameters and clicks "Generate".
2. Frontend uploads data via `FormData` to `POST /api/generate`.
3. Backend saves any uploaded files, registers a background task with a unique `task_id`, and responds with `{"task_id": "..."}`.
4. Frontend connects to the SSE endpoint `GET /api/progress?task_id=<task_id>`.
5. Background task runs the TTS pipeline, sending status and log updates to a shared memory registry.
6. SSE endpoint streams events to the frontend.
7. Upon completion, a final event sends the audio URL. Frontend displays the audio player card.

### Error Handling
* **API/Network Failures:** Caught in the backend worker, logged, and pushed to the frontend via SSE. The frontend displays a prominent red alert banner and stops the progress indicators.
* **Resumability:** Leverages the existing `manifest.json` cache in `storage/cache/`. If a run fails or is stopped, the user can re-submit the form, and the backend will automatically skip completed chunks and resume from where it left off.

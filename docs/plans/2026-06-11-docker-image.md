# Docker Image Implementation Plan

> **For Gemini:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create a Dockerfile and .dockerignore for Mistral-TTS-Booksmith to package the application with Python 3.11-slim and FFmpeg for zero-configuration deployments.

**Architecture:** Build a single-stage Docker image based on `python:3.11-slim` that installs `ffmpeg` via apt-get, installs python dependencies from `requirements.txt`, copies the source code, and sets `src/cli.py` as the entrypoint with `--tui` as the default command.

**Tech Stack:** Docker, Python 3.11, FFmpeg, Debian Slim.

---

### Task 1: Create .dockerignore

**Files:**
- Create: `/.dockerignore`

**Step 1: Write .dockerignore content**

Create `/.dockerignore` with the following content:
```
__pycache__/
*.pyc
*.pyo
*.pyd
.git/
.env
.pytest_cache/
.ruff_cache/
storage/cache/*
storage/output/*
```

**Step 2: Commit**

```bash
git add .dockerignore
git commit -m "chore: add .dockerignore file"
```

---

### Task 2: Create Dockerfile

**Files:**
- Create: `/Dockerfile`

**Step 1: Write Dockerfile content**

Create `/Dockerfile` with the following content:
```dockerfile
# Use official slim Python image as base
FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    DEBIAN_FRONTEND=noninteractive

# Install system dependencies (ffmpeg is required for audio compiling)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy dependency definition
COPY requirements.txt .

# Install python packages
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code and tests
COPY src/ ./src/
COPY tests/ ./tests/
COPY storage/ ./storage/

# Set entrypoint to run the cli.py application
ENTRYPOINT ["python", "src/cli.py"]

# Default command runs the TUI
CMD ["--tui"]
```

**Step 2: Commit**

```bash
git add Dockerfile
git commit -m "feat: add Dockerfile"
```

---

### Task 3: Verify the Docker Image

**Files:**
- Modify: `README.md` (to document how to build and run the Docker container)

**Step 1: Build the Docker image**

Run: `docker build -t mistral-tts-booksmith:latest .`
Expected: Successful build ending with naming the image.

**Step 2: Run tests inside the Docker container**

Run: `docker run --entrypoint python mistral-tts-booksmith:latest -m pytest`
Expected: 7 tests passed successfully.

**Step 3: Document Docker usage in README.md**

Update `README.md` to include a Docker section:
```markdown
### Docker Setup

You can build and run the application using Docker to avoid installing system-level dependencies like FFmpeg:

1. Build the Docker image:
   ```bash
   docker build -t mistral-tts-booksmith .
   ```

2. Run the interactive TUI:
   ```bash
   docker run -it --rm \
     -v $(pwd)/storage:/app/storage \
     -e MISTRAL_API_KEY=your_key \
     mistral-tts-booksmith
   ```

3. Run standard CLI command:
   ```bash
   docker run --rm \
     -v $(pwd)/storage:/app/storage \
     -v $(pwd)/your_text_dir:/app/data \
     -e MISTRAL_API_KEY=your_key \
     mistral-tts-booksmith \
     --text /app/data/book.txt \
     --voice /app/data/sample.mp3 \
     --output /app/storage/output/audiobook.mp3
   ```
```

**Step 4: Commit**

```bash
git add README.md
git commit -m "docs: add Docker usage guidelines to README.md"
```

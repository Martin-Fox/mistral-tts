# Use official slim Python image as base
FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    DEBIAN_FRONTEND=noninteractive

# Install system dependencies (ffmpeg is required for audio compiling, gosu for safe privilege dropping)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    gosu \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user
RUN useradd -u 1000 -m appuser

# Set working directory
WORKDIR /app
RUN chown appuser:appuser /app

# Copy dependency definition
COPY --chown=appuser:appuser requirements.txt .

# Install python packages
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code and tests
COPY --chown=appuser:appuser src/ ./src/
COPY --chown=appuser:appuser tests/ ./tests/

# Prepare default storage directories
RUN mkdir -p storage/cache storage/output storage/translations && chown -R appuser:appuser storage

# Copy entrypoint script to fix volume permissions and drop to appuser
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Expose WebUI port
EXPOSE 8000

# Set entrypoint
ENTRYPOINT ["docker-entrypoint.sh"]

# Default command runs the WebUI
CMD ["uvicorn", "src.web:app", "--host", "0.0.0.0", "--port", "8000"]

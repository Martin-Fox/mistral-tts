# Use official slim Python image as base
FROM python:3.11-slim-trixie@sha256:07d4824036af339fa1b6ef769cc99d9c10a141769538b52b3b597c84f7a7b535 AS base

# Build only the audio components used by this application. No distro FFmpeg,
# video/network demuxers or libxml2 are needed in the runtime dependency graph.
FROM base AS ffmpeg-build
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential ca-certificates curl nasm pkg-config libmp3lame-dev \
    && rm -rf /var/lib/apt/lists/*
COPY scripts/build_ffmpeg.sh /usr/local/bin/build-booksmith-ffmpeg
RUN curl --fail --show-error --location --proto '=https' --tlsv1.2 \
    https://ffmpeg.org/releases/ffmpeg-9.0.2.tar.xz -o /tmp/ffmpeg.tar.xz \
    && sh /usr/local/bin/build-booksmith-ffmpeg /tmp/ffmpeg.tar.xz /opt/ffmpeg

FROM base AS runtime

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    DEBIAN_FRONTEND=noninteractive

# Runtime libraries only; the MP3 encoder is dynamically linked for apt updates.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmp3lame0 \
    gosu \
    util-linux \
    zlib1g \
    && dpkg --compare-versions "$(dpkg-query -W -f='${Version}' zlib1g)" ge '1:1.3.dfsg+really1.3.1-1+deb13u1' \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ffmpeg-build /opt/ffmpeg/bin/ /usr/local/bin/
COPY --from=ffmpeg-build /opt/ffmpeg/share/doc/booksmith-ffmpeg/ /usr/local/share/doc/booksmith-ffmpeg/
RUN ffmpeg -version && ffprobe -version \
    && if dpkg-query -W -f='${Status}' libxml2 2>/dev/null | grep -q 'install ok installed'; then \
         echo 'Unexpected libxml2 runtime dependency' >&2; exit 1; \
       fi

# Create a non-root user
RUN useradd -u 1000 -m appuser

# Set working directory
WORKDIR /app
RUN chown appuser:appuser /app

# Copy dependency definition
COPY --chown=appuser:appuser requirements.txt .

# Install python packages
RUN pip install --no-cache-dir --require-hashes --only-binary=:all: -r requirements.txt \
    && pip check \
    && python -m pip uninstall -y setuptools wheel pip

# Copy runtime source only; smoke helpers are mounted by the external test runner.
COPY --chown=appuser:appuser src/ ./src/

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
CMD ["uvicorn", "src.web:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]

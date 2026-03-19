# ── Stage 1: Build worker SDK wheel ──────────────────────────────
FROM python:3.11-slim AS sdk-builder
WORKDIR /build
COPY services/worker_sdk/pyproject.toml .
COPY services/worker_sdk/src/ src/
RUN pip install --no-cache-dir build && python -m build --wheel --outdir /dist

# ── Stage 2: Runtime ─────────────────────────────────────────────
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Install ffmpeg (static build from BtbN) + fontconfig for Korean text
ARG FFMPEG_VERSION=7.1
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl xz-utils fontconfig \
    && curl -fsSL "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-n${FFMPEG_VERSION}-latest-linux64-gpl-${FFMPEG_VERSION}.tar.xz" \
       -o /tmp/ffmpeg.tar.xz \
    && tar -xf /tmp/ffmpeg.tar.xz -C /tmp \
    && cp /tmp/ffmpeg-n${FFMPEG_VERSION}-latest-linux64-gpl-${FFMPEG_VERSION}/bin/ffmpeg /usr/local/bin/ffmpeg \
    && cp /tmp/ffmpeg-n${FFMPEG_VERSION}-latest-linux64-gpl-${FFMPEG_VERSION}/bin/ffprobe /usr/local/bin/ffprobe \
    && chmod +x /usr/local/bin/ffmpeg /usr/local/bin/ffprobe \
    && rm -rf /tmp/ffmpeg* \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install worker SDK
COPY --from=sdk-builder /dist/heimdex_worker_sdk-*.whl /tmp/
RUN pip install --no-cache-dir /tmp/heimdex_worker_sdk-*.whl && rm -f /tmp/*.whl

# Install heimdex-media-contracts + heimdex-media-pipelines
# For production: CI copies sibling repos into build context before build.
# For local dev: these are volume-mounted via docker-compose.
COPY heimdex-media-contracts/ /tmp/heimdex-media-contracts/
RUN pip install --no-cache-dir /tmp/heimdex-media-contracts \
    && rm -rf /tmp/heimdex-media-contracts
COPY heimdex-media-pipelines/ /tmp/heimdex-media-pipelines/
RUN pip install --no-cache-dir "/tmp/heimdex-media-pipelines[composition]" \
    && rm -rf /tmp/heimdex-media-pipelines

# Install remaining Python dependencies
RUN pip install --no-cache-dir \
      "boto3>=1.34" "pydantic-settings>=2.0" \
      "structlog>=23.0" "requests>=2.31"

# Bundle Korean fonts (Task 10)
COPY services/shorts-render-worker/fonts/ /usr/share/fonts/heimdex/
COPY services/shorts-render-worker/fonts.conf /etc/fonts/conf.d/99-heimdex.conf
RUN fc-cache -f -v

# Copy worker source
COPY services/shorts-render-worker/src/ src/

# Create work directory and non-root user
RUN mkdir -p /data \
    && useradd -m -u 1000 appuser \
    && chown -R appuser:appuser /app /data
USER appuser

CMD ["python", "-m", "src.worker"]

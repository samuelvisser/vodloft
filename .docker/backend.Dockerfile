FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
COPY server ./server
RUN uv sync --no-dev

COPY config ./config
RUN mkdir -p /app/data /downloads

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["sh", "-c", "backend-api db upgrade head && exec backend-api serve --host 0.0.0.0 --port 8000"]

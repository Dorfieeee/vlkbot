FROM python:3.12-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_PROJECT_ENV=/app/.venv

WORKDIR /app

# Install build dependencies and uv
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip && pip install "uv>=0.5.0"

# Copy dependency metadata and install deps into a local venv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Copy the actual application code
COPY . .


FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENV=/app/.venv \
    PATH="/app/.venv/bin:${PATH}"

WORKDIR /app

# Copy venv and sources from builder
COPY --from=builder /app/.venv /app/.venv
COPY . .

# By default, configuration is provided via environment variables.
# Example (using a local .env file):
#   docker run --env-file .env ghcr.io/your-org/vlk-discord-bot:latest

CMD ["python", "run.py", "prod"]



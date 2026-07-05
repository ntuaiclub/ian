# Dockerfile

FROM nvidia/cuda:12.1.1-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive

COPY --from=ghcr.io/astral-sh/uv:0.11.23 /uv /uvx /usr/local/bin/

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*


WORKDIR /app

ENV UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_PYTHON=3.11 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

COPY pyproject.toml uv.lock README.md .python-version ./
RUN uv python install 3.11 && \
    uv sync --locked --no-dev --no-install-project

RUN echo "--- Installed Packages List ---" && \
    uv pip list && \
    echo "--- End of List ---"

COPY . .
RUN uv sync --locked --no-dev

EXPOSE 5190

CMD ["ian", "serve"]

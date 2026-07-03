# Dockerfile

FROM nvidia/cuda:12.1.1-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.11 \
    python3.11-venv \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*


WORKDIR /app

RUN python3.11 -m venv /app/venv

ENV PATH="/app/venv/bin:$PATH"

COPY requirements.txt .
RUN python -m pip install --upgrade pip && \
    python -m pip install --no-cache-dir -r requirements.txt

RUN echo "--- Installed Packages List ---" && \
    python -m pip list && \
    echo "--- End of List ---"

COPY . .
RUN python -m pip install --no-cache-dir --no-deps -e .

RUN chmod +x start.sh

EXPOSE 5190

CMD ["./start.sh"]

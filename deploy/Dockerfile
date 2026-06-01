# RL Agent Tutor — Docker image
# Build:   docker build -t rl-agent-tutor -f deploy/Dockerfile .
# Run:     docker compose -f deploy/docker-compose.yml up -d
FROM python:3.11-slim

# git for librarian's GitHub clone, plus a few build essentials for pymupdf
RUN apt-get update && apt-get install -y --no-install-recommends \
    git build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# install deps first for build cache
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir -e .

# workspace will be a mounted volume in compose
VOLUME ["/workspace"]
ENV WORKSPACE_DIR=/workspace

EXPOSE 8765

# default to web; override with `command: rl-agent daemon ...` for the second container
CMD ["rl-agent-web", "--host", "0.0.0.0", "--port", "8765"]

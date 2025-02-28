# Use Python 3.12 slim image
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install poetry
RUN pip install poetry

# Copy project files
COPY pyproject.toml poetry.lock ./
COPY src ./src/
COPY tests ./tests/

# Install dependencies
RUN poetry config virtualenvs.create false && \
    poetry install --no-interaction --no-ansi && \
    pip uninstall -y google-generativeai google-genai && \
    pip install --no-cache-dir google-genai==1.3.0

# Add version labels and environment variables
ARG GIT_COMMIT
ARG GIT_BRANCH
ARG GIT_MAIN_COMMIT
LABEL org.opencontainers.image.revision=$GIT_COMMIT \
      org.opencontainers.image.version="1.0.0" \
      org.opencontainers.image.source="https://github.com/techpriests/discord_local" \
      git.commit=$GIT_COMMIT \
      git.branch=$GIT_BRANCH \
      git.main_commit=$GIT_MAIN_COMMIT

ENV GIT_COMMIT=$GIT_COMMIT \
    GIT_BRANCH=$GIT_BRANCH \
    GIT_MAIN_COMMIT=$GIT_MAIN_COMMIT

# Run bot
CMD ["python", "src/main.py"] 
# Use an official Python runtime as a parent image
FROM python:3.12-slim

# Set the working directory in the container
WORKDIR /app

# Copy dependency files first
COPY pyproject.toml poetry.lock ./

# Install dependencies in a separate layer
# This layer will be cached unless pyproject.toml or poetry.lock changes
RUN pip install --no-cache-dir --root-user-action=ignore build && \
    pip install --no-cache-dir --root-user-action=ignore poetry && \
    poetry config virtualenvs.create false && \
    poetry install --only main --no-interaction --no-ansi

# Copy the source code
# This layer will only rebuild when code changes
COPY src/ ./src/

# Run the bot
CMD ["python", "-m", "src.main"] 
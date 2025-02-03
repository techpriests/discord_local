# Use an official Python runtime as a parent image
FROM python:3.12-slim

# Set the working directory in the container
WORKDIR /app

# Copy dependency files first
COPY pyproject.toml poetry.lock ./

# Copy source code
COPY src/ ./src/

# Install dependencies
RUN pip install --no-cache-dir build && \
    pip install --no-cache-dir -e .

# Run the bot
CMD ["python", "-m", "src.main"] 
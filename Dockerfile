# Use an official Python runtime as a parent image
FROM python:3.12-slim

# Set the working directory in the container
WORKDIR /app

# Copy dependency files first
COPY pyproject.toml .

# Install dependencies in a separate layer
RUN pip install --no-cache-dir build && \
    pip install --no-cache-dir -e .[dev]

# Copy the rest of the application code
# This layer will only rebuild when code changes
COPY . .

# Final installation to handle any local dependencies
RUN pip install --no-cache-dir -e .

# Run the bot when the container launches
CMD ["python", "src/main.py"] 
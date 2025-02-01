# Use an official Python runtime as a parent image
FROM python:3.12-slim

# Set the working directory in the container
WORKDIR /app

# Copy the pyproject.toml and the rest of your application's code
COPY pyproject.toml .
COPY . .

# Install dependencies
RUN pip install --no-cache-dir -e .

# Run the bot when the container launches
CMD ["python", "main.py"] 
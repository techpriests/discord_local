#!/bin/bash

# Export Git information
export GIT_COMMIT=$(git rev-parse --short HEAD)
export GIT_BRANCH=$(git rev-parse --abbrev-ref HEAD)

# Run docker-compose
docker-compose up -d 
#!/bin/bash
# Pull latest changes
git pull

# Build and restart containers
docker-compose down
docker-compose build
docker-compose up -d

# Show logs
docker-compose logs -f 
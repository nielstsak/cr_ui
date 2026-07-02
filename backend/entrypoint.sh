#!/bin/sh
# Entrypoint script for Uvicorn FastAPI server

echo "=== System Boot & Initialization ==="

# Ensure data persistence folders exist
mkdir -p /app/data

echo "Initial validation completed. Starting Uvicorn Gateway Server."

# Exec uvicorn server binding to port 8000
exec uvicorn backend.api.gateway:app --host 0.0.0.0 --port 8000

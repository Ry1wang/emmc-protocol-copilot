#!/bin/bash
# Startup script for eMMC RAG Agent
# Runs both FastAPI and Streamlit in the background

set -e

echo "Starting eMMC RAG Agent..."

# Start FastAPI in background
echo "Starting FastAPI on port 8000..."
uvicorn app.main:app --host 0.0.0.0 --port 8000 &
FASTAPI_PID=$!

# Wait a bit for FastAPI to initialize
sleep 5

# Start Streamlit
echo "Starting Streamlit on port 8501..."
streamlit run streamlit_app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true &
STREAMLIT_PID=$!

echo "Services started:"
echo "  - FastAPI: http://localhost:8000"
echo "  - Streamlit: http://localhost:8501"

# Wait for both processes
wait $FASTAPI_PID $STREAMLIT_PID

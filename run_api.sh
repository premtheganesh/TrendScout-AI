#!/bin/bash

# Quick Start Script for TrendScout AI API
# This script starts the FastAPI server with proper checks

echo "=============================================================="
echo "TrendScout AI - Starting API Server"
echo "=============================================================="
echo ""

# Check if virtual environment exists
if [ ! -d ".venv" ]; then
    echo "Error: Virtual environment not found!"
    echo "   Run: python -m venv .venv"
    exit 1
fi

# Check if MongoDB is running
echo "Checking MongoDB..."
if ! pgrep -x "mongod" > /dev/null; then
    echo "MongoDB not running. Starting..."
    brew services start mongodb-community
    sleep 2
fi
echo "MongoDB is running"

# Check if Neo4j is accessible (optional check)
echo "Checking Neo4j..."
echo "   Make sure Neo4j Desktop is running with 'trendscout ai' database"
echo ""

# Check if FAISS index exists
if [ ! -f "data/faiss_index.bin" ]; then
    echo "Error: FAISS index not found!"
    echo "   Run: .venv/bin/python scripts/build_indexes.py"
    exit 1
fi
echo "FAISS index found"

if [ ! -f "data/bm25_index.pkl" ]; then
    echo "Error: BM25 index not found!"
    echo "   Run: .venv/bin/python scripts/build_indexes.py"
    exit 1
fi
echo "BM25 index found"
echo ""

# Start the server
echo "Starting FastAPI server..."
echo ""
echo "URLs:"
echo "   - API: http://localhost:8000"
echo "   - Docs: http://localhost:8000/docs"
echo ""
echo "Press CTRL+C to stop"
echo "=============================================================="
echo ""

.venv/bin/python src/api/main.py

#!/usr/bin/env python3
"""Run the app from project root. Usage: python run.py"""
import sys
import os

# Run from project root so src/ is on path and .env/frontend are found
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import uvicorn
from app import app

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5001)

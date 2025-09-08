#!/usr/bin/env python3
"""
Script to run the Table Extraction Pro API server.
"""

import uvicorn
from table_extraction.api.main import app

if __name__ == "__main__":
    print("Starting Table Extraction Pro API server...")
    print("API will be available at: http://localhost:8000")
    print("API documentation at: http://localhost:8000/docs")
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        reload=True,  # Enable auto-reload for development
        log_level="info"
    )

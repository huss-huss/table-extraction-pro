#!/usr/bin/env python3
"""
Run the Table Extraction Pro API (equivalent to `table-extract serve`).

Set TEP_RELOAD=1 for auto-reload during development.
"""

import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "table_extraction.api.main:app",
        host=os.getenv("TEP_HOST", "127.0.0.1"),
        port=int(os.getenv("TEP_PORT", "8000")),
        reload=os.getenv("TEP_RELOAD") == "1",
    )

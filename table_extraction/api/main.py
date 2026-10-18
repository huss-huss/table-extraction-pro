"""
FastAPI REST API for table extraction.
"""

import html as _html
import logging
import shutil
import tempfile
from pathlib import Path
from typing import List

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .. import __version__
from ..export.formats import _cell_text
from ..extraction.pipeline import TableExtractionPipeline
from ..parsers.parser_comparator import ParserComparator

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Table Extraction Pro API",
    description="REST API for extracting tables from PDFs and images",
    version=__version__,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global pipeline instance
pipeline = None
comparator = None


@app.on_event("startup")
async def startup_event():
    """Initialize the pipeline on startup."""
    global pipeline, comparator
    try:
        logger.info("Initializing table extraction pipeline...")
        pipeline = TableExtractionPipeline()
        comparator = ParserComparator()
        logger.info("Pipeline initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize pipeline: {e}")
        raise


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "name": "Table Extraction Pro API",
        "version": __version__,
        "description": "REST API for extracting tables from PDFs and images",
        "endpoints": {"extract": "/extract", "health": "/health", "docs": "/docs"},
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "version": __version__}


@app.post("/extract")
async def extract_tables(
    file: UploadFile = File(...),
    confidence: float = Form(0.5),
    use_fallback: bool = Form(False),
    include_metadata: bool = Form(True),
    output_format: str = Form("json"),
):
    """
    Extract tables from uploaded file.

    Args:
        file: Uploaded file (PDF or image)
        confidence: Confidence threshold (0.0-1.0)
        use_fallback: Whether to use fallback parsers
        include_metadata: Whether to include metadata
        output_format: Output format (json, csv, html)

    Returns:
        Extracted tables in the specified format
    """
    if pipeline is None:
        raise HTTPException(status_code=500, detail="Pipeline not initialized")

    # Validate file type
    allowed_extensions = {".pdf", ".jpg", ".jpeg", ".png", ".bmp", ".tiff"}
    file_extension = Path(file.filename).suffix.lower()

    if file_extension not in allowed_extensions:
        raise HTTPException(
            status_code=400, detail=f"Unsupported file type: {file_extension}. Allowed: {allowed_extensions}"
        )

    # Validate parameters
    if not 0.0 <= confidence <= 1.0:
        raise HTTPException(status_code=400, detail="Confidence must be between 0.0 and 1.0")

    if output_format not in ["json", "csv", "html"]:
        raise HTTPException(status_code=400, detail="Output format must be json, csv, or html")

    # Create temporary file
    with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as tmp_file:
        try:
            # Save uploaded file
            shutil.copyfileobj(file.file, tmp_file)
            # Extraction re-opens the file by name; flush the buffer first or
            # small uploads are read as empty/truncated files.
            tmp_file.flush()
            tmp_file_path = tmp_file.name

            logger.info(f"Processing file: {file.filename}")

            # Extract tables
            if use_fallback and comparator:
                tables = comparator.compare_parsers(tmp_file_path)
            else:
                tables = pipeline.extract_from_file(tmp_file_path)

            if not tables:
                return JSONResponse(
                    status_code=404, content={"message": "No tables found in the document", "tables": []}
                )

            # Prepare response based on format
            if output_format == "json":
                return {
                    "filename": file.filename,
                    "total_tables": len(tables),
                    "tables": tables
                    if include_metadata
                    else [
                        {"table_id": t["table_id"], "page_number": t["page_number"], "data": t["data"]}
                        for t in tables
                    ],
                }

            elif output_format == "csv":
                # For CSV, we'll return the first table as CSV string
                if tables:
                    import csv
                    import io

                    output = io.StringIO()
                    writer = csv.writer(output)

                    for row in tables[0]["data"]:
                        writer.writerow(row)

                    return JSONResponse(
                        content={
                            "filename": file.filename,
                            "table_id": tables[0]["table_id"],
                            "csv_data": output.getvalue(),
                        }
                    )

            elif output_format == "html":
                # Generate HTML table
                html_content = _generate_html_table(tables[0])
                return JSONResponse(
                    content={
                        "filename": file.filename,
                        "table_id": tables[0]["table_id"],
                        "html_data": html_content,
                    }
                )

        except Exception as e:
            logger.error(f"Extraction failed: {e}")
            raise HTTPException(status_code=500, detail=f"Extraction failed: {str(e)}")

        finally:
            # Clean up temporary file
            Path(tmp_file_path).unlink(missing_ok=True)


@app.post("/extract/batch")
async def extract_tables_batch(
    files: List[UploadFile] = File(...),
    confidence: float = Form(0.5),
    use_fallback: bool = Form(False),
    include_metadata: bool = Form(True),
    output_format: str = Form("json"),
):
    """
    Extract tables from multiple uploaded files.

    Args:
        files: List of uploaded files
        confidence: Confidence threshold
        use_fallback: Whether to use fallback parsers
        include_metadata: Whether to include metadata
        output_format: Output format

    Returns:
        Extracted tables from all files
    """
    if pipeline is None:
        raise HTTPException(status_code=500, detail="Pipeline not initialized")

    if len(files) > 10:  # Limit batch size
        raise HTTPException(status_code=400, detail="Maximum 10 files allowed per batch")

    results = {}

    for file in files:
        try:
            # Validate file type
            allowed_extensions = {".pdf", ".jpg", ".jpeg", ".png", ".bmp", ".tiff"}
            file_extension = Path(file.filename).suffix.lower()

            if file_extension not in allowed_extensions:
                results[file.filename] = {"error": f"Unsupported file type: {file_extension}"}
                continue

            # Create temporary file
            with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as tmp_file:
                try:
                    # Save uploaded file
                    shutil.copyfileobj(file.file, tmp_file)
                    tmp_file.flush()
                    tmp_file_path = tmp_file.name

                    # Extract tables
                    if use_fallback and comparator:
                        tables = comparator.compare_parsers(tmp_file_path)
                    else:
                        tables = pipeline.extract_from_file(tmp_file_path)

                    results[file.filename] = {
                        "total_tables": len(tables),
                        "tables": tables
                        if include_metadata
                        else [
                            {"table_id": t["table_id"], "page_number": t["page_number"], "data": t["data"]}
                            for t in tables
                        ],
                    }

                finally:
                    # Clean up temporary file
                    Path(tmp_file_path).unlink(missing_ok=True)

        except Exception as e:
            logger.error(f"Failed to process {file.filename}: {e}")
            results[file.filename] = {"error": str(e)}

    return {"total_files": len(files), "results": results}


@app.get("/extract/download/{filename}")
async def download_extracted_tables(filename: str, format: str = "csv"):
    """
    Download extracted tables in various formats.

    Args:
        filename: Name of the processed file
        format: Download format (csv, json, html)

    Returns:
        File download response
    """
    # This is a placeholder - in a real implementation, you would
    # store the results and provide download links
    raise HTTPException(status_code=501, detail="Download functionality not implemented")


def _generate_html_table(table: dict) -> str:
    """Generate HTML table from extracted table data."""
    data = table["data"]

    if not data:
        return "<p>No data available</p>"

    html = "<table border='1' style='border-collapse: collapse;'>\n"

    # Add table headers if available
    if data:
        html += "  <thead>\n    <tr>\n"
        for i in range(len(data[0])):
            html += f"      <th>Column {i + 1}</th>\n"
        html += "    </tr>\n  </thead>\n"

    # Add table body
    html += "  <tbody>\n"
    for row in data:
        html += "    <tr>\n"
        for cell in row:
            html += f"      <td>{_html.escape(_cell_text(cell))}</td>\n"
        html += "    </tr>\n"
    html += "  </tbody>\n"

    html += "</table>"
    return html


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

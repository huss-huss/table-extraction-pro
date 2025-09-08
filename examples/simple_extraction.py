#!/usr/bin/env python3
"""
Simple example of using Table Extraction Pro to extract tables from a PDF.
"""

import sys
from pathlib import Path

# Add the parent directory to the path so we can import our modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from table_extraction.extraction.pipeline import TableExtractionPipeline
from table_extraction.export.exporter import TableExporter


def main():
    """Simple extraction example."""
    # Initialize the pipeline
    print("Initializing Table Extraction Pipeline...")
    pipeline = TableExtractionPipeline(confidence_threshold=0.5)
    
    # Example file path (you would replace this with your actual file)
    input_file = "example.pdf"  # Replace with your PDF file
    
    if not Path(input_file).exists():
        print(f"Example file {input_file} not found.")
        print("Please place a PDF file named 'example.pdf' in the examples directory.")
        return
    
    try:
        # Extract tables
        print(f"Extracting tables from: {input_file}")
        tables = pipeline.extract_from_file(input_file)
        
        if not tables:
            print("No tables found in the document.")
            return
        
        print(f"Found {len(tables)} table(s)")
        
        # Export tables
        output_dir = Path("output")
        exporter = TableExporter(output_dir)
        
        results = exporter.export_tables(
            tables, 
            "extracted_tables", 
            ["csv", "json", "html"],
            include_metadata=True
        )
        
        print("Export completed:")
        for format_name, output_path in results.items():
            print(f"  {format_name.upper()}: {output_path}")
        
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()

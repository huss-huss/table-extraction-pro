"""
Export functions for converting extracted tables to various formats.
"""

import csv
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Union

import pandas as pd

logger = logging.getLogger(__name__)


def export_to_csv(
    tables: List[Dict[str, Any]], output_path: Union[str, Path], include_metadata: bool = False
) -> None:
    """
    Export extracted tables to CSV format.

    Args:
        tables: List of extracted table dictionaries
        output_path: Output file path
        include_metadata: Whether to include metadata in the output
    """
    output_path = Path(output_path)

    if len(tables) == 1:
        # Single table - export directly
        table = tables[0]
        data = table["data"]

        with open(output_path, "w", newline="", encoding="utf-8") as csvfile:
            writer = csv.writer(csvfile)

            if include_metadata:
                # Add metadata as comments
                metadata = table["metadata"]
                writer.writerow([f"# Table ID: {table['table_id']}"])
                writer.writerow([f"# Page: {table['page_number']}"])
                writer.writerow([f"# Confidence: {metadata['confidence']:.3f}"])
                writer.writerow([f"# Rows: {metadata['num_rows']}, Columns: {metadata['num_columns']}"])
                writer.writerow([])  # Empty row

            # Write table data
            for row in data:
                writer.writerow(row)

    else:
        # Multiple tables - create separate files
        output_path.mkdir(parents=True, exist_ok=True)

        for table in tables:
            table_file = output_path / f"table_{table['table_id']}_page_{table['page_number']}.csv"
            export_to_csv([table], table_file, include_metadata)

    logger.info(f"Exported {len(tables)} table(s) to CSV: {output_path}")


def export_to_json(
    tables: List[Dict[str, Any]],
    output_path: Union[str, Path],
    include_metadata: bool = True,
    pretty_print: bool = True,
) -> None:
    """
    Export extracted tables to JSON format.

    Args:
        tables: List of extracted table dictionaries
        output_path: Output file path
        include_metadata: Whether to include metadata in the output
        pretty_print: Whether to format JSON with indentation
    """
    output_path = Path(output_path)

    # Prepare export data
    export_data = {
        "extraction_info": {
            "total_tables": len(tables),
            "extraction_timestamp": pd.Timestamp.now().isoformat(),
        },
        "tables": [],
    }

    for table in tables:
        table_data = {
            "table_id": table["table_id"],
            "page_number": table["page_number"],
            "data": table["data"],
            "structure": {
                "num_rows": table["structure"]["num_rows"],
                "num_columns": table["structure"]["num_columns"],
                "rows": table["structure"]["rows"],
                "columns": table["structure"]["columns"],
            },
        }

        if include_metadata:
            table_data["metadata"] = table["metadata"]
            table_data["detection"] = table["detection"]

        export_data["tables"].append(table_data)

    # Write JSON file
    with open(output_path, "w", encoding="utf-8") as jsonfile:
        if pretty_print:
            json.dump(export_data, jsonfile, indent=2, ensure_ascii=False)
        else:
            json.dump(export_data, jsonfile, ensure_ascii=False)

    logger.info(f"Exported {len(tables)} table(s) to JSON: {output_path}")


def export_to_html(
    tables: List[Dict[str, Any]],
    output_path: Union[str, Path],
    include_metadata: bool = True,
    style: str = "default",
) -> None:
    """
    Export extracted tables to HTML format.

    Args:
        tables: List of extracted table dictionaries
        output_path: Output file path
        include_metadata: Whether to include metadata in the output
        style: CSS style to apply ("default", "minimal", "bootstrap")
    """
    output_path = Path(output_path)

    # Generate HTML content
    html_content = _generate_html_content(tables, include_metadata, style)

    # Write HTML file
    with open(output_path, "w", encoding="utf-8") as htmlfile:
        htmlfile.write(html_content)

    logger.info(f"Exported {len(tables)} table(s) to HTML: {output_path}")


def export_to_excel(
    tables: List[Dict[str, Any]], output_path: Union[str, Path], include_metadata: bool = True
) -> None:
    """
    Export extracted tables to Excel format.

    Args:
        tables: List of extracted table dictionaries
        output_path: Output file path
        include_metadata: Whether to include metadata in the output
    """
    output_path = Path(output_path)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        # Create summary sheet
        summary_data = []
        for table in tables:
            summary_data.append(
                {
                    "Table ID": table["table_id"],
                    "Page": table["page_number"],
                    "Rows": table["structure"]["num_rows"],
                    "Columns": table["structure"]["num_columns"],
                    "Confidence": table["metadata"]["confidence"],
                }
            )

        summary_df = pd.DataFrame(summary_data)
        summary_df.to_excel(writer, sheet_name="Summary", index=False)

        # Create individual sheets for each table
        for table in tables:
            sheet_name = f"Table_{table['table_id']}_Page_{table['page_number']}"

            # Convert table data to DataFrame
            df = pd.DataFrame(table["data"])

            # Add headers if available
            if table["structure"]["rows"] and table["structure"]["columns"]:
                # Try to extract headers from first row
                if len(df) > 0:
                    df.columns = [f"Column_{i + 1}" for i in range(len(df.columns))]

            df.to_excel(writer, sheet_name=sheet_name, index=False)

    logger.info(f"Exported {len(tables)} table(s) to Excel: {output_path}")


def _generate_html_content(tables: List[Dict[str, Any]], include_metadata: bool, style: str) -> str:
    """Generate HTML content for tables."""

    # CSS styles
    styles = {
        "default": """
        <style>
            body { font-family: Arial, sans-serif; margin: 20px; }
            .table-container { margin-bottom: 30px; }
            .table-title { font-size: 18px; font-weight: bold; margin-bottom: 10px; }
            .metadata { font-size: 12px; color: #666; margin-bottom: 10px; }
            table { border-collapse: collapse; width: 100%; margin-bottom: 20px; }
            th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
            th { background-color: #f2f2f2; font-weight: bold; }
            .confidence { color: #007bff; }
        </style>
        """,
        "minimal": """
        <style>
            body { font-family: monospace; margin: 20px; }
            table { border-collapse: collapse; width: 100%; margin-bottom: 20px; }
            th, td { border: 1px solid #000; padding: 4px; }
            th { background-color: #eee; }
        </style>
        """,
        "bootstrap": """
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
        <style>
            .table-container { margin-bottom: 30px; }
            .confidence { color: #0d6efd; }
        </style>
        """,
    }

    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Extracted Tables</title>
        {styles.get(style, styles["default"])}
    </head>
    <body>
        <h1>Extracted Tables</h1>
        <p>Total tables extracted: {len(tables)}</p>
    """

    for table in tables:
        html += f"""
        <div class="table-container">
            <div class="table-title">Table {table["table_id"]} (Page {table["page_number"]})</div>
        """

        if include_metadata:
            metadata = table["metadata"]
            html += f"""
            <div class="metadata">
                Confidence: <span class="confidence">{metadata["confidence"]:.3f}</span> | 
                Rows: {metadata["num_rows"]} | Columns: {metadata["num_columns"]}
            </div>
            """

        # Generate table HTML
        html += "<table>\n"

        # Add table headers if available
        if table["structure"]["columns"]:
            html += "  <thead>\n    <tr>\n"
            for i in range(table["structure"]["num_columns"]):
                html += f"      <th>Column {i + 1}</th>\n"
            html += "    </tr>\n  </thead>\n"

        # Add table body
        html += "  <tbody>\n"
        for row in table["data"]:
            html += "    <tr>\n"
            for cell in row:
                html += f"      <td>{cell}</td>\n"
            html += "    </tr>\n"
        html += "  </tbody>\n"

        html += "</table>\n</div>\n"

    html += """
    </body>
    </html>
    """

    return html

"""
Unified table exporter that handles multiple output formats.
"""

from typing import List, Dict, Any, Union, Optional
from pathlib import Path
import logging

from .formats import export_to_csv, export_to_json, export_to_html, export_to_excel

logger = logging.getLogger(__name__)


class TableExporter:
    """
    Unified exporter for extracted tables supporting multiple output formats.
    """
    
    SUPPORTED_FORMATS = ["csv", "json", "html", "excel", "xlsx"]
    
    def __init__(self, output_dir: Union[str, Path]):
        """
        Initialize the table exporter.
        
        Args:
            output_dir: Directory to save exported files
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def export_tables(
        self,
        tables: List[Dict[str, Any]],
        filename: str,
        formats: List[str] = None,
        include_metadata: bool = True,
        **kwargs
    ) -> Dict[str, Path]:
        """
        Export tables to multiple formats.
        
        Args:
            tables: List of extracted table dictionaries
            filename: Base filename (without extension)
            formats: List of output formats (default: ["csv", "json"])
            include_metadata: Whether to include metadata
            **kwargs: Additional format-specific options
            
        Returns:
            Dictionary mapping format names to output file paths
        """
        if formats is None:
            formats = ["csv", "json"]
        
        # Validate formats
        invalid_formats = [f for f in formats if f not in self.SUPPORTED_FORMATS]
        if invalid_formats:
            raise ValueError(f"Unsupported formats: {invalid_formats}")
        
        results = {}
        
        for format_name in formats:
            try:
                output_path = self._get_output_path(filename, format_name)
                
                if format_name == "csv":
                    export_to_csv(tables, output_path, include_metadata)
                elif format_name == "json":
                    export_to_json(
                        tables, output_path, include_metadata, 
                        kwargs.get("pretty_print", True)
                    )
                elif format_name == "html":
                    export_to_html(
                        tables, output_path, include_metadata,
                        kwargs.get("style", "default")
                    )
                elif format_name in ["excel", "xlsx"]:
                    export_to_excel(tables, output_path, include_metadata)
                
                results[format_name] = output_path
                logger.info(f"Exported tables to {format_name}: {output_path}")
                
            except Exception as e:
                logger.error(f"Failed to export to {format_name}: {e}")
                raise
        
        return results
    
    def export_single_table(
        self,
        table: Dict[str, Any],
        filename: str,
        formats: List[str] = None,
        include_metadata: bool = True,
        **kwargs
    ) -> Dict[str, Path]:
        """
        Export a single table to multiple formats.
        
        Args:
            table: Single extracted table dictionary
            filename: Base filename (without extension)
            formats: List of output formats
            include_metadata: Whether to include metadata
            **kwargs: Additional format-specific options
            
        Returns:
            Dictionary mapping format names to output file paths
        """
        return self.export_tables(
            [table], filename, formats, include_metadata, **kwargs
        )
    
    def export_batch(
        self,
        batch_results: Dict[str, List[Dict[str, Any]]],
        formats: List[str] = None,
        include_metadata: bool = True,
        **kwargs
    ) -> Dict[str, Dict[str, Path]]:
        """
        Export multiple files' tables in batch.
        
        Args:
            batch_results: Dictionary mapping file paths to extracted tables
            formats: List of output formats
            include_metadata: Whether to include metadata
            **kwargs: Additional format-specific options
            
        Returns:
            Nested dictionary mapping file paths to format results
        """
        if formats is None:
            formats = ["csv", "json"]
        
        all_results = {}
        
        for file_path, tables in batch_results.items():
            if not tables:
                logger.warning(f"No tables found in {file_path}")
                continue
            
            # Generate filename from file path
            file_stem = Path(file_path).stem
            filename = f"{file_stem}_tables"
            
            try:
                results = self.export_tables(
                    tables, filename, formats, include_metadata, **kwargs
                )
                all_results[file_path] = results
                
            except Exception as e:
                logger.error(f"Failed to export tables from {file_path}: {e}")
                all_results[file_path] = {}
        
        return all_results
    
    def _get_output_path(self, filename: str, format_name: str) -> Path:
        """
        Generate output path for a given filename and format.
        
        Args:
            filename: Base filename
            format_name: Output format
            
        Returns:
            Full output path
        """
        # Handle special cases
        if format_name in ["excel", "xlsx"]:
            extension = "xlsx"
        else:
            extension = format_name
        
        return self.output_dir / f"{filename}.{extension}"
    
    def create_summary_report(
        self,
        batch_results: Dict[str, List[Dict[str, Any]]],
        output_path: Optional[Union[str, Path]] = None
    ) -> Path:
        """
        Create a summary report of the extraction results.
        
        Args:
            batch_results: Dictionary mapping file paths to extracted tables
            output_path: Output path for summary report
            
        Returns:
            Path to the created summary report
        """
        if output_path is None:
            output_path = self.output_dir / "extraction_summary.json"
        else:
            output_path = Path(output_path)
        
        # Generate summary statistics
        summary = {
            "extraction_summary": {
                "total_files": len(batch_results),
                "total_tables": sum(len(tables) for tables in batch_results.values()),
                "files_with_tables": sum(1 for tables in batch_results.values() if tables),
                "files_without_tables": sum(1 for tables in batch_results.values() if not tables)
            },
            "file_details": {}
        }
        
        for file_path, tables in batch_results.items():
            file_summary = {
                "num_tables": len(tables),
                "tables": []
            }
            
            for table in tables:
                table_info = {
                    "table_id": table["table_id"],
                    "page_number": table["page_number"],
                    "confidence": table["metadata"]["confidence"],
                    "num_rows": table["structure"]["num_rows"],
                    "num_columns": table["structure"]["num_columns"]
                }
                file_summary["tables"].append(table_info)
            
            summary["file_details"][file_path] = file_summary
        
        # Write summary report
        import json
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Created summary report: {output_path}")
        return output_path

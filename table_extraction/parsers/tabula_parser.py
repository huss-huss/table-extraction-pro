"""
Tabula parser wrapper for table extraction from PDFs.
"""

import tabula
import pandas as pd
from typing import List, Dict, Any, Optional
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class TabulaParser:
    """
    Wrapper for Tabula PDF table extraction library.
    
    Tabula is excellent for extracting tables from PDFs, especially when tables
    have clear boundaries and consistent formatting.
    """
    
    def __init__(self, pages: str = "all", multiple_tables: bool = True):
        """
        Initialize Tabula parser.
        
        Args:
            pages: Pages to process ("all" or specific page numbers)
            multiple_tables: Whether to extract multiple tables per page
        """
        self.pages = pages
        self.multiple_tables = multiple_tables
    
    def extract_tables(
        self, 
        pdf_path: str,
        area: Optional[List[float]] = None,
        columns: Optional[List[float]] = None,
        guess: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Extract tables from PDF using Tabula.
        
        Args:
            pdf_path: Path to PDF file
            area: Table area coordinates [top, left, bottom, right]
            columns: Column positions
            guess: Whether to guess table areas automatically
            
        Returns:
            List of extracted tables with data and metadata
        """
        try:
            logger.info(f"Extracting tables with Tabula from: {pdf_path}")
            
            # Extract tables using Tabula
            dfs = tabula.read_pdf(
                pdf_path,
                pages=self.pages,
                area=area,
                columns=columns,
                guess=guess,
                multiple_tables=self.multiple_tables,
                pandas_options={'header': None}  # Don't assume first row is header
            )
            
            logger.info(f"Tabula found {len(dfs)} table(s)")
            
            # Convert to our standard format
            extracted_tables = []
            for i, df in enumerate(dfs):
                # Clean the DataFrame
                df = df.dropna(how='all').dropna(axis=1, how='all')
                
                # Convert DataFrame to list of lists
                data = df.values.tolist()
                
                # Get table metadata
                metadata = {
                    "parser": "tabula",
                    "pages": self.pages,
                    "num_rows": len(data),
                    "num_columns": len(data[0]) if data else 0,
                    "area": area,
                    "columns": columns
                }
                
                extracted_table = {
                    "table_id": i + 1,
                    "page_number": 1,  # Tabula doesn't provide page info easily
                    "data": data,
                    "metadata": metadata,
                    "structure": {
                        "num_rows": len(data),
                        "num_columns": len(data[0]) if data else 0,
                        "rows": [],
                        "columns": []
                    },
                    "detection": {
                        "bbox": area or [0, 0, 0, 0],
                        "confidence": 0.8,  # Default confidence for Tabula
                        "class": "table"
                    }
                }
                
                extracted_tables.append(extracted_table)
            
            return extracted_tables
            
        except Exception as e:
            logger.error(f"Tabula extraction failed: {e}")
            return []
    
    def extract_tables_with_different_methods(
        self, 
        pdf_path: str
    ) -> List[Dict[str, Any]]:
        """
        Extract tables using different Tabula methods and return the best results.
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            List of extracted tables with the best results
        """
        methods = [
            {"guess": True, "multiple_tables": True},
            {"guess": False, "multiple_tables": True},
            {"guess": True, "multiple_tables": False}
        ]
        
        all_results = []
        
        for i, method in enumerate(methods):
            try:
                logger.info(f"Trying Tabula method {i+1}: {method}")
                
                dfs = tabula.read_pdf(
                    pdf_path,
                    pages=self.pages,
                    guess=method["guess"],
                    multiple_tables=method["multiple_tables"],
                    pandas_options={'header': None}
                )
                
                # Convert to our standard format
                for j, df in enumerate(dfs):
                    df = df.dropna(how='all').dropna(axis=1, how='all')
                    data = df.values.tolist()
                    
                    metadata = {
                        "parser": "tabula",
                        "method": f"method_{i+1}",
                        "guess": method["guess"],
                        "multiple_tables": method["multiple_tables"],
                        "num_rows": len(data),
                        "num_columns": len(data[0]) if data else 0
                    }
                    
                    extracted_table = {
                        "table_id": len(all_results) + 1,
                        "page_number": 1,
                        "data": data,
                        "metadata": metadata,
                        "structure": {
                            "num_rows": len(data),
                            "num_columns": len(data[0]) if data else 0,
                            "rows": [],
                            "columns": []
                        },
                        "detection": {
                            "bbox": [0, 0, 0, 0],
                            "confidence": 0.8,
                            "class": "table"
                        }
                    }
                    
                    all_results.append(extracted_table)
                
            except Exception as e:
                logger.warning(f"Tabula method {i+1} failed: {e}")
                continue
        
        # Remove duplicates and return best results
        return self._deduplicate_and_rank_tables(all_results)
    
    def _deduplicate_and_rank_tables(
        self, 
        tables: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Remove duplicate tables and rank by quality.
        
        Args:
            tables: List of extracted tables
            
        Returns:
            Deduplicated and ranked list of tables
        """
        if not tables:
            return []
        
        # Simple deduplication based on table size and content similarity
        unique_tables = {}
        
        for table in tables:
            # Create a simple hash based on table dimensions and first few cells
            table_hash = self._create_table_hash(table)
            
            if table_hash not in unique_tables:
                unique_tables[table_hash] = table
            else:
                # Keep the one with more complete data
                current_rows = table["structure"]["num_rows"]
                existing_rows = unique_tables[table_hash]["structure"]["num_rows"]
                
                if current_rows > existing_rows:
                    unique_tables[table_hash] = table
        
        # Sort by table ID
        result = list(unique_tables.values())
        result.sort(key=lambda x: x["table_id"])
        
        return result
    
    def _create_table_hash(self, table: Dict[str, Any]) -> str:
        """
        Create a simple hash for table deduplication.
        
        Args:
            table: Table dictionary
            
        Returns:
            Hash string
        """
        data = table["data"]
        if not data:
            return "empty"
        
        # Use table dimensions and first few cells as hash
        rows = len(data)
        cols = len(data[0]) if data else 0
        
        # Get first few cells as string
        first_cells = []
        for i in range(min(3, rows)):
            for j in range(min(3, cols)):
                if i < len(data) and j < len(data[i]):
                    first_cells.append(str(data[i][j])[:10])  # First 10 chars
        
        return f"{rows}x{cols}_{'_'.join(first_cells)}"
    
    def get_table_areas(self, pdf_path: str, page: int = 1) -> List[List[float]]:
        """
        Get suggested table areas for a PDF page.
        
        Args:
            pdf_path: Path to PDF file
            page: Page number to analyze
            
        Returns:
            List of suggested table areas
        """
        try:
            # Use Tabula to detect table areas
            dfs = tabula.read_pdf(
                pdf_path,
                pages=str(page),
                guess=True,
                multiple_tables=True,
                pandas_options={'header': None}
            )
            
            # Tabula doesn't directly provide areas, but we can estimate
            # This is a simplified approach
            areas = []
            for i in range(len(dfs)):
                # Default area - in practice, you might want to use more sophisticated detection
                area = [100, 100, 700, 500]  # [top, left, bottom, right]
                areas.append(area)
            
            return areas
            
        except Exception as e:
            logger.error(f"Failed to get table areas: {e}")
            return []

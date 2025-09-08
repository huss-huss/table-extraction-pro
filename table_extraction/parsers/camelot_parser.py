"""
Camelot parser wrapper for table extraction from PDFs.
"""

import camelot
import pandas as pd
from typing import List, Dict, Any, Optional
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class CamelotParser:
    """
    Wrapper for Camelot PDF table extraction library.
    
    Camelot is excellent for extracting tables from PDFs with clear table structures.
    """
    
    def __init__(self, flavor: str = "lattice", pages: str = "all"):
        """
        Initialize Camelot parser.
        
        Args:
            flavor: Camelot flavor ("lattice" for tables with lines, "stream" for tables without lines)
            pages: Pages to process ("all" or specific page numbers)
        """
        self.flavor = flavor
        self.pages = pages
    
    def extract_tables(
        self, 
        pdf_path: str,
        table_areas: Optional[List[str]] = None,
        columns: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Extract tables from PDF using Camelot.
        
        Args:
            pdf_path: Path to PDF file
            table_areas: List of table areas to extract (e.g., ["390,720,0,576"])
            columns: List of column separators
            
        Returns:
            List of extracted tables with data and metadata
        """
        try:
            logger.info(f"Extracting tables with Camelot from: {pdf_path}")
            
            # Extract tables using Camelot
            tables = camelot.read_pdf(
                pdf_path,
                flavor=self.flavor,
                pages=self.pages,
                table_areas=table_areas,
                columns=columns
            )
            
            logger.info(f"Camelot found {len(tables)} table(s)")
            
            # Convert to our standard format
            extracted_tables = []
            for i, table in enumerate(tables):
                # Get table data
                df = table.df
                
                # Convert DataFrame to list of lists
                data = df.values.tolist()
                
                # Get table metadata
                metadata = {
                    "parser": "camelot",
                    "flavor": self.flavor,
                    "accuracy": table.accuracy,
                    "whitespace": table.whitespace,
                    "order": table.order,
                    "page": table.page,
                    "num_rows": len(data),
                    "num_columns": len(data[0]) if data else 0
                }
                
                extracted_table = {
                    "table_id": i + 1,
                    "page_number": table.page,
                    "data": data,
                    "metadata": metadata,
                    "structure": {
                        "num_rows": len(data),
                        "num_columns": len(data[0]) if data else 0,
                        "rows": [],
                        "columns": []
                    },
                    "detection": {
                        "bbox": [0, 0, 0, 0],  # Camelot doesn't provide bbox
                        "confidence": table.accuracy / 100.0,
                        "class": "table"
                    }
                }
                
                extracted_tables.append(extracted_table)
            
            return extracted_tables
            
        except Exception as e:
            logger.error(f"Camelot extraction failed: {e}")
            return []
    
    def extract_tables_with_multiple_flavors(
        self, 
        pdf_path: str
    ) -> List[Dict[str, Any]]:
        """
        Extract tables using multiple Camelot flavors and return the best results.
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            List of extracted tables with the best results
        """
        flavors = ["lattice", "stream"]
        all_results = []
        
        for flavor in flavors:
            try:
                logger.info(f"Trying Camelot with flavor: {flavor}")
                self.flavor = flavor
                tables = self.extract_tables(pdf_path)
                
                # Add flavor information to metadata
                for table in tables:
                    table["metadata"]["flavor"] = flavor
                
                all_results.extend(tables)
                
            except Exception as e:
                logger.warning(f"Camelot {flavor} failed: {e}")
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
        
        # Simple deduplication based on page number and table size
        unique_tables = {}
        
        for table in tables:
            key = (table["page_number"], table["structure"]["num_rows"], table["structure"]["num_columns"])
            
            if key not in unique_tables:
                unique_tables[key] = table
            else:
                # Keep the one with higher accuracy
                if table["metadata"]["accuracy"] > unique_tables[key]["metadata"]["accuracy"]:
                    unique_tables[key] = table
        
        # Sort by page number and table ID
        result = list(unique_tables.values())
        result.sort(key=lambda x: (x["page_number"], x["table_id"]))
        
        return result
    
    def get_table_areas(self, pdf_path: str, page: int = 1) -> List[str]:
        """
        Get suggested table areas for a PDF page.
        
        Args:
            pdf_path: Path to PDF file
            page: Page number to analyze
            
        Returns:
            List of suggested table areas
        """
        try:
            # Use Camelot to detect table areas
            tables = camelot.read_pdf(
                pdf_path,
                flavor=self.flavor,
                pages=str(page),
                table_areas=None
            )
            
            areas = []
            for table in tables:
                # Convert table coordinates to area format
                # This is a simplified approach - in practice, you might want more sophisticated detection
                area = f"{table._bbox[3]},{table._bbox[1]},{table._bbox[0]},{table._bbox[2]}"
                areas.append(area)
            
            return areas
            
        except Exception as e:
            logger.error(f"Failed to get table areas: {e}")
            return []

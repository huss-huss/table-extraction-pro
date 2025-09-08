"""
Parser comparator for evaluating and selecting the best table extraction results.
"""

from typing import List, Dict, Any, Optional
import logging

from .camelot_parser import CamelotParser
from .tabula_parser import TabulaParser

logger = logging.getLogger(__name__)


class ParserComparator:
    """
    Compares results from different table extraction parsers and selects the best ones.
    """
    
    def __init__(self):
        """Initialize the parser comparator."""
        self.camelot_parser = CamelotParser()
        self.tabula_parser = TabulaParser()
    
    def compare_parsers(
        self, 
        pdf_path: str,
        tatr_tables: Optional[List[Dict[str, Any]]] = None
    ) -> List[Dict[str, Any]]:
        """
        Compare results from multiple parsers and return the best tables.
        
        Args:
            pdf_path: Path to PDF file
            tatr_tables: Tables extracted by TATR (optional)
            
        Returns:
            List of best extracted tables
        """
        logger.info(f"Comparing parsers for: {pdf_path}")
        
        all_results = []
        
        # Add TATR results if provided
        if tatr_tables:
            for table in tatr_tables:
                table["metadata"]["parser"] = "tatr"
            all_results.extend(tatr_tables)
        
        # Try Camelot
        try:
            camelot_tables = self.camelot_parser.extract_tables_with_multiple_flavors(pdf_path)
            all_results.extend(camelot_tables)
            logger.info(f"Camelot extracted {len(camelot_tables)} table(s)")
        except Exception as e:
            logger.warning(f"Camelot extraction failed: {e}")
        
        # Try Tabula
        try:
            tabula_tables = self.tabula_parser.extract_tables_with_different_methods(pdf_path)
            all_results.extend(tabula_tables)
            logger.info(f"Tabula extracted {len(tabula_tables)} table(s)")
        except Exception as e:
            logger.warning(f"Tabula extraction failed: {e}")
        
        # Compare and select best results
        best_tables = self._select_best_tables(all_results)
        
        logger.info(f"Selected {len(best_tables)} best table(s) from {len(all_results)} total")
        return best_tables
    
    def _select_best_tables(
        self, 
        all_tables: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Select the best tables from all extraction results.
        
        Args:
            all_tables: List of all extracted tables from different parsers
            
        Returns:
            List of best tables
        """
        if not all_tables:
            return []
        
        # Group tables by page and approximate location
        table_groups = self._group_similar_tables(all_tables)
        
        best_tables = []
        for group in table_groups:
            if len(group) == 1:
                # Only one table found for this location
                best_tables.append(group[0])
            else:
                # Multiple tables found - select the best one
                best_table = self._select_best_from_group(group)
                best_tables.append(best_table)
        
        # Sort by page number and table ID
        best_tables.sort(key=lambda x: (x["page_number"], x["table_id"]))
        
        return best_tables
    
    def _group_similar_tables(
        self, 
        tables: List[Dict[str, Any]]
    ) -> List[List[Dict[str, Any]]]:
        """
        Group tables that are likely the same table extracted by different parsers.
        
        Args:
            tables: List of all extracted tables
            
        Returns:
            List of table groups
        """
        groups = []
        used_tables = set()
        
        for i, table in enumerate(tables):
            if i in used_tables:
                continue
            
            group = [table]
            used_tables.add(i)
            
            # Find similar tables
            for j, other_table in enumerate(tables[i+1:], i+1):
                if j in used_tables:
                    continue
                
                if self._are_tables_similar(table, other_table):
                    group.append(other_table)
                    used_tables.add(j)
            
            groups.append(group)
        
        return groups
    
    def _are_tables_similar(
        self, 
        table1: Dict[str, Any], 
        table2: Dict[str, Any]
    ) -> bool:
        """
        Check if two tables are likely the same table.
        
        Args:
            table1: First table
            table2: Second table
            
        Returns:
            True if tables are similar
        """
        # Check page number
        if table1["page_number"] != table2["page_number"]:
            return False
        
        # Check table dimensions (allow some tolerance)
        rows1 = table1["structure"]["num_rows"]
        rows2 = table2["structure"]["num_rows"]
        cols1 = table1["structure"]["num_columns"]
        cols2 = table2["structure"]["num_columns"]
        
        # Allow 20% difference in dimensions
        if abs(rows1 - rows2) > max(rows1, rows2) * 0.2:
            return False
        if abs(cols1 - cols2) > max(cols1, cols2) * 0.2:
            return False
        
        # Check content similarity (simple approach)
        similarity = self._calculate_content_similarity(table1, table2)
        return similarity > 0.7  # 70% similarity threshold
    
    def _calculate_content_similarity(
        self, 
        table1: Dict[str, Any], 
        table2: Dict[str, Any]
    ) -> float:
        """
        Calculate content similarity between two tables.
        
        Args:
            table1: First table
            table2: Second table
            
        Returns:
            Similarity score between 0 and 1
        """
        data1 = table1["data"]
        data2 = table2["data"]
        
        if not data1 or not data2:
            return 0.0
        
        # Compare first few rows and columns
        min_rows = min(len(data1), len(data2))
        min_cols = min(len(data1[0]) if data1 else 0, len(data2[0]) if data2 else 0)
        
        if min_rows == 0 or min_cols == 0:
            return 0.0
        
        # Compare up to 3 rows and 3 columns
        compare_rows = min(3, min_rows)
        compare_cols = min(3, min_cols)
        
        matches = 0
        total = compare_rows * compare_cols
        
        for i in range(compare_rows):
            for j in range(compare_cols):
                cell1 = str(data1[i][j]).strip().lower()
                cell2 = str(data2[i][j]).strip().lower()
                
                if cell1 == cell2:
                    matches += 1
                elif cell1 and cell2 and (cell1 in cell2 or cell2 in cell1):
                    matches += 0.5  # Partial match
        
        return matches / total if total > 0 else 0.0
    
    def _select_best_from_group(
        self, 
        group: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Select the best table from a group of similar tables.
        
        Args:
            group: List of similar tables
            
        Returns:
            Best table from the group
        """
        if len(group) == 1:
            return group[0]
        
        # Score each table
        scored_tables = []
        for table in group:
            score = self._calculate_table_score(table)
            scored_tables.append((score, table))
        
        # Sort by score (descending) and return the best
        scored_tables.sort(key=lambda x: x[0], reverse=True)
        return scored_tables[0][1]
    
    def _calculate_table_score(self, table: Dict[str, Any]) -> float:
        """
        Calculate a quality score for a table.
        
        Args:
            table: Table dictionary
            
        Returns:
            Quality score
        """
        score = 0.0
        
        # Base score from parser confidence
        if "confidence" in table["detection"]:
            score += table["detection"]["confidence"] * 0.3
        
        # Score based on table completeness
        data = table["data"]
        if data:
            # Check for empty cells
            total_cells = len(data) * len(data[0]) if data else 0
            non_empty_cells = sum(
                1 for row in data for cell in row 
                if str(cell).strip()
            )
            
            if total_cells > 0:
                completeness = non_empty_cells / total_cells
                score += completeness * 0.4
        
        # Score based on table size (prefer larger tables)
        rows = table["structure"]["num_rows"]
        cols = table["structure"]["num_columns"]
        size_score = min(1.0, (rows * cols) / 100.0)  # Normalize to 0-1
        score += size_score * 0.2
        
        # Parser preference (TATR > Camelot > Tabula)
        parser = table["metadata"].get("parser", "unknown")
        if parser == "tatr":
            score += 0.1
        elif parser == "camelot":
            score += 0.05
        
        return min(1.0, score)  # Cap at 1.0

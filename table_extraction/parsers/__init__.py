"""
Fallback parsers for table extraction when TATR fails or for specific use cases.
"""

from .camelot_parser import CamelotParser
from .tabula_parser import TabulaParser
from .parser_comparator import ParserComparator

__all__ = ["CamelotParser", "TabulaParser", "ParserComparator"]

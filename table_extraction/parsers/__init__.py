"""
Fallback parsers for table extraction when TATR fails or for specific use cases.
"""

from .camelot_parser import CamelotParser
from .parser_comparator import ParserComparator
from .tabula_parser import TabulaParser

__all__ = ["CamelotParser", "TabulaParser", "ParserComparator"]

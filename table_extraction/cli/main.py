"""
Main CLI interface for table extraction.
"""

import logging
from pathlib import Path
from typing import List

import click

from ..export.exporter import TableExporter
from ..extraction.pipeline import TableExtractionPipeline
from ..parsers.parser_comparator import ParserComparator

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
@click.option("--quiet", "-q", is_flag=True, help="Suppress output except errors")
def cli(verbose: bool, quiet: bool):
    """Table Extraction Pro - Extract tables from PDFs and images."""
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    elif quiet:
        logging.getLogger().setLevel(logging.ERROR)


@cli.command()
@click.option("--input", "-i", required=True, help="Input file path (PDF or image)")
@click.option("--output", "-o", required=True, help="Output directory path")
@click.option(
    "--formats",
    "-f",
    multiple=True,
    type=click.Choice(["csv", "json", "html", "excel"]),
    default=["csv", "json"],
    help="Output formats",
)
@click.option("--confidence", "-c", default=0.5, help="Confidence threshold (0.0-1.0)")
@click.option("--use-fallback", is_flag=True, help="Use fallback parsers (Camelot, Tabula)")
@click.option("--include-metadata", is_flag=True, help="Include metadata in output")
def extract(
    input: str, output: str, formats: List[str], confidence: float, use_fallback: bool, include_metadata: bool
):
    """Extract tables from a single file."""
    try:
        logger.info(f"Extracting tables from: {input}")

        # Initialize pipeline
        pipeline = TableExtractionPipeline(confidence_threshold=confidence)

        # Extract tables
        if use_fallback:
            # Use parser comparator for best results
            comparator = ParserComparator()
            tables = comparator.compare_parsers(input)
        else:
            # Use TATR only
            tables = pipeline.extract_from_file(input)

        if not tables:
            logger.warning("No tables found in the document")
            return

        # Export tables
        exporter = TableExporter(output)
        input_stem = Path(input).stem
        results = exporter.export_tables(tables, input_stem, list(formats), include_metadata)

        logger.info(f"Successfully extracted {len(tables)} table(s)")
        for format_name, output_path in results.items():
            logger.info(f"Exported to {format_name}: {output_path}")

    except Exception as e:
        logger.error(f"Extraction failed: {e}")
        raise click.ClickException(str(e))


@cli.command()
@click.option("--input-folder", "-i", required=True, help="Input folder path")
@click.option("--output-folder", "-o", required=True, help="Output folder path")
@click.option(
    "--formats",
    "-f",
    multiple=True,
    type=click.Choice(["csv", "json", "html", "excel"]),
    default=["csv", "json"],
    help="Output formats",
)
@click.option("--confidence", "-c", default=0.5, help="Confidence threshold (0.0-1.0)")
@click.option("--use-fallback", is_flag=True, help="Use fallback parsers")
@click.option("--include-metadata", is_flag=True, help="Include metadata in output")
@click.option(
    "--file-extensions",
    multiple=True,
    default=[".pdf", ".jpg", ".jpeg", ".png", ".bmp", ".tiff"],
    help="File extensions to process",
)
def batch(
    input_folder: str,
    output_folder: str,
    formats: List[str],
    confidence: float,
    use_fallback: bool,
    include_metadata: bool,
    file_extensions: List[str],
):
    """Batch extract tables from multiple files."""
    try:
        input_path = Path(input_folder)
        output_path = Path(output_folder)

        if not input_path.exists():
            raise click.ClickException(f"Input folder does not exist: {input_folder}")

        # Find files to process
        files_to_process = []
        for ext in file_extensions:
            files_to_process.extend(input_path.glob(f"*{ext}"))
            files_to_process.extend(input_path.glob(f"*{ext.upper()}"))

        if not files_to_process:
            logger.warning(f"No files found with extensions: {file_extensions}")
            return

        logger.info(f"Found {len(files_to_process)} files to process")

        # Initialize pipeline
        pipeline = TableExtractionPipeline(confidence_threshold=confidence)
        comparator = ParserComparator() if use_fallback else None

        # Process files
        batch_results = {}
        for file_path in files_to_process:
            try:
                logger.info(f"Processing: {file_path}")

                if use_fallback and comparator:
                    tables = comparator.compare_parsers(str(file_path))
                else:
                    tables = pipeline.extract_from_file(file_path)

                batch_results[str(file_path)] = tables
                logger.info(f"Found {len(tables)} table(s) in {file_path.name}")

            except Exception as e:
                logger.error(f"Failed to process {file_path}: {e}")
                batch_results[str(file_path)] = []

        # Export results
        exporter = TableExporter(output_path)
        export_results = exporter.export_batch(batch_results, list(formats), include_metadata)

        # Create summary report
        summary_path = exporter.create_summary_report(batch_results)

        # Print summary
        total_tables = sum(len(tables) for tables in batch_results.values())
        files_with_tables = sum(1 for tables in batch_results.values() if tables)

        logger.info("Batch processing completed:")
        logger.info(f"  - Files processed: {len(files_to_process)}")
        logger.info(f"  - Files with tables: {files_with_tables}")
        logger.info(f"  - Total tables extracted: {total_tables}")
        logger.info(f"  - Summary report: {summary_path}")

    except Exception as e:
        logger.error(f"Batch processing failed: {e}")
        raise click.ClickException(str(e))


@cli.command()
@click.option("--input", "-i", required=True, help="Input file path")
@click.option("--output", "-o", required=True, help="Output file path")
@click.option(
    "--format", "-f", type=click.Choice(["csv", "json", "html", "excel"]), default="csv", help="Output format"
)
@click.option("--confidence", "-c", default=0.5, help="Confidence threshold")
def quick(input: str, output: str, format: str, confidence: float):
    """Quick extraction with minimal options."""
    try:
        logger.info(f"Quick extraction: {input} -> {output}")

        # Initialize pipeline
        pipeline = TableExtractionPipeline(confidence_threshold=confidence)

        # Extract tables
        tables = pipeline.extract_from_file(input)

        if not tables:
            logger.warning("No tables found")
            return

        # Export to single file
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        exporter = TableExporter(output_path.parent)
        results = exporter.export_tables(tables, output_path.stem, [format], include_metadata=False)

        logger.info(f"Extracted {len(tables)} table(s) to {output}")

    except Exception as e:
        logger.error(f"Quick extraction failed: {e}")
        raise click.ClickException(str(e))


@cli.command()
def version():
    """Show version information."""
    from .. import __version__

    click.echo(f"Table Extraction Pro v{__version__}")


if __name__ == "__main__":
    cli()

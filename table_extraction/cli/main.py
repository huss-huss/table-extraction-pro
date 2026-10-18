"""
Command-line interface for table extraction.
"""

import logging
from pathlib import Path
from typing import List

import click

from .. import __version__
from .._deps import MissingDependencyError, available_backends
from ..engine import ENGINES, SUPPORTED_EXTENSIONS, extract_tables
from ..export.exporter import TableExporter

logger = logging.getLogger("table_extraction.cli")

FORMATS = click.Choice(["csv", "json", "html", "excel"])
CONFIDENCE = click.FloatRange(0.0, 1.0)


def _engine(engine: str, use_fallback: bool) -> str:
    return "fallback" if use_fallback else engine


def _fail(exc: Exception) -> click.ClickException:
    return click.ClickException(str(exc))


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
@click.option("--quiet", "-q", is_flag=True, help="Only log errors")
def cli(verbose: bool, quiet: bool):
    """Table Extraction Pro - extract tables from PDFs and images."""
    level = logging.DEBUG if verbose else logging.ERROR if quiet else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger().setLevel(level)


def engine_options(f):
    f = click.option(
        "--use-fallback", is_flag=True, help="Shortcut for --engine fallback (kept for compatibility)"
    )(f)
    f = click.option(
        "--engine",
        "-e",
        type=click.Choice(ENGINES),
        default="auto",
        show_default=True,
        help="tatr: Table Transformer; fallback: Camelot+Tabula; auto: everything installed, compared",
    )(f)
    f = click.option("--confidence", "-c", type=CONFIDENCE, default=0.5, show_default=True)(f)
    return f


@cli.command()
@click.option("--input", "-i", "input_path", required=True, type=click.Path(exists=True, dir_okay=False))
@click.option("--output", "-o", required=True, type=click.Path(file_okay=False), help="Output directory")
@click.option("--formats", "-f", multiple=True, type=FORMATS, default=["csv", "json"], show_default=True)
@click.option("--include-metadata", is_flag=True, help="Include metadata in output")
@engine_options
def extract(
    input_path: str,
    output: str,
    formats: List[str],
    include_metadata: bool,
    confidence: float,
    engine: str,
    use_fallback: bool,
):
    """Extract tables from a single file."""
    try:
        tables = extract_tables(input_path, _engine(engine, use_fallback), confidence)
    except (MissingDependencyError, ValueError, FileNotFoundError) as e:
        raise _fail(e) from e
    if not tables:
        click.echo("No tables found.")
        return
    results = TableExporter(output).export_tables(
        tables, Path(input_path).stem, list(formats), include_metadata
    )
    click.echo(f"Extracted {len(tables)} table(s) from {input_path}")
    for fmt, path in results.items():
        click.echo(f"  {fmt}: {path}")


@cli.command()
@click.option("--input-folder", "-i", required=True, type=click.Path(exists=True, file_okay=False))
@click.option("--output-folder", "-o", required=True, type=click.Path(file_okay=False))
@click.option("--formats", "-f", multiple=True, type=FORMATS, default=["csv", "json"], show_default=True)
@click.option("--include-metadata", is_flag=True, help="Include metadata in output")
@click.option(
    "--file-extensions",
    multiple=True,
    default=list(SUPPORTED_EXTENSIONS),
    show_default=True,
    help="File extensions to process (case-insensitive)",
)
@engine_options
def batch(
    input_folder: str,
    output_folder: str,
    formats: List[str],
    include_metadata: bool,
    file_extensions: List[str],
    confidence: float,
    engine: str,
    use_fallback: bool,
):
    """Extract tables from every matching file in a folder."""
    wanted = {e.lower() if e.startswith(".") else f".{e.lower()}" for e in file_extensions}
    files = sorted(p for p in Path(input_folder).iterdir() if p.is_file() and p.suffix.lower() in wanted)
    if not files:
        click.echo(f"No files with extensions {sorted(wanted)} in {input_folder}")
        return

    engine = _engine(engine, use_fallback)
    batch_results = {}
    failures = 0
    with click.progressbar(files, label="Extracting") as bar:
        for path in bar:
            try:
                batch_results[str(path)] = extract_tables(path, engine, confidence)
            except MissingDependencyError as e:
                raise _fail(e) from e
            except Exception as e:
                logger.error(f"Failed to process {path}: {e}")
                batch_results[str(path)] = []
                failures += 1

    exporter = TableExporter(output_folder)
    exporter.export_batch(batch_results, list(formats), include_metadata)
    summary = exporter.create_summary_report(batch_results)
    total = sum(len(t) for t in batch_results.values())
    with_tables = sum(1 for t in batch_results.values() if t)
    click.echo(
        f"Processed {len(files)} file(s): {with_tables} with tables, {total} table(s), {failures} failure(s)"
    )
    click.echo(f"Summary: {summary}")


@cli.command()
@click.option("--input", "-i", "input_path", required=True, type=click.Path(exists=True, dir_okay=False))
@click.option("--output", "-o", required=True, type=click.Path(dir_okay=False), help="Output file")
@click.option("--format", "-f", "fmt", type=FORMATS, default="csv", show_default=True)
@engine_options
def quick(input_path: str, output: str, fmt: str, confidence: float, engine: str, use_fallback: bool):
    """Extract and write a single output file without metadata."""
    try:
        tables = extract_tables(input_path, _engine(engine, use_fallback), confidence)
    except (MissingDependencyError, ValueError, FileNotFoundError) as e:
        raise _fail(e) from e
    if not tables:
        click.echo("No tables found.")
        return
    output_path = Path(output)
    results = TableExporter(output_path.parent).export_tables(
        tables, output_path.stem, [fmt], include_metadata=False
    )
    click.echo(f"Extracted {len(tables)} table(s) to {results[fmt]}")


@cli.command()
def backends():
    """Show which extraction backends are installed."""
    for name, ok in available_backends().items():
        click.echo(f"{name:8s} {'available' if ok else 'missing'}")


@cli.command()
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=8000, show_default=True, type=int)
def serve(host: str, port: int):
    """Run the REST API with uvicorn."""
    import uvicorn

    uvicorn.run("table_extraction.api.main:app", host=host, port=port)


@cli.command()
def version():
    """Show version information."""
    click.echo(f"Table Extraction Pro v{__version__}")


if __name__ == "__main__":
    cli()

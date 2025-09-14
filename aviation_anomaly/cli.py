"""Command-line interface for Aviation Anomaly Tracker."""

import datetime
from pathlib import Path

import click

from aviation_anomaly.config import Config, ConfigError


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(version="0.1.0", prog_name="aviation-anomaly")
@click.option(
    "--config",
    type=click.Path(exists=False, path_type=Path),
    default="config.toml",
    help="Path to configuration file (default: config.toml)",
)
@click.pass_context
def main(ctx: click.Context, config: Path) -> None:
    """Aviation Anomaly Tracker - Analyze emergency patterns in flight data.

    This tool processes OpenSky flight data to detect and analyze aviation
    emergencies, aggregating them to H3 hexagonal grids for visualization.
    """
    # Store config path in context for subcommands
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config

    # Try to load config if any subcommand is invoked (not just --help)
    if ctx.invoked_subcommand is not None and not ctx.resilient_parsing:
        if config.exists():
            try:
                ctx.obj["config"] = Config.from_file(config)
            except ConfigError as e:
                click.echo(f"Error loading config: {e}", err=True)
                ctx.exit(1)
        else:
            # Config file not required for --help, but warn if missing for actual commands
            if ctx.invoked_subcommand not in ["--help", None]:
                click.echo(f"Warning: Config file not found at {config}. Using defaults where possible.", err=True)


@main.command()
@click.option(
    "--date",
    type=click.DateTime(["%Y-%m-%d"]),
    help="Single date to extract (YYYY-MM-DD)",
)
@click.option(
    "--from-date",
    type=click.DateTime(["%Y-%m-%d"]),
    help="Start date for range extraction (YYYY-MM-DD)",
)
@click.option(
    "--to-date",
    type=click.DateTime(["%Y-%m-%d"]),
    help="End date for range extraction (YYYY-MM-DD)",
)
@click.option(
    "--output-dir",
    type=click.Path(file_okay=False, dir_okay=True, path_type=Path),
    default=Path("data/raw"),
    help="Output directory for Parquet files",
)
@click.option(
    "--no-resume",
    is_flag=True,
    default=False,
    help="Force re-download of existing files (default: resume from existing)",
)
@click.pass_context
def extract(
    ctx: click.Context,
    date: datetime.datetime | None,
    from_date: datetime.datetime | None,
    to_date: datetime.datetime | None,
    output_dir: Path,
    no_resume: bool,
) -> None:
    """Extract daily data from OpenSky to Parquet files.

    Use either --date for a single day or --from-date and --to-date for a range.
    By default, skips existing hourly files (resumable). Use --no-resume to re-download.
    """
    from aviation_anomaly.extraction import extract_date_range, extract_day
    from aviation_anomaly.logging import configure_logging

    # Configure logging
    configure_logging()

    # Validate arguments
    if date and (from_date or to_date):
        click.echo("Error: Use either --date or --from-date/--to-date, not both", err=True)
        ctx.exit(1)

    if not date and not (from_date and to_date):
        click.echo("Error: Provide either --date or both --from-date and --to-date", err=True)
        ctx.exit(1)

    if date:
        # Single date extraction
        extract_date = date.date()
        click.echo(f"Extracting data for {extract_date}")
        click.echo(f"Output directory: {output_dir}")
        if no_resume:
            click.echo("Force re-download: enabled")

        try:
            output_file = extract_day(extract_date, output_dir, force_redownload=no_resume)
        except Exception as e:
            # Let the error propagate but ensure it's visible to the user
            if "QUERY_QUEUE_FULL" in str(e):
                click.echo("\n⚠️  Rate limiting detected. See error message above for instructions.", err=True)
            raise

        # Get file stats
        size_mb = output_file.stat().st_size / (1024 * 1024)

        # Quick row count
        import duckdb

        conn = duckdb.connect()
        count = conn.execute(f"SELECT COUNT(*) FROM '{output_file}'").fetchone()
        row_count = count[0] if count else 0
        conn.close()

        click.echo(f"✓ Extraction complete: {output_file}")
        click.echo(f"  Size: {size_mb:.2f} MB")
        click.echo(f"  Rows: {row_count:,}")
    else:
        # Date range extraction - we know these are not None due to validation above
        assert from_date is not None and to_date is not None
        start = from_date.date()
        end = to_date.date()

        click.echo(f"Extracting data from {start} to {end}")
        click.echo(f"Output directory: {output_dir}")
        if no_resume:
            click.echo("Force re-download: enabled")

        try:
            output_files = extract_date_range(start, end, output_dir, force_redownload=no_resume)
        except Exception as e:
            # Let the error propagate but ensure it's visible to the user
            if "QUERY_QUEUE_FULL" in str(e):
                click.echo("\n⚠️  Rate limiting detected. See error message above for instructions.", err=True)
            raise

        # Summary statistics
        total_size = sum(f.stat().st_size for f in output_files) / (1024 * 1024)
        click.echo(f"\n✓ Extracted {len(output_files)} files")
        click.echo(f"  Total size: {total_size:.2f} MB")

        for output_file in output_files:
            size_mb = output_file.stat().st_size / (1024 * 1024)
            click.echo(f"  {output_file.name}: {size_mb:.2f} MB")


@main.command()
@click.pass_context
def segment(ctx: click.Context) -> None:
    """Process flight segments with gap detection."""
    click.echo("Segmentation not yet implemented")


@main.command()
@click.pass_context
def detect(ctx: click.Context) -> None:
    """Detect emergency incidents from squawk codes."""
    click.echo("Detection not yet implemented")


@main.command()
@click.pass_context
def aggregate(ctx: click.Context) -> None:
    """Aggregate data to H3 hexagonal cells."""
    click.echo("Aggregation not yet implemented")


@main.command()
@click.pass_context
def tiles(ctx: click.Context) -> None:
    """Generate PMTiles for map visualization."""
    click.echo("Tile generation not yet implemented")


@main.command()
@click.option(
    "--host",
    default="127.0.0.1",
    help="Host to bind to (default: 127.0.0.1)",
)
@click.option(
    "--port",
    default=8000,
    type=int,
    help="Port to bind to (default: 8000)",
)
@click.pass_context
def serve(ctx: click.Context, host: str, port: int) -> None:
    """Start the API server for drill-down queries."""
    click.echo(f"Starting server on {host}:{port}")
    click.echo("Server not yet implemented")


if __name__ == "__main__":
    main()

"""Command-line interface for Aviation Anomaly Tracker."""

import datetime
import logging
from pathlib import Path

import click

from aviation_anomaly.config import Config, ConfigError

logger = logging.getLogger(__name__)


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

    # Load config if any subcommand is invoked (not just --help)
    if ctx.invoked_subcommand is not None and not ctx.resilient_parsing:
        if not config.exists():
            click.echo(f"Error: Config file not found at {config}", err=True)
            click.echo("Please create a config.toml file or specify one with --config", err=True)
            ctx.exit(1)

        try:
            ctx.obj["config"] = Config.from_file(config)
        except ConfigError as e:
            click.echo(f"Error loading config: {e}", err=True)
            ctx.exit(1)


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
@click.option(
    "--date",
    type=click.DateTime(["%Y-%m-%d"]),
    help="Single date to segment (YYYY-MM-DD)",
)
@click.option(
    "--from-date",
    type=click.DateTime(["%Y-%m-%d"]),
    help="Start date for range segmentation (YYYY-MM-DD)",
)
@click.option(
    "--to-date",
    type=click.DateTime(["%Y-%m-%d"]),
    help="End date for range segmentation (YYYY-MM-DD)",
)
@click.option(
    "--output-dir",
    type=click.Path(file_okay=False, dir_okay=True, path_type=Path),
    default=Path("data/segments"),
    help="Output directory for segment files",
)
@click.pass_context
def segment(
    ctx: click.Context,
    date: datetime.datetime | None,
    from_date: datetime.datetime | None,
    to_date: datetime.datetime | None,
    output_dir: Path,
) -> None:
    """Process flight segments with gap detection.

    Detects flight segments based on time gaps, calculates distances,
    and filters based on duration/distance criteria from config.toml.
    """
    from aviation_anomaly.logging import configure_logging
    from aviation_anomaly.segmentation import segment_date_range, segment_day

    configure_logging()

    # Get config from context - guaranteed to exist after main() changes
    config = ctx.obj["config"]

    # Validate arguments (same pattern as extract)
    if date and (from_date or to_date):
        click.echo("Error: Use either --date or --from-date/--to-date, not both", err=True)
        ctx.exit(1)

    if not date and not (from_date and to_date):
        click.echo("Error: Provide either --date or both --from-date and --to-date", err=True)
        ctx.exit(1)

    if date:
        # Single date segmentation
        segment_date = date.date()
        click.echo(f"Segmenting flights for {segment_date}")
        click.echo("Configuration:")
        click.echo(f"  Gap threshold: {config.segments.gap_minutes} minutes")
        click.echo(f"  Min duration: {config.segments.min_duration_s} seconds")
        click.echo(f"  Min distance: {config.segments.min_distance_km} km")

        try:
            output_file = segment_day(segment_date, output_dir, config)
        except FileNotFoundError as e:
            click.echo(f"Error: {e}", err=True)
            ctx.exit(1)

        # Show stats
        size_mb = output_file.stat().st_size / (1024 * 1024)

        # Quick segment count
        import duckdb

        conn = duckdb.connect()
        result = conn.execute(f"SELECT COUNT(*) FROM '{output_file}'").fetchone()
        segment_count = result[0] if result else 0
        conn.close()

        click.echo(f"✓ Segmentation complete: {output_file}")
        click.echo(f"  Size: {size_mb:.2f} MB")
        click.echo(f"  Segments: {segment_count:,}")
    else:
        # Date range segmentation
        assert from_date is not None and to_date is not None
        start = from_date.date()
        end = to_date.date()

        click.echo(f"Segmenting flights from {start} to {end}")
        click.echo("Configuration:")
        click.echo(f"  Gap threshold: {config.segments.gap_minutes} minutes")
        click.echo(f"  Min duration: {config.segments.min_duration_s} seconds")
        click.echo(f"  Min distance: {config.segments.min_distance_km} km")

        try:
            output_files = segment_date_range(start, end, output_dir, config)
        except FileNotFoundError as e:
            click.echo(f"Error: {e}", err=True)
            ctx.exit(1)

        # Summary statistics
        total_size = sum(f.stat().st_size for f in output_files) / (1024 * 1024)
        click.echo(f"\n✓ Segmented {len(output_files)} files")
        click.echo(f"  Total size: {total_size:.2f} MB")

        for output_file in output_files:
            size_mb = output_file.stat().st_size / (1024 * 1024)
            click.echo(f"  {output_file.name}: {size_mb:.2f} MB")


@main.command()
@click.option(
    "--date",
    type=click.DateTime(["%Y-%m-%d"]),
    help="Single date to detect incidents (YYYY-MM-DD)",
)
@click.option(
    "--from-date",
    type=click.DateTime(["%Y-%m-%d"]),
    help="Start date for range detection (YYYY-MM-DD)",
)
@click.option(
    "--to-date",
    type=click.DateTime(["%Y-%m-%d"]),
    help="End date for range detection (YYYY-MM-DD)",
)
@click.option(
    "--segments-dir",
    type=click.Path(file_okay=False, dir_okay=True, path_type=Path),
    default=Path("data/segments"),
    help="Directory containing segment files",
)
@click.option(
    "--output-dir",
    type=click.Path(file_okay=False, dir_okay=True, path_type=Path),
    default=Path("data/incidents"),
    help="Output directory for incident files",
)
@click.option(
    "--stats",
    is_flag=True,
    default=False,
    help="Show incident statistics after detection",
)
@click.pass_context
def detect(
    ctx: click.Context,
    date: datetime.datetime | None,
    from_date: datetime.datetime | None,
    to_date: datetime.datetime | None,
    segments_dir: Path,
    output_dir: Path,
    stats: bool,
) -> None:
    """Detect emergency incidents from flight segments with quality gates.

    Applies temporal validation (5+ samples in 60s), persistence checks (>45s),
    airborne validation (<30% ground), and confidence scoring to identify
    genuine emergency squawks (7500/7600/7700).
    """
    from aviation_anomaly.incident_detection import (
        analyze_incidents,
        detect_incidents,
        detect_incidents_range,
    )
    from aviation_anomaly.logging import configure_logging

    configure_logging()

    # Get config from context
    config = ctx.obj["config"]

    # Validate arguments (same pattern as other commands)
    if date and (from_date or to_date):
        click.echo("Error: Use either --date or --from-date/--to-date, not both", err=True)
        ctx.exit(1)

    if not date and not (from_date and to_date):
        click.echo("Error: Provide either --date or both --from-date and --to-date", err=True)
        ctx.exit(1)

    if date:
        # Single date detection
        detect_date = date.date()
        click.echo(f"Detecting incidents for {detect_date}")
        click.echo("Quality Gates:")
        click.echo("  ✓ Temporal: 5+ samples in 60 seconds")
        click.echo("  ✓ Persistence: >45 seconds duration")
        click.echo("  ✓ Airborne: <30% ground samples")
        click.echo(f"  ✓ Debounce: {config.incidents.debounce_minutes} minutes")

        try:
            output_file = detect_incidents(detect_date, segments_dir, output_dir, config)
        except FileNotFoundError as e:
            click.echo(f"Error: {e}", err=True)
            ctx.exit(1)

        # Show basic stats
        size_mb = output_file.stat().st_size / (1024 * 1024)

        # Quick incident count
        import duckdb

        conn = duckdb.connect()
        conn.execute("SET memory_limit = '1GB'")
        result = conn.execute(
            f"""
            SELECT
                COUNT(*) as total,
                COUNT(DISTINCT icao24) as aircraft,
                COUNT(CASE WHEN emergency_type = '7500' THEN 1 END) as hijack,
                COUNT(CASE WHEN emergency_type = '7600' THEN 1 END) as radio_fail,
                COUNT(CASE WHEN emergency_type = '7700' THEN 1 END) as general
            FROM '{output_file}'
        """
        ).fetchone()
        conn.close()

        click.echo(f"✓ Detection complete: {output_file}")
        click.echo(f"  Size: {size_mb:.2f} MB")

        if result and result[0] > 0:
            click.echo(f"  Incidents: {result[0]} ({result[1]} aircraft)")
            click.echo(f"    7500 (Hijack): {result[2]}")
            click.echo(f"    7600 (Radio Failure): {result[3]}")
            click.echo(f"    7700 (General Emergency): {result[4]}")

            if stats:
                # Show detailed statistics
                incident_stats = analyze_incidents(output_file)
                click.echo("\nDetailed Statistics:")
                click.echo(f"  Average duration: {incident_stats['avg_duration_seconds']:.1f} seconds")
                click.echo(f"  Max duration: {incident_stats['max_duration_seconds']} seconds")
                click.echo(f"  Average confidence: {incident_stats['avg_confidence']:.1f}")
                click.echo(f"  High confidence: {incident_stats['high_confidence_count']}")
                click.echo(f"  Roller-dial detected: {incident_stats['roller_dial_count']}")
        else:
            click.echo("  No incidents detected")
    else:
        # Date range detection
        assert from_date is not None and to_date is not None
        start = from_date.date()
        end = to_date.date()

        click.echo(f"Detecting incidents from {start} to {end}")
        click.echo("Quality Gates:")
        click.echo("  ✓ Temporal: 5+ samples in 60 seconds")
        click.echo("  ✓ Persistence: >45 seconds duration")
        click.echo("  ✓ Airborne: <30% ground samples")
        click.echo(f"  ✓ Debounce: {config.incidents.debounce_minutes} minutes")

        try:
            output_files = detect_incidents_range(start, end, segments_dir, output_dir, config)
        except Exception as e:
            click.echo(f"Error: {e}", err=True)
            ctx.exit(1)

        # Summary statistics
        total_size = sum(f.stat().st_size for f in output_files) / (1024 * 1024)
        click.echo(f"\n✓ Detected incidents for {len(output_files)} days")
        click.echo(f"  Total size: {total_size:.2f} MB")

        for output_file in output_files:
            size_mb = output_file.stat().st_size / (1024 * 1024)
            click.echo(f"  {output_file.name}: {size_mb:.2f} MB")


@main.command()
@click.option(
    "--segment-file",
    type=click.Path(exists=True, path_type=Path),
    help="Path to segment Parquet file",
)
@click.option(
    "--incidents-file",
    type=click.Path(exists=True, path_type=Path),
    help="Path to incidents Parquet file (auto-detected if not provided)",
)
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path),
    default=Path("data/h3"),
    help="Directory for H3 aggregation output (default: data/h3)",
)
@click.option(
    "--resolutions",
    default="3,4,5,6,7",
    help="Comma-separated H3 resolutions (default: 3,4,5,6,7)",
)
@click.pass_context
def aggregate(
    ctx: click.Context,
    segment_file: Path | None,
    incidents_file: Path | None,
    output_dir: Path,
    resolutions: str,
) -> None:
    """Aggregate segments to H3 hexagonal cells at multiple resolutions."""
    from aviation_anomaly.h3_aggregation import compute_h3_coverage_multi_resolution

    # Parse resolutions
    resolution_list = [int(r.strip()) for r in resolutions.split(",")]

    # Auto-detect segment file if not provided
    if segment_file is None:
        segment_dir = Path("data/segments")
        if segment_dir.exists():
            segment_files = sorted(segment_dir.glob("segments_*.parquet"))
            if segment_files:
                segment_file = segment_files[-1]  # Use most recent
                click.echo(f"Using segment file: {segment_file}")
            else:
                click.echo("Error: No segment files found in data/segments/", err=True)
                ctx.exit(1)
        else:
            click.echo("Error: No segment file provided and data/segments/ doesn't exist", err=True)
            ctx.exit(1)

    if not segment_file.exists():
        click.echo(f"Error: Segment file not found: {segment_file}", err=True)
        ctx.exit(1)

    click.echo(f"Computing H3 aggregation for resolutions: {resolution_list}")
    click.echo(f"Input: {segment_file}")
    click.echo(f"Output directory: {output_dir}")

    # Load config
    config = ctx.obj["config"]

    # Run aggregation
    try:
        results = compute_h3_coverage_multi_resolution(
            segment_file=segment_file,
            output_dir=output_dir,
            resolutions=resolution_list,
            config=config,
        )

        click.echo("\nAggregation complete. Output files:")
        for res, path in results.items():
            if path.exists():
                size_mb = path.stat().st_size / (1024 * 1024)
                click.echo(f"  Resolution {res}: {path} ({size_mb:.1f} MB)")

        # Determine incidents file to process
        if incidents_file is None:
            # Auto-detect based on segment filename
            segment_date = segment_file.stem.replace("segments_", "")
            incidents_dir = segment_file.parent.parent / "incidents"
            incidents_file = incidents_dir / f"incidents_{segment_date}.parquet"

            # Only process if auto-detected file exists
            process_incidents = incidents_file.exists()
        else:
            # Explicit file provided - always process
            process_incidents = True

        if process_incidents:
            click.echo(f"\nProcessing incidents from: {incidents_file}")
            from aviation_anomaly.h3_aggregation import compute_dual_incident_metrics

            # Process incidents for each resolution
            for res in resolution_list:
                incident_output = output_dir / f"h3_incidents_r{res}.parquet"
                compute_dual_incident_metrics(
                    incidents_file=incidents_file,
                    segments_file=segment_file,
                    output_file=incident_output,
                    resolution=res,
                    config=config,
                )
                if incident_output.exists():
                    size_mb = incident_output.stat().st_size / (1024 * 1024)
                    click.echo(f"  Incident metrics r{res}: {incident_output} ({size_mb:.1f} MB)")
        else:
            click.echo(f"\nNo incidents file found at {incidents_file}, skipping incident metrics")
    except Exception as e:
        logger.exception("H3 aggregation failed")
        click.echo(f"Error: {e}", err=True)
        ctx.exit(1)


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

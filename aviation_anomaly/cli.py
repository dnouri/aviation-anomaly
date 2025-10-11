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
    "--filter-profile",
    type=str,
    help="Filter profile to use (production/research/high_security/none)",
)
@click.option(
    "--list-profiles",
    is_flag=True,
    default=False,
    help="List available filter profiles and exit",
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
    filter_profile: str | None,
    list_profiles: bool,
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

    # Handle --list-profiles
    if list_profiles:
        click.echo("Available filter profiles:")
        if config.incidents.profiles:
            for name, profile in config.incidents.profiles.items():
                click.echo(f"  {name}: {profile.description}")
        else:
            click.echo("  No profiles configured")
        click.echo(f"\nDefault profile: {config.incidents.default_profile}")
        return

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

        # Show filter profile being used
        if filter_profile:
            if filter_profile in config.incidents.profiles:
                profile = config.incidents.profiles[filter_profile]
                click.echo(f"\nFilter Profile: {filter_profile}")
                click.echo(f"  {profile.description}")
            else:
                click.echo(f"  Filter: {filter_profile}")
        else:
            click.echo(f"\nFilter Profile: {config.incidents.default_profile} (default)")
            if config.incidents.default_profile in config.incidents.profiles:
                profile = config.incidents.profiles[config.incidents.default_profile]
                click.echo(f"  {profile.description}")

        try:
            output_file = detect_incidents(detect_date, segments_dir, output_dir, config, filter_profile)
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

        # Show filter profile being used
        if filter_profile:
            if filter_profile in config.incidents.profiles:
                profile = config.incidents.profiles[filter_profile]
                click.echo(f"\nFilter Profile: {filter_profile}")
                click.echo(f"  {profile.description}")
            else:
                click.echo(f"  Filter: {filter_profile}")
        else:
            click.echo(f"\nFilter Profile: {config.incidents.default_profile} (default)")
            if config.incidents.default_profile in config.incidents.profiles:
                profile = config.incidents.profiles[config.incidents.default_profile]
                click.echo(f"  {profile.description}")

        try:
            output_files = detect_incidents_range(start, end, segments_dir, output_dir, config, filter_profile)
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
    default="3,4,5,6",
    help="Comma-separated H3 resolutions (default: 3,4,5,6)",
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Force regeneration of existing files (default: skip existing)",
)
@click.pass_context
def aggregate(
    ctx: click.Context,
    segment_file: Path | None,
    incidents_file: Path | None,
    output_dir: Path,
    resolutions: str,
    force: bool,
) -> None:
    """Aggregate segments to H3 hexagonal cells at multiple resolutions.

    By default, skips existing output files for faster incremental processing.
    Use --force to regenerate all files regardless of existence.
    """
    from aviation_anomaly.h3_aggregation import compute_h3_coverage_multi_resolution

    # Parse resolutions
    resolution_list = [int(r.strip()) for r in resolutions.split(",")]

    # Auto-detect or validate segment files - always work with explicit file lists
    if segment_file is None:
        # Auto-detect all segment files matching date pattern (YYYY-MM-DD)
        # This excludes test/sample files like segments_sample.parquet
        import re

        DATE_PATTERN = re.compile(r"segments_\d{4}-\d{2}-\d{2}\.parquet$")

        segment_dir = Path("data/segments")
        if segment_dir.exists():
            all_files = sorted(segment_dir.glob("segments_*.parquet"))
            segment_files = [f for f in all_files if DATE_PATTERN.match(f.name)]
            if not segment_files:
                click.echo("Error: No dated segment files found in data/segments/", err=True)
                ctx.exit(1)
        else:
            click.echo("Error: No segment file provided and data/segments/ doesn't exist", err=True)
            ctx.exit(1)
    else:
        # Single file provided - wrap in list for uniform processing
        if not segment_file.exists():
            click.echo(f"Error: Segment file not found: {segment_file}", err=True)
            ctx.exit(1)
        segment_files = [segment_file]

    click.echo(f"Computing H3 aggregation for resolutions: {resolution_list}")
    click.echo(f"Processing {len(segment_files)} segment file(s)")
    for sf in segment_files[:3]:  # Show first 3 files
        click.echo(f"  - {sf.name}")
    if len(segment_files) > 3:
        click.echo(f"  ... and {len(segment_files) - 3} more")
    click.echo(f"Output directory: {output_dir}")
    if force:
        click.echo("Force mode: Will regenerate existing files")
    else:
        click.echo("Skip mode: Will skip existing files (use --force to regenerate)")

    # Load config
    config = ctx.obj["config"]

    # Filter resolutions to process based on existing files
    resolutions_to_process = []
    for res in resolution_list:
        coverage_file = output_dir / f"h3_coverage_r{res}.parquet"
        if force or not coverage_file.exists():
            resolutions_to_process.append(res)
        else:
            size_mb = coverage_file.stat().st_size / (1024 * 1024)
            click.echo(f"  Skipping existing h3_coverage_r{res}.parquet ({size_mb:.1f} MB)")

    # Run aggregation only for missing resolutions
    results = {}
    if resolutions_to_process:
        try:
            from aviation_anomaly.h3_aggregation import compute_h3_coverage_multi_resolution

            results = compute_h3_coverage_multi_resolution(
                segment_files=segment_files,
                output_dir=output_dir,
                resolutions=resolutions_to_process,
                config=config,
            )

            click.echo("\nAggregation complete. Output files:")
            for res, path in results.items():
                if path.exists():
                    size_mb = path.stat().st_size / (1024 * 1024)
                    click.echo(f"  Resolution {res}: {path} ({size_mb:.1f} MB)")
        except Exception as e:
            logger.exception("H3 coverage aggregation failed")
            click.echo(f"Error during coverage aggregation: {e}", err=True)
            ctx.exit(1)
    else:
        click.echo("\nAll H3 coverage files already exist, skipping coverage aggregation")

    # Determine incidents files to process - match each segment file
    if incidents_file is None:
        # Auto-detect incident files matching segment files
        incidents_dir = Path("data/incidents")
        incident_files = []

        for seg_file in segment_files:
            # Extract date from segment filename (e.g., segments_2025-07-02.parquet → 2025-07-02)
            segment_date = seg_file.stem.replace("segments_", "")
            inc_file = incidents_dir / f"incidents_{segment_date}.parquet"
            if inc_file.exists():
                incident_files.append(inc_file)

        process_incidents = len(incident_files) > 0
        if process_incidents:
            click.echo(f"\nFound {len(incident_files)} incident file(s) matching segments")
    else:
        # Single incidents file provided - wrap in list
        if not incidents_file.exists():
            click.echo(f"Error: Incidents file not found: {incidents_file}", err=True)
            ctx.exit(1)
        incident_files = [incidents_file]
        process_incidents = True

    if process_incidents:
        click.echo(f"\nProcessing incidents for {len(incident_files)} day(s)")
        from aviation_anomaly.h3_aggregation import compute_dual_incident_metrics

        # Process incidents for each resolution
        incidents_processed = []
        for res in resolution_list:
            incident_output = output_dir / f"h3_incidents_r{res}.parquet"
            mapping_output = output_dir / f"incident_h3_mapping_r{res}.parquet"

            # Check if both output files exist
            if not force and incident_output.exists() and mapping_output.exists():
                inc_size = incident_output.stat().st_size / (1024 * 1024)
                map_size = mapping_output.stat().st_size / (1024 * 1024)
                click.echo(f"  Skipping existing r{res}: incidents ({inc_size:.1f} MB), mapping ({map_size:.1f} MB)")
                continue

            try:
                click.echo(f"  Processing resolution {res}...")
                compute_dual_incident_metrics(
                    incidents_files=incident_files,
                    segments_files=segment_files,
                    output_file=incident_output,
                    resolution=res,
                    config=config,
                )
                incidents_processed.append(res)

                if incident_output.exists():
                    inc_size = incident_output.stat().st_size / (1024 * 1024)
                    click.echo(f"    ✓ Incident metrics: {inc_size:.1f} MB")
                if mapping_output.exists():
                    map_size = mapping_output.stat().st_size / (1024 * 1024)
                    click.echo(f"    ✓ Incident mapping: {map_size:.1f} MB")
            except Exception as e:
                logger.exception(f"Failed to process incidents for resolution {res}")
                click.echo(f"    ✗ Error: {e}", err=True)

        if incidents_processed:
            click.echo(f"\n✓ Processed incidents for resolutions: {incidents_processed}")
        else:
            click.echo("\nAll incident files already exist, skipping incident processing")
    else:
        click.echo(f"\nNo incidents file found at {incidents_file}, skipping incident metrics")


@main.command()
@click.option(
    "--h3-dir",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
    default=Path("data/h3"),
    help="Directory containing H3 aggregation files",
)
@click.option(
    "--output-dir",
    type=click.Path(file_okay=False, dir_okay=True, path_type=Path),
    default=Path("data/tiles"),
    help="Directory for tile output (GeoJSON and PMTiles)",
)
@click.option(
    "--resolutions",
    multiple=True,
    type=click.IntRange(3, 6),
    help="H3 resolutions to export (default: 3-6)",
)
@click.option(
    "--skip-geojson",
    is_flag=True,
    default=False,
    help="Skip GeoJSON generation if files already exist",
)
@click.option(
    "--pmtiles",
    is_flag=True,
    default=False,
    help="Also generate PMTiles using Tippecanoe",
)
@click.pass_context
def tiles(
    ctx: click.Context,
    h3_dir: Path,
    output_dir: Path,
    resolutions: tuple[int, ...],
    skip_geojson: bool,
    pmtiles: bool,
) -> None:
    """Generate tiles from H3 aggregations for map visualization.

    First exports H3 data to GeoJSON, then optionally generates PMTiles
    using Tippecanoe for efficient web map rendering.
    """
    from aviation_anomaly.pmtiles_generation import (
        check_tippecanoe_installed,
        generate_pmtiles_for_resolutions,
    )
    from aviation_anomaly.tile_generation import export_h3_files_to_geojson

    # Convert resolutions tuple to list, or use default
    res_list = list(resolutions) if resolutions else None

    # Set up directories
    geojsonl_dir = output_dir / "geojsonl"
    pmtiles_dir = output_dir / "pmtiles"

    # Generate GeoJSONL files
    if not skip_geojson:
        click.echo(f"Exporting H3 data from {h3_dir} to {geojsonl_dir}")
        if res_list:
            click.echo(f"Resolutions: {res_list}")

        export_h3_files_to_geojson(h3_dir, geojsonl_dir, res_list)
        click.echo(f"✓ GeoJSONL files written to {geojsonl_dir}")
    else:
        click.echo(f"Skipping GeoJSONL generation (using existing files in {geojsonl_dir})")

    # Generate PMTiles if requested
    if pmtiles:
        if not check_tippecanoe_installed():
            click.echo("\n⚠️  Tippecanoe is not installed. Cannot generate PMTiles.", err=True)
            click.echo("Install it from: https://github.com/mapbox/tippecanoe", err=True)
            ctx.exit(1)

        click.echo(f"\nGenerating PMTiles in {pmtiles_dir}")

        try:
            results = generate_pmtiles_for_resolutions(
                geojson_dir=geojsonl_dir,
                output_dir=pmtiles_dir,
                resolutions=res_list,
            )

            if results:
                click.echo("✓ PMTiles generation complete:")
                for res, path in results.items():
                    size_mb = path.stat().st_size / (1024 * 1024)
                    click.echo(f"  Resolution {res}: {path.name} ({size_mb:.1f} MB)")
            else:
                click.echo("⚠️  No PMTiles generated. Check logs for errors.", err=True)
        except Exception as e:
            click.echo(f"Error generating PMTiles: {e}", err=True)
            ctx.exit(1)
    else:
        click.echo("\nTo generate PMTiles, run with --pmtiles flag")


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
@click.option(
    "--reload",
    is_flag=True,
    default=False,
    help="Enable auto-reload for development",
)
@click.pass_context
def serve(ctx: click.Context, host: str, port: int, reload: bool) -> None:
    """Start the API server for drill-down queries.

    Provides HTTP endpoints for querying H3 cell summaries and incident details.
    Access the interactive API documentation at http://HOST:PORT/docs
    """
    import uvicorn

    from aviation_anomaly.api import create_app

    click.echo(f"Starting Aviation Anomaly Tracker API on {host}:{port}")
    click.echo(f"Interactive API docs: http://{host}:{port}/docs")
    click.echo(f"OpenAPI schema: http://{host}:{port}/openapi.json")
    click.echo("Press CTRL+C to stop the server")

    app = create_app()
    uvicorn.run(app, host=host, port=port, reload=reload)


if __name__ == "__main__":
    main()

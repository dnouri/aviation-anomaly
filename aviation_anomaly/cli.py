"""Command-line interface for Aviation Anomaly Tracker."""

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
@click.pass_context
def extract(ctx: click.Context) -> None:
    """Extract monthly data from OpenSky to Parquet files."""
    click.echo("Extraction not yet implemented")


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

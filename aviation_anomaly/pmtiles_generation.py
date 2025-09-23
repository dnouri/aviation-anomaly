"""Generate PMTiles from GeoJSON using Tippecanoe."""

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def get_zoom_range_for_resolution(resolution: int) -> tuple[int, int]:
    """Get appropriate zoom range for H3 resolution.

    Args:
        resolution: H3 resolution (3-7)

    Returns:
        Tuple of (min_zoom, max_zoom)
    """
    # Map H3 resolution to appropriate zoom ranges
    # H3 res 3 is very coarse (avg edge 59km), good for z3-7
    # H3 res 5 is medium (avg edge 9km), good for z5-9
    # H3 res 7 is fine (avg edge 1.3km), good for z7-11
    zoom_ranges = {
        3: (3, 7),
        4: (4, 8),
        5: (5, 9),
        6: (6, 10),
        7: (7, 11),
    }
    return zoom_ranges.get(resolution, (resolution, resolution + 4))


def build_tippecanoe_command(
    input_file: Path,
    output_file: Path,
    min_zoom: int,
    max_zoom: int,
    preserve_attributes: list[str] | None = None,
) -> list[str]:
    """Build Tippecanoe command with appropriate parameters.

    Args:
        input_file: Input GeoJSONL file (newline-delimited)
        output_file: Output PMTiles file
        min_zoom: Minimum zoom level
        max_zoom: Maximum zoom level
        preserve_attributes: List of attributes to preserve

    Returns:
        Command as list of strings for subprocess
    """
    # Check if input is GeoJSONL format for optimized parsing
    is_geojsonl = input_file.suffix.lower() in (".geojsonl", ".gz")

    cmd = [
        "tippecanoe",
        "-o",
        str(output_file),
        "--layer=h3_cells",  # Standardize layer name across all resolutions
        f"--minimum-zoom={min_zoom}",
        f"--maximum-zoom={max_zoom}",
        "--maximum-tile-features=10000",  # Limit features per tile for size control
        "--simplification=10",  # Simplify geometries at lower zooms
        "--force",  # Overwrite output if exists
        "--drop-densest-as-needed",  # Drop features to stay within limits
        "--extend-zooms-if-still-dropping",  # Extend zooms if features being dropped
    ]

    # Add -P flag for faster parsing of newline-delimited GeoJSON
    if is_geojsonl:
        cmd.append("-P")

    # Add attribute preservation
    if preserve_attributes:
        for attr in preserve_attributes:
            cmd.extend(["--include", attr])

    # Add input file last
    cmd.append(str(input_file))

    return cmd


def check_tippecanoe_installed() -> bool:
    """Check if Tippecanoe is installed and available.

    Returns:
        True if Tippecanoe is available, False otherwise
    """
    try:
        result = subprocess.run(
            ["tippecanoe", "--version"],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


def generate_pmtiles(
    input_file: Path,
    output_file: Path,
    resolution: int,
    preserve_all_attributes: bool = False,
) -> Path:
    """Generate PMTiles from GeoJSONL using Tippecanoe.

    Args:
        input_file: Input GeoJSONL file (newline-delimited)
        output_file: Output PMTiles file
        resolution: H3 resolution (used to determine zoom levels)
        preserve_all_attributes: If True, preserve all GeoJSON properties

    Returns:
        Path to generated PMTiles file

    Raises:
        RuntimeError: If Tippecanoe is not installed or generation fails
        FileNotFoundError: If input file doesn't exist
    """
    if not input_file.exists():
        raise FileNotFoundError(f"Input file not found: {input_file}")

    if not check_tippecanoe_installed():
        raise RuntimeError("Tippecanoe is not installed. Please install it from https://github.com/mapbox/tippecanoe")

    # Get zoom range based on resolution
    min_zoom, max_zoom = get_zoom_range_for_resolution(resolution)

    # Build command
    if preserve_all_attributes:
        # Don't specify attributes to preserve all
        cmd = build_tippecanoe_command(
            input_file=input_file,
            output_file=output_file,
            min_zoom=min_zoom,
            max_zoom=max_zoom,
        )
    else:
        # Preserve key attributes for visualization
        # These must match exactly what's in the GeoJSONL
        key_attributes = [
            "h3_cell",
            "h3_res",
            "incidents_unique",
            "incidents_coverage",
            "unique_flights",
            "incident_rate",
            "predominant_emergency_type",
            "emergency_types_list",
            "emergency_type_diversity",
            "total_segments",
            "unique_segments",
            "unique_aircraft",
            "total_points",
            "aircraft_with_incidents",
        ]
        cmd = build_tippecanoe_command(
            input_file=input_file,
            output_file=output_file,
            min_zoom=min_zoom,
            max_zoom=max_zoom,
            preserve_attributes=key_attributes,
        )

    # Create output directory if needed
    output_file.parent.mkdir(parents=True, exist_ok=True)

    # Run Tippecanoe
    logger.info(f"Running Tippecanoe for resolution {resolution}")
    logger.debug(f"Command: {' '.join(cmd)}")

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(f"Tippecanoe failed with code {result.returncode}\nstderr: {result.stderr}")

    if not output_file.exists():
        raise RuntimeError(f"Tippecanoe completed but output file not found: {output_file}")

    file_size_mb = output_file.stat().st_size / (1024 * 1024)
    logger.info(f"Generated PMTiles: {output_file} ({file_size_mb:.1f} MB) for zoom levels {min_zoom}-{max_zoom}")

    return output_file


def generate_pmtiles_for_resolutions(
    geojson_dir: Path,
    output_dir: Path,
    resolutions: list[int] | None = None,
) -> dict[int, Path]:
    """Generate PMTiles for multiple H3 resolutions.

    Args:
        geojson_dir: Directory containing GeoJSONL files
        output_dir: Directory for PMTiles output
        resolutions: List of resolutions to process (default: 3-7)

    Returns:
        Dictionary mapping resolution to output file path
    """
    if resolutions is None:
        resolutions = [3, 4, 5, 6, 7]

    results = {}

    for res in resolutions:
        # Try compressed and uncompressed GeoJSONL, then legacy GeoJSON
        input_file = geojson_dir / f"h3_r{res}.geojsonl.gz"
        if not input_file.exists():
            input_file = geojson_dir / f"h3_r{res}.geojsonl"
        if not input_file.exists():
            input_file = geojson_dir / f"h3_r{res}.geojson"

        if not input_file.exists():
            logger.warning(f"GeoJSON file not found: {input_file}")
            continue

        output_file = output_dir / f"h3_r{res}.pmtiles"

        try:
            results[res] = generate_pmtiles(
                input_file=input_file,
                output_file=output_file,
                resolution=res,
            )
        except RuntimeError as e:
            logger.error(f"Failed to generate PMTiles for resolution {res}: {e}")
            continue

    return results

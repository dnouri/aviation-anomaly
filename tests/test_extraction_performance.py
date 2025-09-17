"""Test extraction performance improvements."""

import datetime
import time

from aviation_anomaly.extraction import extract_hour


def test_extract_hour_performance(tmp_path, monkeypatch):
    """Test that extraction completes quickly for large datasets."""
    # Arrange - Create mock data (1 million rows)
    mock_data = [
        (
            1704067200 + i,  # time
            f"icao{i:06d}",  # icao24
            f"CALL{i:04d}",  # callsign
            40.0 + (i % 100) / 100,  # lat
            -74.0 + (i % 100) / 100,  # lon
            "7700" if i % 1000 == 0 else "1200",  # squawk
            False,  # onground
            i % 100 == 0,  # alert
        )
        for i in range(1_000_000)
    ]

    # Mock TrinoQueryEngine
    class MockEngine:
        def execute(self, query):
            return iter(mock_data)

    monkeypatch.setattr("aviation_anomaly.extraction.TrinoQueryEngine", MockEngine)

    # Act - Time the extraction
    start_time = time.time()
    output_file = extract_hour(date=datetime.date(2024, 1, 1), hour=0, output_dir=tmp_path)
    elapsed = time.time() - start_time

    # Assert - Should complete in reasonable time
    assert output_file.exists()
    assert output_file.suffix == ".parquet"

    # Should process 1M rows in under 10 seconds (current takes ~700s at 1.3k rows/s)
    assert elapsed < 10.0, f"Extraction took {elapsed:.2f}s, expected < 10s"

    # Verify data integrity
    import duckdb

    conn = duckdb.connect()
    count_result = conn.execute(f"SELECT COUNT(*) FROM '{output_file}'").fetchone()
    assert count_result is not None
    assert count_result[0] == 1_000_000

    # Verify sample data
    sample = conn.execute(f"SELECT * FROM '{output_file}' LIMIT 1").fetchone()
    assert sample is not None
    assert len(sample) == 8  # All columns present

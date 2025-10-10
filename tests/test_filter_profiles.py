"""Tests for filter profile functionality in incident detection."""

import datetime

import pytest

from aviation_anomaly.config import Config, FilterProfile
from aviation_anomaly.incident_detection import detect_incidents


class TestFilterProfiles:
    """Test filter profiles reduce incident counts appropriately."""

    @pytest.fixture
    def config_with_profiles(self):
        """Create config with filter profiles."""
        config = Config()

        # Add filter profiles programmatically
        config.incidents.profiles = {
            "production": FilterProfile(
                name="production",
                description="Balanced filtering",
                min_confidence=70,
                min_duration_s=120,
                max_samples_7500=430,
                max_samples_7600=379,
                max_samples_7700=224,
                min_samples_7500=186,
                min_samples_7600=163,
                min_samples_7700=116,
            ),
            "research": FilterProfile(
                name="research",
                description="Minimal filtering",
                min_confidence=50,
                min_duration_s=60,
                max_samples_7500=993,
                max_samples_7600=614,
                max_samples_7700=538,
                min_samples_7500=100,
                min_samples_7600=86,
                min_samples_7700=82,
            ),
            "high_security": FilterProfile(
                name="high_security",
                description="Strict filtering",
                min_confidence=80,
                min_duration_s=180,
                max_samples_7500=186,
                max_samples_7600=163,
                max_samples_7700=116,
                min_samples_7500=186,
                min_samples_7600=163,
                min_samples_7700=116,
            ),
        }
        config.incidents.default_profile = "none"
        return config

    @pytest.fixture
    def segments_with_many_incidents(self, tmp_path):
        """Create segments file with various incident types."""
        import duckdb

        segments_file = tmp_path / "segments_2025-09-01.parquet"

        conn = duckdb.connect()
        conn.execute("SET memory_limit = '1GB'")

        # Create segments with different characteristics
        # Some will pass filters, some won't
        segments = []

        # 7500 with varying sample counts
        for i, samples in enumerate([5, 10, 50, 100, 200, 300, 500, 1000]):
            segments.append(f"""
                ('7500_{i}', 'abc{i:03d}', 1000, 2000, 1000, {samples + 10},
                 CAST([
                    {"(1000, '7500', false, 45.0, -122.0)," * samples}
                    (2000, '7500', false, 45.0, -122.0)
                 ] AS STRUCT(time INTEGER, squawk VARCHAR, onground BOOLEAN, lat DOUBLE, lon DOUBLE)[])
                )
            """)

        # 7600 and 7700 with moderate counts
        for i in range(3):
            segments.append(f"""
                ('7600_{i}', 'def{i:03d}', 3000, 4000, 1000, 150,
                 CAST([
                    {"(3000, '7600', false, 45.0, -122.0)," * 140}
                    (4000, '7600', false, 45.0, -122.0)
                 ] AS STRUCT(time INTEGER, squawk VARCHAR, onground BOOLEAN, lat DOUBLE, lon DOUBLE)[])
                )
            """)
            segments.append(f"""
                ('7700_{i}', 'ghi{i:03d}', 5000, 6000, 1000, 150,
                 CAST([
                    {"(5000, '7700', false, 45.0, -122.0)," * 140}
                    (6000, '7700', false, 45.0, -122.0)
                 ] AS STRUCT(time INTEGER, squawk VARCHAR, onground BOOLEAN, lat DOUBLE, lon DOUBLE)[])
                )
            """)

        # Execute the creation
        conn.execute(f"""
            COPY (
                SELECT * FROM (VALUES {",".join(segments)})
                AS t(segment_id, icao24, start_time, end_time,
                     duration_seconds, point_count, points)
            ) TO '{segments_file}' (FORMAT PARQUET)
        """)
        conn.close()

        return segments_file

    def test_no_filter_returns_all_incidents(self, config_with_profiles, segments_with_many_incidents, tmp_path):
        """Without filter, all incidents passing basic quality gates are returned."""
        # Run with no filter
        output_file = detect_incidents(
            date=datetime.date(2025, 9, 1),
            segments_dir=segments_with_many_incidents.parent,
            output_dir=tmp_path,
            config=config_with_profiles,
            filter_profile="none",
        )

        # Check results
        import duckdb

        conn = duckdb.connect()
        result = conn.execute(f"""
            SELECT
                COUNT(*) as total,
                COUNT(CASE WHEN emergency_type = '7500' THEN 1 END) as hijack,
                COUNT(CASE WHEN emergency_type = '7600' THEN 1 END) as radio,
                COUNT(CASE WHEN emergency_type = '7700' THEN 1 END) as general
            FROM '{output_file}'
        """).fetchone()
        conn.close()

        assert result is not None, "Query should return results"
        total, hijack, radio, general = result

        # With no filter, we should get most incidents
        # (some very small ones still filtered by basic quality gates)
        assert total > 10
        assert hijack >= 5  # At least the larger sample count ones
        assert radio >= 2
        assert general >= 2

    def test_production_filter_reduces_incidents(self, config_with_profiles, segments_with_many_incidents, tmp_path):
        """Production filter should significantly reduce incidents."""
        # Apply production profile settings
        config_with_profiles.incidents.default_profile = "production"

        output_file = detect_incidents(
            date=datetime.date(2025, 9, 1),
            segments_dir=segments_with_many_incidents.parent,
            output_dir=tmp_path,
            config=config_with_profiles,
            filter_profile="production",
        )

        # Check results
        import duckdb

        conn = duckdb.connect()
        result = conn.execute(f"""
            SELECT
                COUNT(*) as total,
                COUNT(CASE WHEN emergency_type = '7500' THEN 1 END) as hijack,
                COUNT(CASE WHEN emergency_type = '7600' THEN 1 END) as radio,
                COUNT(CASE WHEN emergency_type = '7700' THEN 1 END) as general
            FROM '{output_file}'
        """).fetchone()
        conn.close()

        assert result is not None, "Query should return results"
        total, hijack, radio, general = result

        # Production filter should significantly reduce counts
        assert total < 10  # Much fewer than no filter
        assert hijack <= 3  # Only moderate sample counts pass

    def test_research_filter_is_lenient(self, config_with_profiles, segments_with_many_incidents, tmp_path):
        """Research filter should be more lenient than production."""
        config_with_profiles.incidents.default_profile = "research"

        output_file = detect_incidents(
            date=datetime.date(2025, 9, 1),
            segments_dir=segments_with_many_incidents.parent,
            output_dir=tmp_path,
            config=config_with_profiles,
            filter_profile="research",
        )

        import duckdb

        conn = duckdb.connect()
        result = conn.execute(f"""
            SELECT COUNT(*) as total
            FROM '{output_file}'
        """).fetchone()
        conn.close()

        assert result is not None, "Query should return results"
        research_total = result[0]

        # Now test production for comparison
        output_file_prod = detect_incidents(
            date=datetime.date(2025, 9, 1),
            segments_dir=segments_with_many_incidents.parent,
            output_dir=tmp_path / "prod",
            config=config_with_profiles,
            filter_profile="production",
        )

        conn = duckdb.connect()
        result = conn.execute(f"""
            SELECT COUNT(*) as total
            FROM '{output_file_prod}'
        """).fetchone()
        conn.close()

        assert result is not None, "Query should return results"
        production_total = result[0]

        # Research should have more incidents than production
        assert research_total > production_total

    def test_high_security_filter_is_strictest(self, config_with_profiles, segments_with_many_incidents, tmp_path):
        """High security filter should be the most restrictive."""
        config_with_profiles.incidents.default_profile = "high_security"

        output_file = detect_incidents(
            date=datetime.date(2025, 9, 1),
            segments_dir=segments_with_many_incidents.parent,
            output_dir=tmp_path,
            config=config_with_profiles,
            filter_profile="high_security",
        )

        import duckdb

        conn = duckdb.connect()
        result = conn.execute(f"""
            SELECT COUNT(*) as total
            FROM '{output_file}'
        """).fetchone()
        conn.close()

        assert result is not None, "Query should return results"
        high_sec_total = result[0]

        # High security should have very few or no incidents
        assert high_sec_total <= 2  # Very strict

    @pytest.mark.parametrize(
        "profile,expected_min_confidence",
        [
            ("production", 70),
            ("research", 50),
            ("high_security", 80),
        ],
    )
    def test_filter_profile_confidence_thresholds(
        self, config_with_profiles, segments_with_many_incidents, tmp_path, profile, expected_min_confidence
    ):
        """Each profile should enforce its minimum confidence threshold."""
        output_file = detect_incidents(
            date=datetime.date(2025, 9, 1),
            segments_dir=segments_with_many_incidents.parent,
            output_dir=tmp_path / profile,
            config=config_with_profiles,
            filter_profile=profile,
        )

        # Check that all incidents meet minimum confidence
        import duckdb

        conn = duckdb.connect()

        # First check if any incidents exist
        count_result = conn.execute(f"""
            SELECT COUNT(*) FROM '{output_file}'
        """).fetchone()

        assert count_result is not None, "Count query should return results"
        if count_result[0] > 0:
            # If incidents exist, verify confidence
            result = conn.execute(f"""
                SELECT MIN(confidence_score) as min_conf
                FROM '{output_file}'
            """).fetchone()
            conn.close()

            assert result is not None, "Query should return results"
            min_conf = result[0]
            assert min_conf >= expected_min_confidence
        else:
            # No incidents is also valid (very strict filtering)
            conn.close()
            assert True

    def test_unknown_profile_raises_error(self, config_with_profiles, segments_with_many_incidents, tmp_path):
        """Using an unknown profile should raise an error."""
        with pytest.raises(ValueError, match="Unknown filter profile"):
            detect_incidents(
                date=datetime.date(2025, 9, 1),
                segments_dir=segments_with_many_incidents.parent,
                output_dir=tmp_path,
                config=config_with_profiles,
                filter_profile="nonexistent",
            )

    def test_default_profile_from_config(self, config_with_profiles, segments_with_many_incidents, tmp_path):
        """When no profile specified, should use default from config."""
        # Set default to production
        config_with_profiles.incidents.default_profile = "production"

        # Run without specifying profile
        output_file = detect_incidents(
            date=datetime.date(2025, 9, 1),
            segments_dir=segments_with_many_incidents.parent,
            output_dir=tmp_path,
            config=config_with_profiles,
            filter_profile=None,  # Use default
        )

        # Should behave like production profile
        import duckdb

        conn = duckdb.connect()
        result = conn.execute(f"""
            SELECT COUNT(*) as total
            FROM '{output_file}'
        """).fetchone()
        conn.close()

        assert result is not None, "Query should return results"
        # Should have filtered results like production
        assert result[0] < 10

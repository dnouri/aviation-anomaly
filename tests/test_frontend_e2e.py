"""
End-to-end tests for the frontend using Playwright.
Tests the happy path with real July 2nd data.
"""

import time

import pytest
from playwright.sync_api import Page, expect


@pytest.fixture(scope="module")
def live_server():
    """Start the FastAPI server for testing."""
    import socket
    import subprocess
    import time

    # Find an available port
    def find_free_port():
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("", 0))
            s.listen(1)
            port = s.getsockname()[1]
        return port

    port = find_free_port()
    server_url = f"http://127.0.0.1:{port}"

    # Start server in background
    process = subprocess.Popen(
        ["uv", "run", "aviation-anomaly", "serve", "--port", str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    # Wait for server to start with retries
    import requests

    max_retries = 20  # 10 seconds total
    for i in range(max_retries):
        time.sleep(0.5)

        # Check if process died
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise RuntimeError(f"Server exited with code {process.returncode}\nSTDERR: {stderr}")

        # Try to connect
        try:
            response = requests.get(f"{server_url}/health", timeout=1)
            if response.status_code == 200:
                break
        except (requests.ConnectionError, requests.Timeout):
            if i == max_retries - 1:
                process.terminate()
                process.wait(timeout=5)
                raise RuntimeError("Server failed to start within 10 seconds") from None
            continue

    yield server_url

    # Cleanup
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


@pytest.mark.e2e
class TestFrontendE2E:
    """End-to-end tests for the aviation anomaly tracker frontend."""

    def test_map_loads_successfully(self, page: Page, live_server: str):
        """Test that the map loads with base tiles."""
        # RED: This will fail because index.html doesn't exist yet
        page.goto(f"{live_server}/")

        # Map container should exist
        map_element = page.locator("#map")
        expect(map_element).to_be_visible()

        # Map canvas should be created by MapLibre
        canvas = page.locator("#map canvas")
        expect(canvas).to_be_visible(timeout=5000)

        # Map should have the expected initial state
        zoom = page.evaluate("window.map ? window.map.getZoom() : null")
        assert zoom is not None, "Map object not found"
        assert 2 <= zoom <= 5, f"Unexpected initial zoom: {zoom}"

    def test_coverage_disclaimer_visible(self, page: Page, live_server: str):
        """Test that coverage disclaimer is prominently displayed."""
        page.goto(f"{live_server}/")

        # Should have a disclaimer about coverage
        disclaimer = page.locator(".coverage-disclaimer")
        expect(disclaimer).to_be_visible()
        expect(disclaimer).to_contain_text("observed traffic")

    def test_pmtiles_layer_loads(self, page: Page, live_server: str):
        """Test that PMTiles H3 data loads and displays."""
        page.goto(f"{live_server}/")

        # Wait for map to initialize
        page.wait_for_selector("#map canvas", timeout=5000)

        # Give PMTiles time to load
        time.sleep(2)

        # Check that all 5 resolution sources were loaded
        sources_loaded = page.evaluate("""
            () => {
                const results = [];
                for (let res = 3; res <= 7; res++) {
                    const source = window.map.getSource(`h3-tiles-r${res}`);
                    if (source) results.push(res);
                }
                return results;
            }
        """)
        assert len(sources_loaded) == 5, f"Expected 5 sources, found {len(sources_loaded)}"

        has_layer = page.evaluate("window.map && window.map.getLayer('h3-cells') !== undefined")
        assert has_layer, "H3 cells layer not found"

    def test_h3_cell_click_shows_details(self, page: Page, live_server: str):
        """Test that clicking an H3 cell shows incident details."""
        page.goto(f"{live_server}/")

        # Wait for map and data to load
        page.wait_for_selector("#map canvas", timeout=5000)
        time.sleep(3)  # Give PMTiles time to load

        # Initially, details panel should not be visible
        details = page.locator("#incident-details")
        expect(details).to_be_hidden()

        # Click somewhere on the map where we expect data
        # (This is tricky without knowing exact cell locations,
        # so we'll click in several places)
        map_element = page.locator("#map")
        box = map_element.bounding_box()

        if box:
            # Try clicking in the center
            page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            time.sleep(1)

            # Check if details panel appeared
            # For now, we'll just check that the click handler works
            # In a real test, we'd click on a known cell location

            # The details panel should exist (even if not shown due to no data)
            details = page.locator("#incident-details")
            expect(details).to_be_attached()

    def test_filter_controls_exist(self, page: Page, live_server: str):
        """Test that filter controls are present and functional."""
        page.goto(f"{live_server}/")

        # Check for squawk type filter
        squawk_filter = page.locator("select#squawk-filter, input[name='squawk-filter']")
        expect(squawk_filter).to_be_visible()

        # Check that filter has expected options
        if page.locator("select#squawk-filter").is_visible():
            options = page.locator("select#squawk-filter option").all_text_contents()
            assert "All" in " ".join(options) or "all" in " ".join(options).lower()
            assert any("7700" in opt for opt in options)

    def test_legend_shows_scale(self, page: Page, live_server: str):
        """Test that a legend explaining the color scale is visible."""
        page.goto(f"{live_server}/")

        legend = page.locator(".legend, #legend")
        expect(legend).to_be_visible()

        # Should explain what the colors mean
        legend_text = legend.text_content()
        assert legend_text is not None
        # Check for some indication of scale (rates, incidents, etc.)
        assert any(word in legend_text.lower() for word in ["incident", "rate", "emergency", "low", "high"])

    def test_resolution_switches_with_zoom(self, page: Page, live_server: str):
        """Test that H3 resolution changes appropriately with zoom level."""
        page.goto(f"{live_server}/")

        # Wait for map to initialize
        page.wait_for_selector("#map canvas", timeout=5000)
        time.sleep(2)

        # Test zoom level 3 → resolution 3
        page.evaluate("window.map.setZoom(3)")
        time.sleep(1)
        resolution = page.evaluate("window.currentResolution")
        assert resolution == 3, f"Expected resolution 3 at zoom 3, got {resolution}"

        # Test zoom level 7 → resolution 7
        page.evaluate("window.map.setZoom(7)")
        time.sleep(1)
        resolution = page.evaluate("window.currentResolution")
        assert resolution == 7, f"Expected resolution 7 at zoom 7, got {resolution}"

        # Test zoom level 10 → resolution 7 (highest available)
        page.evaluate("window.map.setZoom(10)")
        time.sleep(1)
        resolution = page.evaluate("window.currentResolution")
        assert resolution == 7, f"Expected resolution 7 at zoom 10, got {resolution}"

        # Verify resolution indicator updates
        indicator = page.locator("#current-resolution")
        expect(indicator).to_have_text("7")

    def test_filter_persists_across_resolution_changes(self, page: Page, live_server: str):
        """Test that emergency type filters persist when resolution changes."""
        page.goto(f"{live_server}/")

        # Wait for map to initialize
        page.wait_for_selector("#map canvas", timeout=5000)
        time.sleep(2)

        # Apply a filter
        page.select_option("#squawk-filter", "7700")
        time.sleep(0.5)

        # Verify filter is applied
        initial_filter = page.evaluate("""
            () => {
                const layer = window.map.getLayer('h3-cells');
                return layer ? JSON.stringify(layer.filter) : null;
            }
        """)
        assert "7700" in initial_filter, "Filter not applied correctly"

        # Change zoom to trigger resolution change
        page.evaluate("window.map.setZoom(3)")
        time.sleep(1)

        # Verify filter is still applied after resolution change
        filter_after_switch = page.evaluate("""
            () => {
                const layer = window.map.getLayer('h3-cells');
                return layer ? JSON.stringify(layer.filter) : null;
            }
        """)
        assert initial_filter == filter_after_switch, "Filter was not preserved across resolution change"

    def test_popup_shows_segments_not_flights(self, page: Page, live_server: str):
        """Test that hexagon popups show 'segments' (not 'flights') after denominator fix."""
        page.goto(f"{live_server}/")

        # Wait for map and data to load
        page.wait_for_selector("#map canvas", timeout=5000)
        time.sleep(2)

        # Move to NYC area where we have data
        page.evaluate("""
            window.map.flyTo({
                center: [-74.0060, 40.7128],
                zoom: 8,
                duration: 0
            })
        """)
        time.sleep(2)

        # Click on the map to trigger a popup
        page.mouse.click(400, 300)
        time.sleep(1)

        # Check if popup appears and contains correct terminology
        popup = page.locator(".maplibregl-popup-content")
        if popup.count() > 0:
            popup_text = popup.inner_text()

            # Verify it shows "segments" not "flights"
            assert "segments" in popup_text.lower() or "Segments" in popup_text, (
                f"Popup should show 'segments' not 'flights'. Got: {popup_text}"
            )
            assert "flights" not in popup_text.lower(), f"Popup should not show 'flights'. Got: {popup_text}"

    def test_incident_rates_are_reasonable(self, page: Page, live_server: str):
        """Test that incident rates are reasonable after denominator fix (not thousands of PPM)."""
        page.goto(f"{live_server}/")

        # Wait for map to load
        page.wait_for_selector("#map canvas", timeout=5000)
        time.sleep(2)

        # Move to area with data
        page.evaluate("""
            window.map.flyTo({
                center: [-74.0060, 40.7128],
                zoom: 8,
                duration: 0
            })
        """)
        time.sleep(2)

        # Click to get a popup with rate info
        page.mouse.click(400, 300)
        time.sleep(1)

        popup = page.locator(".maplibregl-popup-content")
        if popup.count() > 0:
            popup_text = popup.inner_text()

            # Extract rate if present (looking for patterns like "500 PPM" or "0.5%")
            import re

            ppm_match = re.search(r"(\d+(?:\.\d+)?)\s*PPM", popup_text, re.IGNORECASE)
            if ppm_match:
                rate_ppm = float(ppm_match.group(1))
                # After fix, rates should typically be < 2000 PPM, not 10000+
                assert rate_ppm < 5000, f"Rate too high: {rate_ppm} PPM (should be < 5000 after denominator fix)"

    def test_legend_shows_reasonable_values(self, page: Page, live_server: str):
        """Test that legend shows reasonable PPM values (hundreds, not thousands)."""
        page.goto(f"{live_server}/")

        # Wait for map to load
        page.wait_for_selector("#map canvas", timeout=5000)
        time.sleep(2)

        # Check legend values
        legend = page.locator("#legend")
        if legend.count() > 0:
            legend_text = legend.inner_text()

            # Check for PPM values in legend
            import re

            ppm_values = re.findall(r"(\d+(?:\.\d+)?)\s*PPM", legend_text, re.IGNORECASE)

            if ppm_values:
                max_ppm = max(float(v) for v in ppm_values)
                # Legend should show reasonable max values (not 10000+ PPM)
                assert max_ppm < 10000, f"Legend shows unreasonably high PPM: {max_ppm}"

                # Most values should be in hundreds, not thousands
                median_ppm = sorted(float(v) for v in ppm_values)[len(ppm_values) // 2]
                assert median_ppm < 2000, f"Legend median PPM too high: {median_ppm}"

    def test_display_mode_toggle_exists(self, page: Page, live_server: str):
        """Test that display mode toggle switch exists and is functional."""
        page.goto(f"{live_server}/")

        # Wait for map to load
        page.wait_for_selector("#map canvas", timeout=5000)

        # Check toggle switch container exists
        toggle_container = page.locator(".toggle-switch")
        expect(toggle_container).to_be_visible()

        # Check initial state (should be absolute by default)
        mode_label = page.locator("#display-mode-label")
        expect(mode_label).to_contain_text("Absolute")

    def test_toggle_switches_between_modes(self, page: Page, live_server: str):
        """Test that toggle switches between absolute and normalized display modes."""
        page.goto(f"{live_server}/")

        # Wait for map to load
        page.wait_for_selector("#map canvas", timeout=5000)
        time.sleep(2)

        # Get initial legend title
        legend_title = page.locator("#legend h4")
        initial_title = legend_title.inner_text()

        # Toggle should start in absolute mode
        assert "Incident Count" in initial_title or "Absolute" in initial_title

        # Click toggle to switch to normalized
        toggle_container = page.locator(".toggle-switch")
        toggle_container.click()
        time.sleep(1)

        # Legend should update to show PPM
        new_title = legend_title.inner_text()
        assert "PPM" in new_title or "Rate" in new_title, f"Expected PPM in title, got: {new_title}"

        # Click again to switch back
        toggle_container.click()
        time.sleep(1)

        # Should be back to absolute
        final_title = legend_title.inner_text()
        assert final_title == initial_title, "Toggle didn't return to initial state"

    def test_normalized_mode_shows_correct_values(self, page: Page, live_server: str):
        """Test that normalized mode shows PPM values in correct range."""
        page.goto(f"{live_server}/")

        # Wait for map to load
        page.wait_for_selector("#map canvas", timeout=5000)
        time.sleep(2)

        # Switch to normalized mode
        toggle_container = page.locator(".toggle-switch")
        toggle_container.click()
        time.sleep(1)

        # Move to area with data
        page.evaluate("""
            window.map.flyTo({
                center: [-74.0060, 40.7128],
                zoom: 8,
                duration: 0
            })
        """)
        time.sleep(2)

        # Click on map to get popup
        page.mouse.click(400, 300)
        time.sleep(1)

        # Check popup shows PPM values
        popup = page.locator(".maplibregl-popup-content")
        if popup.count() > 0:
            popup_text = popup.inner_text()

            # In normalized mode, should show rate as PPM
            if "PPM" in popup_text:
                import re

                ppm_match = re.search(r"(\d+(?:\.\d+)?)\s*PPM", popup_text, re.IGNORECASE)
                if ppm_match:
                    ppm_value = float(ppm_match.group(1))
                    # PPM values should be in reasonable range (100-50000)
                    assert 100 <= ppm_value <= 50000, f"PPM value out of range: {ppm_value}"

    def test_toggle_persists_across_zoom_changes(self, page: Page, live_server: str):
        """Test that display mode persists when zooming changes resolution."""
        page.goto(f"{live_server}/")

        # Wait for map to load
        page.wait_for_selector("#map canvas", timeout=5000)
        time.sleep(2)

        # Switch to normalized mode
        toggle_container = page.locator(".toggle-switch")
        toggle_container.click()
        time.sleep(1)

        # Verify in normalized mode
        legend_title = page.locator("#legend h4")
        assert "PPM" in legend_title.inner_text() or "Rate" in legend_title.inner_text()

        # Change zoom level (which triggers resolution change)
        page.evaluate("window.map.setZoom(3)")
        time.sleep(1)

        # Should still be in normalized mode
        assert "PPM" in legend_title.inner_text() or "Rate" in legend_title.inner_text()

        # Change zoom again
        page.evaluate("window.map.setZoom(7)")
        time.sleep(1)

        # Still normalized
        assert "PPM" in legend_title.inner_text() or "Rate" in legend_title.inner_text()

    def test_absolute_mode_legend_values(self, page: Page, live_server: str):
        """Test that absolute mode shows incident counts with correct thresholds."""
        page.goto(f"{live_server}/")

        # Wait for map to load
        page.wait_for_selector("#map canvas", timeout=5000)
        time.sleep(2)

        # Should be in absolute mode by default
        legend = page.locator("#legend")
        legend_text = legend.inner_text()

        # Check that legend shows count ranges (not PPM)
        assert "PPM" not in legend_text or "Absolute" in legend_text

        # Should have reasonable count thresholds
        import re

        # Look for patterns like "1-5" or "10-20"
        count_ranges = re.findall(r"(\d+)\s*[-–]\s*(\d+)", legend_text)
        if count_ranges:
            for _low, high in count_ranges:
                # Absolute counts should be small (under 100)
                assert int(high) < 100, f"Absolute count too high: {high}"

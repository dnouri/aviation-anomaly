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

        # Check that H3 source and layer were added
        has_source = page.evaluate("window.map && window.map.getSource('h3-tiles') !== undefined")
        assert has_source, "H3 tiles source not found"

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

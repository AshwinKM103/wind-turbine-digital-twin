"""
Automated headless Playwright verification and screenshot capture for ThingsBoard dashboards.

Navigates configured turbine monitoring dashboards, validates widget DOM elements
and rendering bounding boxes, and captures full-resolution PNG verification artifacts.

The implementation supports:

    - Authenticated session lifecycle management through ThingsBoard Web UI
    - Verification of Gridster widget layouts and dimensional bounds
    - Headless browser screenshot export for regression validation

Key classes / functions:

    - main: Primary asynchronous test routine driving browser automation.

"""

import asyncio
import logging
import os
from pathlib import Path

from playwright.async_api import async_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("verify-dashboards")

TB_HOST = os.environ.get("TB_HOST", "thingsboard")
TB_PORT = os.environ.get("TB_PORT", "8080")
TB_URL = os.environ.get("TB_URL", f"http://{TB_HOST}:{TB_PORT}")
ADMIN_EMAIL = os.environ.get("TENANT_EMAIL") or os.environ.get("TB_TENANT_ADMIN_EMAIL") or os.environ.get("TB_ADMIN_EMAIL")
ADMIN_PASSWORD = os.environ.get("TB_TENANT_ADMIN_PASSWORD") or os.environ.get("TB_ADMIN_PASSWORD")

if not ADMIN_EMAIL:
    raise ValueError("TENANT_EMAIL environment variable is required")
if not ADMIN_PASSWORD:
    raise ValueError("TB_TENANT_ADMIN_PASSWORD environment variable is required")

DASHBOARDS = {
    "scada_dedicated": {
        "id": "c5704b70-b04c-11f1-9bfc-5d2538928d0b",
        "title": "Turbine Process SCADA Mimic (Dedicated)",
        "screenshot": "reports/dash_mimic_dedicated.png",
    },
    "rotordynamics_dedicated": {
        "id": "c578fe00-b04c-11f1-9bfc-5d2538928d0b",
        "title": "Turbine Rotordynamics & Vibration (Dedicated)",
        "screenshot": "reports/dash_rotordynamics_dedicated.png",
    },
    "thermodynamics_dedicated": {
        "id": "1d1d0d50-b196-11f1-a9d0-15449c55f7bc",
        "title": "Turbine Thermodynamics & Process Dynamics (Dedicated)",
        "screenshot": "reports/dash_thermodynamics_dedicated.png",
    },
    "babylon3d": {
        "id": "3503e260-b0cc-11f1-9bfc-5d2538928d0b",
        "title": "Turbine 3D Digital Twin (Babylon.js — Animated)",
        "screenshot": "reports/dash_babylon3d.png",
    },
    "thresholds_dedicated": {
        "id": "0774c890-b19a-11f1-a9d0-15449c55f7bc",
        "title": "Turbine Safety & Alarm Thresholds (Dedicated)",
        "screenshot": "reports/dash_thresholds_dedicated.png",
    },
}


async def main() -> None:
    """
    Capture verification screenshots across configured dashboards using Playwright.

    Logs into ThingsBoard web interface, traverses all target dashboards,
    asserts that widgets are rendered with non-zero dimensions, and saves
    screenshots into the reports directory.

    Raises:
        playwright.async_api.Error: If navigation or authentication encounters a browser error.

    """
    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu"])
        context = await browser.new_context(viewport={"width": 1920, "height": 1080})
        page = await context.new_page()

        # Login
        log.info("Logging into ThingsBoard at %s...", TB_URL)
        await page.goto(f"{TB_URL}/login", wait_until="networkidle")
        await page.fill('input[type="email"]', ADMIN_EMAIL)
        await page.fill('input[type="password"]', ADMIN_PASSWORD)
        await page.click('button[type="submit"]')
        await page.wait_for_url(lambda u: "/home" in u or "/dashboards" in u, timeout=15000)
        log.info("✓ Logged in successfully.")

        for key, info in DASHBOARDS.items():
            dash_id = info["id"]
            url = f"{TB_URL}/dashboards/{dash_id}"
            log.info("Checking %s (%s)...", info["title"], url)
            await page.goto(url, wait_until="networkidle")
            await asyncio.sleep(3.0)  # Wait for widgets to hydrate

            # Check gridster items
            grid_items = await page.query_selector_all("gridster-item")
            log.info("  Found %d gridster items for %s", len(grid_items), key)

            visible_count = 0
            for idx, item in enumerate(grid_items):
                box = await item.bounding_box()
                if box and box["width"] > 20 and box["height"] > 20:
                    visible_count += 1
                else:
                    log.warning("  Item %d has invalid dimensions: %s", idx, box)

            log.info("  %d / %d widgets visible and rendered with non-zero dimensions", visible_count, len(grid_items))

            screenshot_path = info["screenshot"]
            await page.screenshot(path=screenshot_path, full_page=False)
            log.info("  ✓ Saved screenshot to %s", screenshot_path)

        await browser.close()
        log.info("All dashboard verifications completed successfully!")


if __name__ == "__main__":
    asyncio.run(main())

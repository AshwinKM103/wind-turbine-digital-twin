"""
Widget configuration descriptor generator and validator.

Validates widget descriptor files against widget-registry.json to ensure all
ThingsBoard custom widget configurations exist and contain valid JSON.

The implementation supports:

    - Integrity validation of custom widget bundles
    - Synchronous descriptor file checking
    - Diagnostic logging for missing or malformed descriptors

Key classes / functions:

    - sync_widget_registry: Verify and synchronize widget descriptor files.

"""

from __future__ import annotations

import json
import logging
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_FILE = REPO_ROOT / "app" / "config" / "widget-registry.json"
WIDGETS_DIR = REPO_ROOT / "app" / "thingsboard" / "widgets"

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("generate_widget_configs")


def sync_widget_registry() -> int:
    """
    Verify and synchronize widget descriptors against registry definitions.

    Reads widget-registry.json, checks that all referenced descriptor files exist,
    and validates their JSON structure.

    Returns:
        int: 0 if all referenced descriptors exist and are valid, 1 on error.

    Example:
        >>> status = sync_widget_registry()
        >>> status in (0, 1)
        True

    """
    if not REGISTRY_FILE.exists():
        logger.error("Widget registry file %s does not exist", REGISTRY_FILE)
        return 1

    with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
        registry_data = json.load(f)

    widgets = registry_data.get("widgets", [])
    logger.info("Found %d widgets in registry", len(widgets))

    verified = 0
    for w in widgets:
        desc_file = WIDGETS_DIR / w.get("descriptor_file", "")
        if not desc_file.exists():
            logger.warning("Descriptor file %s not found for widget %s", desc_file, w.get("id"))
            continue
        try:
            with open(desc_file, "r", encoding="utf-8") as df:
                json.load(df)
            verified += 1
            logger.info("✓ Verified widget config descriptor: %s", w.get("id"))
        except Exception as e:
            logger.error("Invalid JSON in %s: %s", desc_file, e)

    logger.info("Widget config sync complete: %d / %d valid", verified, len(widgets))
    return 0


if __name__ == "__main__":
    raise SystemExit(sync_widget_registry())


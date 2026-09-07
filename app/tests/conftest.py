"""Shared pytest configuration for the app test suite."""

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "integration: requires the docker-compose stack to be running "
        "(auto-skipped when it is not)",
    )
    config.addinivalue_line(
        "markers", "slow: takes more than 5 seconds; exclude from fast feedback loops"
    )

"""
Fleet topology loader and validation.

Loads turbine fleet definitions from fleet.json and provides typed access to
customer, site, and turbine identifiers. Enforces referential integrity and
generates IoTDB device path identifiers.

The implementation supports:

    - Validation of fleet hierarchy and uniqueness
    - Device path computation for IoTDB writes
    - Multi-tenant data isolation verification

Key classes / functions:

    - Fleet: Aggregated fleet topology container.
    - Customer: Customer identity and associated turbines.
    - Turbine: Turbine identity and device path generator.
    - load_fleet: Load and parse fleet configuration from JSON.

"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DEFAULT_FLEET_PATH = Path(__file__).resolve().parents[1] / "config" / "fleet.json"


class FleetConfigError(Exception):
    """Raised when config/fleet.json is missing, malformed or inconsistent."""


@dataclass(frozen=True, slots=True)
class Turbine:
    """
    Representation of an individual wind turbine within a fleet customer site.

    Args:
        customer_id (str): Identifier of the owning customer.
        site_id (str): Geographic or logical site location identifier.
        turbine_id (str): Unique turbine identifier within the site.
        health_port (int): Port number dedicated to the turbine health endpoint.

    """
    customer_id: str
    site_id: str
    turbine_id: str
    health_port: int

    @property
    def device_path(self) -> str:
        """
        Return the fully qualified IoTDB device path for the turbine.

        Returns:
            str: Path formatted as root.digitaltwin.<customer>.<site>.<turbine>.

        """
        return f"root.digitaltwin.{self.customer_id}.{self.site_id}.{self.turbine_id}"


@dataclass(frozen=True, slots=True)
class Customer:
    """
    Customer entity owning a collection of wind turbines.

    Args:
        customer_id (str): Unique identifier for the customer.
        display_name (str): Human-readable customer organization name.
        turbines (tuple[Turbine, ...]): Immutable collection of turbines owned.

    """
    customer_id: str
    display_name: str
    turbines: tuple[Turbine, ...]


@dataclass(frozen=True, slots=True)
class Fleet:
    """
    Root container representing the entire multi-tenant turbine fleet topology.

    Args:
        device_path_root (str): Root storage group prefix for IoTDB device paths.
        customers (tuple[Customer, ...]): Customers registered in the fleet.

    """
    device_path_root: str
    customers: tuple[Customer, ...]

    @property
    def turbines(self) -> tuple[Turbine, ...]:
        """
        Return a flattened tuple of all turbines across all customers.

        Returns:
            tuple[Turbine, ...]: All registered turbines in the fleet.

        """
        return tuple(t for c in self.customers for t in c.turbines)

    def customer(self, customer_id: str) -> Customer:
        """
        Find and return a customer by identifier.

        Args:
            customer_id (str): The unique customer identifier to search.

        Returns:
            Customer: Customer matching the provided identifier.

        Raises:
            FleetConfigError: If no customer matches the customer_id.

        Example:
            >>> fleet = load_fleet()
            >>> c = fleet.customer("zephyr-energy")
            >>> print(c.display_name)
            Zephyr Energy

        """
        for candidate in self.customers:
            if candidate.customer_id == customer_id:
                return candidate
        raise FleetConfigError(f"unknown customer_id: {customer_id!r}")


def _parse(document: dict) -> Fleet:
    customers: list[Customer] = []
    for raw_customer in document["customers"]:
        turbines = tuple(
            Turbine(
                customer_id=raw_customer["customer_id"],
                site_id=raw_site["site_id"],
                turbine_id=raw_turbine["turbine_id"],
                health_port=int(raw_turbine["health_port"]),
            )
            for raw_site in raw_customer["sites"]
            for raw_turbine in raw_site["turbines"]
        )
        customers.append(
            Customer(
                customer_id=raw_customer["customer_id"],
                display_name=raw_customer["display_name"],
                turbines=turbines,
            )
        )
    fleet = Fleet(
        device_path_root=document["metadata"]["device_path_root"],
        customers=tuple(customers),
    )
    _validate(fleet)
    return fleet


def _validate(fleet: Fleet) -> None:
    if not fleet.customers:
        raise FleetConfigError("fleet defines no customers")

    seen_paths: set[str] = set()
    seen_ports: dict[int, str] = {}
    for turbine in fleet.turbines:
        if turbine.device_path in seen_paths:
            raise FleetConfigError(f"duplicate device path: {turbine.device_path}")
        seen_paths.add(turbine.device_path)
        if turbine.health_port in seen_ports:
            raise FleetConfigError(
                f"health port {turbine.health_port} claimed by both "
                f"{seen_ports[turbine.health_port]} and {turbine.device_path}"
            )
        seen_ports[turbine.health_port] = turbine.device_path

    for customer in fleet.customers:
        if not customer.turbines:
            raise FleetConfigError(f"customer {customer.customer_id} has no turbines")


@lru_cache(maxsize=4)
def load_fleet(path: Path | str = DEFAULT_FLEET_PATH) -> Fleet:
    """
    Load and validate turbine fleet topology from JSON configuration.

    Parses customer, site, and turbine definitions, validating that device paths
    and health ports are globally unique. Results are memoized via LRU cache.

    Args:
        path (Path | str, optional): File path to fleet.json. Defaults to DEFAULT_FLEET_PATH.

    Returns:
        Fleet: Fully populated and validated Fleet hierarchy.

    Raises:
        FleetConfigError: If file is missing, contains invalid JSON, or fails topology checks.

    Example:
        >>> fleet = load_fleet()
        >>> len(fleet.turbines) >= 1
        True

    """
    fleet_path = Path(path)
    try:
        document = json.loads(fleet_path.read_text())
    except FileNotFoundError as exc:
        raise FleetConfigError(f"fleet config not found at {fleet_path}") from exc
    except json.JSONDecodeError as exc:
        raise FleetConfigError(f"fleet config at {fleet_path} is not valid JSON: {exc}") from exc
    try:
        return _parse(document)
    except (KeyError, TypeError, ValueError) as exc:
        raise FleetConfigError(f"fleet config at {fleet_path} is malformed: {exc}") from exc


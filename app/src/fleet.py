"""
fleet.py - Typed accessor for config/fleet.json.

The fleet topology (which turbines belong to which customer, and each
customer's Grafana tenancy) is declared once in config/fleet.json and read
here by every tool that needs it: the schema generator, the Grafana
provisioning script, the dashboard generator and the end-to-end tests.
Keeping it in one file is what makes "customer1 must not see customer2's
turbines" checkable rather than a convention spread across five places.
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
    customer_id: str
    site_id: str
    turbine_id: str
    health_port: int

    @property
    def device_path(self) -> str:
        return f"root.digitaltwin.{self.customer_id}.{self.site_id}.{self.turbine_id}"

    @property
    def service_name(self) -> str:
        """docker-compose service name, e.g. generator-c1-t01."""
        customer_index = self.customer_id.removeprefix("customer")
        turbine_index = self.turbine_id.removeprefix("turbine")
        return f"generator-c{customer_index}-t{turbine_index}"


@dataclass(frozen=True, slots=True)
class Customer:
    customer_id: str
    display_name: str
    grafana_org_id: int
    grafana_login: str
    datasource_uid: str
    dashboard_uid: str
    turbines: tuple[Turbine, ...]


@dataclass(frozen=True, slots=True)
class Fleet:
    device_path_root: str
    customers: tuple[Customer, ...]

    @property
    def turbines(self) -> tuple[Turbine, ...]:
        return tuple(t for c in self.customers for t in c.turbines)

    def customer(self, customer_id: str) -> Customer:
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
                grafana_org_id=int(raw_customer["grafana_org_id"]),
                grafana_login=raw_customer["grafana_login"],
                datasource_uid=raw_customer["datasource_uid"],
                dashboard_uid=raw_customer["dashboard_uid"],
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
    """Catch the topology mistakes that would otherwise surface as silent
    data corruption (two turbines sharing a device path) or a container
    that will not start (two generators binding the same health port)."""
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

    seen_org_ids: set[int] = set()
    for customer in fleet.customers:
        if customer.grafana_org_id in seen_org_ids:
            raise FleetConfigError(f"duplicate grafana_org_id: {customer.grafana_org_id}")
        seen_org_ids.add(customer.grafana_org_id)
        if not customer.turbines:
            raise FleetConfigError(f"customer {customer.customer_id} has no turbines")


@lru_cache(maxsize=4)
def load_fleet(path: Path | str = DEFAULT_FLEET_PATH) -> Fleet:
    """Load and validate the fleet topology. Cached: the file is immutable
    for the lifetime of a process."""
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

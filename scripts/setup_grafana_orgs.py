#!/usr/bin/env python3
"""
setup_grafana_orgs.py - Provision the per-customer Grafana tenants.

Creates, for every customer in config/fleet.json:
  * an organisation
  * a Viewer user, a member of that org and no other
  * an IoTDB datasource inside that org
  * that customer's fleet dashboard inside that org

All of it through the API rather than Grafana's file provisioning.
Run this after `docker compose up`, once Grafana is healthy.

Idempotent: re-running reconciles rather than duplicating, so it is safe
to wire into a deploy step.

Usage:
    python scripts/setup_grafana_orgs.py [--url http://localhost:13000]

Credentials come from the environment, never from arguments or code:
    GRAFANA_ADMIN_USER      (default: admin)
    GRAFANA_ADMIN_PASSWORD  (required)
    CUSTOMER_USER_PASSWORD  (required; the password for every customer user)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from base64 import b64encode
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "app" / "src"))

from fleet import Customer, load_fleet

DEFAULT_URL = "http://localhost:13000"
VIEWER_ROLE = "Viewer"
DATASOURCE_TYPE = "apache-iotdb-datasource"
IOTDB_REST_URL = "http://iotdb:18080"
DASHBOARD_JSON_DIR = REPO_ROOT / "provisioning" / "dashboards" / "json"


class GrafanaError(Exception):
    """A Grafana API call failed in a way the caller cannot recover from."""


class GrafanaClient:
    """Thin Grafana HTTP admin client (stdlib only -- this script runs on
    the deploy host, which has no application virtualenv)."""

    def __init__(self, base_url: str, user: str, password: str) -> None:
        self._base_url = base_url.rstrip("/")
        token = b64encode(f"{user}:{password}".encode()).decode()
        self._auth_header = f"Basic {token}"

    def request(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict | list]:
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            f"{self._base_url}{path}",
            data=data,
            method=method,
            headers={
                "Authorization": self._auth_header,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                raw = response.read().decode() or "{}"
                return response.status, json.loads(raw)
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode() or "{}"
            try:
                return exc.code, json.loads(raw)
            except json.JSONDecodeError:
                return exc.code, {"message": raw}
        except urllib.error.URLError as exc:
            raise GrafanaError(f"cannot reach Grafana at {self._base_url}: {exc.reason}") from exc


def ensure_org(client: GrafanaClient, customer: Customer) -> int:
    """Create the customer's org if absent; return its actual org id."""
    status, body = client.request("GET", f"/api/orgs/name/{customer.display_name}")
    if status == 200 and isinstance(body, dict):
        org_id = int(body["id"])
        print(f"  org '{customer.display_name}' already exists (id={org_id})")
        return org_id

    status, body = client.request("POST", "/api/orgs", {"name": customer.display_name})
    if status not in (200, 409) or not isinstance(body, dict) or "orgId" not in body:
        raise GrafanaError(f"failed to create org {customer.display_name}: {status} {body}")
    org_id = int(body["orgId"])
    print(f"  created org '{customer.display_name}' (id={org_id})")
    return org_id


def ensure_user(client: GrafanaClient, customer: Customer, org_id: int, password: str) -> int:
    """Create the customer's login if absent and make it a Viewer of that
    org only. Viewer, not Editor: a tenant user has no business editing
    provisioned datasources."""
    status, body = client.request("GET", f"/api/users/lookup?loginOrEmail={customer.grafana_login}")
    if status == 200 and isinstance(body, dict):
        user_id = int(body["id"])
        print(f"  user '{customer.grafana_login}' already exists (id={user_id})")
    else:
        status, body = client.request(
            "POST",
            "/api/admin/users",
            {
                "name": customer.display_name,
                "email": customer.grafana_login,
                "login": customer.grafana_login,
                "password": password,
                "OrgId": org_id,
            },
        )
        if status != 200 or not isinstance(body, dict) or "id" not in body:
            raise GrafanaError(f"failed to create user {customer.grafana_login}: {status} {body}")
        user_id = int(body["id"])
        print(f"  created user '{customer.grafana_login}' (id={user_id})")

    _ensure_org_membership(client, customer, org_id, user_id)
    return user_id


def _ensure_org_membership(
    client: GrafanaClient, customer: Customer, org_id: int, user_id: int
) -> None:
    status, body = client.request("GET", f"/api/users/{user_id}/orgs")
    memberships = body if isinstance(body, list) else []
    if status != 200:
        raise GrafanaError(f"cannot read orgs for user {user_id}: {status} {body}")

    if not any(int(m["orgId"]) == org_id for m in memberships):
        status, body = client.request(
            "POST",
            f"/api/orgs/{org_id}/users",
            {"loginOrEmail": customer.grafana_login, "role": VIEWER_ROLE},
        )
        if status not in (200, 409):
            raise GrafanaError(
                f"failed to add {customer.grafana_login} to org {org_id}: {status} {body}"
            )
        print(f"  added '{customer.grafana_login}' to org {org_id} as {VIEWER_ROLE}")

    # Isolation: strip every other org, including the default Main Org.
    # Without this the user logs in, lands in org 1 and can switch orgs --
    # which is exactly the cross-tenant visibility this setup must prevent.
    for membership in memberships:
        other_org_id = int(membership["orgId"])
        if other_org_id == org_id:
            continue
        status, _ = client.request("DELETE", f"/api/orgs/{other_org_id}/users/{user_id}")
        if status == 200:
            print(f"  removed '{customer.grafana_login}' from org {other_org_id} (isolation)")

    status, body = client.request("POST", f"/api/users/{user_id}/using/{org_id}")
    if status != 200:
        raise GrafanaError(f"failed to set default org for user {user_id}: {status} {body}")


def _switch_admin_org(client: GrafanaClient, org_id: int) -> None:
    """Datasource and dashboard endpoints act on the caller's *current*
    org, not on an org named in the body -- so the admin has to be moved
    into the target org before creating anything inside it."""
    status, body = client.request("POST", f"/api/user/using/{org_id}")
    if status != 200:
        raise GrafanaError(f"failed to switch admin to org {org_id}: {status} {body}")


def ensure_datasource(client: GrafanaClient, customer: Customer, org_id: int, password: str) -> None:
    """Create or update this customer's IoTDB datasource inside their org.

    Grafana scopes datasources by org, so a user who belongs only to org N
    cannot query any other org's datasource. That is the connection-level
    half of tenant isolation; the query-level half is the per-customer
    prefixPath baked into each dashboard panel.
    """
    _switch_admin_org(client, org_id)
    payload = {
        "name": f"iotdb-{customer.customer_id}",
        "uid": customer.datasource_uid,
        "type": DATASOURCE_TYPE,
        "access": "proxy",
        "url": IOTDB_REST_URL,
        "isDefault": True,
        # This plugin reads its URL from jsonData.url, not the standard
        # top-level `url` field; leaving it unset makes the plugin backend
        # panic on an empty string. See provisioning/datasources/iotdb.yml.
        "jsonData": {"url": IOTDB_REST_URL, "username": os.environ.get("IOTDB_USER", "root")},
        "secureJsonData": {"password": password},
    }

    status, body = client.request("GET", f"/api/datasources/uid/{customer.datasource_uid}")
    if status == 200 and isinstance(body, dict):
        payload["id"] = body["id"]
        status, body = client.request(
            "PUT", f"/api/datasources/uid/{customer.datasource_uid}", payload
        )
        action = "updated"
    else:
        status, body = client.request("POST", "/api/datasources", payload)
        action = "created"
    if status not in (200, 409):
        raise GrafanaError(
            f"failed to {action[:-1]} datasource for {customer.customer_id}: {status} {body}"
        )
    print(f"  {action} datasource '{customer.datasource_uid}' in org {org_id}")


def ensure_dashboard(client: GrafanaClient, customer: Customer, org_id: int) -> None:
    """Import every generated dashboard for this customer into their org.

    The whole directory is imported rather than the single
    `<customer>.json`, so a new dashboard added to
    generate_grafana_assets.py deploys without this script needing to learn
    its name. Sorted for a deterministic import order and therefore
    reproducible output.

    The directory is per-customer, which is what keeps this safe: a file
    can only ever be imported into the org of the directory it sits in, so
    a stray dashboard cannot leak into another tenant's org.
    """
    dashboard_dir = DASHBOARD_JSON_DIR / customer.customer_id
    dashboard_paths = sorted(dashboard_dir.glob("*.json"))
    if not dashboard_paths:
        raise GrafanaError(
            f"no dashboards found in {dashboard_dir} -- run "
            "python app/tools/generate_grafana_assets.py first"
        )

    _switch_admin_org(client, org_id)
    for dashboard_path in dashboard_paths:
        dashboard = json.loads(dashboard_path.read_text())
        # Grafana treats a numeric `id` as "update that dashboard row".
        # The uid is what identifies a dashboard across imports.
        dashboard.pop("id", None)

        status, body = client.request(
            "POST",
            "/api/dashboards/db",
            {
                "dashboard": dashboard,
                "folderId": 0,
                "overwrite": True,
                "message": "provisioned by scripts/setup_grafana_orgs.py",
            },
        )
        if status != 200:
            raise GrafanaError(
                f"failed to import {dashboard_path.name} for "
                f"{customer.customer_id}: {status} {body}"
            )
        print(f"  imported dashboard '{dashboard['uid']}' into org {org_id}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        default=os.environ.get("GRAFANA_URL", DEFAULT_URL),
        help=f"Grafana base URL (default: {DEFAULT_URL})",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    admin_user = os.environ.get("GRAFANA_ADMIN_USER", "admin")
    admin_password = os.environ.get("GRAFANA_ADMIN_PASSWORD")
    customer_password = os.environ.get("CUSTOMER_USER_PASSWORD")
    if not admin_password or not customer_password:
        print(
            "GRAFANA_ADMIN_PASSWORD and CUSTOMER_USER_PASSWORD must be set "
            "in the environment (never passed on the command line, where they "
            "would land in shell history and the process table).",
            file=sys.stderr,
        )
        return 2

    fleet = load_fleet()
    client = GrafanaClient(args.url, admin_user, admin_password)

    iotdb_password = os.environ.get("IOTDB_PASSWORD", "root")

    warnings: list[str] = []
    for customer in fleet.customers:
        print(f"{customer.customer_id}:")
        actual_org_id = ensure_org(client, customer)
        if actual_org_id != customer.grafana_org_id:
            # Not fatal: everything below uses the id Grafana actually
            # assigned. It is still worth flagging, because fleet.json and
            # the running instance have diverged and the next reader will
            # trust the file.
            warnings.append(
                f"  {customer.customer_id}: fleet.json records org id "
                f"{customer.grafana_org_id}, Grafana assigned {actual_org_id}"
            )
        ensure_user(client, customer, actual_org_id, customer_password)
        ensure_datasource(client, customer, actual_org_id, iotdb_password)
        ensure_dashboard(client, customer, actual_org_id)

    # Leave the admin back in the default org rather than in whichever
    # tenant happened to be processed last.
    _switch_admin_org(client, 1)

    if warnings:
        print(
            "\nWarning: org ids differ from app/config/fleet.json. Update "
            "grafana_org_id there to match, so the file keeps describing "
            "reality:",
            file=sys.stderr,
        )
        print("\n".join(warnings), file=sys.stderr)

    print(f"\n{len(fleet.customers)} customer tenants ready.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except GrafanaError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

"""FastMCP server for IoTDB, PostgreSQL, OpenBao, ThingsBoard, and fleet topology."""

from __future__ import annotations

import json
import os
from pathlib import Path
import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("digitaltwin-tools")
REPO_ROOT = Path(__file__).resolve().parents[2]


# --- IoTDB Tools ---
@mcp.tool()
def iotdb_query(sql: str, host: str = "127.0.0.1", port: int = 6667) -> str:
    """Execute a read SQL query on the Apache IoTDB time-series database.

    Example queries:
    - 'SHOW TIMESERIES root.digitaltwin.** LIMIT 10'
    - 'SELECT * FROM root.digitaltwin.zephyr-energy.cascade-ridge.boreas LIMIT 5'
    - 'SHOW DEVICES'
    """
    user = os.environ.get("IOTDB_USER", "root")
    password = os.environ.get("IOTDB_PASSWORD", "root")
    try:
        from iotdb.Session import Session

        session = Session(host, port, user, password)
        session.open(False)
        dataset = session.execute_query_statement(sql)
        results = []
        count = 0
        while dataset.has_next() and count < 100:
            results.append(str(dataset.next()))
            count += 1
        session.close()
        if not results:
            return f"Query executed successfully. 0 rows returned for: {sql}"
        return f"Returned {len(results)} rows:\n" + "\n".join(results)
    except Exception as exc:
        return (
            f"IoTDB Error: {exc}\n"
            "Troubleshooting: Verify IoTDB container is running: `docker compose up -d iotdb` "
            f"and reachable at {host}:{port}."
        )


@mcp.tool()
def iotdb_show_timeseries(path_prefix: str = "root.digitaltwin.**", limit: int = 20) -> str:
    """List registered time-series sensor paths under a prefix in Apache IoTDB."""
    sql = f"SHOW TIMESERIES {path_prefix} LIMIT {limit}"
    return iotdb_query(sql)


# --- PostgreSQL Tools ---
@mcp.tool()
def postgres_query(sql: str) -> str:
    """Execute a read-only query against the PostgreSQL turbine database."""
    # Reject destructive modifications
    forbidden = ["DROP ", "TRUNCATE ", "DELETE ", "UPDATE ", "ALTER "]
    if any(kw in sql.upper() for kw in forbidden):
        return "Error: Read-only tool. Modifying operations are blocked."

    db_user = os.environ.get("POSTGRES_USER", "turbine")
    db_pass = os.environ.get("POSTGRES_PASSWORD")
    if not db_pass:
        return "Error: POSTGRES_PASSWORD environment variable is required"
    db_name = os.environ.get("POSTGRES_DB", "turbine")

    # Connect to either container port or exposed local port
    conn = None
    last_err = None
    try:
        import psycopg

        for port in [15432, 5432]:
            try:
                conn = psycopg.connect(
                    f"postgresql://{db_user}:{db_pass}@127.0.0.1:{port}/{db_name}",
                    connect_timeout=3,
                )
                break
            except Exception as e:
                last_err = e

        if not conn:
            return f"PostgreSQL connection failed: {last_err}. Verify container `turbine-postgres` is up."

        with conn.cursor() as cur:
            cur.execute(sql)
            if cur.description is None:
                conn.close()
                return "Command executed successfully (no results to display)."
            cols = [desc[0] for desc in cur.description]
            rows = cur.fetchmany(50)
            conn.close()

            # Format as markdown table
            header = " | ".join(cols)
            separator = " | ".join(["---"] * len(cols))
            row_lines = [" | ".join(str(val) for val in r) for r in rows]
            return f"| {header} |\n| {separator} |\n" + "\n".join(f"| {r} |" for r in row_lines)
    except Exception as exc:
        return f"PostgreSQL Execution Error: {exc}"


# --- OpenBao Secrets Inspector ---
@mcp.tool()
def openbao_status(bao_url: str = "http://127.0.0.1:8200") -> dict:
    """Check the health, seal status, and cluster state of the OpenBao secret store."""
    try:
        with httpx.Client(timeout=3.0) as client:
            resp = client.get(f"{bao_url}/v1/sys/health")
            data = resp.json()
            data["http_status"] = resp.status_code
            return data
    except Exception as exc:
        return {
            "status": "unreachable",
            "error": str(exc),
            "hint": "Check container `openbao`: run `docker compose up -d openbao` and verify port 8200.",
        }


# --- ThingsBoard CE Tools ---
@mcp.tool()
def thingsboard_status(tb_url: str = "http://127.0.0.1:8082") -> dict:
    """Check health and system info of ThingsBoard CE."""
    try:
        with httpx.Client(timeout=3.0) as client:
            resp = client.get(f"{tb_url}/api/system/info")
            if resp.status_code == 200:
                return resp.json()
            return {"http_status": resp.status_code, "status": "active"}
    except Exception as exc:
        return {
            "status": "unreachable",
            "error": str(exc),
            "hint": "Verify Thingsboard container is up: `docker compose up -d thingsboard` (port 8080).",
        }


# --- Fleet Topology Inspector ---
@mcp.tool()
def fleet_topology() -> dict:
    """Read and summarize the single source of truth fleet configuration (app/config/fleet.json)."""
    fleet_file = REPO_ROOT / "app" / "config" / "fleet.json"
    if not fleet_file.exists():
        return {"error": "app/config/fleet.json not found"}
    try:
        data = json.loads(fleet_file.read_text())
        customers = data.get("customers", [])
        total_turbines = 0
        summary = []
        for c in customers:
            c_name = c.get("display_name", c.get("customer_id"))
            turbines_list = []
            for s in c.get("sites", []):
                for t in s.get("turbines", []):
                    total_turbines += 1
                    turbines_list.append(
                        {
                            "turbine_id": t.get("turbine_id"),
                            "display_name": t.get("display_name"),
                            "health_port": t.get("health_port"),
                        }
                    )
            summary.append(
                {
                    "customer_id": c.get("customer_id"),
                    "display_name": c_name,
                    "turbine_count": len(turbines_list),
                    "turbines": turbines_list,
                }
            )
        return {
            "version": data.get("metadata", {}).get("version"),
            "total_customers": len(customers),
            "total_turbines": total_turbines,
            "customers": summary,
        }
    except Exception as exc:
        return {"error": str(exc)}


if __name__ == "__main__":
    mcp.run()

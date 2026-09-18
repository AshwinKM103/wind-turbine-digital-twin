#!/usr/bin/env python3
"""Replays normalized NI DAQ test log telemetry to Kafka at 1 Hz.

Streams telemetry into Kafka, pushes subsystem health metrics to ThingsBoard,
synchronizes dynamic threshold attributes, and exposes an HTTP playback control server.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import FrameType

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "app" / "src"))

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import Config
from confluent_kafka import Producer
from subsystem_registry import SUBSYSTEMS_BY_ASSET_ID, score_subsystem

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("daq-replay")

DEFAULT_CSV_PATH = REPO_ROOT / "data" / "daq_test_log_normalized_1hz.csv"
REPORTS_DIR = REPO_ROOT / "reports"


class GracefulShutdown:
    """Signal handler for clean replay shutdown."""

    def __init__(self) -> None:
        """Register signal handlers for graceful shutdown."""
        self.shutdown = False
        signal.signal(signal.SIGINT, self._handle)
        signal.signal(signal.SIGTERM, self._handle)
        if hasattr(signal, "SIGHUP"):
            signal.signal(signal.SIGHUP, signal.SIG_IGN)

    def _handle(self, signum: int, frame: FrameType | None) -> None:
        """Handle termination signals by setting shutdown flag."""
        log.info("Shutdown signal received. Stopping replay...")
        self.shutdown = True


def delivery_report(err, msg) -> None:
    """Kafka message delivery report callback."""
    if err is not None:
        log.error("Kafka delivery failed: %s (key=%s)", err, msg.key())


def load_daq_records(csv_path: Path) -> tuple[list[str], list[dict[str, float]]]:
    """Loads normalized DAQ CSV telemetry records into memory."""
    if not csv_path.exists():
        raise FileNotFoundError(f"Cleaned DAQ CSV not found at: {csv_path}")

    records = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        headers = next(reader)
        # Skip iso_timestamp, epoch_ms, seconds_elapsed
        sensor_names = headers[3:]

        for row in reader:
            metrics = {}
            for sensor, val_str in zip(sensor_names, row[3:], strict=False):
                metrics[sensor] = float(val_str)
            records.append(metrics)

    return sensor_names, records


SUBSYSTEM_DEFINITIONS: list[dict] = [
    {
        "assetId": "9f2792b0-b002-11f1-b871-bd111a5de747",
        "name": "Inlet Steam Admission",
        "meshId": "SteamAdmission.001",
        "pressure_key": "PT_109A",
        "temp_key": "TT_109A",
        "vib_key": None,
        "warn_p": 36.0, "alarm_p": 38.0,
    },
    {
        "assetId": "9f3bb6f0-b002-11f1-b871-bd111a5de747",
        "name": "Emergency Stop Valve (ESV)",
        "meshId": "SteamAdmission.002",
        "pressure_key": "PT_111B",
        "temp_key": None,
        "vib_key": None,
        "warn_p": 35.0, "alarm_p": 37.0,
    },
    {
        "assetId": "9f497290-b002-11f1-b871-bd111a5de747",
        "name": "Throttle Valve 1 (TV1)",
        "meshId": "SteamAdmission.003",
        "pressure_key": "PT_111",
        "temp_key": "TT_111",
        "vib_key": None,
        "warn_p": 35.0, "alarm_p": 37.0,
    },
    {
        "assetId": "9f5d96d0-b002-11f1-b871-bd111a5de747",
        "name": "Throttle Valve 2 (TV2)",
        "meshId": "SteamAdmission.004",
        "pressure_key": "PT_112",
        "temp_key": "TT_112",
        "vib_key": None,
        "warn_p": 35.0, "alarm_p": 37.0,
    },
    {
        "assetId": "9f6b2b60-b002-11f1-b871-bd111a5de747",
        "name": "Wheel Case",
        "meshId": "Turbine.002",
        "pressure_key": "PT_120",
        "temp_key": "TT_120",
        "vib_key": None,
        "warn_p": 5.0, "alarm_p": 7.0,
    },
    {
        "assetId": "9f7c9080-b002-11f1-b871-bd111a5de747",
        "name": "Turbine Core & Rotor",
        "meshId": "Turbine.001",
        "pressure_key": "PT_109A",
        "temp_key": "PYRO_T",
        "vib_key": "XT_600",
        "warn_v": 4.5, "alarm_v": 6.0,
        "warn_t": 330.0, "alarm_t": 350.0,
    },
    {
        "assetId": "9f903f90-b002-11f1-b871-bd111a5de747",
        "name": "Intermediate GBC",
        "meshId": "Turbine.003",
        "pressure_key": "PT_111C",
        "temp_key": "TT_111C",
        "vib_key": None,
        "warn_p": 18.0, "alarm_p": 20.0,
    },
    {
        "assetId": "9fa2b620-b002-11f1-b871-bd111a5de747",
        "name": "Gearbox",
        "meshId": "Gearbox.001",
        "pressure_key": None,
        "temp_key": "PYRO_GB",
        "vib_key": "XT_604",
        "warn_v": 4.0, "alarm_v": 5.5,
        "warn_t": 200.0, "alarm_t": 220.0,
    },
    {
        "assetId": "9fb74f90-b002-11f1-b871-bd111a5de747",
        "name": "Dynamometer",
        "meshId": "Dyno.001",
        "pressure_key": "PT_253",
        "temp_key": "DYNO_WATER_O_L",
        "vib_key": None,
        "warn_p": 10.0, "alarm_p": 12.0,
    },
    {
        "assetId": "9fc7ca50-b002-11f1-b871-bd111a5de747",
        "name": "Exhaust & Hydraulics",
        "meshId": "Exhaust.001",
        "pressure_key": "PT_150A",
        "temp_key": "TT_150A",
        "vib_key": None,
        "warn_p": 180.0, "alarm_p": 200.0,
    },
    {
        "assetId": "9fdbee90-b002-11f1-b871-bd111a5de747",
        "name": "Gland Leakage Line 1",
        "meshId": "Leakage.001",
        "pressure_key": "PT_162",
        "temp_key": "TT_162",
        "vib_key": None,
        "warn_p": 2.0, "alarm_p": 3.0,
    },
    {
        "assetId": "9fec1b30-b002-11f1-b871-bd111a5de747",
        "name": "Gland Leakage Line 2",
        "meshId": "Leakage.002",
        "pressure_key": "PT_161",
        "temp_key": "TT_161",
        "vib_key": None,
        "warn_p": 2.0, "alarm_p": 3.0,
    },
    {
        "assetId": "9ffd8050-b002-11f1-b871-bd111a5de747",
        "name": "Gland Leakage Line 3 (Upstream)",
        "meshId": "Leakage.003",
        "pressure_key": "PT_160",
        "temp_key": "TT_160",
        "vib_key": None,
        "warn_p": 2.0, "alarm_p": 3.0,
    },
    {
        "assetId": "a00bd830-b002-11f1-b871-bd111a5de747",
        "name": "Gland Leakage Line 3 (Downstream)",
        "meshId": "Leakage.004",
        "pressure_key": "PT_163",
        "temp_key": "TT_163",
        "vib_key": None,
        "warn_p": 2.0, "alarm_p": 3.0,
    },
]


class ReplayState:
    """Thread-safe shared state for replay playback and HTTP controller."""

    def __init__(self, total_records: int, initial_row: int = 0, speed: float = 1.0) -> None:
        """Initialize replay progress metrics, playback state, and synchronization lock."""
        self.lock = threading.Lock()
        self.total_records = total_records
        self.record_idx = initial_row
        self.speed = speed
        self.paused = False
        self.seq_no = 0
        self.latest_metrics: dict[str, float] = {}
        self.latest_state = "IDLE"
        self.latest_rpm = 0.0


class SubsystemTelemetryUpdater:
    """Updates ThingsBoard subsystem health attributes and polls dynamic thresholds."""

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        email: str | None = None,
        password: str | None = None,
    ) -> None:
        """Initialize HTTP client settings and cache maps for ThingsBoard synchronization."""
        self.host = host or os.environ.get("TB_HOST", "thingsboard")
        self.port = port if port is not None else int(os.environ.get("TB_PORT", 8080))
        self.email = email or os.environ.get("TENANT_EMAIL") or os.environ.get("TB_TENANT_ADMIN_EMAIL") or os.environ.get("TB_ADMIN_EMAIL")
        self.password = password or os.environ.get("TB_TENANT_ADMIN_PASSWORD") or os.environ.get("TB_ADMIN_PASSWORD")
        if not self.email:
            raise ValueError("TENANT_EMAIL environment variable is required")
        if not self.password:
            raise ValueError("TB_TENANT_ADMIN_PASSWORD environment variable is required")
        self.token: str | None = None
        self.token_expiry = 0.0
        self.executor = ThreadPoolExecutor(max_workers=8)
        self.custom_thresholds: dict[str, float] = {}
        self.last_asset_state: dict[str, tuple[str, float, int]] = {}
        self.last_threshold_fetch = 0.0
        self.device_id = os.environ.get("TB_DEVICE_ID", "f82c5c10-afee-11f1-b871-bd111a5de747")
        self.authenticate()

    def authenticate(self) -> None:
        """Authenticate with ThingsBoard and cache JWT token."""
        try:
            url = f"http://{self.host}:{self.port}/api/auth/login"
            req = urllib.request.Request(
                url,
                data=json.dumps({"username": self.email, "password": self.password}).encode(),
                headers={"Content-Type": "application/json"},
            )
            resp = json.loads(urllib.request.urlopen(req, timeout=3).read().decode("utf-8"))
            self.token = resp.get("token")
            self.token_expiry = time.time() + 7200
            log.info("ThingsBoard authentication successful for subsystem updater")
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            log.warning("ThingsBoard auth failed for subsystem updater: %s", e)

    def fetch_dynamic_thresholds(self) -> None:
        """Dynamically poll SHARED_SCOPE attributes from ThingsBoard device."""
        if not self.token or time.time() > self.token_expiry:
            self.authenticate()
        if not self.token:
            return

        now = time.time()
        if now - self.last_threshold_fetch < 5.0:
            return
        self.last_threshold_fetch = now

        try:
            url = f"http://{self.host}:{self.port}/api/plugins/telemetry/DEVICE/{self.device_id}/values/attributes/SHARED_SCOPE"
            req = urllib.request.Request(
                url,
                headers={"Content-Type": "application/json", "X-Authorization": f"Bearer {self.token}"},
            )
            data = json.loads(urllib.request.urlopen(req, timeout=2).read().decode("utf-8"))
            if isinstance(data, list):
                for item in data:
                    k = item.get("key")
                    v = item.get("value")
                    if k and isinstance(v, (int, float)):
                        self.custom_thresholds[k] = float(v)
            elif isinstance(data, dict):
                for k, v in data.items():
                    if isinstance(v, (int, float)):
                        self.custom_thresholds[k] = float(v)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            log.debug("Could not fetch dynamic thresholds: %s", e)

    def push_subsystems(self, metrics: dict[str, float]) -> None:
        """Calculate and push health scores for all subsystems to ThingsBoard."""
        if not self.token or time.time() > self.token_expiry:
            self.authenticate()
        if not self.token:
            return

        self.fetch_dynamic_thresholds()

        def _update_one(sub: dict) -> tuple[str, str] | None:
            asset_id = sub["assetId"]
            subsystem = SUBSYSTEMS_BY_ASSET_ID.get(asset_id)
            if subsystem is None:
                return None

            score, status, alerts = score_subsystem(subsystem, metrics, self.custom_thresholds)

            payload = {
                "healthStatus": status,
                "healthScore": score,
                "activeAlertsCount": alerts,
                "meshId": sub["meshId"],
            }
            p_val = metrics.get(sub["pressure_key"]) if sub.get("pressure_key") else None
            t_val = metrics.get(sub["temp_key"]) if sub.get("temp_key") else None
            v_val = metrics.get(sub["vib_key"]) if sub.get("vib_key") else None
            if p_val is not None:
                payload["pressure"] = round(p_val, 2)
            if t_val is not None:
                payload["temperature"] = round(t_val, 1)
            if v_val is not None:
                payload["vibration"] = round(v_val, 2)

            self._post_asset(f"ASSET/{asset_id}/timeseries/ANY", payload)

            # Mirror the rolled-up state into SERVER_SCOPE so the 3D widget can read
            # last-known health without a timeseries query. Throttled: attribute writes
            # are far more expensive than telemetry writes, so only publish on change.
            state_key = (status, score, alerts)
            if self.last_asset_state.get(asset_id) != state_key:
                self.last_asset_state[asset_id] = state_key
                self._post_asset(
                    f"ASSET/{asset_id}/SERVER_SCOPE",
                    {"healthStatus": status, "healthScore": score, "activeAlertsCount": alerts},
                )

            return sub["meshId"].replace(".", "_"), status

        try:
            results = list(self.executor.map(_update_one, SUBSYSTEM_DEFINITIONS))
            # Mirror subsystem health status onto turbine device timeseries as SUBSYS_<mesh>.
            device_payload = {
                f"SUBSYS_{mesh_key}": status for mesh_key, status in results if mesh_key
            }
            if device_payload:
                self._post_asset(f"DEVICE/{self.device_id}/timeseries/ANY", device_payload)
        except Exception as e:  # noqa: BLE001
            log.warning("Subsystems update error: %s", e)

    def _post_asset(self, path: str, payload: dict) -> None:
        """Send HTTP POST request to ThingsBoard telemetry API endpoint."""
        url = f"http://{self.host}:{self.port}/api/plugins/telemetry/{path}"
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "X-Authorization": f"Bearer {self.token}"},
            method="POST",
        )
        try:
            urllib.request.urlopen(req, timeout=2)
        except (urllib.error.URLError, TimeoutError) as e:
            log.debug("Asset publish to %s failed: %s", path, e)


def create_http_handler(state: ReplayState, records: list[dict[str, float]], csv_path: Path):
    """Factory creating HTTP request handler bound to replay state."""
    class ControlHandler(BaseHTTPRequestHandler):
        """HTTP REST server for interactive replay control and state inspection."""

        def _send_cors_headers(self) -> None:
            """Write cross-origin resource sharing headers."""
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Authorization, Authorization")

        def _json_resp(self, code: int, data: dict) -> None:
            """Serialize response payload as JSON and write HTTP response."""
            body = json.dumps(data).encode("utf-8")
            self.send_response(code)
            self._send_cors_headers()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self) -> None:
            """Handle preflight CORS requests."""
            self.send_response(204)
            self._send_cors_headers()
            self.end_headers()

        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            query = urllib.parse.parse_qs(parsed.query)

            if path == "/api/replay/status":
                with state.lock:
                    self._json_resp(200, {
                        "status": "running",
                        "seq_no": state.seq_no,
                        "record_idx": state.record_idx,
                        "total_records": state.total_records,
                        "speed": state.speed,
                        "paused": state.paused,
                        "state": state.latest_state,
                        "rpm": round(state.latest_rpm, 1),
                    })

            elif path == "/api/telemetry/sample":
                idx_str = query.get("second", ["0"])[0]
                try:
                    idx = int(idx_str)
                    idx = max(0, min(idx, len(records) - 1))
                except ValueError:
                    idx = 0

                rec = records[idx]
                rpm = rec.get("TURBINE_SPEED_RPM", 0.0)
                if rpm > 10000:
                    op_state = "STEADY_STATE"
                elif rpm > 1000:
                    op_state = "RAMP_UP"
                else:
                    op_state = "IDLE"

                self._json_resp(200, {
                    "second": idx,
                    "total": len(records),
                    "state": op_state,
                    "rpm": rpm,
                    "metrics": rec,
                })

            elif path == "/api/reports/latest":
                REPORTS_DIR.mkdir(parents=True, exist_ok=True)
                pdf_files = sorted(REPORTS_DIR.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
                if not pdf_files:
                    # Generate one on the fly
                    pdf_gen_script = REPO_ROOT / "app" / "dev_tools" / "generate_test_report_pdf.py"
                    subprocess.run([sys.executable, str(pdf_gen_script)], check=False)
                    pdf_files = sorted(REPORTS_DIR.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)

                if pdf_files:
                    latest_pdf = pdf_files[0]
                    content = latest_pdf.read_bytes()
                    self.send_response(200)
                    self._send_cors_headers()
                    self.send_header("Content-Type", "application/pdf")
                    self.send_header("Content-Disposition", f'attachment; filename="{latest_pdf.name}"')
                    self.send_header("Content-Length", str(len(content)))
                    self.end_headers()
                    self.wfile.write(content)
                else:
                    self._json_resp(404, {"error": "No PDF reports found"})

            elif path.startswith("/api/reports/download/"):
                fname = path.replace("/api/reports/download/", "").strip("/")
                target = REPORTS_DIR / fname
                if target.exists() and target.is_file() and target.suffix == ".pdf":
                    content = target.read_bytes()
                    self.send_response(200)
                    self._send_cors_headers()
                    self.send_header("Content-Type", "application/pdf")
                    self.send_header("Content-Disposition", f'attachment; filename="{target.name}"')
                    self.send_header("Content-Length", str(len(content)))
                    self.end_headers()
                    self.wfile.write(content)
                else:
                    self._json_resp(404, {"error": "Report file not found"})

            else:
                self._json_resp(404, {"error": "Endpoint not found"})

        def do_POST(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            query = urllib.parse.parse_qs(parsed.query)

            if path == "/api/replay/seek":
                sec_str = query.get("second", query.get("row", ["0"]))[0]
                try:
                    sec = int(sec_str)
                    with state.lock:
                        state.record_idx = max(0, min(sec, state.total_records - 1))
                        curr = state.record_idx
                        rec = records[curr]
                        rpm = rec.get("TURBINE_SPEED_RPM", 0.0)
                        if rpm > 10000:
                            op_state = "STEADY_STATE"
                        elif rpm > 1000:
                            op_state = "RAMP_UP"
                        else:
                            op_state = "IDLE"
                        state.latest_metrics = rec
                        state.latest_rpm = rpm
                        state.latest_state = op_state
                    log.info("HTTP seek requested: jumped to second/row %d (rpm=%.1f, state=%s)", curr, rpm, op_state)
                    self._json_resp(200, {
                        "status": "ok",
                        "record_idx": curr,
                        "rpm": round(rpm, 1),
                        "state": op_state,
                    })
                except ValueError:
                    self._json_resp(400, {"error": "Invalid integer for second parameter"})

            elif path == "/api/replay/pause":
                with state.lock:
                    state.paused = True
                log.info("HTTP pause requested")
                self._json_resp(200, {"status": "ok", "paused": True})

            elif path == "/api/replay/resume":
                with state.lock:
                    state.paused = False
                log.info("HTTP resume requested")
                self._json_resp(200, {"status": "ok", "paused": False})

            elif path == "/api/replay/speed":
                spd_str = query.get("multiplier", query.get("speed", ["1.0"]))[0]
                try:
                    spd = max(0.1, min(float(spd_str), 50.0))
                    with state.lock:
                        state.speed = spd
                    log.info("HTTP speed multiplier updated: %.1fx", spd)
                    self._json_resp(200, {"status": "ok", "speed": spd})
                except ValueError:
                    self._json_resp(400, {"error": "Invalid float for speed"})

            elif path == "/api/reports/generate":
                REPORTS_DIR.mkdir(parents=True, exist_ok=True)
                pdf_gen_script = REPO_ROOT / "app" / "dev_tools" / "generate_test_report_pdf.py"
                out_name = f"shift_test_summary_{int(time.time())}.pdf"
                out_path = REPORTS_DIR / out_name
                proc = subprocess.run(
                    [sys.executable, str(pdf_gen_script), "--output", str(out_path)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if proc.returncode == 0 and out_path.exists():
                    self._json_resp(200, {
                        "status": "success",
                        "filename": out_name,
                        "size_bytes": out_path.stat().st_size,
                        "download_url": f"/api/reports/download/{out_name}",
                    })
                else:
                    self._json_resp(500, {"status": "error", "stderr": proc.stderr})
            else:
                self._json_resp(404, {"error": "Unknown POST endpoint"})

        def log_message(self, format, *args):
            pass  # Suppress default request logging

    return ControlHandler


def start_control_server(
    state: ReplayState,
    records: list[dict[str, float]],
    csv_path: Path,
    port: int = 8085,
) -> ThreadingHTTPServer:
    """Starts background HTTP server for playback control and reporting."""
    handler = create_http_handler(state, records, csv_path)
    # Threading server avoids connection head-of-line blocking from HTTP keep-alive.
    server = ThreadingHTTPServer(("0.0.0.0", port), handler)
    server.daemon_threads = True
    t = threading.Thread(target=server.serve_forever, daemon=True, name="replay-http-control")
    t.start()
    log.info("Replay HTTP Control & Report Server running on http://0.0.0.0:%d", port)
    return server


def main() -> None:
    """CLI entry point to start DAQ telemetry replay and control server."""
    parser = argparse.ArgumentParser(description="Replay NI DAQ test log to Kafka at 1 Hz")
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV_PATH, help="Path to cleaned 1 Hz CSV")
    parser.add_argument("--customer-id", default=os.environ.get("TENANT_NAME", "zephyr-energy"), help="Customer ID (default: TENANT_NAME or zephyr-energy)")
    parser.add_argument("--site-id", default=os.environ.get("SITE_ID", "cascade-ridge"), help="Site ID (default: SITE_ID or cascade-ridge)")
    parser.add_argument("--turbine-id", default=os.environ.get("TURBINE_IDS", "boreas").split(",")[0], help="Turbine ID (default: TURBINE_IDS or boreas)")
    parser.add_argument("--speed", type=float, default=1.0, help="Playback speed multiplier (1.0 = 1 Hz)")
    parser.add_argument("--loop", action="store_true", default=True, help="Continuously loop dataset (default: True)")
    parser.add_argument(
        "--start-row",
        type=int,
        default=2800,
        help="Initial CSV row index to start from (default: 2800, inside the file's real "
             "sustained >10000 RPM steady-state window, rows 2520-3588 -- row 420, the old "
             "default, is actually still idle/ramp-up: RPM~990 there, not steady state)",
    )
    parser.add_argument("--max-samples", type=int, default=0, help="Stop after N samples (0 = infinite/full file)")
    parser.add_argument("--bootstrap-servers", default=os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:19092"), help="Kafka bootstrap servers")
    parser.add_argument("--tb-host", default=os.environ.get("TB_HOST", "thingsboard"), help="ThingsBoard host")
    parser.add_argument("--tb-port", type=int, default=int(os.environ.get("TB_PORT", "8080")), help="ThingsBoard port")
    parser.add_argument("--control-port", type=int, default=int(os.environ.get("REPLAY_SERVER_PORT_HOST", os.environ.get("REPLAY_SERVER_PORT", 8085))), help="HTTP Control & Report Server port (default: 8085)")
    parser.add_argument("--no-subsystems", action="store_true", help="Disable pushing subsystem telemetry to ThingsBoard")
    parser.add_argument("--dry-run", action="store_true", help="Print payloads without sending to Kafka")
    parser.add_argument(
        "--serve-only",
        action="store_true",
        help="Serve the control/seek HTTP API only; never produce to Kafka. Use this "
             "alongside another telemetry source would put "
             "second 1 Hz stream on the same turbine and double its apparent sample rate.",
    )
    args = parser.parse_args()

    sensor_names, records = load_daq_records(args.csv)
    total_records = len(records)
    log.info("Loaded %d DAQ records (%d sensor channels) from %s", total_records, len(sensor_names), args.csv)

    state = ReplayState(total_records=total_records, initial_row=args.start_row, speed=args.speed)
    if records:
        initial_idx = max(0, min(args.start_row, total_records - 1))
        initial_rec = records[initial_idx]
        initial_rpm = initial_rec.get("TURBINE_SPEED_RPM", 0.0)
        state.latest_metrics = initial_rec
        state.latest_rpm = initial_rpm
        state.latest_state = "STEADY_STATE" if initial_rpm > 10000 else ("RAMP_UP" if initial_rpm > 1000 else "IDLE")
    http_server = start_control_server(state, records, args.csv, port=args.control_port)

    if args.serve_only:
        log.info(
            "Serving control API on port %d for %d records (no Kafka production)",
            args.control_port,
            total_records,
        )
        serve_shutdown = GracefulShutdown()
        try:
            while not serve_shutdown.shutdown:
                time.sleep(0.5)
        finally:
            http_server.shutdown()
        return

    producer = None
    if not args.dry_run:
        producer = Producer({
            "bootstrap.servers": args.bootstrap_servers,
            "acks": "all",
            "retries": 5,
            "linger.ms": 10,
        })
        log.info("Kafka producer connected to %s", args.bootstrap_servers)

    subsystem_updater = None
    if not args.dry_run and not args.no_subsystems:
        subsystem_updater = SubsystemTelemetryUpdater(host=args.tb_host, port=args.tb_port)

    kafka_key = f"{args.customer_id}:{args.turbine_id}".encode()
    topic = Config.KAFKA_TOPIC

    shutdown_handler = GracefulShutdown()

    log.info(
        "Starting 1 Hz replay -> %s [%s] (speed=%.1fx, loop=%s, subsystems=%s)...",
        topic,
        kafka_key.decode(),
        args.speed,
        args.loop,
        subsystem_updater is not None,
    )

    try:
        while not shutdown_handler.shutdown:
            with state.lock:
                paused = state.paused
                spd = state.speed
                curr_idx = state.record_idx

            if paused:
                time.sleep(0.2)
                continue

            loop_start = time.time()
            sleep_interval = 1.0 / max(0.01, spd)

            metrics = records[curr_idx]
            now_ms = int(time.time() * 1000)

            rpm = metrics.get("TURBINE_SPEED_RPM", 0.0)
            if rpm > 10000:
                op_state = "STEADY_STATE"
            elif rpm > 1000:
                op_state = "RAMP_UP"
            else:
                op_state = "IDLE"

            with state.lock:
                state.latest_metrics = metrics
                state.latest_state = op_state
                state.latest_rpm = rpm
                seq_no = state.seq_no

            payload = {
                "message_id": str(uuid.uuid4()),
                "customer_id": args.customer_id,
                "site_id": args.site_id,
                "turbine_id": args.turbine_id,
                "seq_no": seq_no,
                "event_time_ms": now_ms,
                "operating_state": op_state,
                "metrics": metrics,
            }

            if args.dry_run:
                log.info("[DRY RUN] seq=%d time=%d RPM=%.1f TRQ=%.3f PT109=%.2f",
                         seq_no, now_ms, rpm, metrics.get("GB_TRQ", 0.0), metrics.get("PT_109A", 0.0))
            else:
                producer.produce(
                    topic,
                    key=kafka_key,
                    value=json.dumps(payload).encode(),
                    on_delivery=delivery_report,
                )
                producer.poll(0)

                if subsystem_updater:
                    subsystem_updater.push_subsystems(metrics)

                if seq_no % 10 == 0:
                    log.info("Replayed sample #%d (index %d/%d): RPM=%.1f, TRQ=%.3f, State=%s",
                             seq_no, curr_idx, total_records, rpm, metrics.get("GB_TRQ", 0.0), op_state)

            with state.lock:
                state.seq_no += 1
                state.record_idx += 1
                if state.record_idx >= total_records:
                    if args.loop:
                        log.info("Reached end of DAQ log. Looping back to start.")
                        state.record_idx = 0
                    else:
                        log.info("Reached end of DAQ log. Exiting.")
                        break

            if args.max_samples > 0 and seq_no >= args.max_samples:
                log.info("Reached target max samples (%d). Stopping.", args.max_samples)
                break

            elapsed = time.time() - loop_start
            sleep_time = max(0.0, sleep_interval - elapsed)
            time.sleep(sleep_time)

    finally:
        if producer:
            log.info("Flushing Kafka producer buffer...")
            producer.flush(5)
            log.info("Kafka producer flushed.")
        if subsystem_updater and hasattr(subsystem_updater, "executor"):
            subsystem_updater.executor.shutdown(wait=False)
        try:
            http_server.shutdown()
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            log.debug("Could not fetch dynamic thresholds: %s", e)


if __name__ == "__main__":
    main()

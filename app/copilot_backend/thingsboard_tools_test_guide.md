# ThingsBoard Copilot Tools — Manual Test Checklist

This checklist covers hand-verification of `tb_tools.py` functions against a running ThingsBoard instance.
Each test snippet assumes a working Docker Compose stack with TeensBoard on port 8080 and at least one
device publishing MQTT telemetry.

## Test Setup

Before running these tests, ensure:
- ThingsBoard is running on `localhost:8080`
- At least one device (e.g., "Boreas") is provisioned and publishing telemetry
- Python environment includes `app/tools/tb_client.py` and `app/tools/subsystem_registry.py`

## 1. ToolError Exception

- [ ] Verify `ToolError` is raised (not bare `Exception`) on all failure paths
- [ ] Verify error messages include endpoint and HTTP status code
- [ ] Verify error messages are descriptive enough to debug (e.g., "GET /api/alarm/... returned HTTP 404")

```python
from app.copilot_backend.tb_tools import ToolError, get_latest_telemetry
from app.tools.tb_client import ThingsboardClient, ThingsboardConfig

# Example: trigger ToolError on bad entity_id
config = ThingsboardConfig()
client = ThingsboardClient(config)
# Note: caller is responsible for authenticate()
assert client.authenticate()

try:
    result = get_latest_telemetry(client, "DEVICE", "invalid-uuid", ["temperature"])
    print("❌ Expected ToolError, got result:", result)
except ToolError as e:
    print("✓ ToolError raised correctly:", str(e))
except Exception as e:
    print("❌ Wrong exception type:", type(e).__name__, e)
```

## 2. get_latest_telemetry()

- [ ] Returns empty dict `{}` for empty keys list
- [ ] Returns `{key: {"value": v, "ts": t}}` for each valid key
- [ ] Returns only keys that exist on device (no error on missing keys)
- [ ] Raises `ToolError` on bad entity_id or network failure
- [ ] Raises `ToolError` on malformed response body (non-dict)

```python
from app.copilot_backend.tb_tools import get_latest_telemetry
from app.tools.tb_client import ThingsboardClient, ThingsboardConfig

config = ThingsboardConfig()
client = ThingsboardClient(config)
assert client.authenticate()

# Find a device to test (e.g., list all devices)
devices = client.list_devices(page_size=1)
if not devices:
    print("❌ No devices found in ThingsBoard")
else:
    device = devices[0]
    device_id = device.get("id", {}).get("id")
    device_name = device.get("name")
    print(f"Testing with device: {device_name} ({device_id})")

    # Test 1: Fetch latest telemetry for known keys
    keys = ["temperature", "humidity", "PT_109A"]
    result = get_latest_telemetry(client, "DEVICE", device_id, keys)
    print(f"✓ get_latest_telemetry returned: {result}")
    for key in result:
        assert "value" in result[key], f"Missing 'value' for {key}"
        assert "ts" in result[key], f"Missing 'ts' for {key}"

    # Test 2: Empty keys list
    result_empty = get_latest_telemetry(client, "DEVICE", device_id, [])
    assert result_empty == {}, f"Expected {{}}, got {result_empty}"
    print("✓ Empty keys list returns {}")

    # Test 3: Mix of existing and non-existing keys (should return only existing)
    result_mixed = get_latest_telemetry(client, "DEVICE", device_id, ["PT_109A", "DOES_NOT_EXIST"])
    print(f"✓ Mixed keys returned: {result_mixed}")
```

## 3. get_telemetry_range()

- [ ] Returns `{"data": {}, "truncated": False, "interval_ms": 0}` for empty keys
- [ ] Returns `{"data": {key: [...]}, "truncated": bool, "interval_ms": int}`
- [ ] Raises `ToolError` if start_ts >= end_ts
- [ ] Raises `ToolError` if range > 30 days
- [ ] Sets `truncated: True` and calculates `interval_ms` if raw estimate exceeds max_points
- [ ] Each point in returned list has `{"ts": ..., "value": ...}` structure

```python
from app.copilot_backend.tb_tools import get_telemetry_range
from app.tools.tb_client import ThingsboardClient, ThingsboardConfig
import time

config = ThingsboardConfig()
client = ThingsboardClient(config)
assert client.authenticate()

devices = client.list_devices(page_size=1)
if devices:
    device_id = devices[0].get("id", {}).get("id")
    device_name = devices[0].get("name")

    # Test 1: Valid time range (last 24 hours)
    now_ms = int(time.time() * 1000)
    start_ts = now_ms - (24 * 60 * 60 * 1000)
    end_ts = now_ms

    result = get_telemetry_range(
        client, "DEVICE", device_id, ["PT_109A"], start_ts, end_ts, max_points=100
    )
    print(f"✓ 24-hour range result: truncated={result['truncated']}, interval_ms={result['interval_ms']}")
    print(f"  Data keys: {list(result['data'].keys())}")
    for key in result['data']:
        points = result['data'][key]
        print(f"  {key}: {len(points)} points")
        if points:
            first = points[0]
            print(f"    First point: ts={first['ts']}, value={first['value']}")

    # Test 2: Verify truncation behavior (use a small max_points)
    result_tiny = get_telemetry_range(
        client, "DEVICE", device_id, ["PT_109A"], start_ts, end_ts, max_points=5
    )
    print(f"✓ With max_points=5: truncated={result_tiny['truncated']}, interval_ms={result_tiny['interval_ms']}")
    assert len(result_tiny['data']['PT_109A']) <= 5, "Result exceeded max_points"

    # Test 3: Invalid range (start >= end)
    try:
        get_telemetry_range(client, "DEVICE", device_id, ["PT_109A"], end_ts, start_ts)
        print("❌ Expected ToolError for invalid range")
    except Exception as e:
        print(f"✓ Correctly raised error for start_ts >= end_ts: {type(e).__name__}")

    # Test 4: Range > 30 days
    thirty_one_days_ms = 31 * 24 * 60 * 60 * 1000
    try:
        get_telemetry_range(
            client, "DEVICE", device_id, ["PT_109A"],
            start_ts, start_ts + thirty_one_days_ms
        )
        print("❌ Expected ToolError for > 30 day range")
    except Exception as e:
        print(f"✓ Correctly rejected 31-day range: {type(e).__name__}")
```

## 4. list_alarms()

- [ ] Returns empty list `[]` if no alarms exist
- [ ] Returns list of dicts with keys: id, type, severity, status, createdTime, ackTime, clearTime
- [ ] Optional status filter (e.g., "ACTIVE_UNACK", "ACKNOWLEDGED", "CLEARED")
- [ ] Respects limit parameter (max 100, capped automatically)
- [ ] Raises `ToolError` on bad entity_id or network failure

```python
from app.copilot_backend.tb_tools import list_alarms
from app.tools.tb_client import ThingsboardClient, ThingsboardConfig

config = ThingsboardConfig()
client = ThingsboardClient(config)
assert client.authenticate()

devices = client.list_devices(page_size=1)
if devices:
    device_id = devices[0].get("id", {}).get("id")
    device_name = devices[0].get("name")
    print(f"Testing alarms for device: {device_name}")

    # Test 1: List all alarms (no status filter)
    alarms = list_alarms(client, "DEVICE", device_id)
    print(f"✓ list_alarms returned {len(alarms)} alarms")
    if alarms:
        first = alarms[0]
        print(f"  First alarm keys: {list(first.keys())}")
        assert "id" in first, "Missing 'id'"
        assert "type" in first, "Missing 'type'"
        assert "severity" in first, "Missing 'severity'"
        assert "status" in first, "Missing 'status'"

    # Test 2: Filter by status
    active_alarms = list_alarms(client, "DEVICE", device_id, status="ACTIVE_UNACK", limit=10)
    print(f"✓ ACTIVE_UNACK alarms: {len(active_alarms)}")

    # Test 3: Limit capping (request 150, should return max 100)
    limited = list_alarms(client, "DEVICE", device_id, limit=150)
    assert len(limited) <= 100, f"Returned {len(limited)} alarms, expected max 100"
    print(f"✓ Limit capping works: requested 150, got {len(limited)} (capped to 100 max)")
```

## 5. get_sensor_catalog()

- [ ] Returns non-empty list of dicts
- [ ] Each dict has keys: sensor_key, subsystem_name, subsystem_asset_id, warn, alarm, critical, source
- [ ] Primary sensors have warn/alarm/critical = None
- [ ] Scored sensors have numeric warn, alarm, critical values
- [ ] No network calls (should be instant)
- [ ] Consistent with subsystem_registry.SUBSYSTEMS

```python
from app.copilot_backend.tb_tools import get_sensor_catalog

# No client needed; this is purely local registry flattening
catalog = get_sensor_catalog()
print(f"✓ Sensor catalog has {len(catalog)} entries")

# Test 1: Verify structure of first few entries
for i, sensor in enumerate(catalog[:5]):
    print(f"  Entry {i}: {sensor['sensor_key']} in {sensor['subsystem_name']}")
    assert "sensor_key" in sensor, f"Missing 'sensor_key' in {sensor}"
    assert "subsystem_name" in sensor, f"Missing 'subsystem_name' in {sensor}"
    assert "subsystem_asset_id" in sensor, f"Missing 'subsystem_asset_id' in {sensor}"
    assert "warn" in sensor, f"Missing 'warn' in {sensor}"
    assert "alarm" in sensor, f"Missing 'alarm' in {sensor}"
    assert "critical" in sensor, f"Missing 'critical' in {sensor}"
    assert "source" in sensor, f"Missing 'source' in {sensor}"

# Test 2: Verify primary vs scored sensor limits
scored_entries = [s for s in catalog if s['warn'] is not None]
primary_entries = [s for s in catalog if s['warn'] is None]
print(f"✓ Scored sensors: {len(scored_entries)}, Primary sensors: {len(primary_entries)}")
assert len(scored_entries) > 0, "Expected at least some scored sensors"

# Test 3: Spot-check a known sensor (e.g., XT_600 from Turbine Core)
xt600_entries = [s for s in catalog if s['sensor_key'] == 'XT_600']
print(f"✓ Found {len(xt600_entries)} entries for XT_600")
if xt600_entries:
    entry = xt600_entries[0]
    print(f"  XT_600: warn={entry['warn']}, alarm={entry['alarm']}, critical={entry['critical']}")
    assert entry['subsystem_name'] == "Turbine Core & Rotor", f"Unexpected subsystem: {entry['subsystem_name']}"
```

## 6. get_operating_limits()

- [ ] Returns dict with keys: warn, alarm, critical, source (for scored sensors)
- [ ] Returns None if sensor_key not found in any subsystem
- [ ] No network calls (should be instant)
- [ ] Matches subsystem_registry.resolve_limits() behavior
- [ ] Works for both primary and scored sensors (returns None for primary)

```python
from app.copilot_backend.tb_tools import get_operating_limits

# Test 1: Known scored sensor (XT_600)
limits = get_operating_limits("XT_600")
print(f"✓ XT_600 limits: {limits}")
assert limits is not None, "XT_600 should have limits"
assert "warn" in limits and "alarm" in limits and "critical" in limits
assert limits['warn'] < limits['alarm'] < limits['critical'], "Limits not in order"
print(f"  Progression: warn={limits['warn']} < alarm={limits['alarm']} < critical={limits['critical']}")

# Test 2: Non-existent sensor
limits_missing = get_operating_limits("DOES_NOT_EXIST")
print(f"✓ Non-existent sensor returns None: {limits_missing}")
assert limits_missing is None, "Expected None for non-existent sensor"

# Test 3: Another scored sensor (PT_109A)
limits_pt = get_operating_limits("PT_109A")
print(f"✓ PT_109A limits: {limits_pt}")
assert limits_pt is not None, "PT_109A should have limits"
print(f"  Source: {limits_pt['source']}")
```

## Summary Checklist

- [ ] All 6 function signatures implemented with correct type hints
- [ ] All functions include full docstrings
- [ ] ToolError raised (not bare Exception) on all failure paths
- [ ] get_latest_telemetry returns correct shape: `{key: {"value": ..., "ts": ...}}`
- [ ] get_telemetry_range caps unbounded queries and returns wrapped result
- [ ] list_alarms produces compact alarm dicts with expected keys
- [ ] get_sensor_catalog flattens registry correctly without network call
- [ ] get_operating_limits looks up sensor limits correctly
- [ ] No write, RPC, or alarm-acknowledge operations anywhere
- [ ] All ThingsBoard calls use `client._request()` exclusively
- [ ] No credentials or authentication calls in tb_tools.py

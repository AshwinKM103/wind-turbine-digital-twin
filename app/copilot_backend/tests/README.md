# Copilot Backend Test Suite

Tests for the READ-ONLY turbine chatbot backend safety contract. These tests verify that the system enforces strict boundaries around data access and prevents any write, control, or dangerous operations.

## Running Tests

Install test dependencies:

```bash
pip install pytest pytest-cov
```

Run all tests:

```bash
pytest app/copilot_backend/tests/
```

Run a specific test file:

```bash
pytest app/copilot_backend/tests/test_tb_tools.py -v
```

Run with coverage:

```bash
pytest app/copilot_backend/tests/ --cov=app.copilot_backend --cov-report=term-missing
```

Run a specific test class:

```bash
pytest app/copilot_backend/tests/test_tb_tools.py::TestGetTelemetryRange -v
```

## Test Files

### 1. `test_tb_tools.py`
Tests the read-only ThingsBoard tool functions in `app/copilot_backend/tb_tools.py`.

**Coverage:**
- `get_latest_telemetry()`: Fetches latest telemetry values
- `get_telemetry_range()`: Fetches time-series data with automatic aggregation when queries would exceed `max_points`
- `list_alarms()`: Lists alarms with strict read-only enforcement (GET-only, no URL parameters for "ack" or "clear")
- `get_sensor_catalog()`: Verifies sensor catalog is sourced from real `SUBSYSTEMS` registry, not hardcoded
- `get_operating_limits()`: Lookups sensor operating thresholds, returns `None` for nonexistent sensors

**Critical Safety Tests:**
- Aggregation is applied when raw sample count exceeds `max_points` (e.g., 1-day query with 86400 1-Hz samples is aggregated to ≤500 points)
- `list_alarms()` only makes GET requests, never constructs URLs with "ack", "clear", or other control operations
- Sensor catalog `subsystem_asset_id` values are verified against the actual `SUBSYSTEMS` registry

### 2. `test_orchestrator_safety.py`
Tests the orchestrator's tool registration and execution safety in `app/copilot_backend/orchestrator.py` (to be implemented).

**Coverage:**
- Exactly 5 tools registered: `get_latest_telemetry`, `get_telemetry_range`, `list_alarms`, `get_sensor_catalog`, `get_operating_limits`
- No tool names or descriptions contain dangerous substrings: "rpc", "write", "ack", "set_", "control", "execute", "acknowledge"
- 3-tool-call limit per user turn is enforced (if the model requests more tool calls, the loop stops after the 3rd and surfaces a clear "limit reached" condition)

**Skipped Tests:** Tests marked with `@pytest.mark.skip` will be activated once `orchestrator.py` is implemented. They serve as a specification for the module's contract.

### 3. `test_main_contract.py`
Tests the FastAPI application endpoints in `app/copilot_backend/main.py` (to be implemented).

**Coverage:**
- `GET /health`: Returns 200 with `{"status": "ok"}`
- `POST /chat`: Accepts `{"conversation_id": str|None, "message": str, "context": {...}}` and returns a streaming response
- Malformed requests (missing `message` field) return 422
- All external systems mocked (ThingsBoard, vLLM, PostgreSQL)

**Mocking Strategy:**
- `stream_chat_completion()` from `model_gateway.py` is mocked to yield test strings
- PostgreSQL store is mocked to avoid requiring a live database
- ThingsBoard client is mocked to avoid live network calls

**Skipped Tests:** Tests marked with `@pytest.mark.skip` will be activated once `main.py` is implemented.

## Mocking Philosophy

All tests follow the repo's mocking rules:
- **Mock at boundaries:** HTTP clients, databases, external APIs
- **Never mock the unit under test:** Test the actual tool functions, not mocks
- **Use fakes for complex interfaces:** `MockResponse` class mimics `requests.Response` interface
- **Assert on behavior, not call counts:** Tests focus on outputs, not internal implementation details

## Test Naming Convention

Tests follow the repo's naming convention: test names describe the scenario being tested.

Examples:
- ✅ `test_should_apply_aggregation_when_raw_samples_exceed_max_points`
- ✅ `test_list_alarms_never_constructs_urls_with_ack_or_clear`
- ❌ `test_1`
- ❌ `test_get_telemetry_range`

## CI Integration

Currently, these tests are manual. To integrate into CI:

1. Add a pytest step to `.github/workflows/` (e.g., in a new or existing workflow)
2. Run tests on every pull request
3. Fail the build if any test fails or if coverage drops below 80% for new code

Example workflow step:

```yaml
- name: Run copilot backend tests
  run: pytest app/copilot_backend/tests/ --cov=app.copilot_backend -v --tb=short
```

## Follow-Up: Browser-Level Smoke Test

A **Playwright-based end-to-end test** should be added once the dashboard UI integrates the copilot backend. This test should:

1. **Location:** Create `.github/workflows/babylon-widget-tests.yml` (does not exist yet)
2. **Scope:** Open the Babylon 3D turbine dashboard, send a chat message, confirm response streams
3. **Safety Checks:**
   - Assert no UI element ever offers a write/control/acknowledge action
   - Assert chat responses contain only sensor data and analysis, no tool invocation details
   - Assert no dangerous operations are available through the chat interface

Example test structure (to be implemented when dashboard is ready):

```typescript
import { test, expect } from '@playwright/test';

test('copilot_chat_does_not_expose_write_operations', async ({ page }) => {
  await page.goto('/dashboard');
  
  // Send a chat message
  await page.fill('[data-testid="chat-input"]', 'What is the turbine temperature?');
  await page.click('[data-testid="chat-send"]');
  
  // Verify response streams
  await expect(page.locator('[data-testid="chat-response"]')).toContainText(/temperature|sensor/i);
  
  // Verify no write operations are offered
  const dangerous_buttons = page.locator(
    'button[data-testid*="control"], button[data-testid*="write"], button[data-testid*="ack"]'
  );
  await expect(dangerous_buttons).toHaveCount(0);
});
```

**Workflow file path for Playwright tests:** `.github/workflows/babylon-widget-tests.yml`

## Notes

- **No live network calls:** All tests use mocks. The test suite runs offline and deterministically.
- **No skip/todo tests in production:** All skipped tests are marked with clear reasons and will be activated once their corresponding modules are implemented.
- **Independence:** Each test sets up its own mocks and tears them down. Tests can run in any order.
- **Flakiness:** Tests should be deterministic (no timing-dependent assertions, no random values). If a test flakes, investigate and fix or quarantine with a tracking issue.

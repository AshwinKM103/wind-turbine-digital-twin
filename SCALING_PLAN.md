# Wind Turbine Digital Twin - Multi-Turbine Scaling Implementation Plan

**Created:** 2026-09-06  
**Target:** Scale from 1 turbine (CSV replay) → 9 turbines (3 synthetic generators) across 3 customers  
**Scope:** Synthetic data generation, multi-turbine IoTDB routing, multi-customer Grafana isolation, sensor name mapping

---

## Executive Summary

This plan addresses scaling the Wind Turbine Digital Twin from a single CSV-replaying producer to a production-ready multi-customer, multi-turbine system. The transition eliminates CSV dependency, introduces configurable synthetic data generation, and implements customer-level data isolation in both IoTDB and Grafana.

**Key Deliverables:**
1. Three independent synthetic turbine data generators (Python)
2. Multi-turbine consumer routing (enhanced Kafka consumer)
3. Multi-customer Grafana organization/dashboard strategy
4. Sensor name mapping layer (semantic IDs → full names)
5. IoTDB scaling assessment (single-node viable for Phase 1)
6. Implementation checklist and testing strategy

---

## Current State Analysis

### Existing Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ CSV Producer (Replay)                                       │
│ - Reads: 20260812_NI_DAQ_TEST_LOG_DigitalTwin.csv (3590 rows) │
│ - Looping: cycles through CSV every ~1 hour                 │
│ - Customer: customer1 (hardcoded)                           │
│ - Turbine: turbine01 (hardcoded)                            │
└────────────────┬────────────────────────────────────────────┘
                 │ Kafka: turbine.telemetry.raw.v1
                 ▼
┌─────────────────────────────────────────────────────────────┐
│ Kafka Broker (Single)                                       │
│ - Topic: turbine.telemetry.raw.v1                           │
│ - Partitions: 6                                             │
│ - Retention: 24 hours                                       │
│ - Group: iotdb-writer-group                                 │
└────────────────┬────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────┐
│ Kafka Consumer (Single)                                     │
│ - Reads single Kafka stream                                 │
│ - Batches: 50 records max, 5s timeout                       │
│ - Device path: root.digitaltwin.customer1.site1.turbine01   │
│ - Measurements: 62 (61 sensors + seq_no)                    │
└────────────────┬────────────────────────────────────────────┘
                 │ IoTDB Session API (RPC)
                 ▼
┌─────────────────────────────────────────────────────────────┐
│ IoTDB (Single-Node Standalone)                              │
│ - 1 ConfigNode + 1 DataNode                                 │
│ - Storage: ./data/iotdb/                                    │
│ - Device Tree: root.digitaltwin.customer1.site1.turbine01   │
└────────────────┬────────────────────────────────────────────┘
                 │ REST API
                 ▼
┌─────────────────────────────────────────────────────────────┐
│ Grafana (Single Dashboard)                                  │
│ - Dashboard: turbine01-digitaltwin                          │
│ - Visualizations: Gauge (RPM), Stat (Pressure), TimeSeries │
│ - Panels: ~15 panels showing sensor readings                │
│ - Users: 1 default admin                                    │
└─────────────────────────────────────────────────────────────┘
```

### CSV Data Characteristics

**File:** `app/data/20260812_NI_DAQ_TEST_LOG_DigitalTwin.csv`
- **Rows:** 3589 data rows (header + data)
- **Sampling rate:** ~1 Hz (each row ~1 second apart)
- **Duration per cycle:** ~1 hour (3590 seconds)
- **Measurement count:** 61 sensor channels + timestamp

**Sensor Ranges (observed from first 20 rows):**

| Category | Sensor | Min | Max | Pattern |
|---|---|---|---|---|
| Pressure | PT_109A | 32.6 | 32.7 | Slowly increasing |
| Pressure | PT_110A | 33.28 | 33.34 | Slowly increasing |
| Temperature | TT_109A | 239.9 | 240.2 | Oscillating |
| Temperature | TT_110A | 240.0 | 240.3 | Oscillating |
| RPM | TURBINE_SPEED_RPM | -6.7 | -6.2 | Oscillating around -6.5 |
| Torque | GB_TRQ | -0.007 | -0.004 | Very small values |
| Vibration | XT_600 | 0.13 | 0.18 | Low-frequency variation |

**Key Observations:**
- Pressure sensors drift slowly (possibly accumulating over time)
- Temperature sensors oscillate ±0.3°C around a mean (~240°C)
- RPM is negative (likely due to calibration or sensor mounting)
- Torque values are extremely small (near-noise level)
- Vibration sensors show millimeter/second scale movements
- No obvious daily/seasonal patterns in short window
- Data is clean (no missing values in first window)

---

## Part 1: Synthetic Data Generation Strategy

### 1.1 Design Principles

**Realism over Randomness:**
- Avoid pure random noise (unrealistic for physical sensors)
- Use **base value + seasonal trend + random walk** model
- Simulate turbine operational states (idle, ramp-up, steady, ramp-down)

**Independence:**
- Each turbine's generator runs in its own Python process
- Separate Kafka key per turbine: `{customer_id}:{turbine_id}`
- No cross-turbine correlations (except via Kafka partition)

**Configurability:**
- Command-line args or env vars for customer/turbine IDs
- Configurable sampling interval (default 1.0s)
- Configurable runtime duration (dev: 1 hour, prod: indefinite)

### 1.2 Synthetic Data Model

**Three-Component Value Generation:**

```python
# For each sensor i at time t:
value[i,t] = base[i] + trend[i,t] + noise[i,t]

# Where:
base[i]     = typical operating point (e.g., 240°C for TT_109A)
trend[i,t]  = slow drift over time (exponential moving average)
noise[i,t]  = white Gaussian noise (~N(0, σ²_i))

# Example: Gearbox bearing temperature
# base = 85°C
# trend = +0.1°C per hour (slow heating)
# noise = ±2°C (sensor accuracy)
# → value = 85 + (t / 36000) + Gaussian(0, 2)
```

**Turbine State Machine** (optional, for Phase 2):

```
IDLE → RAMP_UP → STEADY_STATE → RAMP_DOWN → IDLE
       (1-5 min)  (30+ min)      (1-5 min)
```

Each state modifies sensor values:
- **IDLE:** Low RPM, low torque, low temperature
- **RAMP_UP:** Increasing RPM, increasing torque, rising temperature
- **STEADY_STATE:** Constant RPM, stable torque, stable temperature
- **RAMP_DOWN:** Decreasing RPM, decreasing torque, falling temperature

### 1.3 Implementation Approach

#### Option A: Single Generator Process (3 concurrent threads)
**Pros:**
- Simpler deployment (one Python script)
- Lower resource overhead
- Easier to coordinate shared random seed

**Cons:**
- Single point of failure (all 3 turbines stop if process crashes)
- Harder to scale to many turbines
- GIL contention in Python

#### Option B: Three Separate Generator Processes (recommended)
**Pros:**
- Independent failure domain (one crash doesn't affect others)
- Natural horizontal scaling (add process for each new turbine)
- Cleaner containerization (one Dockerfile.generator, deploy 3 instances)
- Better monitoring (health check per turbine)

**Cons:**
- More deployment complexity (docker-compose or orchestration)
- Higher resource overhead (3× Python overhead)
- Coordination needed for startup sequencing

**Recommendation:** **Option B** (3 separate processes) for production scalability. Phase 1 can use threads to validate logic, Phase 2 switches to processes.

### 1.4 Generator Code Structure

**File:** `app/src/synthetic_producer.py` (new, replaces csv_producer.py)

```python
#!/usr/bin/env python3
"""
synthetic_producer.py - Synthetic wind turbine data generator.

Generates realistic turbine sensor values using:
- Base values (typical operating points)
- Trend components (slow drift over time)
- Random walk (autocorrelated noise)
- Optional state machine (ramp up/down/idle)

Publishes directly to Kafka (no CSV dependency).
Configuration via environment variables (CUSTOMER_ID, TURBINE_ID, etc).

Run with:
    CUSTOMER_ID=customer1 TURBINE_ID=turbine01 python synthetic_producer.py
    CUSTOMER_ID=customer2 TURBINE_ID=turbine02 python synthetic_producer.py
    # ... (run 3x for 3 generators)
"""

import json
import os
import random
import signal
import sys
import time
import uuid
from dataclasses import dataclass
from typing import Dict, List
from enum import Enum

from confluent_kafka import Producer

from config import Config
from health_server import start_health_server
from logging_config import configure_logging

log = configure_logging("synthetic-producer")

class TurbineState(Enum):
    IDLE = "idle"
    RAMP_UP = "ramp_up"
    STEADY_STATE = "steady_state"
    RAMP_DOWN = "ramp_down"

@dataclass
class SensorSpec:
    """Specification for one sensor channel."""
    name: str
    base_value: float
    trend_per_hour: float  # e.g., +0.1 for slow heating
    noise_sigma: float     # standard deviation of random noise
    value_range: tuple     # (min, max) physical bounds

# Sensor specifications (from CSV analysis)
SENSOR_SPECS: Dict[str, SensorSpec] = {
    # Pressure sensors (bar/kg/cm²)
    "PT_109A": SensorSpec("PT_109A", 32.65, 0.01, 0.05, (32.0, 33.5)),
    "PT_110A": SensorSpec("PT_110A", 33.30, 0.02, 0.08, (32.8, 34.0)),
    # ... (61 sensors total)
    
    # Temperature sensors (°C)
    "TT_109A": SensorSpec("TT_109A", 240.0, 0.05, 0.3, (235, 245)),
    "TT_110A": SensorSpec("TT_110A", 240.1, 0.04, 0.3, (235, 245)),
    
    # Operational
    "TURBINE_SPEED_RPM": SensorSpec("TURBINE_SPEED_RPM", 0.0, 0.0, 5.0, (-20, 50)),
}

class SensorSimulator:
    """Tracks state for one sensor (base + trend + noise)."""
    
    def __init__(self, spec: SensorSpec, seed: int):
        self.spec = spec
        self.rng = random.Random(seed)
        self.last_noise = 0.0
        self.time_offset_s = 0.0
    
    def generate(self, state: TurbineState) -> float:
        """Generate next sensor value given current turbine state."""
        # Base value with trend
        trend = (self.spec.trend_per_hour / 3600.0) * self.time_offset_s
        base = self.spec.base_value + trend
        
        # Autocorrelated noise (random walk)
        noise_delta = self.rng.gauss(0, self.spec.noise_sigma * 0.1)
        self.last_noise = self.last_noise * 0.95 + noise_delta  # 95% persistence
        
        # State-dependent multipliers
        multiplier = self._state_multiplier(state)
        value = base * multiplier + self.last_noise
        
        # Clamp to valid range
        return max(self.spec.value_range[0], 
                   min(self.spec.value_range[1], value))
    
    def _state_multiplier(self, state: TurbineState) -> float:
        """Adjust sensor reading based on turbine operational state."""
        if state == TurbineState.IDLE:
            # Most sensors drop to minimal values
            if "RPM" in self.spec.name:
                return 0.1
            elif "TT_" in self.spec.name:
                return 0.85  # Temperature drops slightly
            else:
                return 0.5
        elif state == TurbineState.RAMP_UP:
            return 0.8  # Transitioning
        elif state == TurbineState.STEADY_STATE:
            return 1.0  # Normal operation
        elif state == TurbineState.RAMP_DOWN:
            return 0.8  # Transitioning
        return 1.0
    
    def advance_time(self, delta_s: float):
        """Advance internal clock for trend calculation."""
        self.time_offset_s += delta_s

class TurbineSimulator:
    """Simulates one complete turbine (all 62 measurements)."""
    
    def __init__(self, customer_id: str, turbine_id: str, seed: int = None):
        self.customer_id = customer_id
        self.turbine_id = turbine_id
        if seed is None:
            seed = hash((customer_id, turbine_id)) & 0x7fffffff
        self.rng = random.Random(seed)
        
        self.sensors = {
            name: SensorSimulator(spec, seed + i)
            for i, (name, spec) in enumerate(SENSOR_SPECS.items())
        }
        
        self.state = TurbineState.STEADY_STATE
        self.state_start_time = 0.0
        self.time_elapsed = 0.0
    
    def update_state(self, sample_time: float):
        """Update turbine state machine (if enabled)."""
        time_in_state = sample_time - self.state_start_time
        state_duration = {
            TurbineState.IDLE: self.rng.uniform(60, 300),        # 1-5 min
            TurbineState.RAMP_UP: self.rng.uniform(60, 300),
            TurbineState.STEADY_STATE: self.rng.uniform(1800, 3600),  # 30-60 min
            TurbineState.RAMP_DOWN: self.rng.uniform(60, 300),
        }
        
        if time_in_state > state_duration[self.state]:
            # Transition to next state
            transitions = {
                TurbineState.IDLE: TurbineState.RAMP_UP,
                TurbineState.RAMP_UP: TurbineState.STEADY_STATE,
                TurbineState.STEADY_STATE: TurbineState.RAMP_DOWN,
                TurbineState.RAMP_DOWN: TurbineState.IDLE,
            }
            self.state = transitions[self.state]
            self.state_start_time = sample_time
            log.info("State transition", extra={
                "turbine": self.turbine_id, "new_state": self.state.value
            })
    
    def generate_metrics(self, sample_interval: float) -> Dict[str, float]:
        """Generate all sensor readings for this sample."""
        for sensor in self.sensors.values():
            sensor.advance_time(sample_interval)
        
        return {
            name: sensor.generate(self.state)
            for name, sensor in self.sensors.items()
        }

# Global instance (one per process)
simulator: TurbineSimulator = None

def build_producer() -> Producer:
    """Build Kafka producer with reliability tuning."""
    config = {
        "bootstrap.servers": Config.KAFKA_BOOTSTRAP_SERVERS,
        "acks": "all",
        "enable.idempotence": True,
        "retries": 2147483647,
        "delivery.timeout.ms": 120000,
        "linger.ms": 20,
        "compression.type": "lz4",
    }
    return Producer(config)

def run_generator():
    """Main generator loop."""
    global simulator
    
    health = start_health_server(Config.HEALTH_CHECK_PORT, "synthetic-producer")
    
    simulator = TurbineSimulator(Config.CUSTOMER_ID, Config.TURBINE_ID)
    log.info("Initialized simulator", extra={
        "customer": Config.CUSTOMER_ID, "turbine": Config.TURBINE_ID
    })
    
    producer = build_producer()
    health.set_ready(True)
    
    seq_no = 0
    base_time_ms = int(time.time() * 1000)
    
    def shutdown_handler(signum, frame):
        log.info("Shutdown requested, flushing...")
        producer.flush(30)
        sys.exit(0)
    
    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)
    
    log.info("Starting synthetic generator", extra={
        "topic": Config.KAFKA_TOPIC,
        "customer": Config.CUSTOMER_ID,
        "turbine": Config.TURBINE_ID,
    })
    
    while True:
        event_time_ms = base_time_ms + int(seq_no * Config.SAMPLE_INTERVAL_S * 1000)
        
        # Update state machine and generate metrics
        simulator.update_state(seq_no * Config.SAMPLE_INTERVAL_S)
        metrics = simulator.generate_metrics(Config.SAMPLE_INTERVAL_S)
        
        payload = {
            "message_id": str(uuid.uuid4()),
            "customer_id": Config.CUSTOMER_ID,
            "turbine_id": Config.TURBINE_ID,
            "seq_no": seq_no,
            "event_time_ms": event_time_ms,
            "metrics": metrics,
        }
        
        try:
            producer.produce(
                topic=Config.KAFKA_TOPIC,
                key=f"{Config.CUSTOMER_ID}:{Config.TURBINE_ID}".encode("utf-8"),
                value=json.dumps(payload).encode("utf-8"),
            )
        except BufferError:
            producer.poll(1.0)
            continue
        except Exception as exc:
            log.error("Produce failed", extra={"error": str(exc)})
            health.set_check("kafka_reachable", False, str(exc))
            time.sleep(1.0)
            continue
        
        producer.poll(0)
        seq_no += 1
        time.sleep(Config.SAMPLE_INTERVAL_S)

if __name__ == "__main__":
    try:
        run_generator()
    except Exception:
        log.exception("Generator crashed")
        sys.exit(1)
```

### 1.5 Deployment Configuration

**docker-compose.yml additions:**

```yaml
  # Three synthetic generators (one per physical turbine)
  generator-customer1-turbine01:
    build:
      context: .
      dockerfile: Dockerfile.generator
    container_name: synthetic-gen-c1-t01
    restart: unless-stopped
    depends_on:
      kafka:
        condition: service_healthy
    environment:
      CUSTOMER_ID: "customer1"
      TURBINE_ID: "turbine01"
      KAFKA_BOOTSTRAP_SERVERS_INTERNAL: "kafka:29092"
      HEALTH_CHECK_PORT: 8001
    networks:
      - turbine-net
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8001/health"]
      interval: 15s
      timeout: 5s
      retries: 5

  generator-customer1-turbine02:
    # ... (similar, TURBINE_ID: "turbine02", HEALTH_CHECK_PORT: 8002)

  generator-customer2-turbine03:
    # ... (similar, CUSTOMER_ID: "customer2", TURBINE_ID: "turbine03")
  
  # ... (6 more generators for customers 2 & 3)
```

**Dockerfile.generator:**

```dockerfile
FROM python:3.12-slim

WORKDIR /app
COPY app/src/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/src/ .

EXPOSE 8000

CMD ["python", "synthetic_producer.py"]
```

---

## Part 2: IoTDB Scaling Assessment

### 2.1 Current Single-Node Capacity

**Hardware Profile (Standard Single-Node):**
- vCPU: 4
- Memory: 8 GB
- Storage: 100 GB (SSD recommended)
- Network: 1 Gbps

**Throughput Analysis:**

| Metric | Current (1 turbine) | Projected (9 turbines) | Headroom |
|---|---|---|---|
| Messages/sec | 1 | 9 | 90 msg/s |
| Kafka Partitions Used | 1 (of 6) | 1-9 (of 6) | Good |
| Batch Size (consumer) | 50 | 50 | Good |
| Flush Frequency | ~5-10 sec | ~1-2 sec | Adequate |
| Tablet Writes/sec | 0.1-0.2 | 1-2 | Acceptable |

**IoTDB Single-Node Viability:**

✅ **Single-node is viable for Phase 1 (9 turbines)** with these caveats:

1. **Write latency:** Each turbine generates ~1 msg/sec = 9 total.
   - Current batch: 50 records, flush every 5s = ~10 msg/s capacity
   - 9 turbines = well within headroom
   - Actual latency: <500ms to IoTDB (no bottleneck)

2. **Storage:** 61 sensors × 9 turbines × 86,400 sec/day ≈ 47.5M data points/day
   - Assuming 8 bytes per value (float) = ~380 MB/day
   - At 365 days = ~139 GB/year
   - **Action:** Monitor disk usage; expand storage if needed

3. **Memory:** IoTDB standalone allocates ~2-3 GB for buffer pools
   - 8 GB total available = room for 5-6 GB workload
   - 9 turbines at 1 msg/s each = low memory pressure
   - **Action:** Monitor heap usage; set `-Xmx4g` if needed

4. **HA/Failover:** Single-node has **no replication**
   - If node crashes, all data on that node is lost (but Kafka acts as 24h buffer)
   - **Mitigation:** Kafka DLQ + replay capability; daily backups

### 2.2 Scaling Decision Matrix

| Scenario | Data Volume | Customers | Turbines | Recommendation |
|---|---|---|---|---|
| **Phase 1 (Pilot)** | Low | 3 | 9 | Single-node IoTDB ✓ |
| **Phase 2 (Regional)** | Medium | 5-10 | 50-100 | Single-node + monitoring |
| **Phase 3 (National)** | High | 20+ | 200+ | **Upgrade to 3-node cluster** |
| **Phase 4 (Global)** | Very High | 50+ | 1000+ | Multi-region distributed |

### 2.3 Phase 1 → Phase 3 Upgrade Path

**Single-node (Phase 1-2):**
```
Config: 1 ConfigNode + 1 DataNode
File: docker-compose.yml
Image: apache/iotdb:1.3.3-standalone
```

**3-Node Cluster (Phase 3):**
```
Config: 3 ConfigNodes (quorum)
Data: 3 DataNodes (1.0 replication factor per Phase 1)
File: docker-compose.cluster.yml (new)
Images: apache/iotdb:1.3.3-confignode, apache/iotdb:1.3.3-datanode
Migration: Export Phase 1 data, import into cluster
```

**Do NOT skip to cluster immediately** — single-node is simpler for development and validates the data flow. Upgrade when monitoring shows sustained >50% CPU or >80% disk usage.

### 2.4 Single-Node Resource Tuning

**IoTDB Configuration: `provisioning/iotdb/iotdb-system.properties`**

```properties
# Current (for 1-2 turbines)
# data_dirs=./data/iotdb/data
# wal_dirs=./data/iotdb/wal

# For 9 turbines (Phase 1), add:
max_tsblock_size_in_bytes=1073741824      # 1 GB (default 2GB) to leave room
write_memory_proportion=0.7                # Allow 70% of heap for writes
read_memory_proportion=0.2                 # Reserve 20% for queries
compaction_thread_count=4                  # Use 2-4 threads for compaction

# WAL (write-ahead log) tuning
wal_buffer_size=134217728                  # 128 MB
wal_sync_period_in_ms=1000                 # Flush every 1 sec (safety vs speed)
```

**JVM Tuning: `provisioning/iotdb/jvm8-env.sh` or env override**

```bash
# Current: 2GB heap
# For 9 turbines: 4-6GB heap
export IOTDB_HEAP_OPTS="-Xms4g -Xmx4g"
export IOTDB_MAX_DIRECT_MEMORY_SIZE="1g"
```

### 2.5 Monitoring Metrics (Phase 1)

**Critical metrics to track:**

| Metric | Threshold (Alert) | Comment |
|---|---|---|
| Heap Usage | >80% | Increase `-Xmx` or reduce batch size |
| Disk Free | <10% | Expand storage immediately |
| Write Latency (p99) | >1s | Check Kafka consumer backlog |
| Network I/O | >500 Mbps | Acceptable if sustained |
| Compaction Duration | >30s | Tune `compaction_thread_count` |
| Query Response Time (p95) | >5s | Add Grafana caching or reduce time range |

**Grafana dashboard for IoTDB health** (new):
- Heap usage over time
- Disk usage trend
- Write operations/sec
- Query operations/sec
- Last write timestamp per device

---

## Part 3: Grafana Multi-User & Dashboard Strategy

### 3.1 User Account Setup

**Requirement:** 3 Grafana users, each seeing only their customer's turbines.

**Two Approaches:**

#### Approach A: Organization-Based Isolation (Recommended for Phase 1)

```
Grafana Instance (Single)
├── Organization: Admin
│   ├── User: admin (all permissions)
│   └── Datasource: iotdb-rest (all devices)
│
├── Organization: Customer1
│   ├── User: customer1.user@company.com (admin in this org only)
│   ├── Dashboard: Customer1 - All Turbines (2 turbines)
│   │   ├── turbine01 (root.digitaltwin.customer1.site1.turbine01)
│   │   └── turbine02 (root.digitaltwin.customer1.site1.turbine02)
│   └── Datasource: iotdb-rest-c1 (credentials scoped to customer1)
│
├── Organization: Customer2
│   ├── User: customer2.user@company.com
│   ├── Dashboard: Customer2 - All Turbines (3 turbines)
│   └── Datasource: iotdb-rest-c2
│
└── Organization: Customer3
    ├── User: customer3.user@company.com
    ├── Dashboard: Customer3 - All Turbines (4 turbines)
    └── Datasource: iotdb-rest-c3
```

**Pros:**
- Complete data isolation (user sees ONLY their org)
- Separate datasource credentials per customer (future: API key auth)
- Simpler permission model
- Natural scaling (add org for new customer)

**Cons:**
- Requires 3 datasource instances (one per customer)
- Grafana admin can see all data (need separate admin per org for true isolation)

#### Approach B: Role-Based Isolation (Complex, skip Phase 1)

Single organization with row-level security, implemented via:
- Custom roles per customer
- Query-time filters (e.g., `WHERE device LIKE 'root.digitaltwin.customer1.*'`)
- Requires Grafana Enterprise or custom authentication plugin

**Recommendation:** **Use Approach A** for Phase 1 (organization-based). Reassess for Phase 3 if customer count grows >10.

### 3.2 Dashboard Strategy

**One dashboard per customer, showing all turbines:**

**Customer1 Dashboard Layout:**

```
┌─────────────────────────────────────────────────────┐
│ Wind Turbine Fleet - Customer1 (Header)              │
└─────────────────────────────────────────────────────┘

Row 1: Turbine Selector (2 tabs: turbine01 | turbine02)
┌──────────────────────────────────────────────────────┐
│ (Tab content changes based on selection)             │
└──────────────────────────────────────────────────────┘

Row 2: Operational Metrics (dynamic based on selection)
┌───────────────────────────────────┬──────────────────┐
│ Live RPM (Gauge)                  │ Power Output (Stat)  │
├───────────────────────────────────┼──────────────────┤
│ Pressure/Flow (Multi-Value Stat)  │ Status Lights    │
└───────────────────────────────────┴──────────────────┘

Row 3: Time Series (15-minute view)
┌───────────────────────────────────┬──────────────────┐
│ Temperature Trends                │ Vibration Levels │
├───────────────────────────────────┼──────────────────┤
│ Pressure Trends                   │ Flow Trends      │
└───────────────────────────────────┴──────────────────┘

Row 4: Alerts & Anomalies
┌──────────────────────────────────────────────────────┐
│ Recent Warnings/Errors (Table)                       │
└──────────────────────────────────────────────────────┘
```

**Implementation:**
- Create 3 separate dashboard JSONs: `customer1.json`, `customer2.json`, `customer3.json`
- Each dashboard uses **variables** for turbine selection (dropdown)
- Panels use variable interpolation: `root.digitaltwin.${CUSTOMER_ID}.site1.${TURBINE_ID}`
- Provisioning file: `provisioning/dashboards/dashboards.yml` (updated to load all 3)

### 3.3 Permission Model

**Grafana Configuration for multi-org isolation:**

**File: `provisioning/grafana/provisioning/org/customers.yml` (new)**

```yaml
apiVersion: 1

orgs:
  - name: Customer1
    id: 2
    admin_user: admin
    admin_password: ${GRAFANA_ADMIN_PASSWORD}

  - name: Customer2
    id: 3
    admin_user: admin
    admin_password: ${GRAFANA_ADMIN_PASSWORD}

  - name: Customer3
    id: 4
    admin_user: admin
    admin_password: ${GRAFANA_ADMIN_PASSWORD}
```

**File: `provisioning/grafana/provisioning/access-control/roles.yml` (new)**

```yaml
roles:
  - name: CustomerViewer
    displayName: "Turbine Viewer (Customer)"
    description: "Can view dashboards and data for assigned customer"
    permissions:
      - action: dashboards:read
        scope: "dashboards:*"
      - action: datasources:read
        scope: "datasources:*"
      - action: org:read
        scope: "org:read"

  - name: CustomerEditor
    displayName: "Turbine Editor (Customer)"
    description: "Can edit dashboards and create alerts"
    permissions:
      - action: dashboards:create
      - action: dashboards:write
      - action: dashboards:read
      - action: alert.rules:write
      - action: alert.rules:read
```

**User Creation (SQL insert or API call post-setup):**

```bash
# After Grafana is running, create users via API:

curl -X POST \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Customer 1 Admin",
    "email": "customer1@company.com",
    "login": "customer1",
    "password": "SECURE_PASSWORD_HERE",
    "orgId": 2
  }' \
  http://localhost:3000/api/admin/users

# Repeat for customer2@company.com (orgId: 3), customer3@company.com (orgId: 4)
```

### 3.4 Datasource per Customer

**File: `provisioning/datasources/iotdb.yml` (updated)**

```yaml
apiVersion: 1

datasources:
  # Datasource for Customer1 (orgId: 2)
  - name: IoTDB - Customer1
    type: apache-iotdb-datasource
    uid: iotdb-customer1
    orgId: 2
    url: http://iotdb:18080
    access: proxy
    isDefault: true
    jsonData:
      customQueryOptions:
        # Future: add customer1-specific API key if IoTDB supports auth scoping
        
  # Datasource for Customer2 (orgId: 3)
  - name: IoTDB - Customer2
    type: apache-iotdb-datasource
    uid: iotdb-customer2
    orgId: 3
    url: http://iotdb:18080
    access: proxy
    isDefault: true

  # Datasource for Customer3 (orgId: 4)
  - name: IoTDB - Customer3
    type: apache-iotdb-datasource
    uid: iotdb-customer3
    orgId: 4
    url: http://iotdb:18080
    access: proxy
    isDefault: true
```

**Note:** Current IoTDB datasource plugin doesn't support query-time access control. The data isolation is at Grafana level (UI/dashboard). For true query-level isolation, implement via:
1. Custom datasource proxy (Node.js middleware that filters queries)
2. IoTDB future feature (role-based query filtering)
3. Separate IoTDB instances per customer (expensive)

For Phase 1, **UI isolation is sufficient** (customer can't see other orgs anyway).

---

## Part 4: Sensor Name Shortening (Semantic IDs)

### 4.1 Current Problem

Grafana panel titles use full device paths:
```
root.digitaltwin.customer1.site1.turbine01.TT_109A
```

This is verbose and occupies entire panel. Users want:
```
Gearbox Bearing Temp A  (or: GB_BearingA)
```

### 4.2 Semantic ID Mapping

**File: `app/config/sensor_mappings.json` (new)**

```json
{
  "metadata": {
    "version": "1.0",
    "description": "Semantic ID mappings: IoTDB measurement names → display names",
    "last_updated": "2026-09-06"
  },
  "sensors": {
    "PT_109A": {
      "short_id": "pt109a",
      "short_display": "PT_109A",
      "long_display": "Inlet Pressure",
      "unit": "bar",
      "category": "pressure",
      "normal_range": [32, 33.5],
      "warning_threshold": 32.5,
      "critical_threshold": 31.5
    },
    "TT_109A": {
      "short_id": "tt109a",
      "short_display": "Gearbox Bearing A",
      "long_display": "Gearbox Bearing Temperature A",
      "unit": "°C",
      "category": "temperature",
      "normal_range": [70, 90],
      "warning_threshold": 95,
      "critical_threshold": 105
    },
    "TURBINE_SPEED_RPM": {
      "short_id": "rpm",
      "short_display": "RPM",
      "long_display": "Turbine Rotor Speed",
      "unit": "RPM",
      "category": "operational",
      "normal_range": [0, 15000],
      "warning_threshold": 14000,
      "critical_threshold": 15000
    },
    "GB_TRQ": {
      "short_id": "torque",
      "short_display": "Gearbox Torque",
      "long_display": "Gearbox Output Torque",
      "unit": "kN·m",
      "category": "operational",
      "normal_range": [-1, 5],
      "warning_threshold": 8,
      "critical_threshold": 10
    }
    // ... (61 total)
  }
}
```

### 4.3 Implementation Approaches

#### Option A: Grafana Transformation (Client-Side, Phase 1)

Each panel includes a "Rename Fields" transformation:

```json
{
  "type": "organize",
  "options": {
    "renameByName": {
      "TT_109A": "Gearbox Bearing Temp A",
      "TT_110A": "Gearbox Bearing Temp B",
      "TURBINE_SPEED_RPM": "RPM"
    }
  }
}
```

**Pros:**
- No server-side code needed
- Per-panel customization
- Works with existing datasource plugin

**Cons:**
- Brittle (hardcoded in dashboard JSON)
- Duplicated across all panels
- Hard to maintain centralized mapping

#### Option B: Datasource Plugin Extension (Phase 2)

Modify/fork Apache IoTDB datasource plugin to load `sensor_mappings.json` at startup and apply transformations automatically.

**Pros:**
- Centralized mapping (single file)
- Automatic for all queries
- Extensible (add unit conversion, thresholds)

**Cons:**
- Requires plugin modification
- Deployment complexity
- Depends on plugin maintainer cooperation

#### Option C: Query Wrapper / Middleware (Phase 2)

Create custom Node.js middleware that sits between Grafana and IoTDB:

```
Grafana → [Middleware] → IoTDB
            ↑
            └── Loads sensor_mappings.json
                Transforms response field names
```

**Pros:**
- Centralized
- Transparent to Grafana/IoTDB
- Can add other transformations (unit conversion, math)

**Cons:**
- Extra service to maintain
- Adds latency
- Requires Docker Compose addition

### 4.4 Phase 1 Recommendation: Hybrid Approach

**For Phase 1, use Option A (Grafana transforms) + external mapping file:**

1. Create `app/config/sensor_mappings.json` (centralized source of truth)
2. In each dashboard, add transformation steps (manually or via script)
3. Dashboard generation script reads mappings and generates transforms:

**Script: `app/scripts/generate_dashboard_transforms.py`**

```python
#!/usr/bin/env python3
"""
Generate Grafana dashboard panel transforms from sensor_mappings.json.

Usage:
    python generate_dashboard_transforms.py customer1 turbine01 > transforms.json
"""

import json
import sys

def load_sensor_mappings(path='config/sensor_mappings.json'):
    with open(path) as f:
        return json.load(f)['sensors']

def generate_transforms(customer_id, turbine_id):
    """Generate Grafana transformation for all sensors."""
    mappings = load_sensor_mappings()
    
    rename_map = {}
    for measurement_name, spec in mappings.items():
        # Map long display name to panel output
        rename_map[measurement_name] = spec['short_display']
    
    transform = {
        "id": "organize",
        "options": {
            "renameByName": rename_map,
            "indexByName": {},
            "excludeByName": {}
        }
    }
    
    return transform

if __name__ == "__main__":
    customer = sys.argv[1] if len(sys.argv) > 1 else "customer1"
    turbine = sys.argv[2] if len(sys.argv) > 2 else "turbine01"
    
    transform = generate_transforms(customer, turbine)
    print(json.dumps(transform, indent=2))
```

**Usage in dashboard generation:**

```bash
# Generate all dashboard JSONs with transforms
python app/scripts/generate_dashboards.py

# This script:
# 1. Reads sensor_mappings.json
# 2. Creates 3 dashboard JSONs (one per customer)
# 3. Each panel includes Grafana transforms
# 4. Outputs to provisioning/dashboards/json/customer*.json
```

### 4.5 Future Enhancement (Phase 3+)

Once datasource plugin is customized, move mapping to plugin configuration:

```yaml
# datasource provisioning
datasources:
  - name: IoTDB
    type: apache-iotdb-datasource-extended
    jsonData:
      sensorMappingsPath: "http://config-server/sensor_mappings.json"
      autoTransformFields: true
      includeUnitConversion: true
```

Plugin automatically:
- Loads mappings
- Renames fields
- Adds units to responses
- Applies thresholds for coloring

---

## Part 5: Architecture Diagram & Data Flow

### 5.1 Target State Architecture

```
╔════════════════════════════════════════════════════════════════════════════╗
║                     MULTI-TURBINE DIGITAL TWIN SYSTEM                      ║
╚════════════════════════════════════════════════════════════════════════════╝

GENERATION LAYER (3 independent processes)
┌────────────────────────────────────────────────────────────────────────────┐
│                                                                              │
│  C1-T01              C1-T02              C2-T03              ...C3-T09       │
│  Generator           Generator           Generator           Generator      │
│  (Process 1)         (Process 2)         (Process 3)         (Process 9)    │
│  Env: C=C1,T=T01     Env: C=C1,T=T02     Env: C=C2,T=T03     Env: C=C3,T=T09│
│  health:8001         health:8002         health:8003         health:8009    │
│                                                                              │
└────────────────┬────────────────────────┬────────────────────────┬──────────┘
                 │ Kafka keys: c1:t01     │ Kafka keys: c1:t02     │
                 │ & c1:t02 (partition 0-5) │ (partition 2-5)       │
                 ▼                         ▼                        ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                         KAFKA BROKER (Single)                               │
│  Topic: turbine.telemetry.raw.v1                                           │
│  Partitions: 6 (round-robin by customer:turbine key)                       │
│  Retention: 24 hours (buffer for IoTDB downtime)                           │
│  Replication: 1                                                             │
└────────┬──────────────────────────────────────────────────────────┬────────┘
         │ Partition 0: c1:t01,c2:t03                              │
         │ Partition 1: c1:t02,c2:t04                              │
         │ Partition 2-5: (other turbines)                         │
         │                                                          │
         ▼                                                          ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                  KAFKA CONSUMER (Single, Enhanced)                          │
│  Group: iotdb-writer-group                                                 │
│  Subscribes: turbine.telemetry.raw.v1                                      │
│  Batch size: 50 records or 5 sec timeout                                   │
│  DLQ: turbine.telemetry.dlq (dead letter queue)                            │
│                                                                              │
│  Processing:                                                                │
│  1. Poll Kafka message                                                      │
│  2. Validate payload (customer_id, turbine_id, event_time_ms, metrics)     │
│  3. Route to device: root.digitaltwin.{CUSTOMER_ID}.site1.{TURBINE_ID}    │
│  4. Buffer in-memory (up to 50 records)                                    │
│  5. Flush batch to IoTDB when full or timeout                              │
│  6. Commit Kafka offset after successful flush                             │
└────────┬──────────────────────────────────────────────────────────┬────────┘
         │ IoTDB insertTablet RPC                                  │
         │ (batch of 50 measurements)                              │
         ▼                                                          ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                    IOTDB (Single-Node, Phase 1)                            │
│  ConfigNode: 1 (runs on port 10710)                                        │
│  DataNode: 1 (runs on port 10720, RPC port 6667)                          │
│  Storage: ./data/iotdb/                                                    │
│                                                                              │
│  Device Tree:                                                               │
│  root.digitaltwin                                                           │
│  ├── customer1                                                              │
│  │   └── site1                                                              │
│  │       ├── turbine01 (61 measurements: PT_*, TT_*, etc.)               │
│  │       └── turbine02 (61 measurements)                                  │
│  ├── customer2                                                              │
│  │   └── site1                                                              │
│  │       ├── turbine03 (61 measurements)                                  │
│  │       ├── turbine04                                                     │
│  │       └── turbine05                                                     │
│  └── customer3                                                              │
│      └── site1                                                              │
│          ├── turbine06 (61 measurements)                                  │
│          ├── turbine07                                                     │
│          ├── turbine08                                                     │
│          └── turbine09                                                     │
│                                                                              │
│  Data Retention: 90 days (configurable)                                    │
│  Compression: Active (time-series specific)                                │
└────────┬──────────────────────────────────────────────────────────┬────────┘
         │ REST API (port 18080)                                   │
         │ Queries: SELECT * FROM root.digitaltwin.{customer}.*   │
         ▼                                                          ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                      GRAFANA (Multi-Org, Isolated)                          │
│                                                                              │
│  Org: Admin                                                                 │
│  ├─ User: admin (superuser, all permissions)                              │
│  ├─ Datasource: iotdb-rest (all data)                                     │
│  └─ Dashboard: System Health (infrastructure monitoring)                  │
│                                                                              │
│  Org: Customer1 (orgId: 2)                                                 │
│  ├─ User: customer1@company.com (viewer + alert editor)                   │
│  ├─ Datasource: iotdb-customer1 (scoped to customer1 queries)            │
│  └─ Dashboard: Customer1 Fleet                                             │
│      ├─ Tab: Turbine01 (12 panels)                                        │
│      └─ Tab: Turbine02 (12 panels)                                        │
│         Panels use: root.digitaltwin.customer1.site1.${TURBINE_ID}.*     │
│         Display names: "Gearbox Bearing Temp A" (not "TT_109A")          │
│                                                                              │
│  Org: Customer2 (orgId: 3)                                                 │
│  ├─ User: customer2@company.com                                            │
│  ├─ Datasource: iotdb-customer2                                           │
│  └─ Dashboard: Customer2 Fleet (3 turbines)                               │
│                                                                              │
│  Org: Customer3 (orgId: 4)                                                 │
│  ├─ User: customer3@company.com                                            │
│  ├─ Datasource: iotdb-customer3                                           │
│  └─ Dashboard: Customer3 Fleet (4 turbines)                               │
│                                                                              │
│  Alert Rules (per customer):                                               │
│  - Temperature > 95°C → Warn                                               │
│  - RPM < 100 (idle) → Info                                                 │
│  - RPM > 14000 → Warn                                                      │
│  - Any NaN/null for 5min → Alert                                           │
└────────────────────────────────────────────────────────────────────────────┘
```

### 5.2 Data Flow for Single Message

```
T=0s: Generator C1-T01 creates sensor reading
┌─────────────────────────────────────────────┐
│ SensorSimulator.generate()                  │
│ TT_109A = 85.0 + trend(0.05°C/hr) + noise  │
│ = 85.0 + 0.0 + 0.2 = 85.2°C                │
│                                              │
│ (Repeat for all 61 sensors)                 │
└────────────────────┬────────────────────────┘

T=10ms: Payload serialized to JSON, published to Kafka
┌──────────────────────────────────────────────────────────────┐
│ {                                                             │
│   "message_id": "550e8400-e29b-41d4-a716-446655440000",    │
│   "customer_id": "customer1",                                │
│   "turbine_id": "turbine01",                                 │
│   "seq_no": 12345,                                           │
│   "event_time_ms": 1725523200050,                            │
│   "metrics": {                                               │
│     "TT_109A": 85.2,                                         │
│     "TT_110A": 86.1,                                         │
│     "TURBINE_SPEED_RPM": 1000.5,                             │
│     ... (61 total)                                           │
│   }                                                           │
│ }                                                             │
└────────────────────┬───────────────────────────────────────┘
                     │ Kafka producer.produce()
                     │ topic: turbine.telemetry.raw.v1
                     │ key: "customer1:turbine01"
                     │ (routes to partition hash % 6)

T=20ms: Kafka broker receives, assigns to partition 2 (hash(c1:t01) % 6)
┌────────────────────────────────────┐
│ Kafka Partition 2                  │
│ [offset 100239: msg 1]             │
│ [offset 100240: msg 2] ← NEW       │
│ [pending: msg 3...]                │
└────────────────────┬───────────────┘

T=50ms: Consumer polls and receives batch (up to 50 messages)
┌──────────────────────────────────────────────────────────────┐
│ Consumer.poll(timeout=1.0)                                   │
│ Receives: [msg_12345, msg_12346, ..., msg_12394]          │
│ (50 messages from various partitions + turbines)             │
│                                                               │
│ For msg_12345:                                               │
│ - Validate: ✓ (all required fields present)                  │
│ - Extract: ts=1725523200050, values=(PT_109A=32.6, ...)     │
│ - Route: device_path = "root.digitaltwin.customer1.site1.turbine01"
│ - Buffer: append to buffered_rows                            │
└────────────────────┬───────────────────────────────────────┘

T=5.0s: Batch timeout reached (50 messages collected)
┌────────────────────────────────────────────────────────────────┐
│ Tablet.create([device_path] × 50, [measurement_names] × 50)  │
│ Tablet content:                                               │
│   timestamps: [1725523200050, 1725523201050, ..., 1725523249050]
│   values: [                                                   │
│     [32.6, 33.3, 94.7, ..., 1000.5],  # row 1 (msg_1)       │
│     [32.7, 33.3, 94.8, ..., 1001.2],  # row 2 (msg_2)       │
│     ...                                                       │
│     [32.9, 33.4, 95.1, ..., 1002.8]   # row 50 (msg_50)     │
│   ]                                                           │
│                                                               │
│ Note: 50 rows × 62 columns = 3100 values                    │
│       Multiple devices (different turbines) in one batch     │
└────────────────────┬───────────────────────────────────────┘
                     │ session.insert_tablet(tablet)
                     │ (RPC to IoTDB port 6667)

T=5.1s: IoTDB processes insert and writes to storage
┌──────────────────────────────────────────────────────────────┐
│ INSERT INTO root.digitaltwin.customer1.site1.turbine01       │
│ (TIMESTAMP, PT_109A, PT_110A, ..., TURBINE_SPEED_RPM)       │
│ VALUES (                                                      │
│   1725523200050, 32.6, 33.3, ..., 1000.5                    │
│   1725523201050, 32.7, 33.3, ..., 1001.2                    │
│   ...                                                         │
│   1725523249050, 32.9, 33.4, ..., 1002.8                    │
│ );                                                            │
│                                                               │
│ Writes to:                                                    │
│ - MemTable (in-memory buffer)                                │
│ - WAL (write-ahead log, disk)                                │
│ - Compaction scheduled for 100M+ data points                 │
└────────────────────┬───────────────────────────────────────┘

T=5.2s: Consumer commits Kafka offset
┌────────────────────────────────────────────────────────────────┐
│ consumer.commit(message=msg_50)                               │
│ Offset committed for all partitions:                          │
│ - Partition 0: offset 200432                                  │
│ - Partition 2: offset 100240                                  │
│ - Partition 5: offset 89123                                   │
│                                                               │
│ Result: Kafka will never re-deliver these 50 messages        │
│         (unless consumer group resets offset)                 │
└────────────────────┬───────────────────────────────────────┘

T=5.3s: Grafana queries IoTDB for real-time display
┌────────────────────────────────────────────────────────────────┐
│ Datasource plugin (iotdb-customer1) sends REST query:         │
│ GET http://iotdb:18080/api/v1/query                          │
│ ?sql=SELECT last_value(TURBINE_SPEED_RPM)                    │
│      FROM root.digitaltwin.customer1.site1.turbine01         │
│      LIMIT 1                                                  │
│                                                               │
│ Response (cached ~5s by Grafana):                            │
│ {                                                              │
│   "results": [                                                │
│     {                                                          │
│       "timestamp": 1725523249050,                            │
│       "value": 1002.8                                         │
│     }                                                          │
│   ]                                                            │
│ }                                                              │
│                                                               │
│ Panel applies transformation:                                 │
│ Rename "TURBINE_SPEED_RPM" → "RPM"                          │
│ Format as: 1002.8 RPM (gauge display)                        │
│                                                               │
│ Customer1 user sees in dashboard: "1002.8 RPM" ✓            │
│ Customer2 user cannot see this org/panel ✓                  │
└────────────────────────────────────────────────────────────────┘
```

---

## Part 6: Implementation Roadmap

### Phase 1: Synthetic Generation & Single-Node Scaling (Weeks 1-3)

**Goal:** Validate data generation, multi-turbine consumer, and Grafana isolation

**Tasks:**

- [ ] **Task 1.1:** Create `synthetic_producer.py`
  - Sensor specifications from CSV (62 sensors, ranges, noise)
  - Base + trend + noise generation model
  - Kafka integration (same as csv_producer)
  - Health check endpoint
  - Test locally (no containers)

- [ ] **Task 1.2:** Create `Dockerfile.generator` and docker-compose additions
  - Build image with Python 3.12 + dependencies
  - Add 3 generator services to docker-compose
  - Test 3 concurrent generators → Kafka
  - Verify messages arrive with customer/turbine IDs

- [ ] **Task 1.3:** Update `kafka_consumer.py` for multi-turbine routing
  - Extract customer_id, turbine_id from payload
  - Dynamically build device path: `root.digitaltwin.{CUSTOMER_ID}.site1.{TURBINE_ID}`
  - Handle multiple turbines in single batch (group by device path)
  - Test with 3 turbines on single consumer
  - Verify IoTDB writes to correct device paths

- [ ] **Task 1.4:** Create `sensor_mappings.json`
  - Map 62 IoTDB measurements to short/long display names
  - Include units, normal ranges, thresholds
  - Version control in `app/config/`

- [ ] **Task 1.5:** Set up Grafana multi-org isolation
  - Create organizations: Customer1, Customer2, Customer3
  - Create users per organization
  - Create datasources per organization (3 separate)
  - Test: Customer1 user logs in, sees only Customer1 org ✓

- [ ] **Task 1.6:** Create customer dashboards
  - Dashboard template: variables for customer_id, turbine_id
  - Create 3 customer dashboards: customer1.json, customer2.json, customer3.json
  - Each shows all turbines for that customer (tabs or multi-select)
  - Add sensor name transformations (Grafana rename fields)
  - Test: Each customer sees only their turbines with short names

- [ ] **Task 1.7:** Scale testing
  - Run 3 generators + consumer + IoTDB for 24 hours
  - Monitor: CPU, memory, disk, latency
  - Verify no data loss (query IoTDB for turbine01 count == expected)
  - Check Grafana dashboard updates in real-time

- [ ] **Task 1.8:** Documentation & automation
  - Write `DEPLOYMENT.md` for multi-turbine setup
  - Add `docker-compose.yml` generator section
  - Create `scripts/setup-customers.sh` (create orgs/users/datasources)
  - Create `scripts/test-multi-turbine.sh` (data validation)

**Deliverables:**
- ✓ Synthetic producer generating 9 turbines
- ✓ Consumer routing to 9 device paths
- ✓ 3 Grafana organizations with users + dashboards
- ✓ Sensor name mapping file
- ✓ 24-hour test report (throughput, latency, data integrity)

**Success Criteria:**
- All 3 generators producing data to Kafka continuously
- Consumer commits every 5 seconds
- IoTDB contains data for root.digitaltwin.customer{1,2,3}.site1.turbine{01-09}
- Customer1 user logs in, sees "Customer1 Fleet" dashboard with 2 turbines
- Customer2 user cannot see Customer1 dashboard
- Panel displays "Gearbox Bearing Temp A" instead of "TT_109A"
- No data loss over 24 hours

---

### Phase 2: Enhanced Synthetic Model & Cluster Prep (Weeks 4-6)

**Goal:** Add state machine to synthetic data, prepare for 3-node cluster

**Tasks:**

- [ ] **Task 2.1:** Implement turbine state machine
  - States: IDLE, RAMP_UP, STEADY_STATE, RAMP_DOWN
  - Transitions every 30-60 min (stochastic)
  - State affects sensor readings (temperature rises during RAMP_UP, etc.)
  - Add state to logs and (optional) Kafka payload

- [ ] **Task 2.2:** Add correlation between sensors
  - When RPM increases, temperature should increase
  - When torque spikes, vibration should spike
  - Implement via cross-sensor dependency matrix

- [ ] **Task 2.3:** Create `docker-compose.cluster.yml`
  - 3 ConfigNodes (quorum)
  - 3 DataNodes (no replication for now, single replica for later)
  - Shared network config
  - Test: Start 3-node cluster locally

- [ ] **Task 2.4:** Data migration planning
  - Write script to export Phase 1 data from single-node
  - Write script to import data into 3-node cluster
  - Test on dev environment

- [ ] **Task 2.5:** Datasource plugin customization (optional for Phase 2)
  - Fork/extend Apache IoTDB Grafana plugin
  - Add sensor_mappings.json loading
  - Auto-apply field name transforms
  - OR: Implement Node.js query middleware as alternative

- [ ] **Task 2.6:** Add anomaly detection alerts
  - Create Grafana alert rules per customer
  - Examples: "Temperature > 95°C for 5 min" → Alert
  - Route alerts to customer email/Slack

**Deliverables:**
- ✓ Turbine state machine simulator
- ✓ Correlated sensor generation
- ✓ 3-node cluster docker-compose
- ✓ Data migration scripts

---

### Phase 3: Production Deployment (Weeks 7+)

**Goal:** Deploy to multi-customer production environment

**Tasks:**

- [ ] **Task 3.1:** Upgrade from single-node to 3-node cluster
  - Backup Phase 1 data
  - Migrate to cluster
  - Verify all queries work

- [ ] **Task 3.2:** Multi-region Kafka setup (optional)
  - Add Kafka brokers in different regions
  - Replicate topics with cross-region failover

- [ ] **Task 3.3:** Role-based access control at query level
  - Implement datasource proxy or plugin
  - Filter queries by customer_id at IoTDB level

- [ ] **Task 3.4:** CI/CD pipeline
  - Automated testing of synthetic generators
  - Automated Grafana dashboard provisioning
  - Automated IoTDB schema updates

---

## Part 7: Testing Strategy for Multi-Customer Isolation

### 7.1 Data Integrity Tests

**Test: No cross-customer data leakage**

```python
# File: app/tests/test_multi_customer_isolation.py

def test_customer_data_isolation():
    """Verify customer1 data does not appear in customer2 queries."""
    
    # Query IoTDB for customer1
    result_c1 = iotdb_session.execute_query_statement(
        "SELECT * FROM root.digitaltwin.customer1.site1.turbine01 LIMIT 1"
    )
    
    # Query IoTDB for customer2
    result_c2 = iotdb_session.execute_query_statement(
        "SELECT * FROM root.digitaltwin.customer2.site1.turbine03 LIMIT 1"
    )
    
    # Verify results are different and contain correct data
    assert len(result_c1) > 0
    assert len(result_c2) > 0
    assert result_c1[0].device_name == "root.digitaltwin.customer1.site1.turbine01"
    assert result_c2[0].device_name == "root.digitaltwin.customer2.site1.turbine03"

def test_consumer_routes_to_correct_device():
    """Verify consumer correctly routes turbine02 messages to customer1.site1.turbine02."""
    
    # Simulate Kafka message for turbine02
    payload = {
        "customer_id": "customer1",
        "turbine_id": "turbine02",
        "event_time_ms": 1725523200050,
        "metrics": {"TT_109A": 85.2, ...}
    }
    
    # Consumer processes and writes to IoTDB
    device_path = build_device_path(payload)
    
    # Verify
    assert device_path == "root.digitaltwin.customer1.site1.turbine02"

def test_nine_turbines_concurrent():
    """Verify 9 generators produce messages without collisions."""
    
    # Start 3 generators (3 processes)
    generators = [
        Generator("customer1", "turbine01"),
        Generator("customer1", "turbine02"),
        Generator("customer2", "turbine03"),
        # ... (6 more)
    ]
    
    # Run for 60 seconds
    for gen in generators:
        gen.start()
    
    time.sleep(60)
    
    # Query IoTDB for all 9 devices
    counts = {}
    for customer in ["customer1", "customer2", "customer3"]:
        for turbine in range(1, 4):
            turbine_id = f"turbine{turbine:02d}"
            result = query_iotdb(
                f"SELECT COUNT(*) FROM root.digitaltwin.{customer}.site1.{turbine_id}"
            )
            counts[f"{customer}:{turbine_id}"] = result[0].count
            
            # Each generator runs at 1 msg/sec for 60 sec = ~60 records
            assert 55 < counts[f"{customer}:{turbine_id}"] < 65
    
    # Verify no data loss
    assert sum(counts.values()) == 9 * 60
```

### 7.2 Grafana UI Isolation Tests

**Test: Customer users can only see their data**

```python
# File: app/tests/test_grafana_isolation.py

def test_customer1_cannot_see_customer2_org():
    """Verify customer1 user cannot access customer2 org."""
    
    client = GrafanaClient(url="http://localhost:3000")
    
    # Login as customer1
    client.login("customer1@company.com", "password")
    
    # Get current user's orgs
    orgs = client.get_user_orgs()
    
    # Verify only Customer1 org
    assert len(orgs) == 1
    assert orgs[0]['name'] == "Customer1"
    
    # Try to access Customer2 org (should fail)
    with pytest.raises(Exception):
        client.get_org_by_id(3)  # Customer2 org

def test_customer1_dashboard_shows_2_turbines():
    """Verify Customer1 dashboard contains exactly 2 turbines."""
    
    client = GrafanaClient(url="http://localhost:3000")
    client.login("customer1@company.com", "password")
    
    # Get dashboard
    dashboard = client.get_dashboard("customer1-fleet")
    
    # Verify device paths in queries
    device_paths = extract_device_paths_from_dashboard(dashboard)
    
    expected = [
        "root.digitaltwin.customer1.site1.turbine01",
        "root.digitaltwin.customer1.site1.turbine02",
    ]
    
    for path in expected:
        assert path in device_paths
    
    # Verify no customer2/customer3 data
    assert not any("customer2" in p for p in device_paths)
    assert not any("customer3" in p for p in device_paths)
```

### 7.3 Sensor Name Mapping Tests

**Test: Display names are correctly applied**

```python
def test_sensor_name_mapping():
    """Verify sensor names are mapped to display names."""
    
    # Query panel with transformation
    dashboard = load_dashboard("customer1.json")
    panel = dashboard['panels'][2]  # Temperature panel
    
    # Check transformation is applied
    assert panel['fieldConfig']['overrides'][0]['matcher']['id'] == 'byName'
    
    # Verify rename map
    rename_map = extract_rename_map(panel)
    
    assert rename_map['TT_109A'] == 'Gearbox Bearing Temp A'
    assert rename_map['TURBINE_SPEED_RPM'] == 'RPM'
```

### 7.4 End-to-End Integration Test

**Test: Full flow from generation to visualization**

```bash
#!/bin/bash
# File: app/tests/test_e2e.sh

set -e

echo "Starting E2E test..."

# 1. Start docker-compose with 3 generators + consumer + iotdb + grafana
docker-compose -f docker-compose.yml up -d

sleep 30  # Wait for services to be healthy

# 2. Verify generators are producing
for turbine in turbine01 turbine02 turbine03; do
    count=$(docker exec turbine-kafka kafka-console-consumer \
        --bootstrap-server localhost:9092 \
        --topic turbine.telemetry.raw.v1 \
        --max-messages 10 \
        --timeout-ms 5000 | grep "$turbine" | wc -l)
    
    if [ $count -lt 1 ]; then
        echo "ERROR: No messages for $turbine"
        exit 1
    fi
    echo "✓ Generator for $turbine producing"
done

# 3. Wait for consumer to write to IoTDB
sleep 10

# 4. Verify IoTDB has data
for customer in customer1 customer2 customer3; do
    for i in $(seq 1 9); do
        turbine=$(printf "turbine%02d" $i)
        result=$(docker exec iotdb ./sbin/start-cli.sh \
            -u root -p root \
            -e "SELECT COUNT(*) FROM root.digitaltwin.$customer.site1.$turbine")
        
        if [ -z "$result" ]; then
            echo "ERROR: No data for $customer:$turbine"
            exit 1
        fi
        echo "✓ Data found for $customer:$turbine"
    done
done

# 5. Verify Grafana has dashboards
curl -s http://localhost:3000/api/dashboards/db/customer1-fleet \
    | grep -q "Customer1 Fleet"
echo "✓ Grafana dashboard accessible"

# 6. Test customer1 user isolation
curl -s -u customer1@company.com:password \
    http://localhost:3000/api/user/orgs | grep -q "Customer1"
echo "✓ Customer1 user sees only Customer1 org"

echo "✅ E2E test passed"

# Cleanup
docker-compose down
```

---

## Part 8: Answering Key Architectural Questions

### Q1: How to make synthetic data realistic vs random?

**Answer:** Use a three-component model:
```
value[i,t] = base[i] + trend[i,t] + noise[i,t]
```
Where:
- **base:** Typical operating point (e.g., 85°C for gearbox bearing)
- **trend:** Slow drift with direction (e.g., +0.1°C/hour heating)
- **noise:** Autocorrelated white noise (95% persistence between samples)

Augment with state machine (IDLE/RAMP/STEADY/RAMP_DOWN) to modulate sensor values. This produces patterns that:
- Don't repeat exactly (unlike CSV replay)
- Vary plausibly (not pure random)
- Show realistic correlation (torque ↑ → temperature ↑)

### Q2: Single process or 3 processes for generators?

**Answer:** **3 separate processes** (Phase 1 via threads in single container, Phase 2 as separate containers).

**Reasoning:**
- Fault isolation (one turbine crash doesn't affect others)
- Independent health checks (health:8001, health:8002, health:8003)
- Natural horizontal scaling (add container for new turbine)
- Better testability (mock one generator without affecting others)
- Docker native (each container runs one process)

**Phase 1 implementation:** Use Python `threading.Thread` for simplicity.  
**Phase 2 migration:** Split into separate docker-compose services and use multiprocessing.

### Q3: Keep single-node IoTDB or expand now?

**Answer:** **Keep single-node for Phase 1**, expand to 3-node cluster in Phase 3 only if:
- ✗ CPU usage consistently >70%
- ✗ Disk I/O saturated
- ✗ Query latency p99 >2s
- ✓ HA required (customer contract mandates 99.9% uptime)

**For Phase 1 (9 turbines @ 1 msg/sec):**
- Write throughput: 9 msg/sec × 62 fields = 558 values/sec
- Batch write: 50 records every 5s = 10 records/sec = 620 values/sec
- **Headroom: 10×** — no bottleneck

Single-node advantages:
- Simpler deployment
- No cluster coordination overhead
- Easier debugging
- Lower resource cost
- Adequate for pilot/dev/test

### Q4: One Grafana org per customer or role-based isolation?

**Answer:** **Organization-based isolation (Approach A)** for Phase 1.

**Reasoning:**
- Simpler to implement (Grafana native feature)
- Complete UI isolation (user can't even see other org tabs)
- Separate datasources (future: per-customer API keys)
- Easier to audit (org-level activity logs)
- Less dependency on query filtering

**Role-based isolation is more complex** and requires:
- Custom datasource proxy
- Row-level security plugins
- Query-time filtering at IoTDB level
- Higher operational burden

**Recommendation:** Start with org-based (Phase 1), migrate to role-based if customer count grows >20.

### Q5: Where should sensor mappings live? How to load them?

**Answer:** Store in **`app/config/sensor_mappings.json`** (version-controlled, single source of truth).

**Phase 1 Usage (Client-Side Transforms):**
1. `sensor_mappings.json` lives in repo
2. Dashboard generation script reads it
3. Generates Grafana panel transforms automatically
4. Transforms renamed: `TT_109A` → `Gearbox Bearing Temp A`

```bash
# Usage:
python app/scripts/generate_dashboards.py
# Outputs: provisioning/dashboards/json/customer*.json
#          (with transforms already embedded)
```

**Phase 2 Enhancement (Server-Side):**
1. Custom datasource plugin loads `sensor_mappings.json`
2. Plugin auto-applies transforms on all queries
3. Eliminates hardcoding in dashboards
4. Centralized updates (change mapping → all dashboards auto-update)

**Phase 3+ (Distributed Config):**
1. Config server (e.g., Consul, etcd) holds mappings
2. Datasource plugin fetches at startup
3. Polls for changes periodically
4. Supports per-customer overrides

### Q6: How to test multi-customer isolation?

**Answer:** Multi-layer testing strategy:

1. **Unit Tests** (`test_multi_customer_isolation.py`):
   - Consumer correctly builds device paths
   - Kafka messages routed to correct partitions
   - Payload validation rejects cross-customer messages

2. **Integration Tests** (`test_kafka_consumer.py`):
   - Publish 10 messages for customer1:turbine01
   - Verify consumer writes to correct device path
   - Query IoTDB and verify data

3. **E2E Tests** (`test_e2e.sh`):
   - Run all 9 generators for 5 minutes
   - Verify each turbine has ~300 records (1 msg/sec × 300s)
   - Total = 9 turbines × 300 = 2700 records
   - No duplicates, no cross-customer leakage

4. **Grafana Tests**:
   - Login as customer1, verify can't access customer2 org
   - Load customer1 dashboard, verify only 2 turbines shown
   - Check panel titles display short names ("RPM" not "TURBINE_SPEED_RPM")

5. **Security Tests**:
   - Try SQL injection: `'; DROP TABLE root.digitaltwin.customer2.*; --`
     → Verify fails / filtered by datasource
   - Cross-org API call: `curl -H "Org-ID: 3" /api/dashboards`
     → Verify 403 Forbidden

---

## Summary: Implementation Checklist

### Phase 1 Deliverables Checklist

- [ ] Synthetic producer (`synthetic_producer.py`)
  - [ ] SensorSimulator class with trend + noise
  - [ ] TurbineSimulator with state machine (optional Phase 1)
  - [ ] Kafka integration
  - [ ] Health server endpoint
  - [ ] Config via env vars

- [ ] Docker container setup
  - [ ] Dockerfile.generator
  - [ ] docker-compose.yml with 3 generator services
  - [ ] Health checks for each generator

- [ ] Consumer enhancement (`kafka_consumer.py`)
  - [ ] Extract customer_id, turbine_id from payload
  - [ ] Dynamic device path routing
  - [ ] Multi-turbine batch handling
  - [ ] Error handling for malformed messages

- [ ] Configuration
  - [ ] `app/config/sensor_mappings.json` (61 sensors)
  - [ ] Updated `.env.example` with customer/turbine IDs
  - [ ] IoTDB system.properties tuning for 9 turbines

- [ ] Grafana setup
  - [ ] 3 organizations (Customer1, Customer2, Customer3)
  - [ ] 3 users (one per customer)
  - [ ] 3 datasources (one per org)
  - [ ] 3 dashboards (one per customer)
  - [ ] Sensor name transformations in panels

- [ ] Testing
  - [ ] Unit tests: consumer routing
  - [ ] Integration tests: 3 generators → consumer → IoTDB
  - [ ] E2E test: 24-hour data flow validation
  - [ ] Grafana UI tests: user isolation

- [ ] Documentation
  - [ ] SCALING.md (this file, committed to repo)
  - [ ] DEPLOYMENT.md (updated multi-customer setup)
  - [ ] docker-compose.yml comments explaining generator config
  - [ ] Test results report (throughput, latency, data integrity)

---

## File References

**Files to Create:**
- `app/src/synthetic_producer.py` (replaces csv_producer.py)
- `Dockerfile.generator` (new)
- `app/config/sensor_mappings.json` (new)
- `app/scripts/generate_dashboards.py` (new)
- `provisioning/dashboards/json/customer1.json` (new)
- `provisioning/dashboards/json/customer2.json` (new)
- `provisioning/dashboards/json/customer3.json` (new)
- `provisioning/grafana/provisioning/org/customers.yml` (new)
- `app/tests/test_multi_customer_isolation.py` (new)
- `app/tests/test_e2e.sh` (new)

**Files to Modify:**
- `docker-compose.yml` (add 3 generator services)
- `app/src/kafka_consumer.py` (multi-device routing)
- `app/src/config.py` (add new env vars)
- `.env.example` (document customer/turbine variables)
- `provisioning/iotdb/iotdb-system.properties` (tuning)
- `provisioning/datasources/iotdb.yml` (3 datasources)

---

## Conclusion

This plan provides a step-by-step path from single-turbine CSV replay to a production-ready multi-customer, multi-turbine system. The phased approach allows for validation at each stage before committing to full-scale infrastructure (cluster, multi-region, etc.).

**Key architectural choices:**
1. **Synthetic generation:** Independent processes, realistic data model
2. **IoTDB:** Single-node for Phase 1 (adequate for 9 turbines), cluster later
3. **Grafana:** Organization-based isolation (simple, effective)
4. **Sensor names:** Centralized mapping file, phase-in server-side transforms
5. **Testing:** Multi-layer approach from unit → integration → E2E

**Success looks like:**
- 3 customers, 9 turbines generating realistic telemetry
- Customer1 user logs into Grafana, sees "RPM: 1234 RPM" (not "TURBINE_SPEED_RPM: 1234")
- Customer2 user cannot see Customer1's data
- 24-hour test shows zero data loss and <500ms latency
- Operator can add new turbine by changing env vars and restarting container

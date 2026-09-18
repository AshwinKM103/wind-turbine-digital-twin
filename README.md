# Wind Turbine Digital Twin

Single turbine (zephyr-energy / cascade-ridge / boreas) after a full reset. Full
documentation is being rewritten from scratch; this is the quick-start.

## Quick start

```bash
cp .env.example .env
docker compose up -d
```

That's it. On a clean clone with no prior state, this one command:

1. Brings up Kafka, Zookeeper, IoTDB, Postgres, OpenBao, and Thingsboard's
   Postgres.
2. Installs the Thingsboard DB schema (`thingsboard-install`, one-shot,
   skipped automatically if already installed).
3. Fixes ownership on fresh volumes/bind mounts that Docker would otherwise
   create root-owned (`bootstrap-permissions`).
4. Initializes and unseals OpenBao, registers policies and AppRoles
   (`openbao-setup`, safe to re-run -- it detects an already-initialized
   vault and unseals it with the saved keys instead of re-initializing).
5. Creates the Thingsboard tenant, activates its admin user, creates one
   device per turbine in `app/config/fleet.json`, and exports each
   device's MQTT access token (`provisioner`).
6. Starts the turbine generator, Kafka consumer, anomaly detector, and the
   Kafka→MQTT bridge into Thingsboard.

Check everything came up:

```bash
docker compose ps
```

First boot takes a few minutes (Thingsboard install + JVM startup). Steps
2-5 above are what used to be several undocumented manual `curl`/`python`
commands after every fresh `docker compose up` -- they're now ordinary
one-shot compose services (`restart: "no"`, exit 0 on success) wired in
with `depends_on: condition: service_completed_successfully`, so `docker
compose ps -a` shows them as `Exited (0)` once done, which is expected.

## Logging in

- **Thingsboard**: http://localhost:8082
  - System admin: `sysadmin@thingsboard.org` / `sysadmin` (Thingsboard's
    own fixed default for the open-source image -- not configurable via
    environment variables at install time). Change it via the admin UI for
    anything beyond local development.
  - Tenant admin (`zephyr-energy`): credentials are generated per-run by
    `provisioner` and written to
    `provisioning/results/provisioning-zephyr-energy-<timestamp>.json`
    (gitignored). Read the latest one:
    ```bash
    ls -t provisioning/results/provisioning-zephyr-energy-*.json | head -1 | xargs cat
    ```
- **OpenBao**: http://localhost:8200 — root token at
  `secrets/openbao/root-token` (gitignored, generated on first init).

## Local LLM (vLLM)

The stack includes a local LLM inference engine (vLLM) powering the turbine copilot chatbot. This requires GPU hardware.

### Prerequisites

- **GPU Hardware**: 1x NVIDIA GPU with a few GB of free VRAM (Qwen2.5-0.5B-Instruct is small enough to run on almost any modern GPU).
- **nvidia-container-toolkit**: Must be installed on the host for Docker GPU access.
  ```bash
  # Install on Ubuntu/Debian:
  distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
  curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
  curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | sudo tee /etc/apt/sources.list.d/nvidia-docker.list
  sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
  sudo systemctl restart docker
  ```

### Setup

1. **Set the API key** in `.env`:
   ```bash
   VLLM_API_KEY=$(openssl rand -base64 32)
   ```

2. **Start vLLM alone** (optional, for debugging):
   ```bash
   docker compose up -d vllm
   ```

3. **Verify the service** is healthy:
   ```bash
   # Wait ~2 minutes for model download and initialization
   curl http://localhost:8000/v1/models \
     -H "Authorization: Bearer $(grep VLLM_API_KEY .env | cut -d= -f2-)"
   ```
   Expected output: `{"object":"list","data":[{"id":"Qwen/Qwen2.5-0.5B-Instruct",...}]}`

4. **Swap models** (if needed) without editing compose files:
   ```bash
   # Edit .env:
   VLLM_MODEL=meta-llama/Llama-3.1-8B-Instruct
   docker compose up -d vllm  # Restart vllm to download and serve the new model
   ```
   Note: swapping to a Llama model also requires changing `--tool-call-parser hermes`
   to `--tool-call-parser llama3_json` in `docker-compose.yml`'s `vllm` service command.

## Adding a customer/turbine

Edit `app/config/fleet.json`, then:

```bash
python app/tools/generate_compose_generators.py
python app/tools/generate_fleet_schema.py
python app/tools/generate_postgres_init.py
docker compose up -d
```

The last `up -d` will start the new generator container and re-run
`provisioner`, which provisions the new tenant/device without touching
existing ones.

## Architecture

```
Turbine Generators (Kafka Producers)
    -> Kafka
        -> Consumer -> IoTDB (raw time-series) -> Thingsboard
        -> Anomaly Detector -> Postgres (alerts, state timeline)
        -> Kafka-MQTT Bridge -> Thingsboard (live telemetry via MQTT)
```

Secrets (Thingsboard tenant credentials, service AppRoles) are managed by
OpenBao, not hardcoded — see `openbao/README.md`.

## Known issues

- The Kafka-MQTT bridge (telemetry -> Thingsboard live view) has had a
  persistent connection issue under investigation; see git log for the fix
  once landed.

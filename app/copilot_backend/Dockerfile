# Copilot Backend
#
# Built from the REPO ROOT (see docker-compose.yml's `context: .` for this
# service) rather than from this directory alone: copilot_backend_main.py and thingsboard_tools.py
# import app.tools.thingsboard_client and app.tools.subsystem_registry (this repo's
# existing hardened ThingsBoard client and sensor registry) plus, optionally,
# app.src.logging_config — those packages must be present in the image with
# the same `app/...` layout they have in the repo for the imports to resolve.

FROM python:3.12-slim

WORKDIR /code

COPY app/copilot_backend/requirements.txt /code/app/copilot_backend/requirements.txt
RUN pip install --no-cache-dir -r /code/app/copilot_backend/requirements.txt

COPY app/copilot_backend /code/app/copilot_backend
COPY app/tools/thingsboard_client.py /code/app/tools/thingsboard_client.py
COPY app/tools/subsystem_registry.py /code/app/tools/subsystem_registry.py
COPY app/src/logging_config.py /code/app/src/logging_config.py
# fleet.json is read directly (not imported) by thingsboard_tools.resolve_turbine_device
# to map a dashboard turbine_id to its real ThingsBoard device name.
COPY app/config/fleet.json /code/app/config/fleet.json

EXPOSE 8090

CMD ["uvicorn", "app.copilot_backend.copilot_backend_main:app", "--host", "0.0.0.0", "--port", "8090"]

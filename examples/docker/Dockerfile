FROM python:3.12-slim

ARG MEMPALACE_VERSION=3.3.0

WORKDIR /app

RUN pip install --no-cache-dir "mempalace==${MEMPALACE_VERSION}"

RUN mkdir -p /data/palace /data/config

ENV MEMPALACE_PALACE_PATH=/data/palace

# Keep the container alive; MCP clients connect via `docker exec`.
CMD ["tail", "-f", "/dev/null"]

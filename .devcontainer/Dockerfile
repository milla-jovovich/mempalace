ARG VARIANT="3.11-bookworm"
FROM mcr.microsoft.com/devcontainers/python:1-${VARIANT}

RUN apt-get update \
    && apt-get install -y --no-install-recommends jq tree \
    && rm -rf /var/lib/apt/lists/*

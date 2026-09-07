# CI fixture only. The application accepts the resulting immutable local ID
# and never installs packages or pulls an image on behalf of generated code.
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

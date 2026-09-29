FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    SRTGO_SETTINGS_FILE=/data/settings.json \
    MCP_TRANSPORT=http \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8742

WORKDIR /app
COPY . .
RUN SETUPTOOLS_SCM_PRETEND_VERSION=0.0.0 pip install . \
    && useradd --system srtgo \
    && mkdir /data \
    && chown srtgo /data

USER srtgo
EXPOSE 8742
CMD ["srtgo-mcp"]

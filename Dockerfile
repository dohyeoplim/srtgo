FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    SRTGO_MCP_TRANSPORT=http \
    SRTGO_MCP_HOST=0.0.0.0 \
    SRTGO_MCP_PORT=8000

WORKDIR /app
COPY . .
RUN SETUPTOOLS_SCM_PRETEND_VERSION=0.0.0 pip install . && useradd --system srtgo

USER srtgo
EXPOSE 8000
CMD ["srtgo-mcp"]

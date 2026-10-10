FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

EXPOSE 3654

# yahoofinance-newsmcp-server now defaults to HTTP, so this image just runs it
# as an always-on HTTP service -- the way a client on a different
# host/container reaches it without an SSH bridge, and the only mode where the
# built-in morning scheduler runs. YF_MCP_HTTP_HOST already defaults to
# 0.0.0.0 (server.py) so it is reachable from outside the container; port/auth
# come from YF_MCP_HTTP_PORT (3654)/YF_MCP_AUTH_TOKEN in .env.
ENV YF_MCP_TRANSPORT=http

CMD ["yahoofinance-newsmcp-server"]

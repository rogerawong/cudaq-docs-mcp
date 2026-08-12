# Runs the MCP server on stdio. The server starts and answers introspection
# without an index; the docs index downloads on first tool use.
FROM python:3.12-slim

WORKDIR /app
COPY . .
RUN pip install --no-cache-dir .

ENTRYPOINT ["cudaq-docs-mcp"]

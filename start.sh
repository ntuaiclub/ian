#!/bin/sh

. /app/.venv/bin/activate

echo "Starting MCP server in HTTP mode (port 5191)..."
ian mcp --http --port 5191 &

echo "Waiting for MCP server to initialize (this may take a while for model loading)..."
MAX_RETRIES=90
RETRY_COUNT=0
while ! curl -s http://localhost:5191/health > /dev/null 2>&1; do
    RETRY_COUNT=$((RETRY_COUNT + 1))
    if [ $RETRY_COUNT -ge $MAX_RETRIES ]; then
        echo "Error: MCP server failed to start after $MAX_RETRIES seconds"
        exit 1
    fi
    echo "Waiting for MCP server... ($RETRY_COUNT/$MAX_RETRIES)"
    sleep 1
done
echo "MCP server is ready!"

echo "Starting Flask server for FB/LINE..."
ian webhook &

echo "Starting daily event reminder daemon..."
ian reminder --daemon &

echo "Starting Discord bot..."
ian discord

import pytest

pytest.skip(
    "External integration tests are intentionally deferred. Future coverage "
    "should exercise MCP runtime wiring, Discord/LINE/Facebook gateways, "
    "Google Sheets or Apps Script integrations, and live LLM flows without "
    "requiring secrets in the default CI suite.",
    allow_module_level=True,
)

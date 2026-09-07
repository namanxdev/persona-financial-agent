"""Persona-configurable agent. Reaches data only through mcp_server via MCP stdio."""

# Imported for its side effect: .env must populate os.environ before any module
# below reads OPENAI_API_KEY at import time.
from agent.config import load_env

load_env()

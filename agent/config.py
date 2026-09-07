"""Load `.env` into the process environment.

The app reads OPENAI_API_KEY from os.environ. Without this, a key sitting in
`.env` is silently ignored and every answer quietly uses the deterministic
fallback -- the failure looks exactly like success, which is the worst kind.

Deliberately a small stdlib parser rather than a python-dotenv dependency:
`python-dotenv` is outside the AGENTS.md allowlist, and the file format we
need is a handful of KEY=VALUE lines.
"""

import os
from pathlib import Path

_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


def load_env(path: Path | None = None) -> None:
    """Populate os.environ from a .env file. Real environment variables win.

    Precedence matters: an explicitly exported variable must beat the file, so
    a reviewer can override a committed default from the shell.
    """
    env_path = path or _ENV_FILE
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value

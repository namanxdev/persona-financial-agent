"""Keep the suite hermetic: no provider calls, one deterministic answer path.

agent/config.py loads `.env` on import, so on any machine with OPENAI_API_KEY
set the whole suite would otherwise make live OpenAI calls and assert against
model-written prose. The provider path is covered instead by
tests/test_synthesis.py, which injects fixed model output, so what runs locally
is what runs in CI.
"""

import os

import pytest

_OVERRIDES = {"AGENT_SYNTHESIS": "off", "OPENAI_API_KEY": None}


@pytest.fixture(autouse=True, scope="session")
def deterministic_answer_path():
    saved = {key: os.environ.get(key) for key in _OVERRIDES}
    for key, value in _OVERRIDES.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    yield
    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value

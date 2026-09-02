import pytest

from copilot_cli.copilot.openai_proxy.prompt_config import ENV_VAR, clear_cache


@pytest.fixture(autouse=True)
def isolate_live_prompts(monkeypatch):
    """Keep A/B edits to prompts.conf from changing unit-test expectations."""
    monkeypatch.setenv(ENV_VAR, "defaults")
    clear_cache()
    yield
    clear_cache()

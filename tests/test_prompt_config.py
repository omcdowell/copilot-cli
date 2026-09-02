from pathlib import Path

import pytest

from copilot_cli.copilot.openai_proxy.message_flattener import flatten_messages
from copilot_cli.copilot.openai_proxy.prompt_config import (
    DEFAULT_PROMPTS,
    ENV_VAR,
    PROMPT_FILE_NAME,
    clear_cache,
    extract_pi_fields,
    get_prompts,
    parse_prompts,
    render_session_context,
    resolve_prompts_path,
)

REPO_PROMPTS = Path(__file__).resolve().parents[1] / PROMPT_FILE_NAME


def test_parse_overrides_sections_and_settings():
    text = """
# comment
[settings]
use_client_system_prompt = false
recency_footer = short footer

[continuation_reminder]
Keep going.

[pi_system]
You are a test agent.
"""
    prompts = parse_prompts(text)
    assert prompts.use_client_system_prompt is False
    assert prompts.recency_footer == "short footer"
    assert prompts.continuation_reminder == "Keep going."
    assert prompts.pi_system == "You are a test agent."
    assert prompts.local_tools_overlay == DEFAULT_PROMPTS.local_tools_overlay


def test_parse_rejects_unknown_section():
    with pytest.raises(ValueError, match="unknown"):
        parse_prompts("[not_a_section]\nhello\n")


def test_repo_prompts_conf_parses():
    text = REPO_PROMPTS.read_text(encoding="utf-8")
    prompts = parse_prompts(text)
    assert prompts.use_client_system_prompt is False
    assert "operating inside pi" in prompts.pi_system
    assert "{{pi.tools}}" in prompts.pi_system
    assert "{{pi.guidelines}}" in prompts.pi_system
    assert "{{pi.docs}}" in prompts.pi_system
    assert "{{pi.project_context}}" in prompts.pi_system
    assert "{{pi.skills}}" in prompts.pi_system
    assert "{{pi.cwd}}" in prompts.pi_system
    assert "- read:" not in prompts.pi_system
    assert "<available_skills>" not in prompts.pi_system
    assert "```tool_call" in prompts.local_tools_overlay
    assert prompts.continuation_reminder.startswith("Continue making")


def test_get_prompts_reloads_when_file_changes(tmp_path, monkeypatch):
    path = tmp_path / "prompts.conf"
    path.write_text("[recency_footer]\nfirst\n", encoding="utf-8")
    monkeypatch.setenv(ENV_VAR, str(path))
    clear_cache()
    assert get_prompts().recency_footer == "first"

    path.write_text("[recency_footer]\nsecond\n", encoding="utf-8")
    path.touch()
    assert get_prompts().recency_footer == "second"


def test_env_defaults_ignores_cwd_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / PROMPT_FILE_NAME).write_text("[recency_footer]\nfrom-cwd\n", encoding="utf-8")
    monkeypatch.setenv(ENV_VAR, "defaults")
    clear_cache()
    assert resolve_prompts_path() is None
    assert get_prompts().recency_footer == DEFAULT_PROMPTS.recency_footer


def test_flatten_uses_configured_pi_system(tmp_path, monkeypatch):
    path = tmp_path / "prompts.conf"
    path.write_text(
        "[settings]\nuse_client_system_prompt = false\n\n"
        "[pi_system]\nCONFIG PI SYSTEM\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(ENV_VAR, str(path))
    clear_cache()
    prompt = flatten_messages(
        [
            {"role": "system", "content": "CLIENT PI SYSTEM"},
            {"role": "user", "content": "hello"},
        ]
    )
    assert "CONFIG PI SYSTEM" in prompt
    assert "CLIENT PI SYSTEM" not in prompt
    assert "## Session context" in prompt


def test_flatten_fills_pi_placeholders_from_client_system(tmp_path, monkeypatch):
    path = tmp_path / "prompts.conf"
    path.write_text(
        "[settings]\nuse_client_system_prompt = false\n\n"
        "[pi_system]\n"
        "Available tools:\n{{pi.tools}}\n\n"
        "cwd={{pi.cwd}}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(ENV_VAR, str(path))
    clear_cache()
    client = (
        "You are an expert coding assistant operating inside pi.\n\n"
        "Available tools:\n"
        "- read: Read file contents\n"
        "- bash: Execute bash commands (ls, grep, find, etc.)\n\n"
        "In addition to the tools above, you may have access to other custom tools depending on the project.\n\n"
        "Guidelines:\n"
        "- Be concise in your responses\n\n"
        "Pi documentation (read only when the user asks about pi itself):\n"
        "- Main documentation: /pi/README.md\n"
        "- Additional docs: /pi/docs\n"
        "- Examples: /pi/examples (extensions, custom tools, SDK)\n"
        "- When reading pi docs or examples, resolve docs/...\n\n"
        "Current working directory: /tmp/project"
    )
    prompt = flatten_messages(
        [
            {"role": "system", "content": client},
            {"role": "user", "content": "hello"},
        ]
    )
    assert "- read: Read file contents" in prompt
    assert "- bash: Execute bash commands" in prompt
    assert "cwd=/tmp/project" in prompt
    assert "{{pi.tools}}" not in prompt
    assert "{{pi.cwd}}" not in prompt


def test_extract_pi_fields_from_typical_system_prompt():
    client = (
        "You are an expert coding assistant operating inside pi, a coding agent harness.\n\n"
        "Available tools:\n"
        "- read: Read file contents\n"
        "- bash: Execute bash commands (ls, grep, find, etc.)\n\n"
        "In addition to the tools above, you may have access to other custom tools depending on the project.\n\n"
        "Guidelines:\n"
        "- Use bash for file operations like ls, rg, find\n"
        "- Be concise in your responses\n\n"
        "Pi documentation (read only when the user asks about pi itself, its SDK, extensions, themes, skills, or TUI):\n"
        "- Main documentation: /opt/pi/README.md\n"
        "- Additional docs: /opt/pi/docs\n"
        "- Examples: /opt/pi/examples (extensions, custom tools, SDK)\n"
        "- When reading pi docs or examples, resolve docs/...\n\n"
        "<project_context>\n\n"
        "Project-specific instructions and guidelines:\n\n"
        "<project_instructions path=\"/home/u/.pi/agent/AGENTS.md\">\n"
        "# Global\n"
        "</project_instructions>\n\n"
        "</project_context>\n\n"
        "The following skills provide specialized instructions for specific tasks.\n"
        "Use the read tool to load a skill's file when the task matches its description.\n\n"
        "<available_skills>\n"
        "  <skill>\n"
        "    <name>tdd</name>\n"
        "  </skill>\n"
        "</available_skills>\n"
        "Current working directory: /work/repo"
    )
    fields = extract_pi_fields(client)
    assert fields["tools"].startswith("- read:")
    assert "Be concise" in fields["guidelines"]
    assert fields["docs"].startswith("- Main documentation: /opt/pi/README.md")
    assert "<project_context>" in fields["project_context"]
    assert "<name>tdd</name>" in fields["skills"]
    assert fields["cwd"] == "/work/repo"

    rendered = render_session_context(
        "tools:\n{{pi.tools}}\n\ncwd={{pi.cwd}}\n",
        client,
    )
    assert "- bash:" in rendered
    assert "cwd=/work/repo" in rendered
    assert "{{pi." not in rendered


def test_flatten_can_passthrough_client_system(tmp_path, monkeypatch):
    path = tmp_path / "prompts.conf"
    path.write_text(
        "[settings]\nuse_client_system_prompt = true\n\n"
        "[pi_system]\nCONFIG PI SYSTEM\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(ENV_VAR, str(path))
    clear_cache()
    prompt = flatten_messages(
        [
            {"role": "system", "content": "CLIENT PI SYSTEM"},
            {"role": "user", "content": "hello"},
        ]
    )
    assert "CLIENT PI SYSTEM" in prompt
    assert "CONFIG PI SYSTEM" not in prompt

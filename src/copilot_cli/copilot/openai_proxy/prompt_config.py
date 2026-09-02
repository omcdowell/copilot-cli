"""Load editable Substrate prompt copy from a live config file.

The file is not part of the installed package. ``get_prompts()`` re-reads it
when the mtime changes, so A/B edits apply on the next Copilot turn without
reinstalling or restarting.

Lookup order:

1. ``COPILOT_CLI_PROMPTS`` — path to a file, or ``defaults`` / ``none`` / ``-``
   to force built-in copy
2. ``prompts.conf`` in the current working directory
3. ``prompts.conf`` walking up from cwd (stops at a ``.git`` directory)
"""

from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass, fields, replace
from pathlib import Path

ENV_VAR = "COPILOT_CLI_PROMPTS"
PROMPT_FILE_NAME = "prompts.conf"
DEFAULT_SENTINELS = frozenset({"", "defaults", "none", "-"})

_TRUE = frozenset({"true", "yes", "1", "on"})
_FALSE = frozenset({"false", "no", "0", "off"})


@dataclass(frozen=True)
class PromptConfig:
    local_tools_overlay: str
    recency_footer: str
    continuation_reminder: str
    pi_system: str
    use_client_system_prompt: bool
    local_tools_heading: str
    session_context_heading: str
    user_request_heading: str
    user_role_prefix: str
    assistant_role_prefix: str


DEFAULT_PROMPTS = PromptConfig(
    local_tools_overlay=(
        "You have access to the tools listed below. They run on the user's machine; "
        "they are not Microsoft 365 Copilot's built-in workplace tools. "
        "When (and only when) you need to call a tool, reply with ONLY one or more "
        "fenced code blocks, each tagged `tool_call` and containing a single JSON "
        "object of this exact form:\n"
        "\n"
        "```tool_call\n"
        '{"name": "<tool_name>", "arguments": { ... }}\n'
        "```\n"
        "\n"
        "To call several tools at once, emit several such blocks back to back, one JSON "
        "object each, and nothing else around them. "
        "Do not add any prose before, between, or after the blocks when calling tools. "
        "If you do not need a tool, reply normally with your answer."
    ),
    recency_footer="If you need a local tool, reply with only ```tool_call fences.",
    continuation_reminder=(
        "Continue making any necessary follow-up ```tool_call requests "
        "until you have completed the task."
    ),
    pi_system="",
    use_client_system_prompt=True,
    local_tools_heading="## Local tools",
    session_context_heading="## Session context",
    user_request_heading="## User request",
    user_role_prefix="[User]:",
    assistant_role_prefix="[Assistant]:",
)

_PROMPT_SECTIONS = frozenset(
    name
    for name in (field.name for field in fields(PromptConfig))
    if name != "use_client_system_prompt"
)
_ALLOWED_SECTIONS = _PROMPT_SECTIONS | {"settings"}

_cache_lock = threading.Lock()
_cache_key: tuple[str | None, float | None] | None = None
_cache_value = DEFAULT_PROMPTS
_cache_path: Path | None = None


def clear_cache() -> None:
    global _cache_key, _cache_value, _cache_path
    with _cache_lock:
        _cache_key = None
        _cache_value = DEFAULT_PROMPTS
        _cache_path = None


def current_prompts_path() -> Path | None:
    """Path last loaded by ``get_prompts()``, or None for built-in defaults."""
    with _cache_lock:
        return _cache_path


def resolve_prompts_path() -> Path | None:
    env = os.environ.get(ENV_VAR)
    if env is not None:
        stripped = env.strip()
        if stripped.lower() in DEFAULT_SENTINELS:
            return None
        path = Path(stripped).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"{ENV_VAR}={env!r} is not a file")
        return path.resolve()

    here = Path.cwd().resolve()
    for directory in (here, *here.parents):
        candidate = directory / PROMPT_FILE_NAME
        if candidate.is_file():
            return candidate
        if (directory / ".git").exists():
            break
    return None


def _parse_bool(value: str) -> bool:
    lowered = value.strip().lower()
    if lowered in _TRUE:
        return True
    if lowered in _FALSE:
        return False
    raise ValueError(f"invalid boolean {value!r} (use true/false)")


def parse_prompts(text: str, *, base: PromptConfig = DEFAULT_PROMPTS) -> PromptConfig:
    """Parse a ``prompts.conf`` body into a config, filling gaps from ``base``."""
    current: str | None = None
    chunks: dict[str, list[str]] = {}
    settings: dict[str, str] = {}

    for raw_line in text.splitlines():
        line = raw_line.rstrip("\r")
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]") and "\n" not in stripped:
            name = stripped[1:-1].strip()
            if name not in _ALLOWED_SECTIONS:
                raise ValueError(
                    f"unknown prompts.conf section [{name}]; "
                    f"expected one of {', '.join(sorted(_ALLOWED_SECTIONS))}"
                )
            current = name
            if current != "settings":
                chunks.setdefault(current, [])
            continue
        if current is None:
            continue
        if current == "settings":
            if not stripped or stripped.startswith("#"):
                continue
            if "=" not in line:
                raise ValueError(f"invalid settings line: {line!r}")
            key, _, value = line.partition("=")
            settings[key.strip()] = value.strip()
            continue
        chunks[current].append(line)

    updates: dict[str, object] = {}
    for name, lines in chunks.items():
        body = "\n".join(lines)
        if body.startswith("\n"):
            body = body[1:]
        updates[name] = body.rstrip()

    if "use_client_system_prompt" in settings:
        updates["use_client_system_prompt"] = _parse_bool(settings["use_client_system_prompt"])
    for key, value in settings.items():
        if key == "use_client_system_prompt":
            continue
        if key not in _PROMPT_SECTIONS:
            raise ValueError(f"unknown prompts.conf setting {key!r}")
        updates[key] = value

    return replace(base, **updates)


def get_prompts() -> PromptConfig:
    """Return live prompt copy, reloading the config file when it changes."""
    global _cache_key, _cache_value, _cache_path
    path = resolve_prompts_path()
    mtime = path.stat().st_mtime if path is not None else None
    key = (str(path) if path else None, mtime)
    with _cache_lock:
        if _cache_key == key:
            return _cache_value
    loaded = parse_prompts(path.read_text(encoding="utf-8")) if path is not None else DEFAULT_PROMPTS
    with _cache_lock:
        _cache_key = key
        _cache_value = loaded
        _cache_path = path
        return _cache_value


# Filled from the client (Pi) system message. Names match {{pi.<name>}} in [pi_system].
_PI_PLACEHOLDER_RE = re.compile(r"\{\{pi\.([a-z_]+)\}\}")
_PI_FIELD_NAMES = (
    "tools",
    "guidelines",
    "docs",
    "project_context",
    "skills",
    "cwd",
)


def extract_pi_fields(client_system: str) -> dict[str, str]:
    """Pull auto-populated Pi sections out of the client system prompt."""
    fields_: dict[str, str] = {name: "" for name in _PI_FIELD_NAMES}
    text = client_system.strip()
    if not text:
        return fields_

    tools = re.search(
        r"Available tools:\n(.*?)(?:\n\nIn addition to the tools above|\n\nGuidelines:)",
        text,
        re.DOTALL,
    )
    if tools:
        fields_["tools"] = tools.group(1).strip()

    guidelines = re.search(
        r"Guidelines:\n(.*?)(?:\n\nPi documentation|\n\n<project_context>|"
        r"\n\nThe following skills|\nCurrent working directory:)",
        text,
        re.DOTALL,
    )
    if guidelines:
        fields_["guidelines"] = guidelines.group(1).strip()

    docs = re.search(
        r"Pi documentation[^\n]*\n("
        r"- Main documentation: [^\n]+\n"
        r"- Additional docs: [^\n]+\n"
        r"- Examples: [^\n]+)",
        text,
    )
    if docs:
        fields_["docs"] = docs.group(1).strip()

    context = re.search(r"<project_context>.*?</project_context>", text, re.DOTALL)
    if context:
        fields_["project_context"] = context.group(0).strip()

    skills = re.search(
        r"The following skills provide specialized instructions for specific tasks\."
        r".*?</available_skills>",
        text,
        re.DOTALL,
    )
    if skills:
        fields_["skills"] = skills.group(0).strip()

    cwd = re.search(r"Current working directory:\s*(.+)\s*$", text)
    if cwd:
        fields_["cwd"] = cwd.group(1).strip()

    return fields_


def render_session_context(template: str, client_system: str) -> str:
    """Apply ``{{pi.*}}`` placeholders from Pi's system message, or return the template."""
    template = template.strip()
    if not template:
        return client_system.strip()
    if "{{pi." not in template:
        return template

    fields_ = extract_pi_fields(client_system)

    def _replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in fields_:
            return match.group(0)
        return fields_[name]

    rendered = _PI_PLACEHOLDER_RE.sub(_replace, template)
    rendered = re.sub(r"\n{3,}", "\n\n", rendered)
    return rendered.strip()

# copilot-cli

Standalone **M365 Copilot CLI** — connect to Microsoft 365 Copilot (Office Business Chat or Teams hub), then chat, recon, dump, or expose an OpenAI-compatible proxy.

| Command | Purpose |
|---------|---------|
| `chat` | Interactive Copilot session |
| `whoami` | User/context recon through Copilot |
| `dump` | Dump documents/emails from whoami recon output |
| `gui` | Browse collected output locally |
| `serve` | OpenAI-compatible HTTP proxy for Pi and other clients |

## Prerequisites

Python 3.9+, Node.js on `PATH`, and Microsoft Edge (for substrate token capture).

## Install

```bash
cd /path/to/copilot-cli
python3 -m venv .venv && source .venv/bin/activate   # Windows: .\.venv\Scripts\Activate.ps1
pip install -e .

cd src/copilot_cli/puppeteer_get_substrate_bearer && npm install && cd -
```

With [uv](https://docs.astral.sh/uv/): `uv venv && source .venv/bin/activate && uv pip install -e .` then `npm install` as above.

## Auth

1. **Cached token** — `--cached-token` reads `substrate_access_token` from `./tokens.json`
2. **Interactive** — Puppeteer opens a visible Edge window with a persistent profile (default `~/.config/copilot-cli/msedge-profile`). Sign in once (MFA/SSO OK); later runs reuse cookies. No passwords on the CLI.

For `officeweb`, the bearer is captured live from the Substrate WebSocket handshake (`access_token=` in the `wss://substrate.office.com/m365Copilot/Chathub/...` URL), with an OAuth-response / MSAL fallback. For `teamshub`, it is read from the MSAL token cache in the signed-in page's `localStorage`.

| Scenario | Surface |
|----------|---------|
| `officeweb` | Opens `https://m365.cloud.microsoft/chat` |
| `teamshub` | Opens Teams (`teams.microsoft.com`) |

Override profile: `COPILOT_CLI_BROWSER_PROFILE`. Override Edge binary: `COPILOT_CLI_EDGE_PATH`.

More detail: [`src/copilot_cli/puppeteer_get_substrate_bearer/readme.md`](src/copilot_cli/puppeteer_get_substrate_bearer/readme.md).

## Usage

First run opens a visible Edge window — sign in once. Prefer `--cached-token` once `./tokens.json` holds a substrate bearer.

```bash
copilot-cli chat -u user@contoso.com -s officeweb
copilot-cli whoami -u user@contoso.com --cached-token -s officeweb
copilot-cli dump -u user@contoso.com --cached-token -s officeweb -d ./whoami_out
copilot-cli gui -d ./whoami_out
copilot-cli serve -u user@contoso.com --cached-token -s officeweb --port 8787
```

## Pi integration (optional)

Run the local OpenAI-compatible proxy, then point Pi at it via the bundled extension.

```bash
copilot-cli serve -u user@contoso.com --cached-token -s officeweb --port 8787
pi -e ./pi-extension
```

In Pi: `/model m365-copilot/default`

The proxy exposes `GET /v1/models` and `POST /v1/chat/completions` on `http://127.0.0.1:8787/v1` (override the bind address with `--host`). Pi keeps local tools; Copilot is the reasoning backend. Tool calling is emulated with `tool_call` / `tool_response` markdown fences. Continuations send a short reminder by default; pass `--tool-protocol full` to re-send the overlay and tools catalog if the model drops the format.

### Streaming fidelity

Substrate does not deliver every character through `writeAtCursor`: some segments only appear in the cumulative `messages[].text` snapshot of a later frame. Streamed text cannot be retracted, so the proxy releases only what a snapshot has confirmed, and the turn's final answer heals anything still outstanding. A hub that streams snapshots gives smooth token-by-token output; a hub that does not gives the complete answer in one chunk at the end of the turn. The text Pi renders always matches the Copilot web UI.

### Diagnosing a truncated or garbled answer

`serve` prints the version, module path, and git revision it is running — check that first when a fix appears to have no effect (a `pip install .` box keeps serving `site-packages` after a `git pull`; use `pip install -e .` or reinstall).

Capture the raw hub frames and replay them offline:

```bash
COPILOT_CLI_WS_TRACE=/tmp/copilot-trace.jsonl \
  copilot-cli serve -u user@contoso.com --cached-token -s officeweb --port 8787
# reproduce the bad turn, then:
python tools/replay_ws_trace.py /tmp/copilot-trace.jsonl
```

The replay reports whether the hub sent mid-stream snapshots, whether they were dropped by the requestId/messageType filters, and exactly which text is missing from the streamed answer. Traces contain prompt and answer text (access tokens are redacted).

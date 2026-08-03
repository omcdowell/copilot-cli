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

The proxy exposes `GET /v1/models` and `POST /v1/chat/completions` on `http://127.0.0.1:8787/v1` (override the bind address with `--host`). Pi keeps local tools; Copilot is the reasoning backend. Tool calling is emulated via Hermes-style `<tool_call>` XML; responses stream live, token by token, from Substrate `writeAtCursor` deltas (falling back to a complete reply only when the hub does not stream).

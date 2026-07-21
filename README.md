# copilot-cli

Standalone **M365 Copilot CLI**

## What it does

Programmatically connect to Microsoft 365 Copilot (Office Business Chat or Teams hub) by acquiring a Substrate/Sydney bearer token, then chat / recon / dump via the Copilot websocket API.

| Command | Purpose |
|---------|---------|
| `chat` | Interactive Copilot session |
| `whoami` | User/context recon through Copilot |
| `dump` | Exfil-style data dump from whoami recon |
| `spear-phishing` | Craft personalized emails via Copilot |
| `gui` | Browse collected output locally |

## Auth model

1. Optional cache: `--cached-token` reads `substrate_access_token` from `./tokens.json`
2. Else: Puppeteer headless login (`office.com` or `teams.microsoft.com`) captures the Substrate bearer
3. Token is attached to `wss://substrate.office.com/m365Copilot/Chathub/...`

Scenarios: `officeweb` | `teamshub`

## Install

```bash
cd /home/noble/code/copilot-cli
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# Node deps for substrate token capture
cd src/copilot_cli/puppeteer_get_substrate_bearer && npm install && cd -
```

Requires Node.js on `PATH` for password-based auth.

## Usage

```bash
copilot-cli chat -u user@contoso.com -p 'password' -s officeweb
copilot-cli whoami -u user@contoso.com --cached-token -s officeweb
copilot-cli dump -u user@contoso.com --cached-token -s officeweb -d ./whoami_out
```

Or: `python -m copilot_cli ...`

## Layout

```
src/copilot_cli/
  cli/                 # argparse + command runners
  copilot/             # connector, chat, whoami, dump, …
  common/              # token cache + file browser GUI
  puppeteer_get_substrate_bearer/   # Node auth helpers
```

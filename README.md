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
2. Else: Puppeteer opens a **visible Microsoft Edge** window with a persistent profile (default `~/.config/copilot-cli/msedge-profile`) and navigates to **https://m365.cloud.microsoft/chat**. Sign in once interactively (MFA/SSO OK); later runs reuse cookies — **no passwords on the CLI**. The CLI captures the Substrate bearer from the chat WebSocket (`access_token=`), not from merely being signed in on the M365 home page.
3. Token is attached to `wss://substrate.office.com/m365Copilot/Chathub/...`

Override the profile directory with `COPILOT_CLI_BROWSER_PROFILE`. Override the Edge binary with `COPILOT_CLI_EDGE_PATH` if needed.

Scenarios: `officeweb` | `teamshub`

## Install

**Prerequisites:** Python 3.9+, Node.js on `PATH`, and Microsoft Edge installed (for substrate token capture).

### Windows (PowerShell)

```powershell
cd path\to\copilot-cli
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip setuptools
pip install -e .

# Node deps for substrate token capture
cd src\copilot_cli\puppeteer_get_substrate_bearer
npm install
cd ..\..\..\..
```

If script activation is blocked: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, then re-run `Activate.ps1`.

Auth uses system Microsoft Edge with a dedicated profile under `%USERPROFILE%\.config\copilot-cli\msedge-profile` (or `COPILOT_CLI_BROWSER_PROFILE`).

### Linux / macOS (Astral / uv — optional)

```bash
cd /path/to/copilot-cli
uv venv                  # uses .python-version (3.11)
source .venv/bin/activate
uv pip install -e .

cd src/copilot_cli/puppeteer_get_substrate_bearer && npm install && cd -
```

### Linux / macOS (plain pip)

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip setuptools
pip install -e .

cd src/copilot_cli/puppeteer_get_substrate_bearer && npm install && cd -
```

If you still see `editable mode currently requires a setup.py`, upgrade pip (`python -m pip install -U pip setuptools`) — this repo includes a thin `setup.py` for older pip, but very old pip still needs a recent setuptools.

Lint / format / typecheck with machine-installed Astral tools (`uv tool install ruff ty`):

```bash
ruff check src
ruff format src
ty check
```

## Make the CLI available (`copilot-cli` and `python -m`)

Editable install (`pip install -e .` / `uv pip install -e .`) does two things:

1. Registers the console script **`copilot-cli`** (from `[project.scripts]` in `pyproject.toml`) into the active environment’s scripts dir
2. Puts the `copilot_cli` package on that environment’s import path so **`python -m copilot_cli`** works

### Windows

```powershell
.\.venv\Scripts\Activate.ps1

Get-Command copilot-cli          # ...\.venv\Scripts\copilot-cli.exe
copilot-cli --help
python -m copilot_cli --help
```

Without activating:

```powershell
.\.venv\Scripts\copilot-cli.exe --help
.\.venv\Scripts\python.exe -m copilot_cli --help
```

If `copilot-cli` is not recognized: activate the venv, or use the `.exe` path above, then re-run `pip install -e .`.

If `No module named copilot_cli`: install into the same interpreter you run — `python -m pip install -e .`.

### Linux / macOS

```bash
source .venv/bin/activate

which copilot-cli            # should be .../.venv/bin/copilot-cli
copilot-cli --help
python -m copilot_cli --help
```

Without activating:

```bash
.venv/bin/copilot-cli --help
.venv/bin/python -m copilot_cli --help
```

## Usage

First run opens a visible Edge window — sign in once. Later runs reuse the profile session.

```bash
copilot-cli chat -u user@contoso.com -s officeweb
copilot-cli whoami -u user@contoso.com --cached-token -s officeweb
copilot-cli dump -u user@contoso.com --cached-token -s officeweb -d ./whoami_out
```

Same via module form:

```bash
python -m copilot_cli chat -u user@contoso.com -s officeweb
```

Optional env vars (paths only — never put passwords in env):

```bash
export COPILOT_CLI_BROWSER_PROFILE=~/.config/copilot-cli/msedge-profile
export COPILOT_CLI_EDGE_PATH=/usr/bin/microsoft-edge   # if auto-detect fails
```

Prefer `--cached-token` once `./tokens.json` already holds a substrate bearer.

## Layout

```
src/copilot_cli/
  cli/                 # argparse + command runners
  copilot/             # connector, chat, whoami, dump, …
  common/              # token cache + file browser GUI
  puppeteer_get_substrate_bearer/   # Node auth helpers
```

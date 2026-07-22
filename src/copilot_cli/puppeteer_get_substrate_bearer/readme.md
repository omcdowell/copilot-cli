# Get the substrate token (CoPilot API)

## Background
1. Context and origin [here](https://docs.google.com/document/d/15xamKGTO2pC2HI9kjL8A9uQzOFK_Bd7FlXwfrCev0Bw/edit#) (BH24 CoPilot effort) and [here](https://github.com/zenitysec/research/tree/develop/scripts/other/puppeteer_get_substrate_bearer).
2. The main goal of this script is to be a POC for programatically getting the substrate token, which is used to interact with CoPilot via WS messages.
3. This is a Node.JS Puppeteer script that drives a **persistent visible Microsoft Edge profile**. Passwords are never passed on the command line.

## Prerequisites and basic functionality
1. [Install Node.JS & NPM](https://nodejs.org/en/download/package-manager) to be able to run the JS script.
2. Install [Microsoft Edge](https://www.microsoft.com/edge) (system browser; scripts locate common install paths, or set `COPILOT_CLI_EDGE_PATH`).
3. Install dependencies by running the following from within this directory:

    ```bash
    npm install
    ```

4. Auth uses a dedicated Edge user-data-dir:
   - Default: `~/.config/copilot-cli/msedge-profile`
   - Override: `export COPILOT_CLI_BROWSER_PROFILE=/path/to/profile`

5. Script execution:
   - Run one of:

      ```bash
      node get_substrate_bearer_teams.js user=<your_user>
      ```

        (uses teams.microsoft.com to get the token)

      ```bash
      node get_substrate_bearer_office.js user=<your_user>
      ```

        (opens **https://m365.cloud.microsoft/chat** and captures `access_token` from the Substrate WebSocket URL)

   - On first run, a visible Edge window opens. Sign in interactively (MFA/SSO supported). The session is stored in the profile directory for later runs.
   - **Token trigger (officeweb):** landing on the M365 home page is not enough. Copilot chat must load so the client opens `wss://substrate.../Chathub/...?access_token=...`. That query param is the bearer the CLI needs.
   - Optional: `debugMode=true` writes network/WS snippets to `network_log.txt` (do not commit).

   - If you see errors regarding missing resources in the node_modules directory when you first run the script, please run the following to clear NPM cache and reinstall dependencies:
     ```bash
     npm cache clean --force
     rm -rf node_modules
     npm install
     ```

   - You should get a print to the terminal of the substrate token (save it securely and delete the terminal output afterwards).

## FAQ
-   **Why do we want the substrate token?**

      We can use this token to interact with the CoPilot API directly and via CLI, scripts, etc.

-   **Why is Puppeteer and Node.JS used for this?**

      Puppeteer drives a real browser so login cookies, MFA, and JS-heavy Microsoft surfaces work. A persistent Edge profile avoids putting passwords on argv or in env.

-   **Why didn't we just use Python?**

      We wanted a POC for getting the substrate token, and JS + Puppeteer provided that more quickly because Teams & CoPilot have pretty busy mechanics which aren't straightforward with Python (headless browsers and JS handle sessions, state, JS rendering, async requests, redirections, etc. more out-of-the-box).

-   **Why didn't we use the [family-of-client-ids-research](https://github.com/secureworks/family-of-client-ids-research) to get the token?**

     Apparently, the substrate token is not in included in the family of tokens tokens documented by the FOCIS.

-   **How can I verify that I actually got the correct token after running the script?**
     Check the token via [jwt.io](jwt.io) and you should see that it has specific details related to the CoPilot token (TBD more info on this). BTW you're basically sending your CoPilot private token when you use this site, so keep that in mind :)

-  **How stable is this script?**

     Testing so far was predominantly successful, however, please note the following:
     1. This depends on the webpage/JS remaining similar; the user journey may need updates if Microsoft changes UI.
     2. Only one Edge process may use a given profile at a time (Chromium `SingletonLock`). Close other instances before re-running.
     3. Do not commit the profile directory, `token_output.txt`, or `network_log.txt`.

-  **What do I do if I encounter errors?**
     1. Confirm Edge is installed and `COPILOT_CLI_EDGE_PATH` points at it if auto-detect fails.
     2. Confirm the profile path is writable and not locked by another Edge process.
     3. Run headed (always visible here) and complete any login/MFA prompts in the window.

// Description: Open M365 Copilot chat in a persistent Edge profile and capture the Substrate bearer token.
// Trigger: loading https://m365.cloud.microsoft/chat causes the client to open
// wss://substrate.../Chathub/...?access_token=<jwt> — that query param is the token —
// and/or obtain a Bearer token scoped to M365Copilot.Read.All via /oauth2/v2.0/token.
// Passwords are never accepted: sign in once in the visible Edge window.

const puppeteer = require('puppeteer');
let Utils = require("./utils.js");
const { launchPersistentEdge } = require("./browser.js");
const fs = require('fs');

const ARGS = Utils.getArguments();
const USER = ARGS["user"];
const DEBUGMODE = ARGS["debugMode"];

const NETWORK_LOG_FILE = 'network_log.txt';
const LOGIN_WAIT_MS = 10 * 60 * 1000;
const TOKEN_WAIT_MS = 90 * 1000;
const COPILOT_CHAT_URL = 'https://m365.cloud.microsoft/chat';

if (DEBUGMODE === 'true') {
  fs.writeFileSync(NETWORK_LOG_FILE, '', { encoding: 'utf8' });
}

function delay(time) {
  return new Promise(resolve => setTimeout(resolve, time));
}

function logMessage(message) {
  console.error(message);
}

function isSubstrateChatUrl(url) {
  return (
    typeof url === 'string' &&
    (url.includes('substrate.office.com') ||
      url.includes('substrate.svc.cloud.microsoft') ||
      /\/m365Copilot\/Chat[Hh]ub\//i.test(url) ||
      /\/m365chat\/SecuredChat[Hh]ub\//i.test(url))
  );
}

function extractAccessTokenFromUrl(url) {
  if (!url || typeof url !== 'string') {
    return null;
  }
  if (!isSubstrateChatUrl(url) && !url.includes('access_token=')) {
    return null;
  }
  let match = url.match(/[?&]access_token=([^&]+)/);
  if (!match) {
    return null;
  }
  try {
    return decodeURIComponent(match[1]);
  } catch (_) {
    return match[1];
  }
}

function scopeIncludesM365Copilot(scope) {
  return String(scope || '').includes('M365Copilot.Read.All');
}

function looksLikeCopilotToken(token) {
  if (!token || typeof token !== 'string' || !token.includes('.')) {
    return false;
  }
  try {
    const payload = JSON.parse(Buffer.from(token.split('.')[1], 'base64url').toString('utf8'));
    return (
      scopeIncludesM365Copilot(payload.scp) ||
      scopeIncludesM365Copilot(payload.roles) ||
      scopeIncludesM365Copilot(payload.aud)
    );
  } catch (_) {
    return false;
  }
}

async function maybePrefillUsername(page, user) {
  try {
    await page.waitForSelector('#i0116', { timeout: 5000 });
    const current = await page.$eval('#i0116', el => el.value || '');
    if (!current) {
      await page.type('#i0116', user);
    }
    logMessage(`Username field present. Complete sign-in in the Edge window (MFA/SSO supported). User hint: ${user}`);
  } catch (_) {
    // Already signed in or a different login surface.
  }
}

async function waitUntilPastLogin(page, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const state = await page.evaluate(() => {
      if (document.querySelector('#i0118') || document.querySelector('#i0116')) {
        return 'login';
      }
      const host = location.hostname || '';
      if (host.includes('login.microsoftonline.com') || host.includes('login.live.com')) {
        return 'login';
      }
      if (host.includes('m365.cloud.microsoft') || host.includes('office.com') || host.includes('microsoft365.com')) {
        return 'app';
      }
      return 'pending';
    });
    if (state === 'app') {
      return true;
    }
    await delay(2000);
  }
  return false;
}

async function readCopilotTokenFromStorage(page) {
  return page.evaluate(() => {
    const SCOPE_MARKER = 'M365Copilot.Read.All';
    const scan = (storage) => {
      try {
        for (const key of Object.keys(storage)) {
          const value = storage.getItem(key);
          if (!value || !value.includes(SCOPE_MARKER)) {
            continue;
          }
          try {
            const data = JSON.parse(value);
            if (data && typeof data.secret === 'string') {
              return data.secret;
            }
            if (Array.isArray(data)) {
              for (const entry of data) {
                if (
                  entry &&
                  typeof entry.secret === 'string' &&
                  String(entry.scope || entry.scopes || '').includes(SCOPE_MARKER)
                ) {
                  return entry.secret;
                }
              }
            }
          } catch (_) {
            const match = value.match(/"secret"\s*:\s*"([^"]+)"/);
            if (match) {
              return match[1];
            }
          }
        }
      } catch (_) {
        // ignore
      }
      return null;
    };
    return scan(localStorage) || scan(sessionStorage);
  });
}

(async () => {
  const windowWidth = 1920;
  const windowHeight = 1080;
  let browser;
  let profileDir;

  try {
    ({ browser, profileDir } = await launchPersistentEdge({ windowWidth, windowHeight }));
  } catch (e) {
    console.error(e.message || e);
    process.exit(1);
  }

  const page = (await browser.pages())[0] || await browser.newPage();
  await page.setViewport({
    width: windowWidth,
    height: windowHeight
  });
  const timeout = 15000;
  page.setDefaultTimeout(timeout);

  let bearerToken = null;
  let tokenCapturedResolver;
  const tokenCapturedPromise = new Promise(resolve => {
    tokenCapturedResolver = resolve;
  });

  const acceptToken = (token, source, { alreadyValidated = false } = {}) => {
    if (!token || bearerToken) {
      return;
    }
    if (!alreadyValidated && !looksLikeCopilotToken(token)) {
      logMessage(`Ignoring unrelated token candidate from ${source}`);
      return;
    }
    bearerToken = token;
    logMessage(`Bearer token captured via ${source}.`);
    if (tokenCapturedResolver) {
      tokenCapturedResolver(bearerToken);
      tokenCapturedResolver = null;
    }
  };

  // Primary trigger: Copilot chat opens a Substrate WebSocket with access_token= in the URL.
  const client = await page.createCDPSession();
  await client.send('Network.enable');
  client.on('Network.webSocketCreated', ({ url }) => {
    if (DEBUGMODE === 'true') {
      fs.appendFileSync(NETWORK_LOG_FILE, `WS created: ${url}\n`, { encoding: 'utf8' });
    }
    const token = extractAccessTokenFromUrl(url);
    if (token) {
      acceptToken(token, 'websocket URL', { alreadyValidated: isSubstrateChatUrl(url) });
    }
  });
  client.on('Network.webSocketWillSendHandshakeRequest', ({ request }) => {
    const url = request && request.url;
    const token = extractAccessTokenFromUrl(url);
    if (token) {
      acceptToken(token, 'websocket handshake', { alreadyValidated: isSubstrateChatUrl(url) });
    }
  });

  // Secondary: MSAL /oauth2/v2.0/token responses scoped to M365Copilot.Read.All.
  page.on('response', async response => {
    try {
      const url = response.url();
      let text = '';
      try {
        text = await response.text();
      } catch (_) {
        return;
      }
      if (DEBUGMODE === 'true') {
        fs.appendFileSync(
          NETWORK_LOG_FILE,
          `URL: ${url}\nStatus: ${response.status()}\nSnippet: ${text.substring(0, 200)}\n--------------------------------\n`,
          { encoding: 'utf8' }
        );
      }
      if (url.includes('/oauth2/v2.0/token') && response.ok()) {
        let json;
        try {
          json = JSON.parse(text);
        } catch (_) {
          return;
        }
        const tokenType = json.token_type || json.tokenType;
        if (
          tokenType === 'Bearer' &&
          json.access_token &&
          scopeIncludesM365Copilot(json.scope || json.scopes)
        ) {
          acceptToken(json.access_token, 'oauth token response', { alreadyValidated: true });
        }
      }
    } catch (err) {
      console.error('Error capturing network response: ', err);
    }
  });

  logMessage(`Navigating to Copilot chat: ${COPILOT_CHAT_URL}`);
  logMessage(`Edge profile: ${profileDir}`);
  await page.goto(COPILOT_CHAT_URL, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await maybePrefillUsername(page, USER);

  if (await page.$('#i0116') || await page.$('#i0118') || (page.url() || '').includes('login.microsoftonline.com')) {
    logMessage(
      `Sign in in the Edge window if prompted (profile at ${profileDir}). MFA/SSO supported. Waiting up to ${LOGIN_WAIT_MS / 60000} minutes...`
    );
    const ok = await waitUntilPastLogin(page, LOGIN_WAIT_MS);
    if (!ok && !bearerToken) {
      logMessage('Login wait timed out or state unclear; continuing to watch for Substrate token...');
    } else if (ok) {
      logMessage('App session detected; waiting for Copilot chat to request Substrate token...');
      // Ensure we are on chat after SSO redirects.
      if (!(page.url() || '').includes('/chat')) {
        await page.goto(COPILOT_CHAT_URL, { waitUntil: 'domcontentloaded', timeout: 60000 });
      }
    }
  } else {
    logMessage('Existing Edge profile session detected; waiting for Substrate WebSocket...');
  }

  // Tertiary: poll MSAL/localStorage while chat boots.
  const storagePoll = (async () => {
    const deadline = Date.now() + TOKEN_WAIT_MS;
    while (!bearerToken && Date.now() < deadline) {
      try {
        const fromStorage = await readCopilotTokenFromStorage(page);
        if (fromStorage) {
          acceptToken(fromStorage, 'local/session storage');
          return;
        }
      } catch (_) {
        // page may be navigating
      }
      await delay(2000);
    }
  })();

  logMessage(
    'Token trigger: open Copilot chat so the page connects to substrate Chathub with access_token= in the WS URL. ' +
    'If chat does not load, open Chat manually in the Edge window.'
  );

  await Promise.race([
    tokenCapturedPromise,
    storagePoll.then(() => bearerToken),
    delay(TOKEN_WAIT_MS).then(() => null)
  ]);

  if (bearerToken) {
    fs.writeFileSync('token_output.txt', bearerToken, { encoding: 'utf8' });
    console.log('access_token:' + bearerToken);
    await browser.close();
    process.exit(0);
  }

  fs.writeFileSync('token_output.txt', 'No valid token captured from network responses.', { encoding: 'utf8' });
  console.error(
    'No Substrate token captured. Ensure Copilot chat loads at m365.cloud.microsoft/chat ' +
    '(not just the M365 home page). Debug with debugMode=true and inspect network_log.txt for WS URLs.'
  );
  console.log('access_token:null');
  await browser.close();
  process.exit(1);
})().catch(err => {
  console.error(err);
  process.exit(1);
});

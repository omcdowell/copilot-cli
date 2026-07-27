// Description: Open M365 Copilot chat in a persistent Edge profile and capture the Substrate bearer token.
// Trigger: loading https://m365.cloud.microsoft/chat causes the client to open
// wss://substrate.../Chathub/...?access_token=<opaque> — that query param is the token —
// and/or obtain a Bearer via MSAL for https://substrate.office.com/sydney/.default
// (same scope Teams uses) and/or M365Copilot.Read.All via /oauth2/v2.0/token.
// Access tokens must be treated as opaque (Microsoft identity platform); never require JWT shape.
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
/** Primary Substrate/Sydney API scope (also used by Teams capture). */
const SYDNEY_SCOPE = 'https://substrate.office.com/sydney/.default';
/** Alternate Graph-style scope seen on some M365 Copilot surfaces. */
const M365_COPILOT_SCOPE = 'M365Copilot.Read.All';

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

/** Chathub path is /.../Chathub/{oid}@{tid} — identity for WS URL rebuild without parsing the token. */
function extractIdentityFromSubstrateUrl(url) {
  if (!url || typeof url !== 'string') {
    return null;
  }
  const match = url.match(/\/(?:Chat[Hh]ub|SecuredChat[Hh]ub)\/([^@/?#]+)@([^/?#]+)/i);
  if (!match) {
    return null;
  }
  return { oid: match[1], tid: match[2] };
}

function isSubstrateBearerScope(scope) {
  const s = String(scope || '');
  return s.includes(SYDNEY_SCOPE) || s.includes(M365_COPILOT_SCOPE);
}

function scopePreference(scope) {
  const s = String(scope || '');
  if (s.includes(SYDNEY_SCOPE)) {
    return 2; // prefer Sydney over M365Copilot.Read.All
  }
  if (s.includes(M365_COPILOT_SCOPE)) {
    return 1;
  }
  return 0;
}

/** Best-effort claims from a JWT-shaped string only. Opaque tokens return null. */
function tryDecodeJwtPayload(token) {
  if (!token || typeof token !== 'string') {
    return null;
  }
  const parts = token.split('.');
  if (parts.length !== 3 || !parts[1]) {
    return null;
  }
  try {
    return JSON.parse(Buffer.from(parts[1], 'base64url').toString('utf8'));
  } catch (_) {
    return null;
  }
}

function identityFromHomeAccountId(homeAccountId) {
  if (!homeAccountId || typeof homeAccountId !== 'string') {
    return null;
  }
  // MSAL: "{oid}.{tid}" or "{oid}.{tid}-login.windows.net"
  const match = homeAccountId.match(/^([0-9a-fA-F-]{36})\.([0-9a-fA-F-]{36})/);
  if (!match) {
    return null;
  }
  return { oid: match[1], tid: match[2] };
}

function mergeIdentity(target, source) {
  if (!source) {
    return target;
  }
  if (source.oid && !target.oid) {
    target.oid = source.oid;
  }
  if (source.tid && !target.tid) {
    target.tid = source.tid;
  }
  if (source.user && !target.user) {
    target.user = source.user;
  }
  return target;
}

function identityFromJwtOrIdToken(token) {
  const payload = tryDecodeJwtPayload(token);
  if (!payload) {
    return null;
  }
  return {
    oid: payload.oid || null,
    tid: payload.tid || null,
    user: payload.upn || payload.unique_name || payload.preferred_username || null
  };
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
  return page.evaluate((sydneyScope, m365Scope) => {
    const identityFromHomeAccountId = (homeAccountId) => {
      if (!homeAccountId || typeof homeAccountId !== 'string') {
        return null;
      }
      const match = homeAccountId.match(/^([0-9a-fA-F-]{36})\.([0-9a-fA-F-]{36})/);
      if (!match) {
        return null;
      }
      return { oid: match[1], tid: match[2] };
    };
    const entryScope = (entry) =>
      String((entry && (entry.scope || entry.scopes || entry.target)) || '');
    const fromEntry = (entry, matchedScope) => {
      if (!entry || typeof entry.secret !== 'string') {
        return null;
      }
      const fromHome = identityFromHomeAccountId(entry.homeAccountId);
      return {
        token: entry.secret,
        oid: (fromHome && fromHome.oid) || null,
        tid: (fromHome && fromHome.tid) || entry.realm || null,
        user: entry.username || null,
        scope: matchedScope || entryScope(entry)
      };
    };
    const scopeRank = (scope) => {
      const s = String(scope || '');
      if (s.includes(sydneyScope)) {
        return 2;
      }
      if (s.includes(m365Scope)) {
        return 1;
      }
      return 0;
    };
    const consider = (candidate, best) => {
      if (!candidate || !candidate.token) {
        return best;
      }
      if (!best || scopeRank(candidate.scope) > scopeRank(best.scope)) {
        return candidate;
      }
      return best;
    };
    const scan = (storage) => {
      let best = null;
      try {
        for (const key of Object.keys(storage)) {
          const value = storage.getItem(key);
          if (!value) {
            continue;
          }
          const hasSydney = value.includes(sydneyScope);
          const hasM365 = value.includes(m365Scope);
          if (!hasSydney && !hasM365) {
            continue;
          }
          try {
            const data = JSON.parse(value);
            const single = fromEntry(data, hasSydney ? sydneyScope : m365Scope);
            best = consider(single, best);
            if (Array.isArray(data)) {
              for (const entry of data) {
                const scope = entryScope(entry);
                if (
                  entry &&
                  typeof entry.secret === 'string' &&
                  (scope.includes(sydneyScope) || scope.includes(m365Scope) || hasSydney || hasM365)
                ) {
                  best = consider(
                    fromEntry(
                      entry,
                      scope.includes(sydneyScope) || hasSydney ? sydneyScope : m365Scope
                    ),
                    best
                  );
                }
              }
            }
          } catch (_) {
            const match = value.match(/"secret"\s*:\s*"([^"]+)"/);
            if (match) {
              best = consider(
                {
                  token: match[1],
                  oid: null,
                  tid: null,
                  user: null,
                  scope: hasSydney ? sydneyScope : m365Scope
                },
                best
              );
            }
          }
        }
      } catch (_) {
        // ignore
      }
      return best;
    };
    return scan(localStorage) || scan(sessionStorage);
  }, SYDNEY_SCOPE, M365_COPILOT_SCOPE);
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
  let bearerPreference = 0; // 0=none, 1=M365Copilot, 2=Sydney scope, 3=Substrate WS URL
  const identity = { oid: null, tid: null, user: USER || null };
  let tokenCapturedResolver;
  const tokenCapturedPromise = new Promise(resolve => {
    tokenCapturedResolver = resolve;
  });

  const acceptToken = (token, source, { alreadyValidated = false, identityHint = null, preference = 1 } = {}) => {
    if (!token) {
      return;
    }
    if (bearerToken && preference <= bearerPreference) {
      return;
    }
    // Prefer non-token identity sources. Soft-decode JWT-shaped tokens only as a fallback
    // (access tokens are opaque per Microsoft identity platform guidance).
    mergeIdentity(identity, identityHint);
    const jwtPayload = tryDecodeJwtPayload(token);
    const jwtIdentity = jwtPayload
      ? {
          oid: jwtPayload.oid || null,
          tid: jwtPayload.tid || null,
          user: jwtPayload.upn || jwtPayload.unique_name || jwtPayload.preferred_username || null
        }
      : null;

    if (!alreadyValidated) {
      if (jwtPayload) {
        const scoped =
          isSubstrateBearerScope(jwtPayload.scp) ||
          isSubstrateBearerScope(jwtPayload.roles) ||
          isSubstrateBearerScope(jwtPayload.aud);
        if (!scoped && !identityHint) {
          logMessage(`Ignoring unrelated token candidate from ${source}`);
          return;
        }
        mergeIdentity(identity, jwtIdentity);
      } else if (!identityHint) {
        // Opaque token without an out-of-band identity/scope hint — do not guess.
        logMessage(`Ignoring opaque token candidate from ${source} (no identity/scope hint)`);
        return;
      }
    } else if (jwtIdentity) {
      mergeIdentity(identity, jwtIdentity);
    }
    const upgrading = Boolean(bearerToken);
    bearerToken = token;
    bearerPreference = preference;
    logMessage(`${upgrading ? 'Upgraded' : 'Captured'} bearer via ${source} (preference=${preference}).`);
    if (tokenCapturedResolver && preference >= 2) {
      // Resolve once we have Sydney or WS — don't finish early on weaker M365Copilot-only hits
      // while Sydney may still appear; still resolve so race can complete if wait ends.
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
      acceptToken(token, 'websocket URL', {
        alreadyValidated: isSubstrateChatUrl(url),
        identityHint: extractIdentityFromSubstrateUrl(url),
        preference: 3
      });
    }
  });
  client.on('Network.webSocketWillSendHandshakeRequest', ({ request }) => {
    const url = request && request.url;
    const token = extractAccessTokenFromUrl(url);
    if (token) {
      acceptToken(token, 'websocket handshake', {
        alreadyValidated: isSubstrateChatUrl(url),
        identityHint: extractIdentityFromSubstrateUrl(url),
        preference: 3
      });
    }
  });

  // Secondary: MSAL /oauth2/v2.0/token responses for Sydney or M365Copilot scopes.
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
        const responseScope = json.scope || json.scopes || '';
        if (
          tokenType === 'Bearer' &&
          json.access_token &&
          isSubstrateBearerScope(responseScope)
        ) {
          // Prefer Sydney scope when both could appear; ID tokens are for clients.
          acceptToken(json.access_token, `oauth token response (${responseScope})`, {
            alreadyValidated: true,
            identityHint: identityFromJwtOrIdToken(json.id_token),
            preference: scopePreference(responseScope)
          });
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

  // Tertiary: poll MSAL/localStorage while chat boots (prefer sydney/.default over M365Copilot.Read.All).
  const storagePoll = (async () => {
    const deadline = Date.now() + TOKEN_WAIT_MS;
    while (Date.now() < deadline) {
      if (bearerPreference >= 2) {
        return bearerToken;
      }
      try {
        const fromStorage = await readCopilotTokenFromStorage(page);
        if (fromStorage && fromStorage.token) {
          acceptToken(fromStorage.token, `local/session storage (${fromStorage.scope || 'unknown scope'})`, {
            alreadyValidated: true,
            identityHint: {
              oid: fromStorage.oid,
              tid: fromStorage.tid,
              user: fromStorage.user
            },
            preference: scopePreference(fromStorage.scope)
          });
          if (bearerPreference >= 2) {
            return bearerToken;
          }
        }
      } catch (_) {
        // page may be navigating
      }
      await delay(2000);
    }
    return bearerToken;
  })();

  logMessage(
    'Token trigger: open Copilot chat so the page connects to substrate Chathub with access_token= in the WS URL, ' +
    `or wait for MSAL cache entry for ${SYDNEY_SCOPE}. ` +
    'If chat does not load, open Chat manually in the Edge window.'
  );

  await Promise.race([
    tokenCapturedPromise,
    storagePoll,
    delay(TOKEN_WAIT_MS).then(() => null)
  ]);

  if (bearerToken) {
    fs.writeFileSync('token_output.txt', bearerToken, { encoding: 'utf8' });
    // stdout contract for Python parser — access token is opaque; identity is separate.
    console.log('access_token:' + bearerToken);
    if (identity.oid) {
      console.log('oid:' + identity.oid);
    }
    if (identity.tid) {
      console.log('tid:' + identity.tid);
    }
    if (identity.user) {
      console.log('user:' + identity.user);
    }
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

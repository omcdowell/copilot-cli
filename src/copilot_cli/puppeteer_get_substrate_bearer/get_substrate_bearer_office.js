// Description: Log into Microsoft Office (interactive Edge profile) and capture the Substrate bearer token.
// Passwords are never accepted: sign in once in the visible Edge window; the persistent profile reuses the session.

const puppeteer = require('puppeteer');
let Utils = require("./utils.js");
const { launchPersistentEdge } = require("./browser.js");
const fs = require('fs');

const ARGS = Utils.getArguments();
const USER = ARGS["user"];
const DEBUGMODE = ARGS["debugMode"];

const NETWORK_LOG_FILE = 'network_log.txt';
const LOGIN_WAIT_MS = 10 * 60 * 1000; // allow MFA / SSO

if (DEBUGMODE === 'true') {
  fs.writeFileSync(NETWORK_LOG_FILE, '', { encoding: 'utf8' });
}

function delay(time) {
  return new Promise(resolve => setTimeout(resolve, time));
}

function logMessage(message) {
  console.error(message);
}

async function maybePrefillUsername(page, user, timeout) {
  try {
    const usernameField = await page.waitForSelector('#i0116', { timeout: 5000 });
    if (usernameField) {
      const current = await page.$eval('#i0116', el => el.value || '');
      if (!current) {
        await page.type('#i0116', user);
      }
      logMessage(`Username field present. Complete sign-in in the Edge window (MFA/SSO supported). User hint: ${user}`);
    }
  } catch (_) {
    // Already signed in or a different login surface — continue.
  }
}

async function waitUntilSignedInOrTimeout(page, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    // Office account button after login, or absence of password field after navigation.
    const signedIn = await page.evaluate(() => {
      if (document.querySelector('#mectrl_headerPicture')) {
        const aria = document.querySelector('#mectrl_headerPicture')?.getAttribute('aria-label') || '';
        // Signed-in control usually includes the account name; guest shows "Sign in".
        if (aria && !/sign in/i.test(aria)) {
          return true;
        }
      }
      // Password field still visible => still on login flow.
      if (document.querySelector('#i0118')) {
        return false;
      }
      // Username field still the focus of login.
      if (document.querySelector('#i0116')) {
        return false;
      }
      return false;
    });
    if (signedIn) {
      return true;
    }
    await delay(2000);
  }
  return false;
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

  const [page] = await browser.pages();
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

  const tokenResponseHandler = async response => {
    try {
      const url = response.url();
      const status = response.status();
      let text = '';
      try {
        text = await response.text();
      } catch (e) {
        text = 'Could not read response body.';
      }

      if (DEBUGMODE === 'true') {
        const logEntry = `URL: ${url}\nStatus: ${status}\nResponse Snippet: ${text.substring(0,200)}\n--------------------------------\n`;
        fs.appendFileSync(NETWORK_LOG_FILE, logEntry, { encoding: 'utf8' });
      }

      if (
        url.includes("/oauth2/v2.0/token") &&
        (text.includes('"token_type":"Bearer"') || text.includes('"tokenType":"Bearer"')) &&
        text.includes("sydney")
      ) {
        let json;
        try {
          json = JSON.parse(text);
        } catch (e) {
          // Fallback regex below.
        }
        if (json && json.access_token) {
          bearerToken = json.access_token;
          logMessage("Bearer token captured from network response.");
          page.off('response', tokenResponseHandler);
          if (tokenCapturedResolver) {
            tokenCapturedResolver(bearerToken);
            tokenCapturedResolver = null;
          }
        } else {
          const match = text.match(/"access_token"\s*:\s*"([^"]+)"/);
          if (match && match[1]) {
            bearerToken = match[1];
            logMessage("Bearer token captured from network response (regex).");
            page.off('response', tokenResponseHandler);
            if (tokenCapturedResolver) {
              tokenCapturedResolver(bearerToken);
              tokenCapturedResolver = null;
            }
          }
        }
      }
    } catch (err) {
      console.error("Error capturing network response: ", err);
    }
  };

  page.on('response', tokenResponseHandler);

  await page.goto('https://www.office.com/');

  await maybePrefillUsername(page, USER, timeout);

  // If already signed in, the account picture is present quickly.
  let needsInteractiveLogin = false;
  try {
    await page.waitForSelector('#mectrl_headerPicture', { timeout: 10000 });
    const label = await page.$eval('#mectrl_headerPicture', el => el.getAttribute('aria-label') || '');
    if (/sign in/i.test(label)) {
      needsInteractiveLogin = true;
      await page.click('#mectrl_headerPicture');
      await maybePrefillUsername(page, USER, timeout);
    }
  } catch (_) {
    needsInteractiveLogin = true;
  }

  if (needsInteractiveLogin || await page.$('#i0116') || await page.$('#i0118')) {
    logMessage(
      `Sign in in the Edge window (profile at ${profileDir}). MFA/SSO supported. Waiting up to ${LOGIN_WAIT_MS / 60000} minutes...`
    );
    const ok = await waitUntilSignedInOrTimeout(page, LOGIN_WAIT_MS);
    if (!ok && !bearerToken) {
      // Soft continue: Copilot journey may still trigger token capture after partial SSO.
      logMessage("Login wait timed out or state unclear; continuing to Copilot journey...");
    } else if (ok) {
      logMessage("Signed-in session detected.");
    }
  } else {
    logMessage("Existing Edge profile session detected.");
  }

  await delay(3000);

  logMessage("Starting user journey to get the Pacman token");

  try {
    const targetPage = page;
    await puppeteer.Locator.race([
      targetPage.locator('#d870f6cd-4aa5-4d42-9626-ab690c041429'),
    ])
      .setTimeout(timeout)
      .click();
  } catch (e) {
    logMessage("Could not click Copilot entry automatically; open Copilot in the Edge window if needed.");
  }
  await delay(10000);

  logMessage("Waiting for Pacman token from network responses");

  await Promise.race([
    tokenCapturedPromise,
    delay(60000).then(() => null)
  ]);

  if (bearerToken) {
    fs.writeFileSync('token_output.txt', bearerToken, { encoding: 'utf8' });
    // stdout contract for Python parser — keep this format.
    console.log('access_token:' + bearerToken);
    await browser.close();
    process.exit(0);
  } else {
    fs.writeFileSync('token_output.txt', 'No valid token captured from network responses.', { encoding: 'utf8' });
    console.error('No valid token captured from network responses.');
    console.log('access_token:null');
    await browser.close();
    process.exit(1);
  }
})().catch(async err => {
  console.error(err);
  process.exit(1);
});

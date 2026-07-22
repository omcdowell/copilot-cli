// Description: Log into Microsoft Teams (interactive Edge profile) and retrieve the Substrate bearer token.
// Passwords are never accepted: sign in once in the visible Edge window; the persistent profile reuses the session.

const puppeteer = require('puppeteer');
let Utils = require("./utils.js");
const { launchPersistentEdge } = require("./browser.js");

const ARGS = Utils.getArguments();
const USER = ARGS["user"];

const LOGIN_WAIT_MS = 10 * 60 * 1000;

function delay(time) {
    return new Promise(function (resolve) {
        setTimeout(resolve, time);
    });
}

function logMessage(message) {
    console.error(message);
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
        // Already signed in or different login surface.
    }
}

async function waitForTeamsSession(page, timeoutMs) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
        const state = await page.evaluate(() => {
            if (document.querySelector('#i0118') || document.querySelector('#i0116')) {
                return 'login';
            }
            // Teams shell / chat list indicators once past login.
            if (
                document.querySelector('#title-chat-list-item_bizChatMetaOSChatListEntryPoint') ||
                document.querySelector('[data-tid="app-layout-area--main"]') ||
                document.querySelector('#app') ||
                document.body?.innerText?.includes('Copilot')
            ) {
                return 'ready';
            }
            return 'pending';
        });
        if (state === 'ready') {
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

    await page.goto('https://teams.microsoft.com/_');
    logMessage("Starting the login process (persistent Edge profile)");

    await maybePrefillUsername(page, USER);

    if (await page.$('#i0116') || await page.$('#i0118')) {
        logMessage(
            `Sign in in the Edge window (profile at ${profileDir}). MFA/SSO supported. Waiting up to ${LOGIN_WAIT_MS / 60000} minutes...`
        );
        const ok = await waitForTeamsSession(page, LOGIN_WAIT_MS);
        if (!ok) {
            logMessage("Login wait timed out or state unclear; continuing to Copilot journey...");
        } else {
            logMessage("Teams session detected.");
        }
    } else {
        logMessage("Existing Edge profile session detected (or login UI not shown).");
        await waitForTeamsSession(page, 30000);
    }

    await delay(5000);
    logMessage("Starting user journey to CoPilot");

    try {
        const targetPage = page;
        const promises = [];
        const startWaitingForEvents = () => {
            promises.push(targetPage.waitForNavigation());
        };
        await puppeteer.Locator.race([
            targetPage.locator('::-p-aria([role=\\"dialog\\"]) >>>> ::-p-aria(Switch now)'),
            targetPage.locator('#ngdialog1 button'),
            targetPage.locator('::-p-xpath(//*[@id=\\"ngdialog1\\"]/div[2]/div/div/div/div[2]/div/div/button)'),
            targetPage.locator(':scope >>> #ngdialog1 button')
        ])
            .setTimeout(timeout)
            .on('action', () => startWaitingForEvents())
            .click({
                offset: {
                    x: 98,
                    y: 11.33331298828125,
                },
            });
        await Promise.all(promises);
    } catch (_) {
        logMessage("No Teams 'Switch now' dialog (ok if already on new Teams).");
    }

    await delay(5000);

    try {
        const targetPage = page;
        await puppeteer.Locator.race([
            targetPage.locator('::-p-aria(Copilot)'),
            targetPage.locator('#title-chat-list-item_bizChatMetaOSChatListEntryPoint'),
            targetPage.locator('::-p-xpath(//*[@id=\\"title-chat-list-item_bizChatMetaOSChatListEntryPoint\\"])'),
            targetPage.locator(':scope >>> #title-chat-list-item_bizChatMetaOSChatListEntryPoint')
        ])
            .setTimeout(timeout)
            .click({
                offset: {
                    x: 25.333328247070312,
                    y: 10.333328247070312,
                },
            });
    } catch (e) {
        logMessage("Could not click Copilot entry automatically; open Copilot in the Edge window if needed.");
    }

    logMessage("Completed user journey, grabbing substrate token from local storage");

    await delay(10000);

    const captured = await page.evaluate(() => {
        const key = Object.keys(localStorage).find(k => {
            const value = localStorage.getItem(k);
            return value && value.includes('https://substrate.office.com/sydney/.default');
        });

        if (!key) {
            return null;
        }
        const data = JSON.parse(localStorage.getItem(key));
        if (!data || typeof data.secret !== 'string') {
            return null;
        }
        let oid = null;
        let tid = data.realm || null;
        const homeAccountId = data.homeAccountId;
        if (typeof homeAccountId === 'string') {
            const match = homeAccountId.match(/^([0-9a-fA-F-]{36})\.([0-9a-fA-F-]{36})/);
            if (match) {
                oid = match[1];
                tid = tid || match[2];
            }
        }
        return {
            token: data.secret,
            oid,
            tid,
            user: data.username || null
        };
    });

    // stdout contract for Python parser — access token is opaque; identity is separate.
    const secretValue = captured && captured.token ? captured.token : null;
    console.log('access_token:%s', secretValue);
    if (captured && captured.oid) {
        console.log('oid:%s', captured.oid);
    }
    if (captured && captured.tid) {
        console.log('tid:%s', captured.tid);
    }
    if (captured && captured.user) {
        console.log('user:%s', captured.user);
    } else if (USER) {
        console.log('user:%s', USER);
    }

    await browser.close();

    if (!secretValue) {
        process.exit(1);
    }
})().catch(err => {
    console.error(err);
    process.exit(1);
});

const fs = require('fs');
const os = require('os');
const path = require('path');
const puppeteer = require('puppeteer');

const DEFAULT_PROFILE_DIR = path.join(os.homedir(), '.config', 'copilot-cli', 'msedge-profile');

const EDGE_CANDIDATES = [
    process.env.COPILOT_CLI_EDGE_PATH,
    // Linux
    '/usr/bin/microsoft-edge',
    '/usr/bin/microsoft-edge-stable',
    '/usr/bin/microsoft-edge-beta',
    '/usr/bin/microsoft-edge-dev',
    '/opt/microsoft/msedge/msedge',
    // macOS
    '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
    '/Applications/Microsoft Edge Beta.app/Contents/MacOS/Microsoft Edge Beta',
    '/Applications/Microsoft Edge Dev.app/Contents/MacOS/Microsoft Edge Dev',
    // Windows
    'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
    'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
].filter(Boolean);

function resolveProfileDir() {
    const profileDir = process.env.COPILOT_CLI_BROWSER_PROFILE || DEFAULT_PROFILE_DIR;
    fs.mkdirSync(profileDir, { recursive: true, mode: 0o700 });
    try {
        fs.chmodSync(profileDir, 0o700);
    } catch (_) {
        // Best-effort on platforms that ignore mode bits.
    }
    return profileDir;
}

function resolveEdgeExecutable() {
    for (const candidate of EDGE_CANDIDATES) {
        try {
            if (candidate && fs.existsSync(candidate)) {
                return candidate;
            }
        } catch (_) {
            // continue
        }
    }
    return null;
}

function assertProfileNotLocked(profileDir) {
    const lockPath = path.join(profileDir, 'SingletonLock');
    if (!fs.existsSync(lockPath)) {
        return;
    }
    let target = '';
    try {
        target = fs.readlinkSync(lockPath);
    } catch (_) {
        target = '(unreadable)';
    }
    throw new Error(
        `Edge profile is locked (SingletonLock -> ${target}). ` +
        `Close other Edge/Puppeteer instances using "${profileDir}", ` +
        `or remove SingletonLock only after confirming no process still holds the profile.`
    );
}

/**
 * Launch a visible Microsoft Edge instance with a persistent user-data-dir.
 * Session cookies survive across runs so passwords never need to be passed in.
 */
async function launchPersistentEdge(options = {}) {
    const profileDir = resolveProfileDir();
    const edgePath = resolveEdgeExecutable();
    if (!edgePath) {
        throw new Error(
            'Microsoft Edge was not found. Install Edge, or set COPILOT_CLI_EDGE_PATH to the msedge/microsoft-edge binary.'
        );
    }
    assertProfileNotLocked(profileDir);

    const windowWidth = options.windowWidth || 1920;
    const windowHeight = options.windowHeight || 1080;

    console.error(`Using Edge profile: ${profileDir}`);
    console.error(`Using Edge binary: ${edgePath}`);

    try {
        const browser = await puppeteer.launch({
            headless: false,
            executablePath: edgePath,
            userDataDir: profileDir,
            defaultViewport: null,
            args: [`--window-size=${windowWidth},${windowHeight}`],
        });
        return { browser, profileDir, edgePath };
    } catch (err) {
        const message = err && err.message ? err.message : String(err);
        if (/Singleton|profile|user data dir|already in use/i.test(message)) {
            throw new Error(
                `Failed to launch Edge with profile "${profileDir}": ${message}. ` +
                `Close other Edge instances using this profile and retry.`
            );
        }
        throw err;
    }
}

module.exports = {
    DEFAULT_PROFILE_DIR,
    launchPersistentEdge,
    resolveProfileDir,
    resolveEdgeExecutable,
};

// The slow acceptance spec (Task 24, design 15.3): for each of the 6 looks, export the sample through the studio's real
// Export button, then compare the studio stage with the export frame at three instants (ffmpeg SSIM >= 0.95, 540x960).
// Each export is a real render (about 2 to 7 min on a shared PC), so this is NOT part of `npx playwright test`. Run it with
//
//     npm run test:match            (or: npx playwright test -c playwright.match.config.js)
//
// It needs the installed renderer (~/.floored/renderer, or FLOORED_RENDERER_DIR) and ffmpeg on PATH. It starts its own
// server on 127.0.0.1:3196 over a throw-away workspace and FLOORED_HOME, so the real ~/.floored (prefs, machine.json)
// is never touched. Output (studio frames, export frames, the exports, match-results.json) goes to FT_MATCH_OUT, default
// <tmp>/ft-match-<stamp>/out. Set FT_MATCH_LOOKS=original,tape to try some looks only.
const { defineConfig } = require('@playwright/test');
const fs = require('fs');
const os = require('os');
const path = require('path');

const PORT = 3196;
const ROOT = __dirname;
if (!process.env.FT_MATCH_RUN) process.env.FT_MATCH_RUN = fs.mkdtempSync(path.join(os.tmpdir(), 'ft-match-'));
const RUN = process.env.FT_MATCH_RUN;
const WORKSPACE = path.join(RUN, 'workspace');
const HOME = path.join(RUN, 'home');
if (!process.env.FT_MATCH_OUT) process.env.FT_MATCH_OUT = path.join(RUN, 'out');
fs.mkdirSync(WORKSPACE, { recursive: true });
fs.mkdirSync(HOME, { recursive: true });
fs.mkdirSync(process.env.FT_MATCH_OUT, { recursive: true });
process.env.FT_MATCH_WORKSPACE = WORKSPACE;

function pythonPath() {
  const venv = process.platform === 'win32'
    ? path.join(ROOT, '.venv', 'Scripts', 'python.exe')
    : path.join(ROOT, '.venv', 'bin', 'python');
  return fs.existsSync(venv) ? venv : (process.platform === 'win32' ? 'python' : 'python3');
}
const SERVER = path.join(ROOT, 'plugin', 'skills', 'floored', 'app', 'floored.py');
const RENDERER = process.env.FLOORED_RENDERER_DIR || path.join(os.homedir(), '.floored', 'renderer');

module.exports = defineConfig({
  testDir: path.join(ROOT, 'tests', 'ui'),
  testMatch: /match\.spec\.js$/,
  timeout: 30 * 60 * 1000,                    // one look = one real render
  expect: { timeout: 20000 },
  workers: 1,
  fullyParallel: false,
  reporter: [['list']],
  outputDir: path.join(RUN, 'results'),
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    channel: process.platform === 'win32' ? 'msedge' : 'chrome',
    viewport: { width: 1600, height: 1100 },   // room for the 540x960 stage the spec pins (at device scale 2)
    trace: 'off',
  },
  webServer: {
    command: `"${pythonPath()}" "${SERVER}" serve --workspace "${WORKSPACE}" --port ${PORT}`,
    url: `http://127.0.0.1:${PORT}/`,
    reuseExistingServer: false,
    timeout: 60000,
    env: Object.assign({}, process.env, { FLOORED_HOME: HOME, FLOORED_RENDERER_DIR: RENDERER, PYTHONUTF8: '1' }),
  },
});

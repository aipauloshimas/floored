// Studio smoke tests (Task 14). `npx playwright test` starts its own server on 127.0.0.1:3199 with a throw-away workspace
// and a throw-away FLOORED_HOME, so the real ~/.floored is never touched. We drive the browser that is installed
// (Edge on Windows, Chrome elsewhere): there is no `npx playwright install` step.
const { defineConfig } = require('@playwright/test');
const fs = require('fs');
const os = require('os');
const path = require('path');

const PORT = 3199;
const ROOT = __dirname;

// One scratch folder per `npx playwright test` run: the main process makes it, the workers inherit it through the env.
if (!process.env.FT_UI_RUN) process.env.FT_UI_RUN = fs.mkdtempSync(path.join(os.tmpdir(), 'ft-ui-'));
const RUN = process.env.FT_UI_RUN;
const WORKSPACE = path.join(RUN, 'workspace');
const HOME = path.join(RUN, 'home');
fs.mkdirSync(WORKSPACE, { recursive: true });
fs.mkdirSync(HOME, { recursive: true });

function pythonPath() {
  const venv = process.platform === 'win32'
    ? path.join(ROOT, '.venv', 'Scripts', 'python.exe')
    : path.join(ROOT, '.venv', 'bin', 'python');
  return fs.existsSync(venv) ? venv : (process.platform === 'win32' ? 'python' : 'python3');
}
const SERVER = path.join(ROOT, 'plugin', 'skills', 'floored', 'app', 'floored.py');

module.exports = defineConfig({
  testDir: path.join(ROOT, 'tests', 'ui'),
  testIgnore: /match\.spec\.js$/,            // slow (real renders): `npm run test:match` (playwright.match.config.js)
  globalSetup: path.join(ROOT, 'tests', 'ui', 'global-setup.js'),
  timeout: 90000,
  expect: { timeout: 20000 },
  workers: 1,
  retries: process.env.CI ? 1 : 0,             // GitHub's runners: one retry for a slow first page load
  fullyParallel: false,
  reporter: [['list']],
  outputDir: path.join(RUN, 'results'),
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,       // the server only answers Host 127.0.0.1:<port> or localhost:<port>
    channel: process.platform === 'win32' ? 'msedge' : 'chrome',
    viewport: { width: 1280, height: 860 },
    trace: 'off',
  },
  webServer: {
    command: `"${pythonPath()}" "${SERVER}" serve --workspace "${WORKSPACE}" --port ${PORT}`,
    url: `http://127.0.0.1:${PORT}/`,
    reuseExistingServer: false,
    timeout: 60000,
    env: Object.assign({}, process.env, { FT_FAKE_MATTE: '1', FLOORED_HOME: HOME, PYTHONUTF8: '1' }),
  },
});

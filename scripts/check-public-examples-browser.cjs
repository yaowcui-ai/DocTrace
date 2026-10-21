// Read-only acceptance against the running local service; no login or model calls.
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const assert = require('node:assert/strict');
const { chromium } = require(path.join(os.tmpdir(), 'doctrace-browser-check/node_modules/playwright-core'));
const root = path.resolve(__dirname, '..');
const report = {kind: 'public_examples_browser_acceptance', checks: [], status: 'started'};
let browser;
const check = (ok, label) => {assert.ok(ok, label); report.checks.push(label);};
(async () => {
  try {
    browser = await chromium.launch({channel: 'msedge', headless: true});
    const context = await browser.newContext();
    const page = await context.newPage();
    const errors = [];
    const prohibited = [];
    page.on('pageerror', error => errors.push(error.message));
    await context.route('**/*', route => {
      const request = route.request();
      const url = new URL(request.url());
      if (url.origin !== 'http://127.0.0.1:8001' || !['GET', 'HEAD'].includes(request.method())) {
        prohibited.push(request.method() + ' ' + url.pathname);
        return route.abort();
      }
      return route.continue();
    });
    await page.goto('http://127.0.0.1:8001/');
    await page.locator('#public-examples-list button').first().waitFor();
    await page.locator('#login-form:not([hidden])').waitFor();
    check(await page.locator('#submit-question').isDisabled(), 'anonymous private composer disabled');
    check(await page.locator('#public-examples-section').isVisible(), 'public examples visible anonymously');
    await page.locator('#public-examples-list button').first().click();
    await page.locator('#public-example-detail:not([hidden])').waitFor();
    check((await page.locator('#public-example-question').innerText()).includes('试用期'), 'published example detail loaded');
    check((await page.locator('#public-example-answer').innerText()).length > 50, 'saved answer rendered');
    await page.locator('#public-example-answer .citation-button').first().click();
    check(await page.locator('#public-example-references details').first().evaluate(el => el.open), 'citation opens public evidence');
    check((await page.locator('#public-example-references').innerText()).includes('CC BY-SA'), 'public evidence retains attribution');
    const privateStatus = await page.evaluate(async () => (await fetch('/records', {credentials: 'omit'})).status);
    check(privateStatus === 401, 'anonymous private history remains protected');
    for (const width of [1280, 390]) {
      await page.setViewportSize({width, height: 900});
      check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `no horizontal overflow at ${width}px`);
    }
    check(errors.length === 0, 'no browser JavaScript errors');
    check(prohibited.length === 0, 'only local read requests observed');
    report.status = 'passed';
  } catch (error) {
    report.status = 'failed';
    report.error = error.message;
    process.exitCode = 1;
  } finally {
    if (browser) await browser.close();
    const filename = new Date().toISOString().replace(/[-:.]/g, '') + '_public_examples_browser.json';
    const target = path.join(root, 'evaluation/runs', filename);
    fs.writeFileSync(target, JSON.stringify(report, null, 2));
    console.log(`Status: ${report.status} Checks: ${report.checks.length}\nReport: ${target}`);
    if (report.error) console.log(report.error);
  }
})();

import {defineConfig} from '@playwright/test';

export default defineConfig({
  testDir: './tests/browser',
  timeout: 45_000,
  expect: {timeout: 10_000},
  workers: 1,
  retries: 0,
  use: {
    baseURL: process.env.DOCTRACE_E2E_BASE_URL ?? 'http://127.0.0.1:8769',
    browserName: 'chromium',
    headless: true,
    viewport: {width: 1440, height: 1000},
    screenshot: 'only-on-failure',
    trace: 'off',
  },
});

import {test, expect} from '@playwright/test';
import type {Page} from '@playwright/test';

// These are public test-only fixture credentials. The server fixture creates its
// own temporary database and replaces the provider, not authentication or APIs.
const password = process.env.DOCTRACE_E2E_PASSWORD ?? 'FixturePass123!';
async function login(page: Page, username: string) {
  await page.getByLabel('用户名', {exact: true}).fill(username);
  await page.getByLabel('密码', {exact: true}).fill(password);
  await page.getByRole('button', {name: '登录', exact: true}).click();
  await expect(page.getByText(`已登录 ${username}`, {exact: false})).toBeVisible();
}

test('real cookie auth, conversations, citations, feedback, lost-response retry and administrator routes', async ({page}) => {
  const browserErrors: string[] = [];
  page.on('pageerror', error => browserErrors.push(error.message));
  await page.goto('/workspace/');
  await expect(page.getByLabel('用户名', {exact: true})).toBeVisible();
  await expect(page.getByRole('button', {name: '发送问题 →'})).toBeDisabled();
  await login(page, process.env.DOCTRACE_E2E_USERNAME ?? 'alice');
  await expect(page.getByRole('button', {name: '知识库与实验报告', exact: true})).toHaveCount(0);
  await page.getByRole('button', {name: '导入旧问答', exact: true}).click();
  await expect(page.getByText('旧问答已导入。重复导入不会创建重复会话。', {exact: true})).toBeVisible();
  await expect(page.locator('.history-list')).toContainText('alice legacy policy question');
  await page.getByLabel('搜索个人会话', {exact: true}).fill('no-such-fixture-conversation');
  await expect(page.getByText('还没有匹配的会话。', {exact: true})).toBeVisible();
  await page.getByLabel('搜索个人会话', {exact: true}).fill('');
  await expect(page.locator('.history-list')).toContainText('alice legacy policy question');
  await page.getByRole('button', {name: '＋ 新建会话', exact: true}).click();
  await expect(page.getByLabel('想了解哪项政策？')).toBeEnabled();
  expect(await page.getByLabel('检索模式', {exact: true}).inputValue()).toBe('naive');
  expect(await page.getByLabel('知识库', {exact: true}).inputValue()).toBe('frozen');
  const sent: {key: string | undefined; question: string; mode: string; knowledgeBase: string; url: string}[] = [];
  page.on('request', request => {
    if (request.method() === 'POST' && /\/api\/v1\/conversations\/[^/]+\/messages$/.test(request.url())) {
      const body = request.postDataJSON(); sent.push({key: request.headers()['idempotency-key'], question: body.question, mode: body.mode, knowledgeBase: body.knowledge_base, url: request.url()});
    }
  });
  await page.getByLabel('想了解哪项政策？').fill('What is the fixture policy?');
  await page.getByRole('button', {name: '发送问题 →'}).click();
  await expect(page.getByText('Offline policy answer [1]', {exact: true})).toBeVisible();
  expect(sent[0].mode).toBe('naive');
  expect(sent[0].knowledgeBase).toBe('frozen');
  await page.getByRole('button', {name: '[1] policy.md', exact: true}).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await expect(page.getByRole('dialog').locator('pre')).toContainText('Fixture policy evidence');
  await page.getByRole('button', {name: '关闭', exact: true}).click();
  await page.getByText('这条回答有帮助吗？', {exact: true}).click();
  await page.getByLabel('补充意见（可选）').fill('Evidence was useful.');
  const feedback = page.waitForResponse(response => response.url().includes('/feedback') && response.request().method() === 'PUT');
  await page.getByRole('button', {name: '有帮助', exact: true}).click();
  expect((await feedback).ok()).toBeTruthy();
  await expect(page.getByText('反馈已保存。', {exact: true})).toBeVisible();
  await page.reload();
  await expect(page.getByText('Offline policy answer [1]', {exact: true})).toBeVisible();
  await page.getByText('这条回答有帮助吗？', {exact: true}).click();
  await expect(page.getByLabel('补充意见（可选）')).toHaveValue('Evidence was useful.');
  await expect(page.getByRole('button', {name: '有帮助', exact: true})).toHaveAttribute('aria-pressed', 'true');
  await page.getByLabel('想了解哪项政策？').fill('Unsent private draft');
  await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')));
  await expect(page.getByLabel('想了解哪项政策？')).toHaveValue('Unsent private draft');
  await expect(page.getByRole('link', {name: '旧版工作台 ↗'})).toHaveAttribute('href', '/');

  // Drop a real, successfully persisted HTTP response. Manual retry must reuse
  // its operation key and recover the same record without another generation.
  let dropped = false;
  await page.route('**/api/v1/conversations/*/messages', async route => {
    if (!dropped && route.request().method() === 'POST') {
      dropped = true;
      const result = await route.fetch();
      expect(result.ok()).toBeTruthy();
      await route.abort('failed');
    } else await route.continue();
  });
  await page.getByLabel('检索模式', {exact: true}).selectOption('mix');
  await page.getByLabel('想了解哪项政策？').fill('Recover this fixture operation.');
  await page.getByRole('button', {name: '发送问题 →'}).click();
  await expect(page.getByRole('button', {name: '使用原操作重试', exact: true})).toBeEnabled();
  const lostOperation = sent[sent.length - 1];
  const beforeRefresh = sent.length;
  await page.reload();
  await expect(page.getByRole('button', {name: '使用原操作重试', exact: true})).toBeVisible();
  expect(sent.length).toBe(beforeRefresh);
  await page.getByRole('button', {name: '使用原操作重试', exact: true}).click();
  await expect(page.getByRole('button', {name: '使用原操作重试', exact: true})).toHaveCount(0);
  expect(sent[sent.length - 1].key).toBe(lostOperation.key);
  expect(sent[sent.length - 1].mode).toBe('mix');
  expect(sent[sent.length - 1].knowledgeBase).toBe('frozen');
  const conversationUrl = new URL(lostOperation.url).pathname.replace(/\/messages$/, '');
  const detail = await page.request.get(conversationUrl);
  expect(detail.ok()).toBeTruthy();
  const stored = (await detail.json()).data;
  expect(stored.messages.filter((message: {question: string}) => message.question === lostOperation.question)).toHaveLength(1);
  await page.screenshot({path: 'test-results/actual-workspace.png', fullPage: true});
  await page.setViewportSize({width: 390, height: 844});
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.screenshot({path: 'test-results/actual-workspace-mobile.png', fullPage: true});
  await page.setViewportSize({width: 1440, height: 1000});

  const adminDenied = await page.request.get('/api/v1/admin/reports');
  expect(adminDenied.status()).toBe(403);
  await page.getByRole('button', {name: '退出登录', exact: true}).click();
  await expect(page.getByLabel('用户名', {exact: true})).toBeVisible();
  await expect(page.getByText('Offline policy answer [1]', {exact: true})).toHaveCount(0);
  await login(page, 'admin');
  const foreign = await page.request.get(conversationUrl);
  expect([403, 404]).toContain(foreign.status());
  await page.getByRole('button', {name: '知识库与实验报告', exact: true}).click();
  await expect(page.getByRole('heading', {name: '知识库与实验报告', exact: true})).toBeVisible();
  await expect(page.getByRole('heading', {name: '请求运行统计', exact: true})).toBeVisible();
  const reports = await page.request.get('/api/v1/admin/reports');
  expect(reports.ok()).toBeTruthy();
  expect(Array.isArray((await reports.json()).data.items)).toBeTruthy();
  await page.getByLabel('上传政策文档', {exact: true}).setInputFiles({name: 'unsupported.pdf', mimeType: 'application/pdf', buffer: Buffer.from('not a supported document')});
  await page.getByRole('button', {name: '提交文档', exact: true}).click();
  await expect(page.getByRole('alert')).toContainText('当前仅支持 UTF-8');
  await page.getByLabel('上传政策文档', {exact: true}).setInputFiles({name: 'browser-fixture.md', mimeType: 'text/markdown', buffer: Buffer.from('# Browser fixture\nOffline upload policy.')});
  const upload = page.waitForResponse(response => response.url().endsWith('/api/v1/admin/documents') && response.request().method() === 'POST');
  await page.getByRole('button', {name: '提交文档', exact: true}).click();
  expect((await upload).ok()).toBeTruthy();
  await expect(page.getByText('文档已保存，尚未完成索引。', {exact: false})).toBeVisible();
  await expect(page.locator('.admin-list')).toContainText('browser-fixture.md');
  await page.getByRole('button', {name: '提交索引', exact: true}).click();
  await expect(page.getByText('索引任务已进入队列。', {exact: false})).toBeVisible();
  await expect(page.locator('.admin-list')).toContainText('queued');
  await expect(page.getByRole('heading', {name: '只读实验报告', exact: true})).toBeVisible();
  await page.screenshot({path: 'test-results/actual-admin.png', fullPage: true});
  expect(browserErrors).toEqual([]);
});

test('late responses cannot cross accounts; an expired session clears rendered private data', async ({page}) => {
  await page.goto('/workspace/');
  await login(page, 'alice');
  await page.getByRole('button', {name: '＋ 新建会话', exact: true}).click();
  await expect(page.getByLabel('想了解哪项政策？')).toBeEnabled();
  const createdMessage = page.waitForResponse(response => /\/conversations\/[^/]+\/messages$/.test(response.url()) && response.request().method() === 'POST');
  await page.getByLabel('想了解哪项政策？').fill('Private alice delayed response question');
  await page.getByRole('button', {name: '发送问题 →'}).click();
  const response = await createdMessage;
  const detailPath = new URL(response.url()).pathname.replace(/\/messages$/, '');
  await expect(page.getByText('Private alice delayed response question', {exact: true})).toBeVisible();
  let release!: () => void;
  let captured!: () => void;
  const waiting = new Promise<void>(resolve => {release = resolve;});
  const received = new Promise<void>(resolve => {captured = resolve;});
  await page.route(`**${detailPath}`, async route => {
    const actual = await route.fetch();
    captured(); await waiting; await route.fulfill({response: actual});
  });
  await page.getByRole('button', {name: '刷新', exact: true}).click();
  await received;
  await expect(page.getByText('正在读取会话…', {exact: true})).toBeVisible();
  await page.getByRole('button', {name: '退出登录', exact: true}).click();
  await expect(page.getByLabel('用户名', {exact: true})).toBeVisible();
  await login(page, 'bob');
  const delivered = page.waitForResponse(result => new URL(result.url()).pathname === detailPath);
  release(); await delivered;
  await expect(page.getByText('Private alice delayed response question', {exact: true})).toHaveCount(0);
  expect((await page.request.get(detailPath)).status()).toBe(404);
  await page.getByRole('button', {name: '＋ 新建会话', exact: true}).click();
  await expect(page.getByLabel('想了解哪项政策？')).toBeEnabled();
  await page.getByLabel('想了解哪项政策？').fill('Private bob session expiration question');
  await page.getByRole('button', {name: '发送问题 →'}).click();
  await expect(page.getByText('Offline policy answer [1]', {exact: true})).toBeVisible();
  const logout = await page.request.post('/auth/logout', {data: {}, headers: {Origin: new URL(page.url()).origin}});
  expect(logout.ok()).toBeTruthy();
  await page.getByRole('button', {name: '刷新', exact: true}).click();
  await expect(page.getByLabel('用户名', {exact: true})).toBeVisible();
  await expect(page.getByText('Private bob session expiration question', {exact: true})).toHaveCount(0);
  await expect(page.getByText('Offline policy answer [1]', {exact: true})).toHaveCount(0);
  await expect(page.getByRole('button', {name: '发送问题 →'})).toBeDisabled();
});

test('older than one hundred conversations remains reachable through real API pagination', async ({page}) => {
  await page.goto('/workspace/');
  await login(page, 'bob');
  const headers = {Origin: new URL(page.url()).origin};
  const title = 'Oldest pagination fixture '+Date.now();
  for (let index = 0; index < 102; index++) {
    const result = await page.request.post('/api/v1/conversations', {headers,
      data: {title: index === 0 ? title : `Pagination fixture ${index}`}});
    expect(result.ok()).toBeTruthy();
  }
  await page.getByRole('button', {name: '刷新', exact: true}).click();
  for (let index = 0; index < 3; index++) {
    const more = page.getByRole('button', {name: '显示更多', exact: true});
    await expect(more).toBeEnabled();
    await more.click();
    await expect.poll(() => page.locator('.history-list li').count()).toBeGreaterThanOrEqual(Math.min(60 + 30 * index, 102));
  }
  await expect(page.locator('.history-list')).toContainText(title);
});

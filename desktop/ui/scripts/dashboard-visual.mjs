/** Smoke the current single-reel review UI and per-tab output-language contract. */
import assert from 'node:assert/strict';
import { chromium } from 'playwright';
import { spawn, spawnSync } from 'node:child_process';
import { mkdirSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const output = path.join(root, 'test-results/dashboard');
mkdirSync(output, { recursive: true });
const sample = path.join(output, 'synthetic.mp4');
const generated = spawnSync('ffmpeg', ['-y', '-v', 'error', '-f', 'lavfi', '-i',
  'color=c=0x234f87:s=360x640:d=2', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=2',
  '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', sample]);
assert.equal(generated.status, 0);
const server = spawn('npm', ['run', 'dev', '--', '--host', '127.0.0.1', '--port', '5179', '--strictPort'],
  { cwd: root, stdio: ['ignore', 'pipe', 'pipe'] });
let logs = ''; server.stdout.on('data', b => logs += b); server.stderr.on('data', b => logs += b);
let browser;
try {
  let ready = false;
  for (let attempt = 0; attempt < 80; attempt++) {
    try { if ((await fetch('http://127.0.0.1:5179')).ok) { ready = true; break; } } catch {}
    await new Promise(resolve => setTimeout(resolve, 250));
  }
  assert.ok(ready, logs);
  browser = await chromium.launch({ headless: true });
  for (const width of [1440, 1280, 1024]) {
    const page = await browser.newPage({ viewport: { width, height: 900 } });
    const errors = []; page.on('pageerror', error => errors.push(error.message));
    await page.route('**/media/sample-*.mp4*', route => route.fulfill({ body: readFileSync(sample), contentType: 'video/mp4' }));
    await page.goto('http://127.0.0.1:5179/?demo=1', { waitUntil: 'networkidle' });
    await page.locator('.reel-card').waitFor();
    assert.equal(await page.locator('.reel-card').count(), 1);
    assert.equal(await page.locator('video').count(), 1);
    assert.equal(await page.locator('.episode-field, input[id*="episode-number"]').count(), 0);
    assert.equal(await page.getByText('에피소드', { exact: false }).count(), 0);
    const language = page.locator('select[id$="-output-language"]');
    assert.equal(await language.locator('option').count(), 3);
    assert.equal(await language.inputValue(), 'en');
    assert.equal(await page.locator('html').getAttribute('lang'), 'en');
    assert.ok(!/[가-힣]/.test(await page.locator('body').innerText()), 'Built-in interface text must be English');
    await page.getByRole('button', { name: 'Settings', exact: true }).click();
    assert.ok(!/[가-힣]/.test(await page.getByRole('dialog', { name: 'Generation settings' }).innerText()));
    await page.keyboard.press('Escape');
    for (const code of ['en', 'zh', 'ko']) {
      await language.selectOption(code);
      assert.equal(await language.inputValue(), code);
    }
    await language.selectOption('zh');
    await page.reload({ waitUntil: 'networkidle' });
    assert.equal(await language.inputValue(), 'zh');
    await page.getByRole('button', { name: 'Next reel', exact: true }).click();
    assert.ok(await page.locator('.reel-card').innerText());
    const layout = await page.evaluate(() => ({ viewport: innerWidth, content: document.documentElement.scrollWidth }));
    assert.ok(layout.content <= layout.viewport + 2, JSON.stringify(layout));
    assert.equal(errors.length, 0, errors.join('\n'));
    await page.screenshot({ path: path.join(output, `dashboard-${width}x900.png`), fullPage: true });
    await page.close();
  }
  // Real request construction is checked against an isolated fake backend, never a paid model.
  const page = await browser.newPage();
  let submitted;
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/jobs' && route.request().method() === 'POST') {
      submitted = route.request().postDataJSON();
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
        job_id: 'test-job', status: 'loading', n_storylines: 0, output_language: submitted.output_language,
        source_url: submitted.youtube_url, episode_number: 1, storylines: [] }) });
    }
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
      job_id: null, status: 'idle', n_storylines: 0, storylines: [], speed: 1.2, configured: false }) });
  });
  await page.goto('http://127.0.0.1:5179/#token=test', { waitUntil: 'networkidle' });
  await page.locator('select[id$="-output-language"]').selectOption('en');
  await page.locator('input[type="url"]').fill('https://www.youtube.com/watch?v=abcdefghijk');
  await page.locator('.youtube-source button[type="submit"]').click();
  await page.waitForFunction(() => document.querySelector('input[type="url"]')?.disabled);
  assert.equal(submitted.output_language, 'en');
  assert.equal(submitted.youtube_url, 'https://www.youtube.com/watch?v=abcdefghijk');
  await page.close();
  console.log('PASS: three viewports, English interface and defaults, output languages, saved preference, reel navigation, local export UI, authenticated request payload');
} finally {
  await browser?.close();
  server.kill('SIGTERM');
}

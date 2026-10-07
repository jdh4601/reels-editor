import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, mkdir, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import net from "node:net";
import { chromium } from "playwright";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const work = await mkdtemp(path.join(tmpdir(), "reels-parallel-"));
const probe = net.createServer();
await new Promise((resolve) => probe.listen(0, "127.0.0.1", resolve));
const port = probe.address().port;
await new Promise((resolve) => probe.close(resolve));
const base = `http://127.0.0.1:${port}`;
let logs = "";
const engine = spawn(path.join(root, ".venv/bin/python"), [path.join(root, "desktop/ui/scripts/parallel-fixture.py"), work, String(port)], { cwd: root });
engine.stdout.on("data", (chunk) => { logs += chunk; });
engine.stderr.on("data", (chunk) => { logs += chunk; });
const headers = { Authorization: "Bearer parallel-test", "Content-Type": "application/json" };
const readJob = async (id) => (await fetch(`${base}/api/snapshot?job_id=${id}`, { headers })).json();
let browser;
let page;
try {
  for (let count = 0; count < 100; count += 1) {
    try { if ((await fetch(`${base}/api/health`)).ok) break; } catch {}
    if (engine.exitCode !== null) throw new Error(logs);
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  browser = await chromium.launch({ headless: true, ...(process.env.REELS_TEST_BROWSER_CHANNEL ? { channel: process.env.REELS_TEST_BROWSER_CHANNEL } : {}) });
  page = await browser.newPage({ viewport: { width: 1280, height: 900 }, reducedMotion: "reduce" });
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const sockets = [];
  page.on("websocket", (socket) => sockets.push(socket.url()));
  await page.goto(`${base}/#token=parallel-test`);
  const panel = () => page.locator('[role="tabpanel"]:visible');
  const tabs = page.getByRole("tab");
  const add = page.getByRole("button", { name: /새 탭/ });
  const urls = ["https://youtu.be/dQw4w9WgXcQ", "https://youtu.be/aqz-KE-bpKQ", "https://youtu.be/jNQXAC9IVRw"];
  const jobs = [];
  for (let index = 0; index < 3; index += 1) {
    if (index) await add.click();
    await panel().getByRole("textbox", { name: "창업가 인터뷰 YouTube 링크" }).fill(urls[index]);
    await panel().getByLabel("에피소드 번호").fill(String(index + 11));
    const response = page.waitForResponse((response) => response.url() === `${base}/api/jobs` && response.request().method() === "POST");
    await panel().getByRole("button", { name: "후보 10개 분석" }).click();
    jobs.push((await (await response).json()).job_id);
    await panel().locator('.candidate-item').first().waitFor();
    await panel().locator('.candidate-item').nth(index).click();
  }
  assert.equal(await tabs.count(), 3);
  assert.equal(await add.isDisabled(), true);
  assert.equal(new Set(jobs).size, 3);
  await tabs.nth(2).focus();
  await page.keyboard.press("Home");
  assert.equal(await tabs.nth(0).getAttribute("aria-selected"), "true");
  await page.keyboard.press("ArrowLeft");
  assert.equal(await tabs.nth(2).getAttribute("aria-selected"), "true");
  for (let index = 0; index < 3; index += 1) {
    await tabs.nth(index).click();
    assert.equal(await panel().getByRole("textbox", { name: "창업가 인터뷰 YouTube 링크" }).inputValue(), urls[index]);
    assert.equal(await panel().getByLabel("에피소드 번호").inputValue(), String(index + 11));
    assert.equal(await panel().locator('.candidate-item input:checked').count(), 1);
    assert.equal(await panel().locator('.candidate-item input').nth(index).isChecked(), true);
    await panel().getByRole("button", { name: "선택한 후보로 릴스 생성" }).click();
    await panel().getByRole("textbox", { name: "창업가 인터뷰 YouTube 링크" }).waitFor();
    await page.waitForFunction((id) => document.querySelector(`[aria-controls="${id}"]`)?.textContent.includes("처리 중"), await panel().getAttribute("id"));
    assert.equal(await page.getByRole("button", { name: `작업 ${index + 1} 탭 닫기` }).isDisabled(), true);
  }
  const running = await Promise.all(jobs.map(readJob));
  assert.ok(running.every((job) => ["generating", "rendering_base", "rendering_overlay"].includes(job.status)), JSON.stringify(running));
  const fourth = await fetch(`${base}/api/jobs`, { method: "POST", headers, body: JSON.stringify({ youtube_url: "https://youtu.be/9bZkp7q19f0" }) });
  assert.equal(fourth.status, 409);
  assert.match((await fourth.json()).detail, /최대 3개/);
  assert.ok(jobs.every((id) => sockets.some((url) => new URL(url).searchParams.get("job_id") === id)));
  await mkdir(path.join(root, "desktop/ui/test-results"), { recursive: true });
  await page.screenshot({ path: path.join(root, "desktop/ui/test-results/parallel-running.png"), fullPage: true });
  await writeFile(path.join(work, "release-render"), "ok");
  await page.waitForFunction(() => [...document.querySelectorAll('[role="tab"] small')].every((node) => node.textContent === "완료"));
  for (let index = 0; index < 3; index += 1) {
    await tabs.nth(index).click();
    assert.equal(await panel().getByRole("textbox", { name: "창업가 인터뷰 YouTube 링크" }).inputValue(), urls[index]);
    assert.equal(await panel().locator(".reel-card").count(), 1);
    const job = await readJob(jobs[index]);
    assert.equal(job.status, "ready");
    assert.equal(job.episode_number, index + 11);
    assert.deepEqual(job.selected_candidate_ids, [`c${index + 1}`]);
  }
  // Five ranked titles arrive in one request; choosing a candidate edits only
  // the draft, retains it across tabs, and does not rerender until explicitly saved.
  await tabs.nth(0).click();
  const beforeTitle = (await readJob(jobs[0])).storylines[0].title;
  await panel().getByRole("button", { name: "제목·이름·에피소드·캡션 수정하기" }).click();
  const titleResponse = page.waitForResponse((response) => response.url().endsWith("/title/suggestion"));
  await panel().getByRole("button", { name: "후보 5개 생성" }).click();
  assert.equal((await (await titleResponse).json()).suggestions.length, 5);
  const candidates = panel().getByRole("group", { name: "제목 후보 5개" });
  await candidates.waitFor();
  assert.equal(await candidates.getByRole("button").count(), 5);
  assert.equal(await candidates.getByRole("button").first().getAttribute("aria-pressed"), "true");
  await candidates.getByRole("button").nth(1).click();
  const selectedText = await panel().locator('.title-editor:not(.metadata-editor) input').evaluateAll((inputs) => inputs.map((input) => input.value).join(" "));
  assert.equal(selectedText, "회사가 커질수록 대표가 외로워지는 이유");
  assert.equal((await readJob(jobs[0])).storylines[0].title, beforeTitle);
  await page.setViewportSize({ width: 800, height: 900 });
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
  await page.screenshot({ path: path.join(root, "desktop/ui/test-results/title-candidates.png"), fullPage: true });
  await tabs.nth(1).click();
  assert.equal(await panel().getByRole("group", { name: "제목 후보 5개" }).count(), 0);
  await tabs.nth(0).click();
  assert.equal(await candidates.getByRole("button").nth(1).getAttribute("aria-pressed"), "true");
  await tabs.nth(2).click();
  // A tab reset must leave the other completed jobs and their subscriptions intact.
  await panel().getByRole("button", { name: "비우기" }).click();
  assert.equal(await panel().getByRole("textbox", { name: "창업가 인터뷰 YouTube 링크" }).inputValue(), "");
  await tabs.nth(0).click();
  assert.equal(await panel().getByRole("textbox", { name: "창업가 인터뷰 YouTube 링크" }).inputValue(), urls[0]);
  await page.getByRole("button", { name: "작업 3 탭 닫기" }).click();
  assert.equal(await tabs.count(), 2);
  assert.equal(await add.isEnabled(), true);
  await add.click();
  assert.equal(await panel().getByRole("textbox", { name: "창업가 인터뷰 YouTube 링크" }).inputValue(), "");
  await page.setViewportSize({ width: 800, height: 900 });
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
  await page.screenshot({ path: path.join(root, "desktop/ui/test-results/parallel-compact.png"), fullPage: true });
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ ok: true, parallelJobs: jobs.length, checks: ["three independent URLs", "tab state and candidate retention", "keyboard tab navigation", "concurrent rendering", "fourth job rejected", "job-scoped WebSockets", "background completion", "tab reset and close", "compact desktop layout"] }, null, 2));
} catch (error) {
  console.error(error);
  console.error(await page?.locator("body").innerText());
  throw error;
} finally {
  await browser?.close();
  engine.kill("SIGTERM");
  const killTimer = setTimeout(() => engine.kill("SIGKILL"), 3000);
  await new Promise((resolve) => { if (engine.exitCode !== null || engine.signalCode !== null) resolve(); else engine.once("exit", resolve); });
  clearTimeout(killTimer);
  await rm(work, { recursive: true, force: true });
}

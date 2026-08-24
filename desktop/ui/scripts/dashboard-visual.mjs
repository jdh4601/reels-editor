import { chromium } from "playwright";
import { spawn, spawnSync } from "node:child_process";
import crypto from "node:crypto";
import { existsSync, mkdirSync } from "node:fs";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const uiRoot = path.resolve(__dirname, "..");
const repoRoot = path.resolve(uiRoot, "../..");
const sampleRoot = path.join(repoRoot, "reels_editor/desktop/sample_media");
const screenshotRoot = path.join(uiRoot, "test-results/dashboard");
mkdirSync(screenshotRoot, { recursive: true });

function ensureSampleMedia() {
  mkdirSync(sampleRoot, { recursive: true });
  const colors = ["0x234f87", "0x7a4b24", "0x2f6a4f"];
  const tones = ["440", "554", "659"];
  colors.forEach((color, index) => {
    const output = path.join(sampleRoot, `sample-${index + 1}.mp4`);
    if (existsSync(output)) return;
    const result = spawnSync(
      "ffmpeg",
      [
        "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", `color=c=${color}:s=360x640:d=2`,
        "-f", "lavfi", "-i", `sine=frequency=${tones[index]}:duration=2`,
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-profile:v", "main",
        "-c:a", "aac", "-movflags", "+faststart", output,
      ],
      { encoding: "utf8" },
    );
    if (result.status !== 0) {
      throw new Error(`Failed to generate ${output}: ${result.stderr || result.error}`);
    }
  });
}

ensureSampleMedia();

const viewports = [
  { width: 1440, height: 900, name: "dashboard-1440x900.png" },
  { width: 1280, height: 800, name: "dashboard-1280x800.png" },
  { width: 1024, height: 800, name: "dashboard-1024x800.png" },
];

function startVite() {
  const child = spawn("npm", ["run", "dev", "--", "--host", "127.0.0.1", "--port", "5179"], {
    cwd: uiRoot,
    env: { ...process.env, BROWSER: "none" },
    stdio: ["ignore", "pipe", "pipe"],
  });
  let log = "";
  child.stdout.on("data", (chunk) => {
    log += chunk.toString();
  });
  child.stderr.on("data", (chunk) => {
    log += chunk.toString();
  });
  return { child, getLog: () => log };
}

async function waitForServer(url, getLog) {
  const deadline = Date.now() + 20_000;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch {
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
  }
  throw new Error(`Vite did not become ready. Log:\n${getLog()}`);
}

async function routeSampleMedia(page) {
  await page.route("**/api/media?demo=1", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        items: [1, 2, 3].map((number) => ({
          name: `sample-${number}.mp4`,
          url: `/media/sample-${number}.mp4`,
        })),
      }),
    });
  });
  await page.route("**/media/sample-*.mp4", async (route) => {
    const name = path.basename(new URL(route.request().url()).pathname);
    const file = path.join(sampleRoot, name);
    if (!existsSync(file)) throw new Error(`Missing sample media: ${file}`);
    await route.fulfill({ path: file, contentType: "video/mp4" });
  });
}

async function assertNoCriticalOverlap(page) {
  const result = await page.evaluate(() => {
    const selectors = [
      ".topbar",
      ".generation-option",
      ".status-row",
      ".generation-progress",
      ".lane",
      ".phone-frame",
      ".title-options",
      ".lane-footer",
      ".export-bar",
    ];
    const elements = selectors.flatMap((selector) => Array.from(document.querySelectorAll(selector)));
    const rects = elements
      .map((element) => {
        const rect = element.getBoundingClientRect();
        return {
          selector: element.className || element.tagName,
          left: rect.left,
          top: rect.top,
          right: rect.right,
          bottom: rect.bottom,
          width: rect.width,
          height: rect.height,
        };
      })
      .filter((rect) => rect.width > 1 && rect.height > 1);

    const failures = [];
    for (let i = 0; i < rects.length; i += 1) {
      for (let j = i + 1; j < rects.length; j += 1) {
        const a = rects[i];
        const b = rects[j];
        const overlapX = Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left));
        const overlapY = Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top));
        const area = overlapX * overlapY;
        const nested =
          (a.left <= b.left && a.right >= b.right && a.top <= b.top && a.bottom >= b.bottom) ||
          (b.left <= a.left && b.right >= a.right && b.top <= a.top && b.bottom >= a.bottom);
        const stickyExport = a.selector.includes("export-bar") || b.selector.includes("export-bar");
        if (area > 120 && !nested && !stickyExport) {
          failures.push({ a, b, area });
        }
      }
    }
    return failures;
  });
  if (result.length) {
    throw new Error(`Detected layout overlaps: ${JSON.stringify(result.slice(0, 3), null, 2)}`);
  }
}

async function assertVideosReady(page) {
  const result = await page.evaluate(async () => {
    const videos = Array.from(document.querySelectorAll("video"));
    await Promise.all(
      videos.map(
        (video) =>
          new Promise((resolve, reject) => {
            if (video.readyState >= 1) {
              resolve(true);
              return;
            }
            video.addEventListener("loadedmetadata", () => resolve(true), { once: true });
            video.addEventListener("error", () => reject(new Error(`metadata failed: ${video.currentSrc}`)), { once: true });
            video.load();
          }),
      ),
    );
    return videos.map((video) => ({ src: video.currentSrc, duration: video.duration, readyState: video.readyState }));
  });
  if (result.length !== 3 || result.some((video) => !Number.isFinite(video.duration) || video.duration <= 0)) {
    throw new Error(`Expected 3 playable videos, got ${JSON.stringify(result, null, 2)}`);
  }
}

async function assertPortraitPreviewGeometry(page) {
  const frames = await page.locator(".phone-frame").evaluateAll((elements) =>
    elements.map((element) => {
      const rect = element.getBoundingClientRect();
      return { width: rect.width, height: rect.height, ratio: rect.width / rect.height };
    }),
  );
  const failures = frames.filter((frame) => Math.abs(frame.ratio - 9 / 16) > 0.03 || frame.height <= frame.width);
  if (frames.length !== 3 || failures.length) {
    throw new Error(`Expected 3 portrait 9:16 preview frames, got ${JSON.stringify(frames, null, 2)}`);
  }
}

async function assertStoryStructureReadable(page) {
  const result = await page.locator(".story-beat").evaluateAll((elements) => ({
    count: elements.length,
    clipped: elements.some((element) => {
      const paragraph = element.querySelector("p");
      return paragraph && (paragraph.scrollHeight > paragraph.clientHeight + 1 || paragraph.scrollWidth > paragraph.clientWidth + 1);
    }),
    missingLabels: elements.some((element) =>
      !element.querySelector(".story-beat-heading strong")?.textContent?.trim()
      || !element.querySelector(".story-beat-heading span")?.textContent?.trim(),
    ),
  }));
  if (result.count !== 18 || result.clipped || result.missingLabels) {
    throw new Error(`Expected 18 complete role-labeled story sections, got ${JSON.stringify(result)}`);
  }
}

async function assertVerticalLaneLayout(page, minPreviewHeight, maxPreviewHeight, maxLaneHeight) {
  const geometry = await page.evaluate(() => ({
    lanes: Array.from(document.querySelectorAll(".lane")).map((element) => {
      const rect = element.getBoundingClientRect();
      return { top: rect.top, bottom: rect.bottom, left: rect.left, right: rect.right, height: rect.height };
    }),
    frames: Array.from(document.querySelectorAll(".phone-frame")).map((element) => {
      const rect = element.getBoundingClientRect();
      return { width: rect.width, height: rect.height };
    }),
  }));
  const lanesStacked = geometry.lanes.every((lane, index) => index === 0 || lane.top >= geometry.lanes[index - 1].bottom + 8);
  const previewsCompact = geometry.frames.every((frame) => frame.height >= minPreviewHeight && frame.height <= maxPreviewHeight);
  const lanesCompact = geometry.lanes.every((lane) => lane.height <= maxLaneHeight);
  if (geometry.lanes.length !== 3 || !lanesStacked || !previewsCompact || !lanesCompact) {
    throw new Error(`Expected vertically stacked compact lanes, got ${JSON.stringify(geometry, null, 2)}`);
  }
}

async function assertSingleAudibleVideo(page) {
  const initial = await page.locator("video").evaluateAll((videos) => videos.map((video) => video.muted));
  if (initial.filter((muted) => !muted).length !== 1) {
    throw new Error(`Expected exactly one initially unmuted selected video, got ${JSON.stringify(initial)}`);
  }
  await page.keyboard.press("Digit3");
  const afterSelect = await page.locator("video").evaluateAll((videos) => videos.map((video) => video.muted));
  if (afterSelect.filter((muted) => !muted).length !== 1 || afterSelect[2] !== false) {
    throw new Error(`Expected only selected third video to be audible, got ${JSON.stringify(afterSelect)}`);
  }
}

async function assertProductionFailureDoesNotLeakDemo(browser) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  const websocketUrls = [];
  const authHeaders = [];
  let mediaCalled = false;

  page.on("websocket", (socket) => {
    websocketUrls.push(socket.url());
  });

  await page.route("**/api/snapshot", async (route) => {
    authHeaders.push(route.request().headers().authorization ?? "");
    await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ error: "down" }) });
  });
  await page.route("**/api/media**", async (route) => {
    mediaCalled = true;
    await route.fulfill({ status: 500, body: "unexpected media fallback" });
  });

  await page.goto("http://127.0.0.1:5179/#token=hash-secret", { waitUntil: "networkidle" });
  await page.waitForSelector(".lane", { state: "visible" });
  await page.waitForFunction(() => document.body.innerText.includes("YouTube 링크 없음"));

  const bodyText = await page.locator("body").innerText();
  const laneCount = await page.locator(".lane").count();
  const videoCount = await page.locator("video").count();

  if (laneCount !== 3 || videoCount !== 0) {
    throw new Error(`Expected 3 empty placeholder lanes and no videos, got ${JSON.stringify({ laneCount, videoCount })}`);
  }
  if (bodyText.includes("김현지") || bodyText.includes("대표 인터뷰 원본") || bodyText.includes("숫자보다 중요한 대표의 기준")) {
    throw new Error("Production failure leaked demo content");
  }
  if (mediaCalled) {
    throw new Error("Production failure called /api/media demo fallback");
  }
  if (!authHeaders.some((header) => header === "Bearer hash-secret")) {
    throw new Error(`Protected fetch did not include Authorization bearer token: ${JSON.stringify(authHeaders)}`);
  }
  if (!websocketUrls.some((url) => url.includes("/api/events") && url.includes("token=hash-secret"))) {
    throw new Error(`WebSocket URL did not include token query: ${JSON.stringify(websocketUrls)}`);
  }
  await page.close();
}

async function assertEmptySnapshotPadsToThree(browser) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  let clearCalled = false;
  await page.route("**/api/snapshot", async (route) => {
    if (route.request().method() === "DELETE") {
      clearCalled = true;
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          job_id: "",
          project_name: "Reels Editor",
          project_path: null,
          source_label: "프로젝트 없음",
          storylines: [],
          subtitles_on: true,
        }),
      });
      return;
    }
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        job_id: "empty-job",
        project_name: "운영 프로젝트",
        project_path: "/real/project",
        source_label: "운영 원본",
        storylines: [],
        subtitles_on: true,
      }),
    });
  });

  await page.goto("http://127.0.0.1:5179/", { waitUntil: "networkidle" });
  await page.waitForSelector(".lane", { state: "visible" });
  const laneCount = await page.locator(".lane").count();
  const videoCount = await page.locator("video").count();
  const bodyText = await page.locator("body").innerText();
  if (laneCount !== 3 || videoCount !== 0 || !bodyText.includes("YouTube 인터뷰 링크를 넣으면")) {
    throw new Error(`Expected successful empty snapshot to pad to 3 placeholder lanes, got ${JSON.stringify({ laneCount, videoCount })}`);
  }
  await page.getByRole("button", { name: "비우기" }).click();
  await page.waitForFunction(() => document.body.innerText.includes("프로젝트 없음"));
  if (!clearCalled) throw new Error("Expected clear project button to call DELETE /api/snapshot");
  await page.close();
}

async function assertMediaTokenAndMutationFailures(browser) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  const mediaTokens = [];
  const selectionBodies = [];
  let batchExportBody = null;

  await page.route("**/api/snapshot", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        job_id: "job-42",
        project_name: "운영 프로젝트",
        project_path: "/real/project",
        source_label: "운영 원본",
        selected_storyline_id: "s1",
        subtitles_on: true,
        storylines: [1, 2, 3].map((number) => ({
          storyline_id: `s${number}`,
          index: number,
          label: `스토리라인 ${number}`,
          hook: `운영 훅 ${number}`,
          summary: `운영 요약 ${number}`,
          status: "ready",
          progress: 100,
          video_url: `/media/protected-${number}.mp4`,
          title_options: [`운영 제목 ${number}-1`, `운영 제목 ${number}-2`, `운영 제목 ${number}-3`],
          selected_title_index: 0,
        })),
      }),
    });
  });
  await page.route("**/media/protected-*.mp4**", async (route) => {
    mediaTokens.push(new URL(route.request().url()).searchParams.get("token"));
    const file = path.join(sampleRoot, "sample-1.mp4");
    await route.fulfill({ path: file, contentType: "video/mp4" });
  });
  await page.route("**/api/jobs/job-42/storylines/*/selection", async (route) => {
    selectionBodies.push(JSON.parse(route.request().postData() ?? "{}"));
    await route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({ error: "conflict" }) });
  });
  await page.route("**/api/jobs/job-42/export-batch", async (route) => {
    batchExportBody = JSON.parse(route.request().postData() ?? "{}");
    await route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({ error: "conflict" }) });
  });

  await page.goto("http://127.0.0.1:5179/#token=media-secret", { waitUntil: "networkidle" });
  await page.waitForSelector("video", { state: "attached" });
  await assertVideosReady(page);
  if (!mediaTokens.length || mediaTokens.some((token) => token !== "media-secret")) {
    throw new Error(`Expected protected media requests to include token query, got ${JSON.stringify(mediaTokens)}`);
  }

  await page.locator(".lane").nth(0).locator("fieldset.title-options label").nth(1).click();
  await page.waitForFunction(() => document.body.innerText.includes("제목 변경 요청이 실패했습니다."));
  await page.locator(".export-bar .switch").click();
  await page.waitForFunction(() => document.body.innerText.includes("자막 변경 요청이 실패했습니다."));
  await page.locator(".lane").nth(1).locator("fieldset.title-options label").nth(1).click();
  await page.locator(".lane").nth(1).locator("input[name='selected-video']").check();
  await Promise.all([
    page.waitForRequest((request) => request.url().includes("/api/jobs/job-42/export-batch")),
    page.getByRole("button", { name: /선택 영상.*내보내기/ }).click(),
  ]);

  if (!batchExportBody) throw new Error("Expected batch export mutation to be called");
  if (JSON.stringify(batchExportBody.storyline_ids) !== JSON.stringify(["s1", "s2"])) {
    throw new Error(`Expected two selected storylines in batch export: ${JSON.stringify(batchExportBody)}`);
  }
  if (selectionBodies.length < 3) throw new Error(`Expected selection mutations, got ${JSON.stringify(selectionBodies)}`);
  if (selectionBodies.some((body) => "selected_for_export" in body)) {
    throw new Error(`Title/subtitle mutations should not control multi-selection: ${JSON.stringify(selectionBodies)}`);
  }
  await page.close();
}

function websocketFrame(payload) {
  const body = Buffer.from(payload);
  if (body.length >= 126) throw new Error("test websocket payload is too large");
  return Buffer.concat([Buffer.from([0x81, body.length]), body]);
}

function websocketAccept(key) {
  return crypto
    .createHash("sha1")
    .update(`${key}258EAFA5-E914-47DA-95CA-C5AB0DC85B11`)
    .digest("base64");
}

async function assertHeartbeatDoesNotReplaceSnapshot(browser) {
  const sockets = new Set();
  const cancelAuthHeaders = [];
  const heartbeatServer = http.createServer((request, response) => {
    if (request.url?.startsWith("/api/jobs/heartbeat-job/cancel") && request.method === "POST") {
      cancelAuthHeaders.push(request.headers.authorization ?? "");
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({ ok: true }));
      return;
    }
    if (request.url?.startsWith("/api/snapshot")) {
      response.writeHead(200, { "content-type": "application/json" });
      response.end(
        JSON.stringify({
          job_id: "heartbeat-job",
          project_name: "하트비트 프로젝트",
          project_path: "/real/heartbeat",
          source_label: "하트비트 원본",
          selected_storyline_id: "hb1",
          subtitles_on: true,
          event_seq: 4,
          storylines: [1, 2, 3].map((number) => ({
            storyline_id: `hb${number}`,
            index: number,
            label: `스토리라인 ${number}`,
            hook: `하트비트 훅 ${number}`,
            summary: `하트비트 요약 ${number}`,
            status: number === 1 ? "overlaying" : "ready",
            progress: number === 1 ? 95 : 100,
            video_url: null,
            title_options: [`하트비트 제목 ${number}-1`, `하트비트 제목 ${number}-2`, `하트비트 제목 ${number}-3`],
            selected_title_index: 0,
          })),
        }),
      );
      return;
    }
    response.writeHead(200, { "content-type": "text/html" });
    response.end(
      '<!doctype html><html lang="ko"><body><div id="root"></div><script type="module" src="http://127.0.0.1:5179/src/main.tsx"></script></body></html>',
    );
  });

  heartbeatServer.on("upgrade", (request, socket) => {
    if (!request.url?.startsWith("/api/events")) {
      socket.destroy();
      return;
    }
    const key = request.headers["sec-websocket-key"];
    if (!key || Array.isArray(key)) {
      socket.destroy();
      return;
    }
    socket.write(
      [
        "HTTP/1.1 101 Switching Protocols",
        "Upgrade: websocket",
        "Connection: Upgrade",
        `Sec-WebSocket-Accept: ${websocketAccept(key)}`,
        "",
        "",
      ].join("\r\n"),
    );
    socket.write(websocketFrame(JSON.stringify({ event: "heartbeat", seq: 5 })));
    sockets.add(socket);
    socket.on("close", () => sockets.delete(socket));
  });

  await new Promise((resolve) => heartbeatServer.listen(5181, "127.0.0.1", resolve));
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  try {
    await page.goto("http://127.0.0.1:5181/#token=heartbeat-secret", { waitUntil: "domcontentloaded" });
    await page.waitForSelector(".lane", { state: "visible" });
    await page.waitForTimeout(500);
    const bodyText = await page.locator("body").innerText();
    const exportDisabled = await page.locator(".export-button").isDisabled();
    const generateButton = page.getByRole("button", { name: /생성 중/ });
    const cancelButton = page.getByRole("button", { name: "작업 취소" });
    if (!bodyText.includes("하트비트 훅 1") || !bodyText.includes("하트비트 제목 1-1")) {
      throw new Error("Populated lanes did not survive heartbeat event");
    }
    if (bodyText.includes("YouTube 인터뷰 링크를 넣으면")) {
      throw new Error("Heartbeat was incorrectly normalized as an empty snapshot");
    }
    if (!exportDisabled) {
      throw new Error("Export should stay disabled while selected lane is overlaying");
    }
    if (!(await generateButton.isDisabled())) {
      throw new Error("Generate should be disabled and labeled 생성 중 while selected job is overlaying");
    }
    if (!(await cancelButton.isVisible()) || !(await cancelButton.isEnabled())) {
      throw new Error("Cancel button should be visible and enabled while job is busy");
    }
    await cancelButton.click();
    await page.waitForFunction(() => document.body.innerText.includes("작업 취소를 요청했습니다."));
    if (!cancelAuthHeaders.includes("Bearer heartbeat-secret")) {
      throw new Error(`Cancel request did not include bearer token: ${JSON.stringify(cancelAuthHeaders)}`);
    }
  } finally {
    await page.close();
    for (const socket of sockets) socket.destroy();
    await new Promise((resolve) => heartbeatServer.close(resolve));
  }
}

async function assertRegenerateAppliesNewJobAndReconnects(browser) {
  const sockets = new Set();
  const websocketUrls = [];
  let createCalls = 0;
  let createBody = null;
  const regenerationServer = http.createServer(async (request, response) => {
    if (request.url?.startsWith("/api/jobs") && request.method === "POST") {
      createCalls += 1;
      const chunks = [];
      for await (const chunk of request) chunks.push(chunk);
      createBody = JSON.parse(Buffer.concat(chunks).toString("utf8"));
      response.writeHead(200, { "content-type": "application/json" });
      response.end(
        JSON.stringify({
          job_id: "new-job",
          project_name: "새 작업 프로젝트",
          project_path: "/real/project",
          source_label: "/real/project",
          status: "loading",
          phase: "loading",
          progress: 0.02,
          event_seq: 2,
          storylines: [],
          subtitles_on: true,
          duration_s: createBody.duration_s,
          n_storylines: createBody.n_storylines,
          provider: createBody.provider,
          voice_isolation: createBody.voice_isolation,
        }),
      );
      return;
    }
    if (request.url?.startsWith("/api/settings/voice-isolation")) {
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({ enabled: false, configured: true, masked_key: "xi_••••" }));
      return;
    }
    if (request.url?.startsWith("/api/snapshot")) {
      response.writeHead(200, { "content-type": "application/json" });
      response.end(
        JSON.stringify({
          job_id: "old-job",
          project_name: "이전 프로젝트",
          project_path: "/real/project",
          source_label: "/real/project",
          status: "failed",
          event_seq: 7,
          storylines: [],
          subtitles_on: true,
          duration_s: 30,
          n_storylines: 3,
          provider: "codex-cli",
        }),
      );
      return;
    }
    response.writeHead(200, { "content-type": "text/html" });
    response.end(
      '<!doctype html><html lang="ko"><body><div id="root"></div><script type="module" src="http://127.0.0.1:5179/src/main.tsx"></script></body></html>',
    );
  });

  regenerationServer.on("upgrade", (request, socket) => {
    if (!request.url?.startsWith("/api/events")) {
      socket.destroy();
      return;
    }
    websocketUrls.push(request.url);
    const key = request.headers["sec-websocket-key"];
    if (!key || Array.isArray(key)) {
      socket.destroy();
      return;
    }
    socket.write(
      [
        "HTTP/1.1 101 Switching Protocols",
        "Upgrade: websocket",
        "Connection: Upgrade",
        `Sec-WebSocket-Accept: ${websocketAccept(key)}`,
        "",
        "",
      ].join("\r\n"),
    );
    socket.write(websocketFrame(JSON.stringify({ event: "heartbeat", seq: 9 })));
    sockets.add(socket);
    socket.on("close", () => sockets.delete(socket));
  });

  await new Promise((resolve) => regenerationServer.listen(5182, "127.0.0.1", resolve));
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  try {
    await page.goto("http://127.0.0.1:5182/#token=regenerate-secret", { waitUntil: "domcontentloaded" });
    await page.waitForFunction(() => document.body.innerText.includes("이전 프로젝트"));
    await page.waitForTimeout(200);
    const voiceProcessingSwitch = page.getByRole("switch", { name: "다음 생성에 Voice Isolation과 Speech Enhancement 적용" });
    await page.locator(".generation-option .switch").click();
    if (!(await voiceProcessingSwitch.isChecked())) {
      throw new Error("Voice processing choice did not turn on before regeneration");
    }
    await page.getByRole("tab", { name: "설정" }).click();
    await page.getByText("60초", { exact: true }).click();
    await page.getByText("10개", { exact: true }).click();
    await page.getByLabel("모델 프로바이더").selectOption("claude-cli");
    await page.getByRole("button", { name: "다시 생성" }).click();
    await page.waitForFunction(() => document.body.innerText.includes("새 작업 프로젝트"));
    await page.getByRole("tab", { name: "대시보드" }).click();
    const requestedLaneCount = await page.locator(".lane").count();
    if (requestedLaneCount !== 10) {
      throw new Error(`Expected selected 10-storyline layout after regeneration, got ${requestedLaneCount}`);
    }
    const generateButton = page.getByRole("button", { name: "생성 중" });
    if (!(await generateButton.isDisabled())) {
      throw new Error("Generate should be disabled immediately after a new job starts");
    }
    const deadline = Date.now() + 2_000;
    while (websocketUrls.length < 2 && Date.now() < deadline) {
      await page.waitForTimeout(25);
    }
    if (createCalls !== 1) {
      throw new Error(`Expected one regenerate request, got ${createCalls}`);
    }
    if (createBody?.duration_s !== 60 || createBody?.n_storylines !== 10 || createBody?.provider !== "claude-cli" || createBody?.voice_isolation !== true) {
      throw new Error(`Expected selected generation settings in regenerate request, got ${JSON.stringify(createBody)}`);
    }
    if (!websocketUrls.some((url) => new URL(url, "http://127.0.0.1").searchParams.get("after") === "2")) {
      throw new Error(`Expected event reconnect at new job seq 2, got ${JSON.stringify(websocketUrls)}`);
    }
  } finally {
    await page.close();
    for (const socket of sockets) socket.destroy();
    await new Promise((resolve) => regenerationServer.close(resolve));
  }
}

const server = startVite();
try {
  await waitForServer("http://127.0.0.1:5179", server.getLog);
  const browser = await chromium.launch({ headless: true });
  const summary = [];
  for (const viewport of viewports) {
    const page = await browser.newPage({ viewport: { width: viewport.width, height: viewport.height } });
    await routeSampleMedia(page);
    await page.goto("http://127.0.0.1:5179/?demo=1", { waitUntil: "networkidle" });
    await page.waitForSelector(".lane", { state: "visible" });

    const laneCount = await page.locator(".lane").count();
    const videoCount = await page.locator("video").count();
    const titleRadioCount = await page.locator("fieldset.title-options input[type='radio']").count();
    const selectedVideoCount = await page.locator("input[name='selected-video']:checked").count();
    const switchCount = await page.locator("input[role='switch']").count();

    if (laneCount !== 3 || videoCount !== 3 || titleRadioCount !== 9 || selectedVideoCount !== 1 || switchCount !== 3) {
      throw new Error(
        `Unexpected dashboard counts at ${viewport.width}x${viewport.height}: ` +
          JSON.stringify({ laneCount, videoCount, titleRadioCount, selectedVideoCount, switchCount }),
      );
    }

    await assertVideosReady(page);
    await assertPortraitPreviewGeometry(page);
    await assertStoryStructureReadable(page);
    await assertVerticalLaneLayout(page, 470, 630, 900);
    await assertSingleAudibleVideo(page);
    await page.keyboard.press("Digit2");
    const selectedAfterShortcuts = await page.locator("input[name='selected-video']:checked").count();
    if (selectedAfterShortcuts !== 3) throw new Error(`Expected keyboard shortcuts to add multiple selections, got ${selectedAfterShortcuts}`);

    await assertNoCriticalOverlap(page);
    const screenshot = path.join(screenshotRoot, viewport.name);
    await page.screenshot({ path: screenshot, fullPage: true });
    summary.push({ viewport: `${viewport.width}x${viewport.height}`, screenshot });

    await page.getByRole("tab", { name: "설정" }).click();
    const durationRadioCount = await page.locator("input[name='video-duration']").count();
    const storylineCountRadioCount = await page.locator("input[name='storyline-count']").count();
    const selectedDuration = await page.locator("input[name='video-duration']:checked").getAttribute("value");
    const selectedStorylineCount = await page.locator("input[name='storyline-count']:checked").getAttribute("value");
    const selectedProvider = await page.getByLabel("모델 프로바이더").inputValue();
    const voiceIsolationKeyInputs = await page.getByLabel("ElevenLabs API 키").count();
    const speedControl = page.getByLabel("재생 배속");
    const speedAttributes = {
      min: await speedControl.getAttribute("min"),
      max: await speedControl.getAttribute("max"),
      step: await speedControl.getAttribute("step"),
      value: await speedControl.inputValue(),
    };
    if (durationRadioCount !== 3 || storylineCountRadioCount !== 10 || selectedDuration !== "30" || selectedStorylineCount !== "3" || selectedProvider !== "codex-cli" || voiceIsolationKeyInputs !== 1 || JSON.stringify(speedAttributes) !== JSON.stringify({ min: "1", max: "1.5", step: "0.05", value: "1.2" })) {
      throw new Error(`Unexpected settings controls: ${JSON.stringify({ durationRadioCount, storylineCountRadioCount, selectedDuration, selectedStorylineCount, selectedProvider, voiceIsolationKeyInputs, speedAttributes })}`);
    }
    const storylineControlOverflows = await page.locator(".storyline-count-control").evaluate(
      (element) => element.scrollWidth > element.clientWidth + 1,
    );
    if (storylineControlOverflows) throw new Error(`Storyline count control overflows at ${viewport.width}px`);
    if (viewport.width === 1280) {
      await page.waitForTimeout(250);
      const settingsScreenshot = path.join(screenshotRoot, "settings-1280x800.png");
      await page.screenshot({ path: settingsScreenshot, fullPage: true });
      summary.push({ viewport: "settings-1280x800", screenshot: settingsScreenshot });
    }
    await speedControl.hover();
    await page.mouse.wheel(0, -100);
    await page.waitForTimeout(300);
    if (await speedControl.inputValue() !== "1.25") {
      throw new Error(`Expected mouse wheel to raise playback speed by 0.05, got ${await speedControl.inputValue()}`);
    }
    await page.close();
  }
  const progressPage = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  await routeSampleMedia(progressPage);
  await progressPage.goto("http://127.0.0.1:5179/?demo=1&generation-progress=1", { waitUntil: "networkidle" });
  await progressPage.waitForSelector(".generation-progress", { state: "visible" });
  const progressText = await progressPage.locator(".generation-progress").innerText();
  const progressValue = await progressPage.locator(".generation-progress-track").getAttribute("aria-valuenow");
  if (!progressText.includes("생성 진행 · 4/4단계") || !progressText.includes("제목·자막 오버레이") || progressValue !== "64") {
    throw new Error(`Unexpected generation progress panel: ${JSON.stringify({ progressText, progressValue })}`);
  }
  await assertNoCriticalOverlap(progressPage);
  const progressScreenshot = path.join(screenshotRoot, "generation-progress-1280x800.png");
  await progressPage.screenshot({ path: progressScreenshot, fullPage: true });
  summary.push({ viewport: "generation-progress-1280x800", screenshot: progressScreenshot });
  await progressPage.close();
  await assertProductionFailureDoesNotLeakDemo(browser);
  await assertEmptySnapshotPadsToThree(browser);
  await assertMediaTokenAndMutationFailures(browser);
  await assertHeartbeatDoesNotReplaceSnapshot(browser);
  await assertRegenerateAppliesNewJobAndReconnects(browser);
  await browser.close();
  console.log(JSON.stringify({ ok: true, summary }, null, 2));
} finally {
  server.child.kill("SIGTERM");
}

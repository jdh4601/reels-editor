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
const logoFixture = path.join(repoRoot, "desktop/assets/reels-editor-icon.png");
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
  await page.route("**/img.youtube.com/vi/**", async (route) => {
    await route.fulfill({ path: logoFixture, contentType: "image/png" });
  });
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

async function assertBrandAndSourceControls(page) {
  const result = await page.evaluate(() => {
    const logo = document.querySelector(".brand-mark");
    const thumbnail = document.querySelector(".youtube-thumbnail");
    const sourceEntry = document.querySelector(".youtube-source-entry");
    const episode = document.querySelector("#episode-number");
    const topbar = document.querySelector(".topbar");
    const actions = document.querySelector(".workbar-actions");
    const rect = (element) => element ? element.getBoundingClientRect() : null;
    return {
      logoAlt: logo?.getAttribute("alt"),
      logoLoaded: logo instanceof HTMLImageElement && logo.complete && logo.naturalWidth > 0,
      logo: rect(logo),
      thumbnail: rect(thumbnail),
      sourceEntry: rect(sourceEntry),
      episodeValue: episode?.value,
      episodeMin: episode?.getAttribute("min"),
      archiveButton: Array.from(document.querySelectorAll("button")).some((button) => button.textContent?.includes("과거 릴스")),
      topbar: rect(topbar),
      actions: rect(actions),
      viewportWidth: window.innerWidth,
    };
  });
  if (result.logoAlt !== "Reels Editor 로고" || !result.logoLoaded || !result.logo || !result.thumbnail || !result.sourceEntry) {
    throw new Error(`Expected logo and YouTube thumbnail source controls: ${JSON.stringify(result)}`);
  }
  if (result.logo.left > 24 || result.thumbnail.right > result.sourceEntry.left + 1 || result.episodeValue !== "37" || result.episodeMin !== "1" || !result.archiveButton) {
    throw new Error(`Unexpected source identity geometry or values: ${JSON.stringify(result)}`);
  }
  if (result.actions && result.actions.right > result.viewportWidth + 1) {
    throw new Error(`Top actions escaped the viewport: ${JSON.stringify(result)}`);
  }
}

async function assertNoCriticalOverlap(page) {
  const result = await page.evaluate(() => {
    const selectors = [
      ".topbar",
      ".status-row",
      ".generation-progress",
      ".lane",
      ".phone-frame",
      ".lane-title",
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
  await page.waitForSelector(".youtube-source", { state: "visible" });
  await page.waitForFunction(() => document.body.innerText.includes("YouTube 링크 없음"));

  const bodyText = await page.locator("body").innerText();
  const laneCount = await page.locator(".lane").count();
  const videoCount = await page.locator("video").count();

  if (laneCount !== 0 || videoCount !== 0) {
    throw new Error(`Expected an empty production workspace and no videos, got ${JSON.stringify({ laneCount, videoCount })}`);
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

async function assertEmptySnapshotStaysEmpty(browser) {
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
          source_url: null,
          source_label: "YouTube 링크 없음",
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
        source_url: "https://youtu.be/empty-job",
        source_label: "YouTube · 운영 인터뷰",
        storylines: [],
        n_storylines: 0,
        subtitles_on: true,
      }),
    });
  });

  await page.goto("http://127.0.0.1:5179/", { waitUntil: "networkidle" });
  await page.waitForSelector(".youtube-source", { state: "visible" });
  const laneCount = await page.locator(".lane").count();
  const videoCount = await page.locator("video").count();
  const bodyText = await page.locator("body").innerText();
  if (laneCount !== 0 || videoCount !== 0) {
    throw new Error(`Expected successful empty snapshot to stay empty, got ${JSON.stringify({ laneCount, videoCount })}`);
  }
  await page.getByRole("button", { name: "비우기" }).click();
  await page.waitForFunction(() => document.body.innerText.includes("YouTube 링크 없음"));
  if (!clearCalled) throw new Error("Expected clear button to call DELETE /api/snapshot");
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
        source_url: "https://youtu.be/job-42",
        source_label: "YouTube · 운영 인터뷰",
        selected_storyline_id: "s1",
        subtitles_on: true,
        n_storylines: 3,
        storylines: [1, 2, 3].map((number) => ({
          storyline_id: `s${number}`,
          index: number,
          label: `스토리라인 ${number}`,
          hook: `운영 훅 ${number}`,
          summary: `운영 요약 ${number}`,
          status: "ready",
          progress: 100,
          video_url: `/media/protected-${number}.mp4`,
          title: `운영 제목 ${number}`,
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

  await page.locator(".export-bar .switch").click();
  await page.waitForFunction(() => document.body.innerText.includes("자막 변경 요청이 실패했습니다."));
  await page.locator(".lane").nth(1).locator("input[name='selected-video']").check();
  await Promise.all([
    page.waitForRequest((request) => request.url().includes("/api/jobs/job-42/export-batch")),
    page.getByRole("button", { name: /선택 영상.*내보내기/ }).click(),
  ]);

  if (!batchExportBody) throw new Error("Expected batch export mutation to be called");
  if (JSON.stringify(batchExportBody.storyline_ids) !== JSON.stringify(["s1", "s2"])) {
    throw new Error(`Expected two selected storylines in batch export: ${JSON.stringify(batchExportBody)}`);
  }
  if (!selectionBodies.length) throw new Error(`Expected selection mutations, got ${JSON.stringify(selectionBodies)}`);
  if (selectionBodies.some((body) => "title_index" in body)) {
    throw new Error(`Selection mutations should no longer carry a title choice: ${JSON.stringify(selectionBodies)}`);
  }
  if (selectionBodies.some((body) => "selected_for_export" in body)) {
    throw new Error(`Subtitle mutations should not control multi-selection: ${JSON.stringify(selectionBodies)}`);
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
          source_url: "https://youtu.be/heartbeat",
          source_label: "YouTube · 하트비트 인터뷰",
          selected_storyline_id: "hb1",
          subtitles_on: true,
          n_storylines: 3,
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
            title: `하트비트 제목 ${number}`,
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
    const generateButton = page.getByRole("button", { name: /처리 중/ });
    const cancelButton = page.getByRole("button", { name: "작업 취소" });
    if (!bodyText.includes("하트비트 훅 1") || !bodyText.includes("하트비트 제목 1")) {
      throw new Error("Populated lanes did not survive heartbeat event");
    }
    if (bodyText.includes("YouTube 인터뷰 링크를 넣으면")) {
      throw new Error("Heartbeat was incorrectly normalized as an empty snapshot");
    }
    if (!exportDisabled) {
      throw new Error("Export should stay disabled while selected lane is overlaying");
    }
    if (!(await generateButton.isDisabled())) {
      throw new Error("Analyze should be disabled and labeled 처리 중 while the selected job is overlaying");
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

async function assertCandidateSelectionGeneratesOnlyChosenReels(browser) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  let generationBody = null;
  const candidates = Array.from({ length: 10 }, (_, index) => ({
    id: `c${index + 1}`,
    content_type: ["story", "strategy", "failure", "principle"][index % 4],
    type_label: ["스토리형", "전략형", "실패 분석형", "원칙형"][index % 4],
    title: `서로 다른 창업 인사이트 ${index + 1}`,
    summary: `영상에서 확인한 구체적인 실행 과정 ${index + 1}`,
    takeaway: `1인 창업가가 바로 적용할 행동 ${index + 1}`,
  }));
  const analyzedSnapshot = {
    job_id: "candidate-job",
    project_name: "후보 선택 프로젝트",
    source_url: "https://youtu.be/candidates",
    source_label: "YouTube · 영어 원문 자막",
    status: "awaiting_selection",
    phase: "awaiting_selection",
    progress: 1,
    event_seq: 12,
    duration_s: 35,
    n_storylines: 0,
    content_types: ["story", "strategy", "failure", "principle"],
    candidates,
    selected_candidate_ids: [],
    storylines: [],
  };
  await page.route("**/api/snapshot", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(analyzedSnapshot) });
  });
  await page.route("**/api/jobs/candidate-job/generate", async (route) => {
    generationBody = JSON.parse(route.request().postData() ?? "{}");
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        ...analyzedSnapshot,
        status: "generating",
        phase: "generating",
        progress: 0.2,
        n_storylines: 2,
        selected_candidate_ids: generationBody.candidate_ids,
      }),
    });
  });

  await page.goto("http://127.0.0.1:5179/#token=candidate-secret", { waitUntil: "networkidle" });
  await page.waitForSelector(".candidate-item", { state: "visible" });
  const candidateCount = await page.locator(".candidate-item").count();
  if (candidateCount !== 10) throw new Error(`Expected exactly 10 candidate cards, got ${candidateCount}`);
  await page.getByText("서로 다른 창업 인사이트 2", { exact: true }).click();
  await page.getByText("서로 다른 창업 인사이트 7", { exact: true }).click();
  const selectedCount = await page.locator(".candidate-item.selected").count();
  if (selectedCount !== 2) throw new Error(`Expected two selected candidate cards, got ${selectedCount}`);
  await page.screenshot({ path: path.join(screenshotRoot, "candidate-selection-1280x900.png"), fullPage: true });
  await page.getByRole("button", { name: "선택한 후보로 릴스 생성" }).click();
  await page.waitForSelector(".candidate-workspace", { state: "detached" });
  if (JSON.stringify(generationBody) !== JSON.stringify({ candidate_ids: ["c2", "c7"] })) {
    throw new Error(`Expected only selected candidate IDs in generation request, got ${JSON.stringify(generationBody)}`);
  }
  await page.close();
}

async function assertInstagramCaptionGeneration(browser) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  let captionCalls = 0;
  const caption = "Ep 1. 광고 없이 첫 고객을 만든 방법\n\n이 창업가는 제품을 완성하기 전에 잠재 고객을 직접 만났습니다.\n\n반복해서 확인된 문제 하나에 집중해 첫 유료 제안을 만들었습니다.\n\n1인 창업가에게는 기능보다 구매 이유를 먼저 검증하는 순서가 중요합니다.\n\n여러분은 지금 어떤 문제를 먼저 검증하고 있나요?\n\n다음 이야기가 궁금하다면 디원을 팔로우해주세요 🚀";
  const snapshot = (instagramCaption = "") => ({
    job_id: "caption-job",
    project_name: "캡션 프로젝트",
    source_url: "https://youtu.be/caption",
    source_label: "YouTube · 영어 원문 자막",
    status: "ready",
    phase: "ready",
    progress: 1,
    event_seq: 20 + captionCalls,
    duration_s: 35,
    n_storylines: 1,
    selected_storyline_id: "s1",
    storylines: [{
      storyline_id: "s1",
      index: 1,
      label: "릴스 1",
      hook: "첫 고객을 만든 가장 작은 실험",
      summary: "광고보다 문제 검증이 먼저였습니다.",
      sections: [{ beat: "전략", role: "실행", text: "잠재 고객을 직접 만나 유료 제안을 검증했습니다." }],
      status: "ready",
      progress: 100,
      video_url: null,
      title: "광고비 0원, 첫 고객",
      instagram_caption: instagramCaption,
    }],
  });
  await page.route("**/api/snapshot", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(snapshot()) });
  });
  await page.route("**/api/jobs/caption-job/storylines/s1/caption", async (route) => {
    captionCalls += 1;
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(snapshot(caption)) });
  });

  await page.goto("http://127.0.0.1:5179/#token=caption-secret", { waitUntil: "networkidle" });
  const generateButton = page.getByRole("button", { name: "캡션 생성하기" });
  await generateButton.click();
  await page.waitForFunction(() => document.body.innerText.includes("다음 이야기가 궁금하다면 디원을 팔로우해주세요 🚀"));
  if (captionCalls !== 1) throw new Error(`Expected one caption generation request, got ${captionCalls}`);
  if (!(await page.getByRole("button", { name: "캡션 복사" }).isVisible())) {
    throw new Error("Expected copy action after Instagram caption generation");
  }
  if (!(await page.getByRole("button", { name: "다시 생성" }).isVisible())) {
    throw new Error("Expected regenerate action after Instagram caption generation");
  }
  await page.screenshot({ path: path.join(screenshotRoot, "instagram-caption-1280x900.png"), fullPage: true });
  await page.close();
}

async function assertSourceThumbnailAndEpisodePayload(browser) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  let createBody = null;
  await page.route("**/img.youtube.com/vi/**", async (route) => {
    await route.fulfill({ path: logoFixture, contentType: "image/png" });
  });
  await page.route("**/api/snapshot", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        job_id: "source-control-job",
        project_name: "Reels Editor",
        source_url: null,
        source_label: "YouTube 링크 없음",
        status: "idle",
        n_storylines: 0,
        storylines: [],
      }),
    });
  });
  await page.route("**/api/jobs", async (route) => {
    createBody = JSON.parse(route.request().postData() ?? "{}");
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        job_id: "episode-37-job",
        project_name: "회차 테스트",
        source_url: createBody.youtube_url,
        source_label: "YouTube · 테스트",
        status: "loading",
        phase: "loading",
        episode_number: createBody.episode_number,
        n_storylines: 0,
        storylines: [],
      }),
    });
  });

  await page.goto("http://127.0.0.1:5179/", { waitUntil: "networkidle" });
  const urlInput = page.getByLabel("창업가 인터뷰 YouTube 링크");
  await urlInput.fill("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=12s");
  await page.waitForSelector(".youtube-thumbnail", { state: "visible" });
  let thumbnailSrc = await page.locator(".youtube-thumbnail").getAttribute("src");
  if (!thumbnailSrc?.includes("/vi/dQw4w9WgXcQ/hqdefault.jpg")) {
    throw new Error(`Long YouTube URL produced wrong thumbnail: ${thumbnailSrc}`);
  }
  await urlInput.fill("https://www.youtube.com/watch?v=dQw4w9");
  await page.waitForSelector(".youtube-thumbnail", { state: "detached" });
  await urlInput.fill("https://youtu.be/9bZkp7q19f0");
  await page.waitForSelector(".youtube-thumbnail", { state: "visible" });
  thumbnailSrc = await page.locator(".youtube-thumbnail").getAttribute("src");
  if (!thumbnailSrc?.includes("/vi/9bZkp7q19f0/hqdefault.jpg")) {
    throw new Error(`Short YouTube URL produced wrong thumbnail: ${thumbnailSrc}`);
  }
  await page.getByLabel("회차").fill("37");
  await page.getByRole("button", { name: "후보 10개 분석" }).click();
  await page.waitForFunction(() => document.body.innerText.includes("회차 테스트"));
  if (createBody?.youtube_url !== "https://youtu.be/9bZkp7q19f0" || createBody?.episode_number !== 37) {
    throw new Error(`Expected episode 37 and normalized source payload, got ${JSON.stringify(createBody)}`);
  }
  await page.screenshot({ path: path.join(screenshotRoot, "source-thumbnail-episode-1280x800.png"), fullPage: true });
  await page.close();
}

async function assertReadyTitleEditing(browser) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  let patchCalls = 0;
  let patchBody = null;
  const snapshot = (title = "고객을 먼저 만난 이유", revision = 1) => ({
    job_id: "title-job",
    project_name: "제목 수정 프로젝트",
    source_url: "https://youtu.be/dQw4w9WgXcQ",
    source_label: "YouTube · 제목 테스트",
    status: "ready",
    phase: "ready",
    progress: 1,
    episode_number: 37,
    n_storylines: 1,
    selected_storyline_id: "title-story",
    storylines: [{
      storyline_id: "title-story",
      index: 1,
      label: "릴스 1",
      hook: "검증 순서",
      summary: "고객 검증을 먼저 한 이유",
      sections: [{ beat: "훅", role: "문제 제기", text: "제품보다 먼저 고객을 만났습니다." }],
      status: "ready",
      progress: 100,
      video_url: "/media/title-video.mp4",
      title,
      revision,
    }],
  });
  await page.route("**/api/snapshot", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(snapshot()) });
  });
  await page.route("**/media/title-video.mp4**", async (route) => {
    await route.fulfill({ path: path.join(sampleRoot, "sample-1.mp4"), contentType: "video/mp4" });
  });
  await page.route("**/api/jobs/title-job/storylines/title-story/title", async (route) => {
    if (route.request().method() !== "PATCH") throw new Error(`Title endpoint expected PATCH, got ${route.request().method()}`);
    patchCalls += 1;
    patchBody = JSON.parse(route.request().postData() ?? "{}");
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(snapshot(patchBody.title, 2)) });
  });

  await page.goto("http://127.0.0.1:5179/", { waitUntil: "networkidle" });
  const titleInput = page.getByLabel("화면 제목");
  await titleInput.fill("짧은제목");
  await page.getByRole("button", { name: "수정하기" }).click();
  await page.waitForFunction(() => document.body.innerText.includes("6자 이상"));
  if (patchCalls !== 0) throw new Error("Invalid display title should not call PATCH");

  const revisedTitle = "고객 문제를 먼저 검증한 진짜 이유";
  await titleInput.fill(revisedTitle);
  await page.getByRole("button", { name: "수정하기" }).click();
  await page.waitForFunction(() => document.body.innerText.includes("재생 영상에 수정 내용이 반영되었습니다."));
  if (patchCalls !== 1 || JSON.stringify(patchBody) !== JSON.stringify({ title: revisedTitle })) {
    throw new Error(`Unexpected title PATCH contract: ${JSON.stringify({ patchCalls, patchBody })}`);
  }
  const videoSrc = await page.locator("video").getAttribute("src");
  if (!videoSrc || !new URL(videoSrc, "http://127.0.0.1").searchParams.has("revision")) {
    throw new Error(`Updated title did not cache-bust video URL: ${videoSrc}`);
  }
  await page.screenshot({ path: path.join(screenshotRoot, "title-edit-1280x900.png"), fullPage: true });
  await page.close();
}

async function assertCompletedArchiveWorkflow(browser) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  let openCalls = 0;
  let captionCalls = 0;
  let exportCalls = 0;
  const readyStoryline = (caption = "") => ({
    storyline_id: "archive-ready",
    index: 1,
    label: "릴스 1",
    hook: "완료된 고객 검증 이야기",
    summary: "고객을 먼저 만난 과정",
    sections: [{ beat: "훅", role: "문제 제기", text: "고객을 먼저 만나 답을 찾았습니다." }],
    status: "ready",
    progress: 100,
    video_url: "/media/archive-ready.mp4",
    title: "고객을 먼저 만난 이유",
    instagram_caption: caption,
  });
  const openedSnapshot = (caption = "") => ({
    job_id: "archive-job",
    project_name: "김현지 대표 인터뷰",
    source_url: "https://youtu.be/dQw4w9WgXcQ",
    source_label: "YouTube · 보관 인터뷰",
    status: "ready",
    phase: "ready",
    progress: 1,
    episode_number: 37,
    n_storylines: 2,
    selected_storyline_id: "archive-ready",
    storylines: [
      readyStoryline(caption),
      { ...readyStoryline(), storyline_id: "archive-failed", label: "릴스 2", status: "failed", video_url: "/media/archive-failed.mp4", error: "과거 실패" },
    ],
  });
  await page.route("**/img.youtube.com/vi/**", async (route) => {
    await route.fulfill({ path: logoFixture, contentType: "image/png" });
  });
  await page.route("**/api/snapshot", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ job_id: "empty", project_name: "Reels Editor", status: "idle", n_storylines: 0, storylines: [] }) });
  });
  await page.route("**/api/archive", async (route) => {
    if (route.request().method() !== "GET") throw new Error(`Archive endpoint expected GET, got ${route.request().method()}`);
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ items: [
        { id: "ready-item", job_id: "archive-job", storyline_id: "archive-ready", status: "ready", episode_number: 37, project_name: "김현지 대표 인터뷰", reel_title: "고객을 먼저 만난 이유", source_url: "https://youtu.be/dQw4w9WgXcQ", source_thumbnail_url: "https://img.youtube.com/vi/dQw4w9WgXcQ/hqdefault.jpg", video_url: "/media/archive-ready.mp4", completed_at: "2026-08-25T12:30:00+09:00" },
        { id: "failed-item", job_id: "failed-job", storyline_id: "failed", status: "failed", episode_number: 4, project_name: "실패 작업", reel_title: "완료되지 않음" },
        { id: "analysis-item", job_id: "analysis-job", storyline_id: "analysis", status: "ready", episode_number: 5, project_name: "분석 작업", reel_title: "재생 파일 없음" },
      ] }),
    });
  });
  await page.route("**/api/jobs/archive-job/open", async (route) => {
    if (route.request().method() !== "POST") throw new Error(`Open endpoint expected POST, got ${route.request().method()}`);
    openCalls += 1;
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(openedSnapshot()) });
  });
  await page.route("**/media/archive-*.mp4**", async (route) => {
    await route.fulfill({ path: path.join(sampleRoot, "sample-1.mp4"), contentType: "video/mp4" });
  });
  await page.route("**/api/jobs/archive-job/storylines/archive-ready/caption", async (route) => {
    captionCalls += 1;
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(openedSnapshot("Ep 37. 고객을 먼저 만난 이유\n\n완료된 릴스의 캡션입니다.")) });
  });
  await page.route("**/api/jobs/archive-job/export-batch", async (route) => {
    exportCalls += 1;
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        ...openedSnapshot("Ep 37. 고객을 먼저 만난 이유\n\n완료된 릴스의 캡션입니다."),
        export: { output_path: "/Users/test/Movies/Reels Editor/Ep-37_김현지 대표 인터뷰/reel.mp4" },
      }),
    });
  });

  await page.goto("http://127.0.0.1:5179/", { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "과거 릴스" }).click();
  await page.waitForSelector(".archive-item", { state: "visible" });
  const archiveViewFocus = await page.evaluate(() => ({
    tag: document.activeElement?.tagName,
    text: document.activeElement?.textContent?.trim(),
  }));
  if (archiveViewFocus.tag !== "H1" || archiveViewFocus.text !== "과거 릴스") {
    throw new Error(`Opening the archive should focus its visible heading: ${JSON.stringify(archiveViewFocus)}`);
  }
  const archiveCount = await page.locator(".archive-item").count();
  if (archiveCount !== 1 || !(await page.locator(".archive-item").innerText()).includes("에피소드 37")) {
    throw new Error(`Archive must display only completed entries, got ${archiveCount}`);
  }
  const archiveThumbnailSrc = await page.locator(".archive-thumbnail").getAttribute("src");
  if (!archiveThumbnailSrc?.includes("/vi/dQw4w9WgXcQ/hqdefault.jpg")) {
    throw new Error(`Archive did not normalize source_thumbnail_url: ${archiveThumbnailSrc}`);
  }
  await page.screenshot({ path: path.join(screenshotRoot, "archive-list-1280x900.png"), fullPage: true });
  await page.getByRole("button", { name: "고객을 먼저 만난 이유 열기" }).click();
  await page.waitForSelector(".lane", { state: "visible" });
  const openedArchiveFocus = await page.evaluate(() => ({
    tag: document.activeElement?.tagName,
    text: document.activeElement?.textContent?.trim(),
  }));
  if (openedArchiveFocus.tag !== "H1" || openedArchiveFocus.text !== "김현지 대표 인터뷰") {
    throw new Error(`Opening an archived reel should focus its visible workspace heading: ${JSON.stringify(openedArchiveFocus)}`);
  }
  if (openCalls !== 1 || await page.locator(".lane").count() !== 1 || await page.locator("video").count() !== 1) {
    throw new Error(`Opening an archived item should show one playable completed lane: ${JSON.stringify({ openCalls })}`);
  }
  for (const forbidden of ["비우기", "다시 분석", "다시 시도", "생성 설정"]) {
    if (await page.getByRole("button", { name: forbidden, exact: true }).count()) throw new Error(`Archive mode exposed forbidden action: ${forbidden}`);
  }
  if (await page.locator("input[role='switch']").count()) throw new Error("Archive mode exposed subtitle re-render control");
  if (await page.getByRole("button", { name: "수정하기", exact: true }).count() !== 1) {
    throw new Error("Archive mode must keep the completed reel title editor available");
  }

  await page.getByRole("button", { name: "캡션 생성하기" }).click();
  await page.waitForFunction(() => document.body.innerText.includes("완료된 릴스의 캡션입니다."));
  if (captionCalls !== 1 || !(await page.getByRole("button", { name: "캡션 복사" }).isVisible())) {
    throw new Error("Archived reel caption generation/copy actions are not available");
  }
  await page.getByRole("button", { name: "보관 영상 다시 내보내기" }).click();
  await page.waitForFunction(() => document.body.innerText.includes("Ep-37_김현지 대표 인터뷰/reel.mp4"));
  if (exportCalls !== 1) throw new Error("Archived reel did not call fixed-path re-export");
  await page.screenshot({ path: path.join(screenshotRoot, "archive-opened-1280x900.png"), fullPage: true });
  await page.close();
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
          source_url: "https://youtu.be/original",
          source_label: "YouTube · 기존 인터뷰",
          status: "loading",
          phase: "loading",
          progress: 0.02,
          event_seq: 2,
          storylines: [],
          subtitles_on: true,
          duration_s: 35,
          n_storylines: 0,
          content_types: createBody.content_types,
          candidates: [],
          provider: createBody.provider,
        }),
      );
      return;
    }
    if (request.url?.startsWith("/api/snapshot")) {
      response.writeHead(200, { "content-type": "application/json" });
      response.end(
        JSON.stringify({
          job_id: "old-job",
          project_name: "이전 프로젝트",
          source_url: "https://youtu.be/replacement",
          source_label: "YouTube · 새 인터뷰",
          status: "failed",
          event_seq: 7,
          storylines: [],
          subtitles_on: true,
          duration_s: 35,
          n_storylines: 0,
          content_types: ["story", "strategy", "failure", "principle"],
          candidates: [],
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
    await page.getByRole("button", { name: "생성 설정" }).click();
    await page.waitForSelector(".settings-popover", { state: "visible" });
    await page.getByLabel("모델 프로바이더").selectOption("claude-cli");
    await page.keyboard.press("Escape");
    await page.waitForSelector(".settings-popover", { state: "detached" });
    await page.getByRole("button", { name: "다시 분석" }).click();
    await page.waitForFunction(() => document.body.innerText.includes("새 작업 프로젝트"));
    const requestedLaneCount = await page.locator(".lane").count();
    if (requestedLaneCount !== 0) {
      throw new Error(`Expected analysis to start without reel placeholders, got ${requestedLaneCount}`);
    }
    const generateButton = page.getByRole("button", { name: "처리 중" });
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
    if (JSON.stringify(createBody?.content_types) !== JSON.stringify(["story", "strategy", "failure", "principle"]) || createBody?.provider !== "claude-cli" || createBody?.episode_number !== 1 || "duration_s" in createBody || "n_storylines" in createBody) {
      throw new Error(`Expected four content types, provider, and episode number in analysis request, got ${JSON.stringify(createBody)}`);
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
    const laneTitleCount = await page.locator(".title-editor input").count();
    const selectedVideoCount = await page.locator("input[name='selected-video']:checked").count();
    const switchCount = await page.locator("input[role='switch']").count();
    const contentTypeCount = await page.locator("input[name='content-type']").count();
    const selectedContentTypeCount = await page.locator("input[name='content-type']:checked").count();

    if (laneCount !== 3 || videoCount !== 3 || laneTitleCount !== 3 || selectedVideoCount !== 1 || switchCount !== 1 || contentTypeCount !== 4 || selectedContentTypeCount !== 4) {
      throw new Error(
        `Unexpected dashboard counts at ${viewport.width}x${viewport.height}: ` +
          JSON.stringify({ laneCount, videoCount, laneTitleCount, selectedVideoCount, switchCount, contentTypeCount, selectedContentTypeCount }),
      );
    }

    await assertVideosReady(page);
    await assertBrandAndSourceControls(page);
    await assertPortraitPreviewGeometry(page);
    await assertStoryStructureReadable(page);
    await assertVerticalLaneLayout(page, 470, 630, 900);
    await assertSingleAudibleVideo(page);
    await page.keyboard.press("Digit2");
    const selectedAfterShortcuts = await page.locator("input[name='selected-video']:checked").count();
    if (selectedAfterShortcuts !== 3) throw new Error(`Expected keyboard shortcuts to add multiple selections, got ${selectedAfterShortcuts}`);

    const subtitleSwitch = page.locator("input[role='switch']");
    await subtitleSwitch.focus();
    const switchFocus = await page.locator(".switch-track").evaluate((track) => {
      const style = getComputedStyle(track);
      return {
        inputFocused: document.activeElement?.getAttribute("role") === "switch",
        outlineStyle: style.outlineStyle,
        outlineWidth: style.outlineWidth,
        boxShadow: style.boxShadow,
      };
    });
    if (!switchFocus.inputFocused || switchFocus.outlineStyle === "none" || switchFocus.outlineWidth === "0px") {
      throw new Error(`Subtitle switch focus is not visibly represented on its track: ${JSON.stringify(switchFocus)}`);
    }

    await assertNoCriticalOverlap(page);
    const screenshot = path.join(screenshotRoot, viewport.name);
    await page.screenshot({ path: screenshot, fullPage: true });
    summary.push({ viewport: `${viewport.width}x${viewport.height}`, screenshot });

    const settingsTrigger = page.getByRole("button", { name: "생성 설정" });
    await settingsTrigger.click();
    await page.waitForSelector(".settings-popover", { state: "visible" });
    const durationRadioCount = await page.locator("input[name='video-duration']").count();
    const storylineCountRadioCount = await page.locator("input[name='storyline-count']").count();
    const selectedProvider = await page.getByLabel("모델 프로바이더").inputValue();
    const speedControl = page.getByLabel("재생 배속");
    if (!(await speedControl.evaluate((control) => document.activeElement === control))) {
      throw new Error("Opening generation settings should focus the first meaningful control");
    }
    const speedAttributes = {
      min: await speedControl.getAttribute("min"),
      max: await speedControl.getAttribute("max"),
      step: await speedControl.getAttribute("step"),
      value: await speedControl.inputValue(),
    };
    if (durationRadioCount !== 0 || storylineCountRadioCount !== 0 || selectedProvider !== "codex-cli" || JSON.stringify(speedAttributes) !== JSON.stringify({ min: "1", max: "1.5", step: "0.05", value: "1.2" })) {
      throw new Error(`Unexpected settings controls: ${JSON.stringify({ durationRadioCount, storylineCountRadioCount, selectedProvider, speedAttributes })}`);
    }
    if (viewport.width === 1280) {
      await page.waitForTimeout(250);
      const settingsScreenshot = path.join(screenshotRoot, "settings-1280x800.png");
      await page.screenshot({ path: settingsScreenshot, fullPage: true });
      summary.push({ viewport: "settings-1280x800", screenshot: settingsScreenshot });
    }
    await speedControl.fill("1.25");
    await page.waitForTimeout(300);
    if (await speedControl.inputValue() !== "1.25") {
      throw new Error(`Expected playback speed to change to 1.25, got ${await speedControl.inputValue()}`);
    }
    await page.keyboard.press("Escape");
    await page.waitForSelector(".settings-popover", { state: "detached" });
    if (!(await settingsTrigger.evaluate((trigger) => document.activeElement === trigger))) {
      throw new Error("Escape should restore focus to the generation settings trigger");
    }
    if (viewport.width === 1280) {
      await settingsTrigger.click();
      await page.waitForSelector(".settings-popover", { state: "visible" });
      await page.locator(".project-brand").click();
      await page.waitForSelector(".settings-popover", { state: "detached" });
      if (!(await settingsTrigger.evaluate((trigger) => document.activeElement === trigger))) {
        throw new Error("Clicking outside settings should restore focus to its trigger");
      }

      await settingsTrigger.click();
      await page.waitForSelector(".settings-popover", { state: "visible" });
      await settingsTrigger.click();
      await page.waitForSelector(".settings-popover", { state: "detached" });
      if (!(await settingsTrigger.evaluate((trigger) => document.activeElement === trigger))) {
        throw new Error("Closing settings from its trigger should retain trigger focus");
      }
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
  await assertEmptySnapshotStaysEmpty(browser);
  await assertMediaTokenAndMutationFailures(browser);
  await assertHeartbeatDoesNotReplaceSnapshot(browser);
  await assertCandidateSelectionGeneratesOnlyChosenReels(browser);
  await assertInstagramCaptionGeneration(browser);
  await assertSourceThumbnailAndEpisodePayload(browser);
  await assertReadyTitleEditing(browser);
  await assertCompletedArchiveWorkflow(browser);
  await assertRegenerateAppliesNewJobAndReconnects(browser);
  await browser.close();
  console.log(JSON.stringify({ ok: true, summary }, null, 2));
} finally {
  server.child.kill("SIGTERM");
}

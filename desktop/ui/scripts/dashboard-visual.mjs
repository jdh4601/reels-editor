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
      ".status-row",
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
  await page.waitForFunction(() => document.body.innerText.includes("프로젝트 없음"));

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
  await page.route("**/api/snapshot", async (route) => {
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
  if (laneCount !== 3 || videoCount !== 0 || !bodyText.includes("프로젝트를 선택하면")) {
    throw new Error(`Expected successful empty snapshot to pad to 3 placeholder lanes, got ${JSON.stringify({ laneCount, videoCount })}`);
  }
  await page.close();
}

async function assertMediaTokenAndMutationFailures(browser) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  const mediaTokens = [];
  const selectionBodies = [];
  let exportCalled = false;

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
  await page.route("**/api/jobs/job-42/export", async (route) => {
    exportCalled = true;
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
  await page.locator(".switch").click();
  await page.waitForFunction(() => document.body.innerText.includes("자막 변경 요청이 실패했습니다."));
  await page.locator(".lane").nth(1).locator("fieldset.title-options label").nth(1).click();
  await page.getByRole("button", { name: "선택 영상 내보내기" }).click();
  await page.waitForFunction(() => document.body.innerText.includes("내보내기에 실패했습니다."));

  if (!exportCalled) throw new Error("Expected export mutation to be called");
  if (selectionBodies.length < 3) throw new Error(`Expected selection mutations, got ${JSON.stringify(selectionBodies)}`);
  if (selectionBodies[0].selected_for_export !== true || selectionBodies[1].selected_for_export !== true) {
    throw new Error(`Selected lane title/subtitle mutations must preserve selected_for_export=true: ${JSON.stringify(selectionBodies)}`);
  }
  if ("selected_for_export" in selectionBodies[2]) {
    throw new Error(`Non-selected title mutation should not move export selection: ${JSON.stringify(selectionBodies[2])}`);
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
    if (bodyText.includes("프로젝트를 선택하면")) {
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

    if (laneCount !== 3 || videoCount !== 3 || titleRadioCount !== 9 || selectedVideoCount !== 1 || switchCount !== 1) {
      throw new Error(
        `Unexpected dashboard counts at ${viewport.width}x${viewport.height}: ` +
          JSON.stringify({ laneCount, videoCount, titleRadioCount, selectedVideoCount, switchCount }),
      );
    }

    await assertVideosReady(page);
    await assertPortraitPreviewGeometry(page);
    await assertSingleAudibleVideo(page);
    await page.keyboard.press("Digit2");
    const secondSelected = await page.locator(".lane").nth(1).locator("input[name='selected-video']").isChecked();
    if (!secondSelected) throw new Error("Keyboard shortcut 2 did not select the second ready video");

    await assertNoCriticalOverlap(page);
    const screenshot = path.join(screenshotRoot, viewport.name);
    await page.screenshot({ path: screenshot, fullPage: true });
    summary.push({ viewport: `${viewport.width}x${viewport.height}`, screenshot });
    await page.close();
  }
  await assertProductionFailureDoesNotLeakDemo(browser);
  await assertEmptySnapshotPadsToThree(browser);
  await assertMediaTokenAndMutationFailures(browser);
  await assertHeartbeatDoesNotReplaceSnapshot(browser);
  await browser.close();
  console.log(JSON.stringify({ ok: true, summary }, null, 2));
} finally {
  server.child.kill("SIGTERM");
}

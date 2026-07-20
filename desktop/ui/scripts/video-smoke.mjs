import { chromium } from "playwright";

const baseUrl = process.env.REELS_DESKTOP_URL;
if (!baseUrl) {
  throw new Error("REELS_DESKTOP_URL is required");
}

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage();
await page.goto(baseUrl, { waitUntil: "networkidle" });
await page.waitForSelector("video", { state: "attached" });

const result = await page.evaluate(async () => {
  const videos = Array.from(document.querySelectorAll("video"));
  await Promise.all(
    videos.map(
      (video) =>
        new Promise((resolve, reject) => {
          const done = () => resolve(true);
          const fail = () => reject(new Error(`video failed: ${video.currentSrc}`));
          video.addEventListener("loadedmetadata", done, { once: true });
          video.addEventListener("error", fail, { once: true });
          video.load();
        })
    )
  );
  await Promise.all(
    videos.map(
      (video) =>
        new Promise((resolve, reject) => {
          const target = Math.min(1, Math.max(0.1, video.duration / 2));
          const done = () => resolve(video.currentTime);
          const fail = () => reject(new Error(`seek failed: ${video.currentSrc}`));
          video.addEventListener("seeked", done, { once: true });
          video.addEventListener("error", fail, { once: true });
          video.currentTime = target;
        })
    )
  );
  return videos.map((video) => ({
    src: video.currentSrc,
    duration: video.duration,
    currentTime: video.currentTime,
    readyState: video.readyState
  }));
});

await browser.close();
console.log(JSON.stringify({ videoCount: result.length, videos: result }, null, 2));

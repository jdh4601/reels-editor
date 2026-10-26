import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  CircleAlert,
  Clock3,
  Copy,
  Download,
  FolderOpen,
  FolderX,
  History,
  ImageOff,
  Link,
  Loader2,
  MessageSquareText,
  NotebookPen,
  Pencil,
  Plus,
  X,
  RefreshCcw,
  Scissors,
  Settings2,
  Trash2,
  Volume2,
  VolumeX,
  WifiOff,
} from "lucide-react";
import "./styles.css";

type LaneStatus = "queued" | "rendering" | "ready" | "overlaying" | "failed";
type JobStatus = "idle" | "loading" | "generating" | "awaiting_selection" | "rendering_base" | "rendering_overlay" | "ready" | "exporting" | "failed" | "cancelled";
type ConnectionState = "connected" | "connecting" | "disconnected";
type ExportState = "idle" | "exporting" | "done" | "failed";
type ContentType = "story" | "strategy" | "failure" | "principle";
type ModelProvider = "codex-cli" | "claude-cli" | "gemini-cli" | "openai" | "kimi";
type SettingsSaveState = "idle" | "saving" | "saved" | "error";
type CaptionActionState = "idle" | "generating" | "error" | "copied";
type NoteActionState = "idle" | "saving" | "saved" | "error";
type TitleActionState = "idle" | "generating" | "saving" | "error" | "suggested" | "saved";
type MetadataDraft = { name: string; role: string };
type TitleDraft = { upper: string; lower: string };
type AppView = "workspace" | "archive";
type PlaybackSpeedSettings = {
  speed: number;
};
type GoogleDriveSettings = {
  configured: boolean;
  my_drive_path: string;
  cancelled?: boolean;
};

type MediaItem = {
  name: string;
  url: string;
  size?: number;
};

type StorySection = {
  beat: string;
  role: string;
  text: string;
};

type Storyline = {
  id: string;
  serverId: string;
  index: number;
  label: string;
  hook: string;
  summary: string;
  sections: StorySection[];
  status: LaneStatus;
  progress: number;
  videoUrl: string | null;
  thumbnailUrl?: string | null;
  title: string;
  titleUpper: string;
  titleLower: string;
  speaker?: { name: string; role: string };
  episodeNumber?: number;
  instagramCaption: string;
  error?: string;
  revision: number;
};

type ContentCandidate = {
  id: string;
  contentType: ContentType;
  typeLabel: string;
  title: string;
  summary: string;
  takeaway: string;
};

type DownloadProgress = {
  component: "video" | "audio" | "media";
  component_fraction: number;
  downloaded_bytes: number | null;
  total_bytes: number | null;
  finished: boolean;
};

type Snapshot = {
  jobId: string;
  jobStatus: JobStatus;
  jobPhase: string | null;
  jobProgress: number;
  jobMessage: string | null;
  downloadProgress?: DownloadProgress | null;
  jobError: string | null;
  projectName: string;
  sourceUrl: string | null;
  transcriptLanguage: string | null;
  transcriptKind: string | null;
  sourceLabel: string;
  connection: ConnectionState;
  generatedAt: string;
  storylines: Storyline[];
  selectedStorylineId: string | null;
  subtitlesEnabled: boolean;
  durationS: number;
  nStorylines: number;
  contentTypes: ContentType[];
  candidates: ContentCandidate[];
  selectedCandidateIds: string[];
  provider: ModelProvider;
  model: string;
  outputLanguage?: "ko" | "en" | "zh";
  episodeNumber: number;
  eventSeq: number;
};

type ArchiveItem = {
  id: string;
  jobId: string;
  storylineId: string;
  episodeNumber: number;
  projectName: string;
  reelTitle: string;
  sourceUrl: string | null;
  thumbnailUrl: string | null;
  videoUrl: string | null;
  completedAt: string | null;
};

type ApiArchiveItem = {
  id?: string;
  job_id?: string;
  jobId?: string;
  storyline_id?: string | null;
  storylineId?: string | null;
  episode_number?: number;
  episodeNumber?: number;
  project_name?: string;
  projectName?: string;
  source_title?: string;
  sourceTitle?: string;
  reel_title?: string;
  reelTitle?: string;
  storyline_title?: string;
  storylineTitle?: string;
  title?: string;
  title_upper?: string;
  titleUpper?: string;
  title_lower?: string;
  titleLower?: string;
  source_url?: string | null;
  sourceUrl?: string | null;
  source_thumbnail_url?: string | null;
  sourceThumbnailUrl?: string | null;
  thumbnail_url?: string | null;
  thumbnailUrl?: string | null;
  video_url?: string | null;
  videoUrl?: string | null;
  completed_at?: string | null;
  completedAt?: string | null;
  generated_at?: string | null;
  generatedAt?: string | null;
  status?: string;
};

type ApiStoryline = {
  thumbnail_url?: string | null;
  id?: string;
  storyline_id?: string;
  index?: number;
  label?: string;
  hook?: string;
  summary?: string;
  sections?: StorySection[];
  status?: LaneStatus;
  progress?: number;
  video_url?: string | null;
  videoUrl?: string | null;
  title?: string;
  title_upper?: string;
  titleUpper?: string;
  title_lower?: string;
  titleLower?: string;
  speaker?: { name: string; role: string };
  episode_number?: number;
  instagram_caption?: string;
  instagramCaption?: string;
  error?: string;
  revision?: number;
};

type ApiSnapshot = {
  job_id?: string;
  jobId?: string;
  status?: JobStatus;
  phase?: string | null;
  progress?: number;
  message?: string | null;
  download_progress?: DownloadProgress | null;
  error?: string | null;
  project_name?: string;
  projectName?: string;
  source_url?: string | null;
  sourceUrl?: string | null;
  output_language?: "ko" | "en" | "zh";
  transcript_language?: string | null;
  transcriptLanguage?: string | null;
  transcript_kind?: string | null;
  transcriptKind?: string | null;
  source_label?: string;
  sourceLabel?: string;
  connection?: ConnectionState;
  generated_at?: string;
  generatedAt?: string;
  storylines?: ApiStoryline[];
  selected_storyline_id?: string | null;
  selectedStorylineId?: string | null;
  subtitles_on?: boolean;
  subtitlesEnabled?: boolean;
  duration_s?: number;
  durationS?: number;
  n_storylines?: number;
  nStorylines?: number;
  content_types?: ContentType[];
  contentTypes?: ContentType[];
  candidates?: Array<{
    id?: string;
    content_type?: ContentType;
    contentType?: ContentType;
    type_label?: string;
    typeLabel?: string;
    title?: string;
    summary?: string;
    takeaway?: string;
  }>;
  selected_candidate_ids?: string[];
  selectedCandidateIds?: string[];
  provider?: string;
  model?: string;
  episode_number?: number;
  episodeNumber?: number;
  seq?: number;
  event_seq?: number;
};

type EventPayload =
  | ApiSnapshot
  | { snapshot?: ApiSnapshot; seq?: number; event_seq?: number }
  | { event: "heartbeat"; seq?: number; event_seq?: number };

const DEMO_TITLES = ["Why Practice Was Not Enough", "How a Simple Note Changed Daily Practice", "Leave One Question After Reading"];
const DEMO_SUMMARIES = ["Synthetic preview about practice.", "Synthetic preview about taking notes.", "Synthetic preview about reading habits."];
const DEMO_SECTIONS: StorySection[][] = DEMO_TITLES.map((title) => [
  { beat: "Hook", role: "Key question", text: title },
  { beat: "Context", role: "Source evidence", text: "The selected original speech appears here in an actual video." },
  { beat: "Conclusion", role: "Preview information", text: "This preview uses synthetic data, not a real interview quotation." },
]);

const STATUS_LABEL: Record<LaneStatus, string> = {
  queued: "Queued",
  rendering: "Rendering",
  ready: "Ready",
  overlaying: "Updating overlay",
  failed: "Failed",
};

const EMPTY_TITLE = "Title pending";
const EMPTY_SUMMARY = "Paste a YouTube video link to see clip ideas and hook titles here.";
const ACTIVE_JOB_STATUSES = new Set<JobStatus>(["loading", "generating", "rendering_base", "rendering_overlay", "exporting"]);
const GENERATION_JOB_STATUSES = new Set<JobStatus>(["loading", "generating", "rendering_base", "rendering_overlay"]);
const GENERATION_STAGES = [
  { label: "Download captions" },
  { label: "Prepare captions" },
  { label: "Generate ideas and titles" },
  { label: "Generate reel scripts" },
  { label: "Render video" },
  { label: "Final review" },
] as const;
const ALL_CONTENT_TYPES: ContentType[] = ["story", "strategy", "failure", "principle"];
const MIN_PLAYBACK_SPEED = 1;
const MAX_PLAYBACK_SPEED = 1.5;
const PLAYBACK_SPEED_STEP = 0.05;
const DEFAULT_PLAYBACK_SPEED = 1.2;
const DEFAULT_EPISODE_NUMBER = 1;
const REELS_EDITOR_LOGO_URL = new URL("../../assets/reels-editor-icon.png", import.meta.url).href;
const PROVIDER_OPTIONS: Array<{ value: ModelProvider; label: string; description: string }> = [
  { value: "codex-cli", label: "Codex CLI", description: "Uses your local Codex sign-in and selected model." },
  { value: "claude-cli", label: "Claude CLI", description: "Uses your installed Claude Code CLI." },
  { value: "gemini-cli", label: "Gemini CLI", description: "Uses your local Gemini sign-in and default model." },
  { value: "openai", label: "OpenAI API", description: "Uses credentials from OPENAI_API_KEY." },
  { value: "kimi", label: "Kimi API", description: "Uses credentials from MOONSHOT_API_KEY." },
];
const MODEL_OPTIONS: Record<ModelProvider, Array<{ value: string; label: string }>> = {
  "codex-cli": [
    { value: "gpt-5.6-sol", label: "5.6 Sol" },
    { value: "gpt-5.6-terra", label: "5.6 Terra" },
    { value: "gpt-5.6-luna", label: "5.6 Luna" },
    { value: "gpt-5.5", label: "5.5" },
    { value: "gpt-5.4", label: "5.4" },
    { value: "gpt-5.4-mini", label: "5.4 mini" },
  ],
  "claude-cli": [{ value: "", label: "Default model" }],
  "gemini-cli": [{ value: "", label: "Default model" }],
  openai: [{ value: "gpt-4o", label: "GPT-4o" }],
  kimi: [{ value: "kimi-k2-0905-preview", label: "Kimi K2" }],
};

function defaultModel(provider: ModelProvider): string {
  return MODEL_OPTIONS[provider][0]?.value ?? "";
}

function modelProvider(value: string | undefined): ModelProvider {
  return PROVIDER_OPTIONS.some((option) => option.value === value) ? value as ModelProvider : "codex-cli";
}

function positiveInteger(value: unknown, fallback = DEFAULT_EPISODE_NUMBER): number {
  const number = typeof value === "number" ? value : Number(value);
  return Number.isInteger(number) && number > 0 ? number : fallback;
}

function youtubeVideoId(value: string | null | undefined): string | null {
  if (!value?.trim()) return null;
  try {
    const parsed = new URL(value.trim());
    const hostname = parsed.hostname.toLowerCase().replace(/^www\./, "").replace(/^m\./, "");
    let candidate: string | null = null;
    if (hostname === "youtu.be") {
      candidate = parsed.pathname.split("/").filter(Boolean)[0] ?? null;
    } else if (hostname === "youtube.com" || hostname === "music.youtube.com") {
      if (parsed.pathname === "/watch") candidate = parsed.searchParams.get("v");
      else {
        const [kind, id] = parsed.pathname.split("/").filter(Boolean);
        if (["shorts", "embed", "live"].includes(kind)) candidate = id ?? null;
      }
    }
    return candidate && /^[A-Za-z0-9_-]{11}$/.test(candidate) ? candidate : null;
  } catch {
    return null;
  }
}

function youtubeThumbnailUrl(sourceUrl: string | null | undefined): string | null {
  const videoId = youtubeVideoId(sourceUrl);
  return videoId ? `https://img.youtube.com/vi/${videoId}/hqdefault.jpg` : null;
}

function titleDisplayLength(title: string): number {
  const compact = title.replace(/\s/gu, "");
  return Array.from(new Intl.Segmenter("en", { granularity: "grapheme" }).segment(compact)).length;
}

function combineTitleLines(draft: TitleDraft): string {
  return [draft.upper.trim(), draft.lower.trim()].filter(Boolean).join(" ");
}

function splitTitleForEditor(title: string): TitleDraft {
  const normalized = title.trim().replace(/\s+/gu, " ");
  if (titleDisplayLength(normalized) <= 11) return { upper: "", lower: normalized };
  const words = normalized.split(" ");
  if (words.length > 1) {
    const choices = words.slice(1).map((_, index) => ({
      upper: words.slice(0, index + 1).join(" "),
      lower: words.slice(index + 1).join(" "),
    }));
    return choices.reduce((best, candidate) => {
      const bestDifference = Math.abs(titleDisplayLength(best.upper) - titleDisplayLength(best.lower));
      const candidateDifference = Math.abs(titleDisplayLength(candidate.upper) - titleDisplayLength(candidate.lower));
      return candidateDifference < bestDifference ? candidate : best;
    });
  }
  const graphemes = Array.from(new Intl.Segmenter("en", { granularity: "grapheme" }).segment(normalized), (item) => item.segment);
  const midpoint = Math.ceil(graphemes.length / 2);
  return { upper: graphemes.slice(0, midpoint).join(""), lower: graphemes.slice(midpoint).join("") };
}

function titleValidationMessage(draft: TitleDraft): string | null {
  if (!draft.lower.trim()) return "Enter the second title line.";
  const length = titleDisplayLength(combineTitleLines(draft));
  if (length < 6) return "The on-screen title needs at least 6 characters, excluding spaces.";
  if (length > 24) return "The on-screen title can have up to 24 characters, excluding spaces.";
  return null;
}

function cacheBustedMediaUrl(url: string | null, revision: string | number): string | null {
  if (!url) return null;
  const parsed = new URL(url, window.location.origin);
  parsed.searchParams.set("revision", String(revision));
  return `${parsed.pathname}${parsed.search}${parsed.hash}`;
}

function formatArchiveDate(value: string | null): string {
  if (!value) return "No completion date";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeStyle: "short" }).format(date);
}

function normalizeArchiveItem(item: ApiArchiveItem, index: number): ArchiveItem | null {
  if (item.status && !["ready", "completed"].includes(item.status)) return null;
  const jobId = item.job_id ?? item.jobId;
  if (!jobId) return null;
  const storylineId = item.storyline_id ?? item.storylineId ?? null;
  if (!storylineId) return null;
  const sourceUrl = item.source_url ?? item.sourceUrl ?? null;
  const videoUrl = mediaUrl(item.video_url ?? item.videoUrl ?? null);
  if (!videoUrl) return null;
  return {
    id: item.id ?? `${jobId}:${storylineId ?? index}`,
    jobId,
    storylineId,
    episodeNumber: positiveInteger(item.episode_number ?? item.episodeNumber),
    projectName: item.project_name ?? item.projectName ?? item.source_title ?? item.sourceTitle ?? "Untitled video",
    reelTitle: item.reel_title ?? item.reelTitle ?? item.storyline_title ?? item.storylineTitle ?? item.title ?? "Untitled reel",
    sourceUrl,
    thumbnailUrl: mediaUrl(
      item.thumbnail_url
      ?? item.thumbnailUrl
      ?? item.source_thumbnail_url
      ?? item.sourceThumbnailUrl
      ?? youtubeThumbnailUrl(sourceUrl)),
    videoUrl,
    completedAt: item.completed_at ?? item.completedAt ?? item.generated_at ?? item.generatedAt ?? null,
  };
}

function exportedPathFromPayload(payload: unknown): string | null {
  if (!payload || typeof payload !== "object") return null;
  const record = payload as Record<string, unknown>;
  for (const key of ["path", "export_path", "archive_path", "export_root"]) {
    if (typeof record[key] === "string" && record[key]) return record[key];
  }
  for (const key of ["paths", "exported_paths", "items"]) {
    const value = record[key];
    if (!Array.isArray(value) || value.length === 0) continue;
    const first = value[0];
    if (typeof first === "string") return first;
    if (first && typeof first === "object" && typeof (first as Record<string, unknown>).path === "string") {
      return (first as Record<string, string>).path;
    }
  }
  const exportState = record.export;
  if (exportState && typeof exportState === "object") {
    const exportRecord = exportState as Record<string, unknown>;
    const outputPath = exportRecord.output_path ?? exportRecord.outputPath;
    if (typeof outputPath === "string" && outputPath) return outputPath;
  }
  return null;
}

function completedOnlySnapshot(snapshot: Snapshot, selectedStorylineId: string | null = snapshot.selectedStorylineId): Snapshot {
  const storylines = snapshot.storylines.filter((storyline) => storyline.status === "ready" && Boolean(storyline.videoUrl));
  return {
    ...snapshot,
    storylines,
    nStorylines: storylines.length,
    selectedStorylineId: selectedStorylineId && storylines.some((storyline) => storyline.id === selectedStorylineId)
      ? selectedStorylineId
      : storylines[0]?.id ?? null,
  };
}

function progressPercent(value: number | undefined): number {
  if (value === undefined || !Number.isFinite(value)) return 0;
  const percent = value <= 1 ? value * 100 : value;
  return Math.max(0, Math.min(100, Math.round(percent)));
}

function normalizePlaybackSpeed(value: number): number {
  const stepped = Math.round(value / PLAYBACK_SPEED_STEP) * PLAYBACK_SPEED_STEP;
  return Number(Math.min(MAX_PLAYBACK_SPEED, Math.max(MIN_PLAYBACK_SPEED, stepped)).toFixed(2));
}

function playbackSpeedLabel(value: number): string {
  return value.toFixed(value * 10 === Math.round(value * 10) ? 1 : 2);
}

function generationStageIndex(phase: string | null | undefined, status: JobStatus): number {
  if (phase === "review") return 5;
  if (phase === "transcript") return 1;
  if (phase === "analyzing") return 2;
  if (status === "generating" || phase === "generating") return 3;
  if (["rendering", "overlay"].includes(phase ?? "") || status === "rendering_base" || status === "rendering_overlay") return 4;
  return 0;
}

function estimatedRenderMinutes(storylineCount: number): number {
  const count = Math.max(1, storylineCount);
  return Math.max(2.5, Math.ceil(count / 2) * 2.5);
}

function estimatedRemainingMinutes(
  phase: string | null | undefined,
  status: JobStatus,
  progress: number,
  renderMinutes: number,
): number {
  if (["rendering", "overlay"].includes(phase ?? "") || status === "rendering_base" || status === "rendering_overlay") {
    const renderProgress = Math.max(0, Math.min(1, (progress - 28) / 68));
    return Math.max(0.5, renderMinutes * (1 - renderProgress));
  }
  if (status === "generating" || phase === "generating") return renderMinutes + 1;
  if (phase === "analyzing") return renderMinutes + 2;
  if (phase === "transcript") return renderMinutes + 3;
  if (phase === "downloading") {
    const downloadProgress = Math.max(0, Math.min(1, (progress - 4) / 10));
    return renderMinutes + 2 + 2 * (1 - downloadProgress);
  }
  return renderMinutes + 4;
}

function remainingTimeLabel(minutes: number): string {
  return minutes <= 1 ? "Less than a minute" : `About ${Math.ceil(minutes)} minutes`;
}

function isDemoMode(): boolean {
  return new URLSearchParams(window.location.search).has("demo");
}

function sessionToken(): string | null {
  const hashToken = new URLSearchParams(window.location.hash.replace(/^#/, "")).get("token");
  return hashToken ?? new URLSearchParams(window.location.search).get("token");
}

function apiUrl(path: string, params: Record<string, string | number | boolean | null | undefined> = {}): string {
  const url = new URL(path, window.location.origin);
  Object.entries(params).forEach(([key, value]) => {
    if (value !== null && value !== undefined) url.searchParams.set(key, String(value));
  });
  return `${url.pathname}${url.search}`;
}

function wsUrl(path: string, params: Record<string, string | number | boolean | null | undefined> = {}): string {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  const token = sessionToken();
  return `${scheme}://${window.location.host}${apiUrl(path, { ...params, token })}`;
}

function apiFetch(path: string, init?: RequestInit, params?: Record<string, string | number | boolean | null | undefined>) {
  const headers = new Headers(init?.headers);
  const token = sessionToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  return fetch(apiUrl(path, params), { ...init, headers });
}

async function apiMutation(path: string, init?: RequestInit, params?: Record<string, string | number | boolean | null | undefined>) {
  const response = await apiFetch(path, init, params);
  if (!response.ok) {
    let detail = `request failed: ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload.detail) detail = payload.detail;
    } catch {
      // JSON이 아닌 오류 응답은 상태 코드 메시지를 유지한다.
    }
    throw new Error(detail);
  }
  return response;
}

function mediaUrl(url: string | null): string | null {
  if (!url) return url;
  if (!url.startsWith("/")) return url;
  const token = sessionToken();
  return apiUrl(url, { token });
}

function makePlaceholderStoryline(index: number): Storyline {
  return {
    id: `placeholder-${index + 1}`,
    serverId: `placeholder-${index + 1}`,
    index: index + 1,
    label: `Reel ${index + 1}`,
    hook: "Pending",
    summary: EMPTY_SUMMARY,
    sections: [],
    status: "queued",
    progress: 0,
    videoUrl: null,
    title: EMPTY_TITLE,
    titleUpper: "",
    titleLower: EMPTY_TITLE,
    instagramCaption: "",
    revision: 0,
  };
}

function makeEmptySnapshot(connection: ConnectionState = "disconnected"): Snapshot {
  return {
    jobId: "empty",
    jobStatus: "idle",
    jobPhase: null,
    jobProgress: 0,
    jobMessage: null,
    jobError: null,
    projectName: "Reels Editor",
    sourceUrl: null,
    transcriptLanguage: null,
    transcriptKind: null,
    sourceLabel: "No YouTube link",
    connection,
    generatedAt: new Date().toISOString(),
    selectedStorylineId: null,
    subtitlesEnabled: true,
    durationS: 35,
    nStorylines: 0,
    contentTypes: ALL_CONTENT_TYPES,
    candidates: [],
    selectedCandidateIds: [],
    provider: "codex-cli",
    model: defaultModel("codex-cli"),
    episodeNumber: DEFAULT_EPISODE_NUMBER,
    eventSeq: 0,
    storylines: [],
  };
}

function makeDemoSnapshot(media?: MediaItem[]): Snapshot {
  const items = media?.length ? media : [1, 2, 3].map((number) => ({ name: `sample-${number}.mp4`, url: `/media/sample-${number}.mp4` }));
  const showGenerationProgress = new URLSearchParams(window.location.search).has("generation-progress");
  return {
    jobId: "demo-job-synthetic",
    jobStatus: showGenerationProgress ? "rendering_base" : "ready",
    jobPhase: showGenerationProgress ? "rendering" : "ready",
    jobProgress: showGenerationProgress ? 64 : 100,
    jobMessage: showGenerationProgress
      ? "Reel 2: compositing title, subtitles and audio. 1 of 3 complete."
      : "3 videos are ready.",
    jobError: null,
    projectName: "Synthetic video preview",
    sourceUrl: "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    transcriptLanguage: "en",
    transcriptKind: "automatic",
    sourceLabel: "YouTube · English automatic captions",
    connection: "connected",
    generatedAt: "2026-07-20T09:00:00+09:00",
    selectedStorylineId: "storyline-1",
    subtitlesEnabled: true,
    durationS: 35,
    nStorylines: 3,
    contentTypes: ALL_CONTENT_TYPES,
    candidates: [],
    selectedCandidateIds: [],
    provider: "codex-cli",
    model: defaultModel("codex-cli"),
    episodeNumber: 37,
    eventSeq: 1,
    storylines: [0, 1, 2].map((index) => ({
      id: `storyline-${index + 1}`,
      serverId: `storyline-${index + 1}`,
      index: index + 1,
      label: `Reel ${index + 1}`,
      hook: ["Practice methods", "Taking notes", "Reading questions"][index],
      summary: DEMO_SUMMARIES[index],
      sections: DEMO_SECTIONS[index],
      status: showGenerationProgress ? (["ready", "overlaying", "rendering"] as LaneStatus[])[index] : "ready",
      progress: showGenerationProgress ? [100, 78, 45][index] : 100,
      videoUrl: mediaUrl(items[index]?.url ?? `/media/sample-${index + 1}.mp4`),
      title: DEMO_TITLES[index],
      titleUpper: splitTitleForEditor(DEMO_TITLES[index]).upper,
      titleLower: splitTitleForEditor(DEMO_TITLES[index]).lower,
      instagramCaption: "",
      revision: 1,
    })),
  };
}

function normalizeSnapshot(payload: ApiSnapshot): Snapshot {
  const targetStorylineCount = Math.max(0, Math.min(10, payload.n_storylines ?? payload.nStorylines ?? 0));
  const storylines: Storyline[] = (payload.storylines ?? []).slice(0, targetStorylineCount).map((storyline, index) => {
    const title = storyline.title ?? EMPTY_TITLE;
    const fallbackLines = splitTitleForEditor(title);
    const serverId = storyline.storyline_id ?? storyline.id ?? `storyline-${index + 1}`;
    return {
      id: serverId,
      serverId,
      index: storyline.index ?? index + 1,
      label: storyline.label ?? `Reel ${index + 1}`,
      hook: storyline.hook ?? title ?? "Video",
      summary: storyline.summary ?? EMPTY_SUMMARY,
      sections: (storyline.sections ?? []).filter(
        (section) => section.beat.trim() && section.role.trim() && section.text.trim(),
      ),
      status: storyline.status ?? "queued",
      progress: storyline.progress ?? 0,
      videoUrl: mediaUrl(storyline.video_url ?? storyline.videoUrl ?? null),
      thumbnailUrl: mediaUrl(storyline.thumbnail_url ?? null),
      title,
      titleUpper: storyline.title_upper ?? storyline.titleUpper ?? fallbackLines.upper,
      titleLower: storyline.title_lower ?? storyline.titleLower ?? fallbackLines.lower,
      speaker: storyline.speaker,
      episodeNumber: storyline.episode_number ?? payload.episode_number ?? DEFAULT_EPISODE_NUMBER,
      instagramCaption: storyline.instagram_caption ?? storyline.instagramCaption ?? "",
      error: storyline.error,
      revision: storyline.revision ?? 1,
    };
  });
  while (storylines.length < targetStorylineCount) {
    storylines.push(makePlaceholderStoryline(storylines.length));
  }

  return {
    jobId: (payload.job_id ?? payload.jobId ?? "active-job") || "empty",
    jobStatus: payload.status ?? "idle",
    jobPhase: payload.phase ?? null,
    jobProgress: progressPercent(payload.progress),
    jobMessage: payload.message ?? null,
    downloadProgress: payload.download_progress ?? null,
    jobError: payload.error ?? null,
    projectName: payload.project_name ?? payload.projectName ?? "Reels Editor",
    sourceUrl: payload.source_url ?? payload.sourceUrl ?? null,
    transcriptLanguage: payload.transcript_language ?? payload.transcriptLanguage ?? null,
    transcriptKind: payload.transcript_kind ?? payload.transcriptKind ?? null,
    sourceLabel: payload.source_label ?? payload.sourceLabel ?? "Selected source",
    connection: payload.connection ?? "connected",
    generatedAt: payload.generated_at ?? payload.generatedAt ?? new Date().toISOString(),
    storylines,
    selectedStorylineId:
      payload.selected_storyline_id ??
      payload.selectedStorylineId ??
      storylines.find((storyline) => storyline.status === "ready")?.id ??
      null,
    subtitlesEnabled: payload.subtitles_on ?? payload.subtitlesEnabled ?? true,
    durationS: payload.duration_s ?? payload.durationS ?? 35,
    nStorylines: targetStorylineCount,
    contentTypes: payload.content_types ?? payload.contentTypes ?? ALL_CONTENT_TYPES,
    candidates: (payload.candidates ?? []).map((candidate, index) => ({
      id: candidate.id ?? `c${index + 1}`,
      contentType: candidate.content_type ?? candidate.contentType ?? "principle",
      typeLabel: candidate.type_label ?? candidate.typeLabel ?? "Principle",
      title: candidate.title ?? "Untitled",
      summary: candidate.summary ?? "",
      takeaway: candidate.takeaway ?? "",
    })),
    selectedCandidateIds: payload.selected_candidate_ids ?? payload.selectedCandidateIds ?? [],
    provider: modelProvider(payload.provider),
    model: payload.model ?? "",
    outputLanguage: payload.output_language ?? "ko",
    episodeNumber: positiveInteger(payload.episode_number ?? payload.episodeNumber),
    eventSeq: payload.event_seq ?? payload.seq ?? 0,
  };
}

function extractSnapshot(payload: ApiSnapshot | { snapshot?: ApiSnapshot }): ApiSnapshot {
  if ("snapshot" in payload && payload.snapshot) return payload.snapshot;
  return payload as ApiSnapshot;
}

function isHeartbeat(payload: EventPayload): payload is { event: "heartbeat"; seq?: number; event_seq?: number } {
  return "event" in payload && payload.event === "heartbeat";
}

async function readSnapshot(jobId?: string | null): Promise<Snapshot> {
  if (jobId === "empty") return makeEmptySnapshot("connected");
  const demo = isDemoMode();
  if (demo) {
    try {
      const response = await apiFetch("/api/media", undefined, { demo: 1 });
      if (response.ok) {
        const payload = (await response.json()) as { items?: MediaItem[] };
        return makeDemoSnapshot(payload.items);
      }
    } catch {
      return makeDemoSnapshot();
    }
    return makeDemoSnapshot();
  }

  const snapshotResponse = await apiFetch("/api/snapshot", undefined, { job_id: jobId });
  if (!snapshotResponse.ok) throw new Error("snapshot unavailable");
  return normalizeSnapshot((await snapshotResponse.json()) as ApiSnapshot);
}

function statusTone(status: LaneStatus): string {
  if (status === "ready") return "ready";
  if (status === "failed") return "failed";
  if (status === "overlaying") return "overlay";
  return "working";
}

function Thumbnail({ src, alt, className }: { src: string; alt: string; className: string }) {
  const [failed, setFailed] = useState(false);

  useEffect(() => setFailed(false), [src]);

  if (failed) {
    return (
      <div className={`${className} thumbnail-fallback`} role="img" aria-label={`${alt}  preview could not be loaded`}>
        <ImageOff size={18} aria-hidden="true" />
        <span>No preview</span>
      </div>
    );
  }

  return <img className={className} src={src} alt={alt} onError={() => setFailed(true)} />;
}

const MAX_WORKSPACE_TABS = 3;

type WorkspaceTab = { id: string; initialJobId?: string; label: string; status: JobStatus; busy: boolean };
function TabbedApp() {
  const [tabs, setTabs] = useState<WorkspaceTab[]>([{ id: "workspace-1", label: "Workspace 1", status: "idle", busy: false }]);
  const [activeTab, setActiveTab] = useState("workspace-1");
  const updateTab = useCallback((id: string, next: Snapshot, busy: boolean) => {
    setTabs((current) => current.map((tab) => tab.id === id ? {
      ...tab, label: next.sourceUrl ? next.projectName : "New workspace", status: next.jobStatus, busy,
    } : tab));
  }, []);
  function addTab() {
    if (tabs.length >= MAX_WORKSPACE_TABS) return;
    const id = `workspace-${crypto.randomUUID()}`;
    setTabs((current) => current.length < MAX_WORKSPACE_TABS
      ? [...current, { id, initialJobId: "empty", label: "New workspace", status: "idle", busy: false }]
      : current);
    setActiveTab(id);
  }

  function closeTab(tab: WorkspaceTab) {
    if (tab.busy || tabs.length === 1) return;
    setTabs((current) => current.filter((item) => item.id !== tab.id));
    if (activeTab === tab.id) setActiveTab(tabs.find((item) => item.id !== tab.id)!.id);
  }

  return <>
    <nav className="workspace-tabs" aria-label="Reel workspaces">
      <div role="tablist" aria-label="Parallel workspaces (up to 3)">
        {tabs.map((tab, index) => <div className="workspace-tab" key={tab.id}>
          <button type="button" role="tab" id={`${tab.id}-tab`} aria-controls={`${tab.id}-panel`}
            aria-selected={activeTab === tab.id} tabIndex={activeTab === tab.id ? 0 : -1}
            title={tab.label} onClick={() => setActiveTab(tab.id)} onKeyDown={(event) => {
              if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
              event.preventDefault();
              const nextIndex = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1
                : (index + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
              setActiveTab(tabs[nextIndex].id);
              document.getElementById(`${tabs[nextIndex].id}-tab`)?.focus();
            }}>
            {tab.busy ? <Loader2 size={14} className="spin" /> : tab.status === "ready" ? <CheckCircle2 size={14} /> : null}
            <span>{index + 1}. {tab.label}</span>
            <small>{tab.busy ? "Processing" : tab.status === "awaiting_selection" ? "Choose clips" : tab.status === "failed" ? "Failed" : tab.status === "ready" ? "Done" : "Queued"}</small>
          </button>
          <button type="button" className="workspace-tab-close" aria-label={`Close workspace ${index + 1} tab`}
            disabled={tab.busy || tabs.length === 1} title={tab.busy ? "You can close this tab when processing finishes." : " tab"}
            onClick={() => closeTab(tab)}><X size={14} /></button>
        </div>)}
      </div>
      <button type="button" className="workspace-tab-add" disabled={tabs.length >= MAX_WORKSPACE_TABS} onClick={addTab}>
        <Plus size={16} /> New tab <small>{tabs.length}/{MAX_WORKSPACE_TABS}</small>
      </button>
    </nav>
    {tabs.map((tab) => <div key={tab.id} role="tabpanel" id={`${tab.id}-panel`} aria-labelledby={`${tab.id}-tab`} hidden={activeTab !== tab.id}>
      <App tabId={tab.id} active={activeTab === tab.id} initialJobId={tab.initialJobId} onTabUpdate={updateTab} />
    </div>)}
  </>;
}
function App({ tabId, active, initialJobId, onTabUpdate }: {
  tabId: string; active: boolean; initialJobId?: string;
  onTabUpdate: (id: string, next: Snapshot, busy: boolean) => void;
}) {
  const initialJobIdRef = useRef(initialJobId);
  const requestPendingRef = useRef(false);
  const [requestPending, setRequestPending] = useState(false);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedExportIds, setSelectedExportIds] = useState<string[]>([]);
  const [expandedDetailsId, setExpandedDetailsId] = useState<string | null>(null);
  const [soundEnabled, setSoundEnabled] = useState(true);
  const [audioNeedsGesture, setAudioNeedsGesture] = useState(false);
  const [connection, setConnection] = useState<ConnectionState>("connecting");
  const [exportState, setExportState] = useState<ExportState>("idle");
  const [selectedCandidateIds, setSelectedCandidateIds] = useState<string[]>([]);
  const [selectedProvider, setSelectedProvider] = useState<ModelProvider>("codex-cli");
  const [selectedModel, setSelectedModel] = useState(defaultModel("codex-cli"));
  const [playbackSpeed, setPlaybackSpeed] = useState(DEFAULT_PLAYBACK_SPEED);
  const [speedSettingsSaveState, setSpeedSettingsSaveState] = useState<SettingsSaveState>("idle");
  const [googleDriveSettings, setGoogleDriveSettings] = useState<GoogleDriveSettings | null>(null);
  const [googleDriveConnecting, setGoogleDriveConnecting] = useState(false);
  const [youtubeUrl, setYoutubeUrl] = useState("");
  const [outputLanguage, setOutputLanguage] = useState<"ko" | "en" | "zh">(() => {
    const saved = localStorage.getItem("reels-output-language-v2");
    return saved === "ko" || saved === "zh" ? saved : "en";
  });
  const [youtubeError, setYoutubeError] = useState<string | null>(null);
  const [appView, setAppView] = useState<AppView>("workspace");
  const [archiveMode, setArchiveMode] = useState(false);
  const [archiveItems, setArchiveItems] = useState<ArchiveItem[]>([]);
  const [archiveLoading, setArchiveLoading] = useState(false);
  const [archiveError, setArchiveError] = useState<string | null>(null);
  const [openingArchiveId, setOpeningArchiveId] = useState<string | null>(null);
  const [deletingArchiveId, setDeletingArchiveId] = useState<string | null>(null);
  const [deletingAllArchive, setDeletingAllArchive] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const settingsMenuRef = useRef<HTMLDivElement | null>(null);
  const settingsTriggerRef = useRef<HTMLButtonElement | null>(null);
  const settingsDialogRef = useRef<HTMLDivElement | null>(null);
  const settingsFirstControlRef = useRef<HTMLInputElement | null>(null);
  const restoreSettingsFocusRef = useRef(false);
  const archiveHeadingRef = useRef<HTMLHeadingElement | null>(null);
  const workspaceHeadingRef = useRef<HTMLHeadingElement | null>(null);
  const pendingViewFocusRef = useRef<AppView | null>(null);
  const [eventConnectionVersion, setEventConnectionVersion] = useState(0);
  const [liveMessage, setLiveMessage] = useState("Connecting to the workspace");
  const [captionStates, setCaptionStates] = useState<Record<string, CaptionActionState>>({});
  const [captionErrors, setCaptionErrors] = useState<Record<string, string | null>>({});
  const [noteStates, setNoteStates] = useState<Record<string, NoteActionState>>({});
  const [noteErrors, setNoteErrors] = useState<Record<string, string | null>>({});
  const [metadataDrafts, setMetadataDrafts] = useState<Record<string, MetadataDraft>>({});
  const [metadataStates, setMetadataStates] = useState<Record<string, TitleActionState>>({});
  const [metadataErrors, setMetadataErrors] = useState<Record<string, string | null>>({});
  const [titleDrafts, setTitleDrafts] = useState<Record<string, TitleDraft>>({});
  const [titleSuggestions, setTitleSuggestions] = useState<Record<string, TitleDraft[]>>({});
  const [titleStates, setTitleStates] = useState<Record<string, TitleActionState>>({});
  const [titleErrors, setTitleErrors] = useState<Record<string, string | null>>({});
  const videoRefs = useRef<Record<string, HTMLVideoElement | null>>({});
  const eventSeqRef = useRef(0);
  const activeJobIdRef = useRef<string | null>(null);
  const archiveModeRef = useRef(false);
  const speedSaveTimerRef = useRef<number | undefined>(undefined);

  const applySnapshot = useCallback((next: Snapshot) => {
    const jobChanged = activeJobIdRef.current !== next.jobId;
    activeJobIdRef.current = next.jobId;
    const defaultSelectedId = next.selectedStorylineId
      ?? next.storylines.find((storyline) => storyline.status === "ready")?.id
      ?? next.storylines[0]?.id
      ?? null;
    const availableIds = new Set(next.storylines.map((storyline) => storyline.id));
    setSnapshot(next);
    setTitleDrafts((current) => {
      const drafts = jobChanged ? {} : { ...current };
      next.storylines.forEach((storyline) => {
        if (jobChanged || drafts[storyline.id] === undefined) {
          drafts[storyline.id] = { upper: storyline.titleUpper, lower: storyline.titleLower };
        }
      });
      return drafts;
    });
    setSelectedId((current) => current && availableIds.has(current) ? current : defaultSelectedId);
    setSelectedExportIds((current) => {
      if (jobChanged) current = [];
      return current.filter((id) => availableIds.has(id));
    });
    if (jobChanged) {
      setSelectedCandidateIds(next.selectedCandidateIds);
      setSelectedProvider(next.provider);
      setSelectedModel(next.model || defaultModel(next.provider));
      setYoutubeUrl(next.sourceUrl ?? "");
      if (next.jobId !== "empty" && !isDemoMode()) setOutputLanguage(next.outputLanguage ?? "ko");
      setYoutubeError(null);
      setCaptionStates({});
      setCaptionErrors({});
      setNoteStates({});
      setNoteErrors({});
      setMetadataDrafts({});
      setMetadataStates({});
      setMetadataErrors({});
      setTitleStates({});
      setTitleSuggestions({});
      setTitleErrors({});
      setExportState("idle");
      setExpandedDetailsId(null);
    }
    setConnection(next.connection);
    eventSeqRef.current = jobChanged ? next.eventSeq : Math.max(eventSeqRef.current, next.eventSeq);
    setLiveMessage(next.jobMessage ?? `${next.projectName} Workspace loaded.`);
  }, []);

  useEffect(() => {
    let cancelled = false;
    readSnapshot(initialJobIdRef.current)
      .then((payload) => {
        if (!cancelled) applySnapshot(payload);
      })
      .catch(() => {
        if (!cancelled) {
          setSnapshot(makeEmptySnapshot("disconnected"));
          setConnection("disconnected");
          setLiveMessage("Disconnected from the backend. Showing an empty workspace.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [applySnapshot]);

  useEffect(() => {
    if (isDemoMode()) return;
    let cancelled = false;
    void apiFetch("/api/settings/playback-speed")
      .then(async (response) => {
        if (!response.ok) throw new Error("Could not load playback speed settings.");
        const settings = (await response.json()) as PlaybackSpeedSettings;
        if (!cancelled) setPlaybackSpeed(normalizePlaybackSpeed(settings.speed));
      })
      .catch(() => {
        if (!cancelled) setSpeedSettingsSaveState("error");
      });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (isDemoMode()) {
      setGoogleDriveSettings({ configured: true, my_drive_path: "~/Google Drive/My Drive/Reels" });
      return;
    }
    let cancelled = false;
    void apiFetch("/api/settings/google-drive")
      .then(async (response) => {
        if (!response.ok) throw new Error("Could not load Google Drive settings.");
        const settings = (await response.json()) as GoogleDriveSettings;
        if (!cancelled) setGoogleDriveSettings(settings);
      })
      .catch(() => {
        if (!cancelled) setGoogleDriveSettings({ configured: false, my_drive_path: "" });
      });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => () => {
    if (speedSaveTimerRef.current !== undefined) window.clearTimeout(speedSaveTimerRef.current);
  }, []);

  useEffect(() => {
    archiveModeRef.current = archiveMode;
  }, [archiveMode]);

  useEffect(() => {
    if (!active || pendingViewFocusRef.current !== appView) return;
    const heading = appView === "archive" ? archiveHeadingRef.current : workspaceHeadingRef.current;
    if (!heading) return;
    heading.focus();
    pendingViewFocusRef.current = null;
  }, [appView, snapshot?.jobId, active]);

  useEffect(() => {
    if (isDemoMode() || !snapshot || snapshot.jobId === "empty") return undefined;
    const connectionJobId = snapshot.jobId;
    let closedByEffect = false;
    let reconnectAttempt = 0;
    let reconnectTimer: number | undefined;
    let events: WebSocket | null = null;

    const connect = () => {
      events = new WebSocket(wsUrl("/api/events", { after: eventSeqRef.current, job_id: connectionJobId }));
      events.onmessage = (event) => {
        if (closedByEffect || activeJobIdRef.current !== connectionJobId) return;
        reconnectAttempt = 0;
        try {
          const payload = JSON.parse(event.data) as EventPayload;
          const nextSeq = payload.event_seq ?? payload.seq;
          if (typeof nextSeq === "number") eventSeqRef.current = Math.max(eventSeqRef.current, nextSeq);
          if (isHeartbeat(payload)) {
            setConnection("connected");
            return;
          }
          const normalized = normalizeSnapshot(extractSnapshot(payload));
          if (normalized.jobId !== connectionJobId) return;
          applySnapshot(archiveModeRef.current ? completedOnlySnapshot(normalized) : normalized);
        } catch {
          setLiveMessage("Could not read the event message.");
        }
      };
      events.onclose = () => {
        if (closedByEffect) return;
        setConnection("disconnected");
        void readSnapshot(connectionJobId)
          .then((next) => {
            if (!closedByEffect && activeJobIdRef.current === connectionJobId) applySnapshot(archiveModeRef.current ? completedOnlySnapshot(next) : next);
          })
          .catch(() => {
            setSnapshot((current) => current ?? makeEmptySnapshot("disconnected"));
          });
        if (reconnectAttempt < 5) {
          reconnectAttempt += 1;
          reconnectTimer = window.setTimeout(connect, Math.min(5000, 400 * 2 ** reconnectAttempt));
        }
      };
      events.onerror = () => events?.close();
    };

    connect();
    return () => {
      closedByEffect = true;
      if (reconnectTimer) window.clearTimeout(reconnectTimer);
      events?.close();
    };
  }, [applySnapshot, eventConnectionVersion, snapshot?.jobId]);

  const storylines = snapshot?.storylines ?? [];
  const selectedStoryline = storylines.find((storyline) => storyline.id === selectedId) ?? null;
  const selectedExportStorylines = storylines.filter((storyline) => selectedExportIds.includes(storyline.id));
  const readySelected = selectedExportStorylines.length > 0
    && selectedExportStorylines.every((storyline) => storyline.status === "ready");
  const jobBusy = requestPending || ACTIVE_JOB_STATUSES.has(snapshot?.jobStatus ?? "idle") || storylines.some(
    (storyline) => !storyline.serverId.startsWith("placeholder-") && ["queued", "rendering", "overlaying"].includes(storyline.status),
  );
  useEffect(() => {
    if (snapshot) onTabUpdate(tabId, snapshot, jobBusy);
  }, [snapshot, jobBusy, tabId, onTabUpdate]);

  const canAnalyze = Boolean(snapshot?.sourceUrl) && !jobBusy;
  const candidateSelectionActive = snapshot?.jobStatus === "awaiting_selection";
  const generateLabel = jobBusy ? "Processing" : "Analyze again";
  const generationActive = GENERATION_JOB_STATUSES.has(snapshot?.jobStatus ?? "idle");
  const activeGenerationStage = generationStageIndex(snapshot?.jobPhase, snapshot?.jobStatus ?? "idle");
  const generationProgress = snapshot?.jobProgress ?? 0;
  const downloading = snapshot?.jobPhase === "downloading";
  const download = snapshot?.downloadProgress;
  const downloadLabel = download?.component === "audio" ? "Download audio" : "Download video";
  const visibleProgress = downloading
    ? (download ? progressPercent(download.component_fraction) : null)
    : generationProgress;
  const progressLabel = downloading ? downloadLabel : "Overall generation progress";
  const estimatedStorylineCount = snapshot?.nStorylines || selectedCandidateIds.length || 3;
  const renderMinutes = estimatedRenderMinutes(estimatedStorylineCount);
  const remainingMinutes = estimatedRemainingMinutes(
    snapshot?.jobPhase,
    snapshot?.jobStatus ?? "idle",
    generationProgress,
    renderMinutes,
  );
  const sourceThumbnailUrl = youtubeThumbnailUrl(youtubeUrl);

  function updateStoryline(id: string, patch: Partial<Storyline>) {
    setSnapshot((current) => {
      if (!current) return current;
      return {
        ...current,
        storylines: current.storylines.map((storyline) =>
          storyline.id === id ? { ...storyline, ...patch, revision: storyline.revision + 1 } : storyline,
        ),
      };
    });
  }

  function selectForExport(storyline: Storyline, checked?: boolean) {
    setSelectedId(storyline.id);
    setSelectedExportIds((current) => {
      const isSelected = current.includes(storyline.id);
      const shouldSelect = checked ?? !isSelected;
      const next = shouldSelect
        ? Array.from(new Set([...current, storyline.id]))
        : current.filter((id) => id !== storyline.id);
      setLiveMessage(
        shouldSelect
          ? `${storyline.label} Video selected for export.`
          : `${storyline.label} Video removed from export selection.`,
      );
      return next;
    });
  }

  function rerenderStoryline(storyline: Storyline) {
    setLiveMessage(`${storyline.label} : rerendering the video.`);
    if (isDemoMode()) {
      updateStoryline(storyline.id, { status: "rendering", progress: 38, error: undefined });
      window.setTimeout(() => {
        updateStoryline(storyline.id, { status: "ready", progress: 100 });
        setLiveMessage(`${storyline.label} : video is ready.`);
      }, 500);
      return;
    }
    if (snapshot) {
      void apiMutation(`/api/jobs/${snapshot.jobId}/storylines/${storyline.serverId}/retry`, { method: "POST" }).catch(() =>
        setLiveMessage("Rerender request failed."),
      );
    }
  }

  async function generateInstagramCaption(storyline: Storyline) {
    if (storyline.status !== "ready") return;
    setCaptionStates((current) => ({ ...current, [storyline.id]: "generating" }));
    setCaptionErrors((current) => ({ ...current, [storyline.id]: null }));
    setLiveMessage(`${storyline.label} Generating an Instagram caption.`);
    try {
      if (isDemoMode()) {
        await new Promise((resolve) => window.setTimeout(resolve, 450));
        updateStoryline(storyline.id, {
          instagramCaption: `${storyline.title}

This is a preview based on the selected original speech.

Check the source and subtitles before exporting.`,
        });
      } else {
        if (!snapshot) return;
        const response = await apiMutation(`/api/jobs/${snapshot.jobId}/storylines/${storyline.serverId}/caption`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ provider: selectedProvider, model: selectedModel }),
        });
        const payload = (await response.json()) as ApiSnapshot;
        const normalized = normalizeSnapshot(payload);
        applySnapshot(archiveModeRef.current ? completedOnlySnapshot(normalized) : normalized);
      }
      setCaptionStates((current) => ({ ...current, [storyline.id]: "idle" }));
      setNoteStates((current) => ({ ...current, [storyline.id]: "idle" }));
      setNoteErrors((current) => ({ ...current, [storyline.id]: null }));
      setLiveMessage(`${storyline.label} Instagram caption ready.`);
    } catch (error) {
      const detail = error instanceof Error ? error.message : "Could not generate the Instagram caption.";
      setCaptionStates((current) => ({ ...current, [storyline.id]: "error" }));
      setCaptionErrors((current) => ({ ...current, [storyline.id]: detail }));
      setLiveMessage(detail);
    }
  }

  async function copyInstagramCaption(storyline: Storyline) {
    if (!storyline.instagramCaption) return;
    try {
      await navigator.clipboard.writeText(storyline.instagramCaption);
      setCaptionStates((current) => ({ ...current, [storyline.id]: "copied" }));
      setLiveMessage(`${storyline.label} Caption copied to clipboard.`);
      window.setTimeout(() => {
        setCaptionStates((current) => ({ ...current, [storyline.id]: "idle" }));
      }, 1400);
    } catch {
      setCaptionStates((current) => ({ ...current, [storyline.id]: "error" }));
      setLiveMessage("Could not copy the caption. Select and copy the text manually.");
    }
  }

  async function saveInstagramCaptionToNotes(storyline: Storyline) {
    if (!storyline.instagramCaption || noteStates[storyline.id] === "saving") return;
    setNoteStates((current) => ({ ...current, [storyline.id]: "saving" }));
    setNoteErrors((current) => ({ ...current, [storyline.id]: null }));
    setLiveMessage(`${storyline.label} Saving the caption to Mac Notes for iCloud sync with your iPhone.`);
    try {
      if (isDemoMode()) {
        await new Promise((resolve) => window.setTimeout(resolve, 350));
      } else {
        if (!snapshot) throw new Error("The current workspace could not be found.");
        await apiMutation(`/api/jobs/${snapshot.jobId}/storylines/${storyline.serverId}/caption/note`, {
          method: "POST",
          body: JSON.stringify({ caption: storyline.instagramCaption }),
        });
      }
      setNoteStates((current) => ({ ...current, [storyline.id]: "saved" }));
      setLiveMessage(`${storyline.label} Caption body saved to iCloud Notes.`);
      window.setTimeout(() => {
        setNoteStates((current) => ({ ...current, [storyline.id]: "idle" }));
      }, 1800);
    } catch (error) {
      const detail = error instanceof Error ? error.message : "Could not save to iCloud Notes.";
      setNoteStates((current) => ({ ...current, [storyline.id]: "error" }));
      setNoteErrors((current) => ({ ...current, [storyline.id]: detail }));
      setLiveMessage(detail);
    }
  }

  async function clearProject() {
    if (!snapshot?.sourceUrl || jobBusy) return;
    setLiveMessage("Clearing the current video selection.");
    try {
      applySnapshot(makeEmptySnapshot("connected"));
      setYoutubeUrl("");
      setLiveMessage("Video selection cleared. Existing job files are preserved.");
    } catch {
      setLiveMessage("Could not clear the project selection.");
    }
  }

  async function showArchive() {
    pendingViewFocusRef.current = "archive";
    restoreSettingsFocusRef.current = false;
    setAppView("archive");
    setArchiveLoading(true);
    setArchiveError(null);
    setSettingsOpen(false);
    try {
      if (isDemoMode()) {
        const demo = makeDemoSnapshot();
        setArchiveItems(demo.storylines.map((storyline) => ({
          id: `${demo.jobId}:${storyline.id}`,
          jobId: demo.jobId,
          storylineId: storyline.id,
          episodeNumber: demo.episodeNumber,
          projectName: demo.projectName,
          reelTitle: storyline.title,
          sourceUrl: demo.sourceUrl,
          thumbnailUrl: youtubeThumbnailUrl(demo.sourceUrl),
          videoUrl: storyline.videoUrl,
          completedAt: demo.generatedAt,
        })));
      } else {
        const response = await apiMutation("/api/archive");
        const payload = (await response.json()) as { items?: ApiArchiveItem[] };
        setArchiveItems((payload.items ?? []).map(normalizeArchiveItem).filter((item): item is ArchiveItem => item !== null));
      }
    } catch (error) {
      setArchiveError(error instanceof Error ? error.message : "Could not load archived reels.");
    } finally {
      setArchiveLoading(false);
    }
  }

  async function openArchiveItem(item: ArchiveItem) {
    setOpeningArchiveId(item.id);
    setArchiveError(null);
    try {
      let next: Snapshot;
      if (isDemoMode()) {
        next = makeDemoSnapshot();
      } else {
        const response = await apiMutation(`/api/jobs/${item.jobId}/open`, { method: "POST" });
        next = normalizeSnapshot((await response.json()) as ApiSnapshot);
      }
      archiveModeRef.current = true;
      pendingViewFocusRef.current = "workspace";
      applySnapshot(completedOnlySnapshot(next, item.storylineId));
      setArchiveMode(true);
      setAppView("workspace");
      setLiveMessage(`Archived reel opened.`);
    } catch (error) {
      setArchiveError(error instanceof Error ? error.message : "Could not open the archived reel.");
    } finally {
      setOpeningArchiveId(null);
    }
  }

  async function deleteArchiveItem(item: ArchiveItem) {
    if (openingArchiveId !== null || deletingArchiveId !== null || deletingAllArchive) return;
    const confirmed = window.confirm(
      `Delete “${item.reelTitle}”?

The archived video and job files will be permanently deleted.`,
    );
    if (!confirmed) return;
    setDeletingArchiveId(item.id);
    setArchiveError(null);
    try {
      if (isDemoMode()) {
        await new Promise((resolve) => window.setTimeout(resolve, 250));
      } else {
        await apiMutation(
          `/api/archive/${encodeURIComponent(item.jobId)}/${encodeURIComponent(item.storylineId)}`,
          { method: "DELETE" },
        );
      }
      setArchiveItems((current) => current.filter((candidate) => candidate.id !== item.id));
      setLiveMessage(`“${item.reelTitle}” and its job files were deleted.`);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Could not delete the archived reel.";
      setArchiveError(message);
      setLiveMessage(message);
    } finally {
      setDeletingArchiveId(null);
    }
  }

  async function deleteAllArchive() {
    if (archiveItems.length === 0 || openingArchiveId !== null || deletingArchiveId !== null || deletingAllArchive) return;
    const count = archiveItems.length;
    const confirmed = window.confirm(
      `Delete all ${count} archived reels?

The archived videos and job files will be permanently deleted.`,
    );
    if (!confirmed) return;
    setDeletingAllArchive(true);
    setArchiveError(null);
    try {
      if (isDemoMode()) {
        await new Promise((resolve) => window.setTimeout(resolve, 300));
      } else {
        await apiMutation("/api/archive", { method: "DELETE" });
      }
      setArchiveItems([]);
      setLiveMessage(`${count} archived reels and their job files were deleted.`);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Could not delete all archived reels.";
      setArchiveError(message);
      setLiveMessage(message);
    } finally {
      setDeletingAllArchive(false);
    }
  }

  async function updateMetadata(storyline: Storyline, draft: MetadataDraft) {
    if (!snapshot || storyline.status !== "ready") return;
    const episode = storyline.episodeNumber ?? snapshot.episodeNumber;
    if (!draft.name.trim()) {
      setMetadataErrors((current) => ({ ...current, [storyline.id]: "Enter a name." }));
      return;
    }
    setMetadataStates((current) => ({ ...current, [storyline.id]: "saving" }));
    setMetadataErrors((current) => ({ ...current, [storyline.id]: null }));
    setLiveMessage(`${storyline.label} : updating the name and role on the video.`);
    try {
      let next: Snapshot;
      if (isDemoMode()) {
        next = { ...snapshot, storylines: snapshot.storylines.map((item) => item.id === storyline.id
          ? { ...item, speaker: { name: draft.name.trim(), role: draft.role.trim() }, episodeNumber: episode, instagramCaption: "", revision: item.revision + 1 }
          : item) };
      } else {
        const response = await apiMutation(`/api/jobs/${snapshot.jobId}/storylines/${storyline.serverId}/metadata`, {
          method: "PATCH", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: draft.name.trim(), role: draft.role.trim(), episode_number: episode }),
        });
        next = normalizeSnapshot((await response.json()) as ApiSnapshot);
        next.storylines = next.storylines.map((item) => item.id === storyline.id
          ? { ...item, videoUrl: cacheBustedMediaUrl(item.videoUrl, `${item.revision}-${Date.now()}`) } : item);
      }
      applySnapshot(archiveModeRef.current ? completedOnlySnapshot(next, storyline.id) : next);
      setMetadataDrafts((current) => { const updated = { ...current }; delete updated[storyline.id]; return updated; });
      setMetadataStates((current) => ({ ...current, [storyline.id]: "saved" }));
      setLiveMessage("Name and role updated on the video.");
    } catch (error) {
      const detail = error instanceof Error ? error.message : "Could not update the video information.";
      setMetadataStates((current) => ({ ...current, [storyline.id]: "error" }));
      setMetadataErrors((current) => ({ ...current, [storyline.id]: detail }));
      setLiveMessage(detail);
    }
  }

  async function updateTitle(storyline: Storyline) {
    if (!snapshot || storyline.status !== "ready") return;
    const draft = titleDrafts[storyline.id] ?? { upper: storyline.titleUpper, lower: storyline.titleLower };
    const validationError = titleValidationMessage(draft);
    if (validationError) {
      setTitleStates((current) => ({ ...current, [storyline.id]: "error" }));
      setTitleErrors((current) => ({ ...current, [storyline.id]: validationError }));
      return;
    }
    setTitleStates((current) => ({ ...current, [storyline.id]: "saving" }));
    setTitleErrors((current) => ({ ...current, [storyline.id]: null }));
    setLiveMessage(`${storyline.label} : updating the on-screen title.`);
    try {
      let next: Snapshot;
      if (isDemoMode()) {
        await new Promise((resolve) => window.setTimeout(resolve, 450));
        next = {
          ...snapshot,
          storylines: snapshot.storylines.map((item) => item.id === storyline.id ? {
            ...item,
            title: combineTitleLines(draft),
            titleUpper: draft.upper.trim(),
            titleLower: draft.lower.trim(),
            instagramCaption: "",
            revision: item.revision + 1,
            videoUrl: cacheBustedMediaUrl(item.videoUrl, Date.now()),
          } : item),
        };
      } else {
        const response = await apiMutation(`/api/jobs/${snapshot.jobId}/storylines/${storyline.serverId}/title`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ title_upper: draft.upper.trim(), title_lower: draft.lower.trim() }),
        });
        const normalized = normalizeSnapshot((await response.json()) as ApiSnapshot);
        next = {
          ...normalized,
          storylines: normalized.storylines.map((item) => item.id === storyline.id
            ? { ...item, videoUrl: cacheBustedMediaUrl(item.videoUrl, `${item.revision}-${Date.now()}`) }
            : item),
        };
      }
      applySnapshot(archiveModeRef.current ? completedOnlySnapshot(next, storyline.id) : next);
      setTitleDrafts((current) => ({
        ...current,
        [storyline.id]: { upper: draft.upper.trim(), lower: draft.lower.trim() },
      }));
      setTitleStates((current) => ({ ...current, [storyline.id]: "saved" }));
      setLiveMessage(`${storyline.label} On-screen title and overlay updated.`);
    } catch (error) {
      const detail = error instanceof Error ? error.message : "Could not update the on-screen title.";
      setTitleStates((current) => ({ ...current, [storyline.id]: "error" }));
      setTitleErrors((current) => ({ ...current, [storyline.id]: `${detail} The previous video remains playable.` }));
      setLiveMessage(detail);
    }
  }

  async function regenerateTitle(storyline: Storyline) {
    if (!snapshot || storyline.status !== "ready") return;
    setTitleStates((current) => ({ ...current, [storyline.id]: "generating" }));
    setTitleErrors((current) => ({ ...current, [storyline.id]: null }));
    setLiveMessage(`${storyline.label}: generating four title suggestions.`);
    try {
      let suggestions: TitleDraft[];
      if (isDemoMode()) {
        await new Promise((resolve) => window.setTimeout(resolve, 550));
        suggestions = [
          { upper: "You Practice Every Day", lower: "Why Your Skills Do Not Improve" },
          { upper: "The Same Time Spent", lower: "Why Learning Speeds Differ" },
          { upper: "Record Your Mistakes", lower: "Change Your Next Practice" },
          { upper: "Before Closing the Book", lower: "Leave Yourself One Question" },
        ];
      } else {
        const response = await apiMutation(
          `/api/jobs/${snapshot.jobId}/storylines/${storyline.serverId}/title/suggestion`,
          { method: "POST" },
        );
        const payload = await response.json() as { suggestions?: { title_upper?: string; title_lower?: string }[] };
        if (!Array.isArray(payload.suggestions) || payload.suggestions.length !== 4) throw new Error("Could not get four title suggestions.");
        suggestions = payload.suggestions.map((item) => ({
          upper: String(item.title_upper ?? "").trim(),
          lower: String(item.title_lower ?? "").trim(),
        }));
      }
      for (const suggestion of suggestions) {
        const validationError = titleValidationMessage(suggestion);
        if (validationError) throw new Error(validationError);
      }
      setTitleSuggestions((current) => ({ ...current, [storyline.id]: suggestions }));
      setTitleDrafts((current) => ({ ...current, [storyline.id]: suggestions[0] }));
      setTitleStates((current) => ({ ...current, [storyline.id]: "suggested" }));
      setLiveMessage(`Four title suggestions are ready. The recommended title is selected. Choose a title, then click Apply changes.`);
    } catch (error) {
      const detail = error instanceof Error ? error.message : "Could not suggest a new on-screen title.";
      setTitleStates((current) => ({ ...current, [storyline.id]: "error" }));
      setTitleErrors((current) => ({ ...current, [storyline.id]: detail }));
      setLiveMessage(detail);
    }
  }

  async function startYoutubeJob(sourceUrl: string) {
    const normalized = sourceUrl.trim();
    if (!normalized) {
      const message = "Enter a YouTube video link.";
      setYoutubeError(message);
      setLiveMessage(message);
      return;
    }
    if (!youtubeVideoId(normalized)) {
      const message = "Enter a supported YouTube video URL.";
      setYoutubeError(message);
      setLiveMessage(message);
      return;
    }
    setYoutubeError(null);
    if (requestPendingRef.current || jobBusy) return;
    requestPendingRef.current = true;
    setRequestPending(true);
    try {
      setLiveMessage("Reading the YouTube video and analyzing ten clip ideas.");
      const response = await apiMutation("/api/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          youtube_url: normalized,
          output_language: outputLanguage,
          content_types: ALL_CONTENT_TYPES,
          provider: selectedProvider,
          model: selectedModel,
        }),
      });
      applySnapshot(normalizeSnapshot((await response.json()) as ApiSnapshot));
      setEventConnectionVersion((version) => version + 1);
    } finally {
      requestPendingRef.current = false;
      setRequestPending(false);
    }
  }

  function toggleCandidate(candidateId: string) {
    setSelectedCandidateIds((current) => (
      current.includes(candidateId)
        ? current.filter((value) => value !== candidateId)
        : [...current, candidateId]
    ));
  }

  async function generateSelectedCandidates() {
    if (!snapshot || !candidateSelectionActive || selectedCandidateIds.length === 0 || requestPendingRef.current) return;
    requestPendingRef.current = true;
    setRequestPending(true);
    try {
      setLiveMessage(`Generating ${selectedCandidateIds.length} selected reels.`);
      const response = await apiMutation(`/api/jobs/${snapshot.jobId}/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ candidate_ids: selectedCandidateIds }),
      });
      applySnapshot(normalizeSnapshot((await response.json()) as ApiSnapshot));
      setEventConnectionVersion((version) => version + 1);
    } finally {
      requestPendingRef.current = false;
      setRequestPending(false);
    }
  }

  function submitYoutube(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (jobBusy) return;
    if (isDemoMode()) {
      setLiveMessage("Analyzing ten clip ideas from the YouTube link.");
      return;
    }
    void startYoutubeJob(youtubeUrl).catch((error) => {
      const detail = error instanceof Error ? error.message : "Could not process the YouTube link.";
      setYoutubeError(detail);
      setLiveMessage(detail);
    });
  }

  async function exportSelected() {
    if (!readySelected || !snapshot) return;
    setExportState("exporting");
    setLiveMessage(`Preparing ${selectedExportStorylines.length} selected videos for export.`);
    try {
      let completedPath = googleDriveSettings?.my_drive_path || "~/Movies/Reels Editor Exports";
      if (!isDemoMode()) {
        const response = await apiMutation(`/api/jobs/${snapshot.jobId}/export-batch`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            storyline_ids: selectedExportStorylines.map((storyline) => storyline.serverId),
            subtitles_on: true,
          }),
        });
        const payload = await response.json().catch(() => null) as unknown;
        completedPath = exportedPathFromPayload(payload) ?? completedPath;
      } else {
        await new Promise((resolve) => window.setTimeout(resolve, 450));
        completedPath = `${completedPath}/${snapshot.projectName}/`;
      }
      setExportState("done");
      setLiveMessage(`Saved ${selectedExportStorylines.length} videos to ${completedPath}.`);
    } catch (error) {
      setExportState("failed");
      const detail = error instanceof Error ? `: ${error.message}` : "";
      setLiveMessage(`Export failed${detail}`);
    }
  }

  async function connectGoogleDrive() {
    if (isDemoMode()) {
      setLiveMessage("Google Drive export folder selected.");
      return;
    }
    setGoogleDriveConnecting(true);
    try {
      const response = await apiMutation("/api/settings/google-drive/choose", { method: "POST" });
      const settings = (await response.json()) as GoogleDriveSettings;
      setGoogleDriveSettings(settings);
      setLiveMessage(settings.cancelled
        ? "Google Drive folder selection cancelled."
        : "Google Drive export folder selected.");
    } catch (error) {
      setLiveMessage(error instanceof Error ? error.message : "Could not connect to Google Drive.");
    } finally {
      setGoogleDriveConnecting(false);
    }
  }

  async function savePlaybackSpeed(speed: number) {
    if (isDemoMode()) {
      setSpeedSettingsSaveState("saved");
      return;
    }
    try {
      const response = await apiMutation("/api/settings/playback-speed", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ speed }),
      });
      const settings = (await response.json()) as PlaybackSpeedSettings;
      setPlaybackSpeed(normalizePlaybackSpeed(settings.speed));
      setSpeedSettingsSaveState("saved");
      setLiveMessage(`Playback speed set to ${playbackSpeedLabel(settings.speed)}×.`);
    } catch (error) {
      setSpeedSettingsSaveState("error");
      setLiveMessage(error instanceof Error ? error.message : "Could not save playback speed.");
    }
  }

  function updatePlaybackSpeed(value: number) {
    if (jobBusy) return;
    const next = normalizePlaybackSpeed(value);
    setPlaybackSpeed(next);
    setSpeedSettingsSaveState("saving");
    if (speedSaveTimerRef.current !== undefined) window.clearTimeout(speedSaveTimerRef.current);
    speedSaveTimerRef.current = window.setTimeout(() => {
      speedSaveTimerRef.current = undefined;
      void savePlaybackSpeed(next);
    }, 240);
  }

  function playSelected() {
    if (!selectedStoryline) return;
    const selectedVideo = videoRefs.current[selectedStoryline.id];
    if (!selectedVideo) return;
    Object.entries(videoRefs.current).forEach(([id, video]) => {
      if (video && id !== selectedStoryline.id) video.pause();
    });
    if (audioNeedsGesture) {
      selectedVideo.muted = false;
      selectedVideo.volume = 1;
      setSoundEnabled(true);
      setAudioNeedsGesture(false);
      void selectedVideo.play().catch(() => setAudioNeedsGesture(true));
    } else if (selectedVideo.paused) void selectedVideo.play().catch(() => undefined);
    else selectedVideo.pause();
  }

  function toggleSound() {
    if (!selectedStoryline) return;
    const video = videoRefs.current[selectedStoryline.id];
    if (!video) return;
    const nextEnabled = audioNeedsGesture || !soundEnabled;
    video.muted = !nextEnabled;
    video.volume = 1;
    setSoundEnabled(nextEnabled);
    setAudioNeedsGesture(false);
    if (nextEnabled) {
      void video.play().catch(() => setAudioNeedsGesture(true));
    }
    setLiveMessage(nextEnabled ? "Video sound enabled." : "Video sound muted.");
  }

  const selectedStorylineIndex = Math.max(0, storylines.findIndex((storyline) => storyline.id === selectedId));

  function moveToStoryline(offset: number) {
    if (storylines.length === 0) return;
    const nextIndex = Math.min(storylines.length - 1, Math.max(0, selectedStorylineIndex + offset));
    const next = storylines[nextIndex];
    if (!next || next.id === selectedId) return;
    setSelectedId(next.id);
    setExpandedDetailsId(null);
    setLiveMessage(`${next.label} selected. ${nextIndex + 1}/${storylines.length}`);
  }

  function toggleSelectedForExport() {
    if (selectedStoryline?.status === "ready") selectForExport(selectedStoryline);
  }

  function toggleDetails(storyline: Storyline) {
    const opening = expandedDetailsId !== storyline.id;
    setExpandedDetailsId(opening ? storyline.id : null);
    if (opening) {
      window.requestAnimationFrame(() => {
        document.getElementById(`${tabId}-${storyline.id}-details`)?.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    }
  }

  useEffect(() => {
    if (!active) { Object.values(videoRefs.current).forEach((video) => video?.pause()); return; }
    if (!selectedStoryline?.videoUrl || selectedStoryline.status !== "ready") return;
    setAudioNeedsGesture(false);
    const frame = window.requestAnimationFrame(() => {
      const video = videoRefs.current[selectedStoryline.id];
      if (!video) return;
      video.volume = 1;
      video.muted = !soundEnabled;
      void video.play().catch(() => {
        if (!soundEnabled) return;
        video.muted = true;
        setAudioNeedsGesture(true);
        void video.play().catch(() => undefined);
      });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [selectedStoryline?.id, selectedStoryline?.videoUrl, selectedStoryline?.status, soundEnabled, active]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (!active) return;
      const target = event.target as HTMLElement | null;
      if (target?.matches("input, textarea, select, button, a, [contenteditable='true']")) return;
      const key = event.key.toLowerCase();
      if (event.key === "Enter" || (event.metaKey && key === "e")) {
        event.preventDefault();
        void exportSelected();
      } else if (event.key === "ArrowLeft") {
        event.preventDefault();
        moveToStoryline(-1);
      } else if (event.key === "ArrowRight") {
        event.preventDefault();
        moveToStoryline(1);
      } else if (event.code === "Space") {
        event.preventDefault();
        toggleSelectedForExport();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  });

  function closeSettingsPopover() {
    restoreSettingsFocusRef.current = true;
    setSettingsOpen(false);
  }

  async function reconnect() {
    setConnection("connecting");
    setLiveMessage("Reconnecting to the backend.");
    try {
      const next = await readSnapshot(activeJobIdRef.current);
      applySnapshot(archiveModeRef.current ? completedOnlySnapshot(next) : next);
    } catch {
      setConnection("disconnected");
      setLiveMessage("Could not reconnect.");
    }
  }

  useEffect(() => {
    if (!active) return;
    if (settingsOpen) {
      const firstControl = settingsFirstControlRef.current;
      if (firstControl && !firstControl.disabled) firstControl.focus();
      else settingsDialogRef.current?.focus();
      return;
    }
    if (!restoreSettingsFocusRef.current) return;
    restoreSettingsFocusRef.current = false;
    settingsTriggerRef.current?.focus();
  }, [settingsOpen, active]);

  // 설정은 팝오버 안에서만 열리므로, 바깥을 누르거나 Esc를 눌러 닫는다.
  useEffect(() => {
    if (!active || !settingsOpen) return;
    function onOutsideClick(event: MouseEvent) {
      if (!settingsMenuRef.current?.contains(event.target as Node)) closeSettingsPopover();
    }
    function onEscape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        closeSettingsPopover();
      }
    }
    window.addEventListener("click", onOutsideClick);
    window.addEventListener("keydown", onEscape);
    return () => {
      window.removeEventListener("click", onOutsideClick);
      window.removeEventListener("keydown", onEscape);
    };
  }, [settingsOpen, active]);

  function SettingsPopover() {
    return (
      <div ref={settingsDialogRef} className="settings-popover" role="dialog" aria-label="Generation settings" tabIndex={-1}>
        <div className="settings-field">
          <div className="settings-field-heading">
            <h3>Playback speed</h3>
            <strong>{playbackSpeedLabel(playbackSpeed)}×</strong>
          </div>
          <input
            ref={settingsFirstControlRef}
            type="range"
            min={MIN_PLAYBACK_SPEED}
            max={MAX_PLAYBACK_SPEED}
            step={PLAYBACK_SPEED_STEP}
            value={playbackSpeed}
            disabled={jobBusy}
            aria-label="Playback speed"
            aria-valuetext={`${playbackSpeedLabel(playbackSpeed)}×`}
            style={{
              "--range-progress": `${((playbackSpeed - MIN_PLAYBACK_SPEED) / (MAX_PLAYBACK_SPEED - MIN_PLAYBACK_SPEED)) * 100}%`,
            } as React.CSSProperties}
            onChange={(event) => updatePlaybackSpeed(Number(event.target.value))}
          />
          <p className={speedSettingsSaveState === "error" ? "settings-note error" : "settings-note"}>
            {speedSettingsSaveState === "saving"
              ? "Saving"
              : speedSettingsSaveState === "saved"
                ? "Saved"
                : speedSettingsSaveState === "error"
                  ? "Save failed"
                  : jobBusy
                    ? "Cannot change while a job is running"
                    : "Applies to the next generation"}
          </p>
        </div>

        <div className="settings-field">
          <div className="settings-field-heading">
            <h3>Model</h3>
          </div>
          <select
            id="model-provider"
            aria-label="Model provider"
            value={selectedProvider}
            disabled={jobBusy}
            onChange={(event) => {
              const provider = event.target.value as ModelProvider;
              setSelectedProvider(provider);
              setSelectedModel(defaultModel(provider));
            }}
          >
            {PROVIDER_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
          <p className="settings-note">
            {PROVIDER_OPTIONS.find((option) => option.value === selectedProvider)?.description}
          </p>
          <label className="settings-select-label" htmlFor="model-name">Model name</label>
          <select
            id="model-name"
            aria-label="Model name"
            value={selectedModel}
            disabled={jobBusy}
            onChange={(event) => setSelectedModel(event.target.value)}
          >
            {MODEL_OPTIONS[selectedProvider].map((option) => (
              <option key={option.value || "default"} value={option.value}>{option.label}</option>
            ))}
          </select>
        </div>

        <div className="settings-field integration-settings-field">
          <div className="settings-field-heading">
            <h3>Google Drive export</h3>
            <strong>{googleDriveSettings?.configured ? "Connected" : "Not configured"}</strong>
          </div>
          <p className="drive-path" title={googleDriveSettings?.my_drive_path || undefined}>
            {googleDriveSettings?.my_drive_path || "Saves to your selected Google Drive folder."}
          </p>
          <button
            type="button"
            onClick={() => { void connectGoogleDrive(); }}
            disabled={googleDriveConnecting}
          >
            <FolderOpen size={15} aria-hidden="true" />
            {googleDriveConnecting ? "Choosing" : googleDriveSettings?.configured ? "Choose another folder" : "Choose export folder"}
          </button>
          <p className="settings-note">Save MP4 files to the selected export folder.</p>
        </div>

      </div>
    );
  }

  function onVideoPlay(id: string) {
    if (!active) { videoRefs.current[id]?.pause(); return; }
    Object.entries(videoRefs.current).forEach(([otherId, video]) => {
      if (otherId !== id && video) video.pause();
    });
  }

  if (!snapshot) {
    return (
      <main className="loading-shell" aria-busy="true">
        <Loader2 className="spin" aria-hidden="true" />
        <p>Preparing the workspace</p>
      </main>
    );
  }

  if (appView === "archive") {
    return (
      <main className="app-shell archive-shell">
        <div className="topbar">
          <div className="project-brand">
            <img className="brand-mark" src={REELS_EDITOR_LOGO_URL} alt="Reels Editor logo" />
            <div className="project-block">
              <p className="eyebrow">Reels Editor</p>
              <h1 ref={archiveHeadingRef} className="view-focus-target" tabIndex={-1}>Archived reels</h1>
            </div>
          </div>
          <div className="workbar-actions" aria-label="Archive tools">
            <button type="button" className="ghost-button" onClick={() => {
              archiveModeRef.current = false;
              pendingViewFocusRef.current = "workspace";
              setArchiveMode(false);
              setAppView("workspace");
            }}>
              Back to workspace
            </button>
          </div>
        </div>

        <section className="archive-workspace" aria-labelledby="archive-title" aria-busy={archiveLoading || deletingAllArchive || deletingArchiveId !== null}>
          <header className="archive-header">
            <div>
              <p className="eyebrow">Completed videos only</p>
              <h2 id="archive-title">Your saved reels</h2>
              <p>Open a video to reuse it. Reels are automatically removed seven days after completion.</p>
            </div>
            <div className="archive-summary">
              <strong>{archiveItems.length}<span></span></strong>
              {archiveItems.length > 0 ? (
                <button
                  type="button"
                  className="archive-delete-all"
                  disabled={archiveLoading || openingArchiveId !== null || deletingArchiveId !== null || deletingAllArchive}
                  onClick={() => { void deleteAllArchive(); }}
                >
                  {deletingAllArchive ? <Loader2 size={15} className="spin" aria-hidden="true" /> : <Trash2 size={15} aria-hidden="true" />}
                  {deletingAllArchive ? "Deleting" : "Delete all"}
                </button>
              ) : null}
            </div>
          </header>

          {archiveLoading ? (
            <div className="archive-state" role="status"><Loader2 className="spin" aria-hidden="true" /> Loading archived reels.</div>
          ) : archiveError ? (
            <div className="archive-state error" role="alert">
              <CircleAlert aria-hidden="true" />
              <span>{archiveError}</span>
              <button type="button" onClick={() => { void showArchive(); }}>Reload</button>
            </div>
          ) : archiveItems.length === 0 ? (
            <div className="archive-state empty">
              <History aria-hidden="true" />
              <strong>No completed reels yet.</strong>
              <span>Completed videos appear here for you to reopen.</span>
            </div>
          ) : (
            <div className="archive-list" role="list">
              {archiveItems.map((item) => (
                <article className="archive-item" role="listitem" key={item.id}>
                  <div className="archive-preview">
                    {item.thumbnailUrl ? (
                      <Thumbnail src={item.thumbnailUrl} alt={`${item.reelTitle}  thumbnail`} className="archive-thumbnail" />
                    ) : item.videoUrl ? (
                      <video src={item.videoUrl} preload="metadata" muted aria-label={`${item.reelTitle}  video preview`} />
                    ) : (
                      <div className="archive-thumbnail thumbnail-fallback" role="img" aria-label="No preview"><ImageOff aria-hidden="true" /></div>
                    )}
                  </div>
                  <div className="archive-copy">
                    <h3>{item.reelTitle}</h3>
                    <p>{item.projectName}</p>
                    <small><Clock3 size={13} aria-hidden="true" /> {formatArchiveDate(item.completedAt)}</small>
                  </div>
                  <div className="archive-actions">
                    <button
                      type="button"
                      className="archive-open"
                      disabled={openingArchiveId !== null || deletingArchiveId !== null || deletingAllArchive}
                      onClick={() => { void openArchiveItem(item); }}
                      aria-label={`${item.reelTitle} Open`}
                    >
                      {openingArchiveId === item.id ? <Loader2 size={16} className="spin" /> : null}
                      {openingArchiveId === item.id ? "Opening" : "Open"}
                    </button>
                    <button
                      type="button"
                      className="archive-delete"
                      disabled={openingArchiveId !== null || deletingArchiveId !== null || deletingAllArchive}
                      onClick={() => { void deleteArchiveItem(item); }}
                      aria-label={`${item.reelTitle} Delete`}
                    >
                      {deletingArchiveId === item.id ? <Loader2 size={15} className="spin" aria-hidden="true" /> : <Trash2 size={15} aria-hidden="true" />}
                      {deletingArchiveId === item.id ? "Deleting" : "Delete"}
                    </button>
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>
        <div className="sr-only" role="status" aria-live="polite">{liveMessage}</div>
      </main>
    );
  }

  return (
    <main className="app-shell">
      <div className="topbar">
        <div className="project-brand">
          <img className="brand-mark" src={REELS_EDITOR_LOGO_URL} alt="Reels Editor logo" />
          <div className="project-block">
            <p className="eyebrow">Reels Editor</p>
            <h1 ref={workspaceHeadingRef} className="view-focus-target" tabIndex={-1}>{snapshot.projectName}</h1>
          </div>
        </div>
        <div className="workbar-actions" aria-label="Workspace tools">
          <button type="button" className="ghost-button archive-button topbar-tool-button" onClick={() => { void showArchive(); }}>
            <History size={17} /> Archived reels
          </button>
          <div className="settings-menu" ref={settingsMenuRef}>
            <button
              ref={settingsTriggerRef}
              type="button"
              className={settingsOpen ? "ghost-button topbar-tool-button active" : "ghost-button topbar-tool-button"}
              aria-label="Settings"
              aria-haspopup="dialog"
              aria-expanded={settingsOpen}
              onClick={() => {
                if (settingsOpen) {
                  closeSettingsPopover();
                  return;
                }
                restoreSettingsFocusRef.current = false;
                setSettingsOpen(true);
              }}
            >
              <Settings2 size={17} /> Settings
            </button>
            {settingsOpen ? <SettingsPopover /> : null}
          </div>
          <button
            type="button"
            className="ghost-button topbar-tool-button"
            disabled={!snapshot.sourceUrl || jobBusy}
            onClick={clearProject}
          >
            <FolderX size={17} /> Clear
          </button>
          <button
            type="button"
            className="ghost-button topbar-tool-button"
            disabled={!canAnalyze}
            onClick={() => {
              if (!isDemoMode()) {
                if (snapshot.sourceUrl) {
                  setLiveMessage("Reanalyzing ten clip ideas from this YouTube video.");
                  void startYoutubeJob(snapshot.sourceUrl).catch((error) => {
                    const detail = error instanceof Error ? error.message : "Generation request failed.";
                    setYoutubeError(detail);
                    setLiveMessage(detail);
                  });
                  return;
                }
                setLiveMessage("Enter a YouTube video link first.");
                return;
              }
              setLiveMessage("Reanalyzing ten clip ideas.");
            }}
          >
            <RefreshCcw size={17} /> {generateLabel}
          </button>
          <button
            type="button"
            className="topbar-icon-button export-button"
            disabled={!readySelected || exportState === "exporting"}
            onClick={exportSelected}
            aria-label={exportState === "done" ? "Export saved" : archiveMode ? "Export archived video again" : `Export ${selectedExportStorylines.length} selected videos`}
            title={archiveMode ? "Export archived video again" : `Export ${selectedExportStorylines.length} selected videos`}
          >
            {exportState === "exporting" ? <Loader2 size={19} className="spin" /> : <Download size={19} />}
          </button>
        </div>
      </div>

      {generationActive ? (
        <section className="generation-progress" aria-labelledby={`${tabId}-generation-progress-title`} aria-live="polite">
          <div className="generation-progress-heading">
            <div className="generation-progress-title">
              <span className="generation-progress-icon" aria-hidden="true"><Loader2 size={16} className="spin" /></span>
              <div>
                <p>Current stage · {activeGenerationStage + 1}/{GENERATION_STAGES.length}</p>
                <h2 id={`${tabId}-generation-progress-title`}>{downloading ? (download ? downloadLabel : "Download captions") : GENERATION_STAGES[activeGenerationStage].label}</h2>
              </div>
            </div>
            <div className="generation-progress-summary">
              {!downloading ? <div className="generation-progress-eta">
                <span>Estimated time</span>
                <strong>{remainingTimeLabel(remainingMinutes)}</strong>
              </div>
              : null}
              <strong className="generation-progress-percent">{visibleProgress === null ? "Preparing" : `${visibleProgress}%`}</strong>
            </div>
          </div>
          <div
            className="generation-progress-track"
            role="progressbar"
            aria-label={progressLabel}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={visibleProgress ?? undefined}
          >
            <span style={{ width: `${visibleProgress ?? 0}%` }} />
          </div>
          {snapshot.jobMessage ? <p className="generation-progress-detail">{snapshot.jobMessage}</p> : null}
          {downloading ? <p className="generation-progress-note">Captions are analyzed first. Only the necessary video sections are downloaded after you select clips.</p> : null}
        </section>
      ) : null}

      <form className="youtube-source" onSubmit={submitYoutube} hidden={archiveMode}>
        <div className="youtube-source-controls">
          {sourceThumbnailUrl ? (
            <Thumbnail src={sourceThumbnailUrl} alt="Thumbnail of the YouTube source" className="youtube-thumbnail" />
          ) : null}
          <div className="youtube-source-entry">
            <label htmlFor={`${tabId}-youtube-url`} className="sr-only">YouTube video URL</label>
            <span aria-hidden="true"><Link size={17} /></span>
            <input
              id={`${tabId}-youtube-url`}
              type="url"
              inputMode="url"
              autoComplete="url"
              placeholder="https://www.youtube.com/watch?v=..."
              value={youtubeUrl}
              disabled={jobBusy}
              aria-invalid={Boolean(youtubeError)}
              aria-describedby={`${tabId}-youtube-source-help`}
              onChange={(event) => {
                setYoutubeUrl(event.target.value);
                setYoutubeError(null);
              }}
            />
            <button type="submit" disabled={jobBusy || !youtubeUrl.trim()}>
              {jobBusy ? <Loader2 size={16} className="spin" /> : <Scissors size={16} />}
              {jobBusy ? "Analyzing" : "Analyze 10 ideas"}
            </button>
          </div>
          <label className="language-field" htmlFor={`${tabId}-output-language`}>
            <span>Output language</span>
            <select id={`${tabId}-output-language`} value={outputLanguage} disabled={jobBusy}
              onChange={(event) => {
                const value = event.target.value as "ko" | "en" | "zh";
                setOutputLanguage(value); localStorage.setItem("reels-output-language-v2", value);
              }}>
              <option value="en">English</option><option value="ko">Korean</option><option value="zh">Simplified Chinese</option>
            </select>
          </label>

        </div>
        {youtubeError ? <p id={`${tabId}-youtube-source-help`} className="youtube-source-help error">{youtubeError}</p> : null}
      </form>

      {snapshot.jobStatus === "failed" && snapshot.jobError ? (
        <section className="notice error" role="alert">
          <CircleAlert size={18} aria-hidden="true" />
          <span><strong>Clip generation failed</strong>{snapshot.jobError}</span>
        </section>
      ) : null}

      {candidateSelectionActive ? (
        <section className="candidate-workspace" aria-labelledby={`${tabId}-candidate-workspace-title`}>
          <header className="candidate-workspace-header">
            <div>
              <p className="eyebrow">Analysis complete · duplicates removed</p>
              <h2 id={`${tabId}-candidate-workspace-title`}>Choose the reels you want to make</h2>
              <p>
                Only selected clips will be produced. Script generation and rendering take {remainingTimeLabel(estimatedRenderMinutes(selectedCandidateIds.length || 3) + 1)} .
              </p>
            </div>
            <strong>{selectedCandidateIds.length}<span> selected</span></strong>
          </header>
          <div className="candidate-list">
            {snapshot.candidates.map((candidate, index) => {
              const selected = selectedCandidateIds.includes(candidate.id);
              return (
                <label className={selected ? "candidate-item selected" : "candidate-item"} key={candidate.id}>
                  <input
                    type="checkbox"
                    checked={selected}
                    onChange={() => toggleCandidate(candidate.id)}
                  />
                  <span className="candidate-index">{String(index + 1).padStart(2, "0")}</span>
                  <span className="candidate-copy">
                    <strong>{candidate.title}</strong>
                    <span>{candidate.summary}</span>
                    <small><b>Takeaway</b>{candidate.takeaway}</small>
                  </span>
                  <span className="candidate-check" aria-hidden="true"><Check size={17} /></span>
                </label>
              );
            })}
          </div>
          <div className="candidate-action">
            <span>{selectedCandidateIds.length > 0 ? `Only ${selectedCandidateIds.length} selected clips will be produced.` : "Select at least one clip idea."}</span>
            <button
              type="button"
              disabled={jobBusy || selectedCandidateIds.length === 0}
              onClick={() => {
                void generateSelectedCandidates().catch((error) => {
                  setLiveMessage(error instanceof Error ? error.message : "Could not request reel generation.");
                });
              }}
            >
              <Scissors size={17} /> Generate selected reels
            </button>
          </div>
        </section>
      ) : null}

      {connection === "disconnected" ? (
        <section className="notice" role="status">
          <WifiOff size={18} aria-hidden="true" />
          <span>Disconnected from the local Python engine. This screen shows the last known state.</span>
          <button type="button" onClick={reconnect}>Reconnect</button>
        </section>
      ) : null}

      <section className="reel-deck" aria-label="Browse generated reels" hidden={storylines.length === 0}>
        {selectedStoryline ? (() => {
          const storyline = selectedStoryline;
          const selectedForExport = selectedExportIds.includes(storyline.id);
          const detailsOpen = expandedDetailsId === storyline.id;
          const titleDraft = titleDrafts[storyline.id]
            ?? { upper: storyline.titleUpper, lower: storyline.titleLower };
          const metadataDraft = metadataDrafts[storyline.id] ?? {
            name: storyline.speaker?.name ?? "", role: storyline.speaker?.role ?? "",
          };
          const metadataSaving = metadataStates[storyline.id] === "saving";
          const overlayBusy = metadataSaving || titleStates[storyline.id] === "saving" || titleStates[storyline.id] === "generating";
          const metadataChanged = metadataDraft.name.trim() !== (storyline.speaker?.name ?? "")
            || metadataDraft.role.trim() !== (storyline.speaker?.role ?? "");
          const titleChanged = titleDraft.upper.trim() !== storyline.titleUpper
            || titleDraft.lower.trim() !== storyline.titleLower;
          return (
            <article className={selectedForExport ? "reel-card selected-reel" : "reel-card"} key={storyline.id} aria-labelledby={`${tabId}-${storyline.id}-title`}>
              <h2 id={`${tabId}-${storyline.id}-title`} className="sr-only">{storyline.hook}</h2>

              <div className="deck-stage">
                <button type="button" className="deck-arrow previous" aria-label="Previous reel" disabled={selectedStorylineIndex === 0} onClick={() => moveToStoryline(-1)}>
                  <ChevronLeft size={30} />
                </button>
                <div className="reel-phone-frame">
                  {storyline.videoUrl ? (
                    <video
                      ref={(node) => { videoRefs.current[storyline.id] = node; }}
                      autoPlay={active}
                      loop
                      muted={!soundEnabled || audioNeedsGesture}
                      playsInline
                      preload="auto"
                      src={storyline.videoUrl}
                      poster={storyline.thumbnailUrl ?? undefined}
                      onClick={playSelected}
                      onPlay={() => onVideoPlay(storyline.id)}
                      aria-label={`${storyline.label}  video. Click to play or pause.`}
                    />
                  ) : <div className="video-placeholder">Waiting to render</div>}
                  {storyline.videoUrl ? (
                    <button
                      type="button"
                      className={soundEnabled && !audioNeedsGesture ? "reel-sound-toggle is-on" : "reel-sound-toggle"}
                      aria-label={soundEnabled && !audioNeedsGesture ? "Mute reel" : "Unmute reel"}
                      aria-pressed={soundEnabled && !audioNeedsGesture}
                      onClick={toggleSound}
                    >
                      {soundEnabled && !audioNeedsGesture ? <Volume2 size={18} /> : <VolumeX size={18} />}
                      {audioNeedsGesture ? "Enable sound" : soundEnabled ? "Sound on" : "Muted"}
                    </button>
                  ) : null}
                  {selectedForExport ? (
                    <div className="selection-confirmation" aria-live="polite">
                      <CheckCircle2 size={58} strokeWidth={2.4} />
                      <strong>Selected for export</strong>
                    </div>
                  ) : null}
                  {storyline.status !== "ready" ? (
                    <div className="render-overlay" aria-live="polite">
                      {storyline.status === "failed" ? "Clip generation failed" : `${storyline.progress}%`}
                    </div>
                  ) : null}
                  <span className="reel-position" aria-label={`Current reel ${selectedStorylineIndex + 1} of ${storylines.length}`}>
                    {selectedStorylineIndex + 1} / {storylines.length}
                  </span>
                </div>
                <button type="button" className="deck-arrow next" aria-label="Next reel" disabled={selectedStorylineIndex === storylines.length - 1} onClick={() => moveToStoryline(1)}>
                  <ChevronRight size={30} />
                </button>
              </div>

              <div className="deck-shortcuts" aria-label="Keyboard shortcuts">
                <span><kbd>←</kbd> Previous</span>
                <button type="button" className={selectedForExport ? "space-action selected" : "space-action"} disabled={storyline.status !== "ready"} onClick={toggleSelectedForExport}>
                  {selectedForExport ? <CheckCircle2 size={17} /> : null}<kbd>Space</kbd> {selectedForExport ? "Selected" : "Select for export"}
                </button>
                <span>Next <kbd>→</kbd></span>
                <span><kbd>Enter</kbd> Export</span>
              </div>

              <button type="button" className="details-toggle" aria-expanded={detailsOpen} aria-controls={`${tabId}-${storyline.id}-details`} onClick={() => toggleDetails(storyline)}>
                <Pencil size={16} /> {detailsOpen ? "Hide editing controls" : "Edit title, name and caption"}
                {detailsOpen ? <ChevronUp size={17} /> : <ChevronDown size={17} />}
              </button>

              {detailsOpen ? (
                <div className="reel-details" id={`${tabId}-${storyline.id}-details`}>
                  {storyline.thumbnailUrl ? (
                    <section className="reel-cover" aria-label="Automatically generated reel cover">
                      <img src={storyline.thumbnailUrl} alt={`${storyline.title}  thumbnail`} />
                      <div>
                        <strong>Reel cover</strong>
                        <p>Generated from the source frame and title. Exported as a JPG alongside the video.</p>
                      </div>
                    </section>
                  ) : null}
                  <section className="story-structure" aria-label={`${storyline.label} Story structure`}>
                    <div className="story-structure-heading">
                      <strong>Story structure</strong>
                      <span>{storyline.sections.length > 0 ? `${storyline.sections.length} sections` : "Structure pending"}</span>
                    </div>
                    {storyline.sections.length > 0 ? (
                      <ol className="story-beats">
                        {storyline.sections.map((section, sectionIndex) => (
                          <li className={section.beat.includes("Hook") ? "story-beat is-hook" : "story-beat"} key={`${section.beat}-${sectionIndex}`}>
                            <span className="story-beat-index" aria-hidden="true">{String(sectionIndex + 1).padStart(2, "0")}</span>
                            <div className="story-beat-content">
                              <div className="story-beat-heading"><strong>{section.beat}</strong><span>{section.role}</span></div>
                              <p>{section.text}</p>
                            </div>
                          </li>
                        ))}
                      </ol>
                    ) : <p className="summary">{storyline.summary}</p>}
                  </section>

                  {storyline.status === "ready" ? (
                    <div className="lane-title title-editor">
                      <div className="title-editor-heading"><p className="eyebrow">On-screen title</p><span>{titleDisplayLength(combineTitleLines(titleDraft))}/24 characters</span></div>
                      <div className="title-editor-controls">
                        <div className="title-editor-fields">
                          {([{ key: "upper", label: "First title line", tone: "White" }, { key: "lower", label: "Second title line", tone: "Orange" }] as const).map(({ key, label, tone }) => (
                            <label className={`title-editor-field ${key}`} key={key} htmlFor={`${tabId}-${storyline.id}-title-${key}`}>
                              <span><i aria-hidden="true" />{label}<small>{tone}</small></span>
                              <input id={`${tabId}-${storyline.id}-title-${key}`} type="text" value={titleDraft[key]}
                                disabled={overlayBusy}
                                aria-invalid={Boolean(titleErrors[storyline.id])} aria-describedby={`${tabId}-${storyline.id}-title-help`}
                                onChange={(event) => {
                                  const nextDraft = { ...titleDraft, [key]: event.target.value };
                                  setTitleDrafts((current) => ({ ...current, [storyline.id]: nextDraft }));
                                  setTitleStates((current) => ({ ...current, [storyline.id]: "idle" }));
                                  setTitleErrors((current) => ({ ...current, [storyline.id]: titleValidationMessage(nextDraft) }));
                                }} />
                            </label>
                          ))}
                        </div>
                        <div className="title-editor-actions">
                          <button type="button" className="title-regenerate-button" disabled={overlayBusy} onClick={() => { void regenerateTitle(storyline); }}>
                            {titleStates[storyline.id] === "generating" ? <Loader2 size={15} className="spin" /> : <RefreshCcw size={15} />}{titleStates[storyline.id] === "generating" ? "Generating 4 titles" : "Suggest 4 titles"}
                          </button>
                          <button type="button" disabled={overlayBusy || !titleChanged} onClick={() => { void updateTitle(storyline); }}>
                            {titleStates[storyline.id] === "saving" ? <Loader2 size={15} className="spin" /> : <Pencil size={15} />}{titleStates[storyline.id] === "saving" ? "Applying" : "Apply changes"}
                          </button>
                        </div>
                      </div>
                      {titleSuggestions[storyline.id]?.length === 4 ? (
                        <div className="title-suggestions" role="group" aria-label="Four title suggestions">
                          <p className="title-editor-help">Choose a title, then click Apply changes to update the video.</p>
                          {titleSuggestions[storyline.id].map((suggestion, index) => (
                            <button key={combineTitleLines(suggestion)} type="button" disabled={overlayBusy}
                              aria-pressed={suggestion.upper === titleDraft.upper && suggestion.lower === titleDraft.lower}
                              onClick={() => {
                                setTitleDrafts((current) => ({ ...current, [storyline.id]: suggestion }));
                                setTitleStates((current) => ({ ...current, [storyline.id]: "suggested" }));
                                setTitleErrors((current) => ({ ...current, [storyline.id]: null }));
                              }}>
                              <span>{index + 1}{index === 0 ? " · AI recommendation" : ""}</span>
                              <strong>{suggestion.upper}<br />{suggestion.lower}</strong>
                            </button>
                          ))}
                        </div>
                      ) : null}
                      <p id={`${tabId}-${storyline.id}-title-help`} className={titleErrors[storyline.id] ? "title-editor-help error" : titleStates[storyline.id] === "saved" ? "title-editor-help success" : "title-editor-help"} role={titleErrors[storyline.id] ? "alert" : "status"}>
                        {titleErrors[storyline.id] ?? (titleStates[storyline.id] === "saving" ? "Rerendering the title overlay." : titleStates[storyline.id] === "saved" ? "Changes applied to the video." : "These lines appear as the white and orange on-screen title.")}
                      </p>
                    </div>
                  ) : <div className="lane-title"><p className="eyebrow">On-screen title</p><strong>{storyline.title}</strong></div>}

                  {storyline.status === "ready" ? (
                    <div className="lane-title title-editor metadata-editor">
                      <div className="title-editor-heading"><p className="eyebrow">Name and role</p></div>
                      <div className="title-editor-controls">
                        <div className="title-editor-fields metadata-editor-fields">
                          {([{ key: "name", label: "Name", placeholder: "Michael Truell" }, { key: "role", label: "Role", placeholder: "Anysphere CEO" }] as const).map(({ key, label, placeholder }) => (
                            <label className="title-editor-field" key={key} htmlFor={`${tabId}-${storyline.id}-metadata-${key}`}>
                              <span>{label}</span>
                              <input id={`${tabId}-${storyline.id}-metadata-${key}`} type="text"
                                maxLength={100} placeholder={placeholder} value={metadataDraft[key]}
                                disabled={overlayBusy} aria-describedby={`${tabId}-${storyline.id}-metadata-help`}
                                onChange={(event) => {
                                  setMetadataDrafts((current) => ({ ...current, [storyline.id]: { ...metadataDraft, [key]: event.target.value } }));
                                  setMetadataStates((current) => ({ ...current, [storyline.id]: "idle" }));
                                  setMetadataErrors((current) => ({ ...current, [storyline.id]: null }));
                                }} />
                            </label>
                          ))}
                        </div>
                        <div className="title-editor-actions">
                          <button type="button" disabled={overlayBusy || !metadataChanged} onClick={() => { void updateMetadata(storyline, metadataDraft); }}>
                            {metadataSaving ? <Loader2 size={15} className="spin" /> : <Pencil size={15} />}{metadataSaving ? "Applying" : "Apply changes"}
                          </button>
                        </div>
                      </div>
                      <p id={`${tabId}-${storyline.id}-metadata-help`} className={`title-editor-help${metadataErrors[storyline.id] ? " error" : metadataStates[storyline.id] === "saved" ? " success" : ""}`} role={metadataErrors[storyline.id] ? "alert" : "status"}>
                        {metadataErrors[storyline.id] ?? (metadataSaving ? "Rerendering the video overlay." : metadataStates[storyline.id] === "saved" ? "Changes applied to the video." : "Updates the name and role on this reel. The role can be left blank.")}
                      </p>
                    </div>
                  ) : null}

                  <section className={storyline.instagramCaption ? "caption-tool has-caption" : "caption-tool"} aria-label={`${storyline.label} Instagram caption`}>
                    <div className="caption-tool-heading">
                      <div><MessageSquareText size={16} aria-hidden="true" /><h3>Instagram caption</h3></div>
                    </div>
                    {storyline.instagramCaption ? (
                      <div className="caption-result">
                        <div className="caption-text" tabIndex={0}>{storyline.instagramCaption}</div>
                      </div>
                    ) : <p>Create an Instagram caption grounded in this reel's actual content.</p>}
                    <div className="caption-actions">
                      <button type="button" className="caption-regenerate" disabled={storyline.status !== "ready" || captionStates[storyline.id] === "generating"} onClick={() => { void generateInstagramCaption(storyline); }}>
                        {captionStates[storyline.id] === "generating" ? <Loader2 size={15} className="spin" /> : <RefreshCcw size={15} />}
                        {captionStates[storyline.id] === "generating" ? "Generating caption" : storyline.instagramCaption ? "Regenerate" : "Generate caption"}
                      </button>
                      {storyline.instagramCaption ? (
                        <div className="caption-result-actions">
                          <button type="button" className="caption-copy" onClick={() => { void copyInstagramCaption(storyline); }}>
                            {captionStates[storyline.id] === "copied" ? <Check size={15} /> : <Copy size={15} />}{captionStates[storyline.id] === "copied" ? "Copied" : "Copy caption"}
                          </button>
                          <button type="button" className="caption-notes" disabled={noteStates[storyline.id] === "saving"} onClick={() => { void saveInstagramCaptionToNotes(storyline); }}>
                            {noteStates[storyline.id] === "saving" ? <Loader2 size={15} className="spin" /> : noteStates[storyline.id] === "saved" ? <Check size={15} /> : <NotebookPen size={15} />}
                            {noteStates[storyline.id] === "saving" ? "Saving" : noteStates[storyline.id] === "saved" ? "Saved" : "Save to iPhone Notes"}
                          </button>
                        </div>
                      ) : null}
                    </div>
                    {captionStates[storyline.id] === "error" ? <p className="caption-error" role="alert">{captionErrors[storyline.id] ?? "Caption operation failed. Please try again."}</p> : null}
                    {noteStates[storyline.id] === "error" ? <p className="caption-error" role="alert">{noteErrors[storyline.id] ?? "Could not save to iCloud Notes."}</p> : null}
                  </section>

                  {storyline.status === "failed" && !archiveMode ? <button type="button" disabled={jobBusy} onClick={() => rerenderStoryline(storyline)}><RefreshCcw size={15} /> Try again</button> : null}
                  {storyline.error ? <p className="lane-error" role="alert">{storyline.error}</p> : null}
                </div>
              ) : null}
            </article>
          );
        })() : null}
      </section>

      <div className="sr-only" role="status" aria-live="polite">{liveMessage}</div>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<TabbedApp />);

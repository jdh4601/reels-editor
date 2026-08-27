import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Check,
  CircleAlert,
  Clock3,
  Copy,
  Download,
  FolderX,
  History,
  ImageOff,
  Link,
  Loader2,
  MessageSquareText,
  Pencil,
  RefreshCcw,
  Scissors,
  Settings2,
  Square,
  Subtitles,
  WifiOff,
} from "lucide-react";
import "./styles.css";

type LaneStatus = "queued" | "rendering" | "ready" | "overlaying" | "failed";
type JobStatus = "idle" | "loading" | "generating" | "awaiting_selection" | "rendering_base" | "rendering_overlay" | "ready" | "exporting" | "failed" | "cancelled";
type ConnectionState = "connected" | "connecting" | "disconnected";
type ExportState = "idle" | "exporting" | "done" | "failed";
type ContentType = "story" | "strategy" | "failure" | "principle";
type ModelProvider = "codex-cli" | "claude-cli" | "openai" | "kimi";
type SettingsSaveState = "idle" | "saving" | "saved" | "error";
type CaptionActionState = "idle" | "generating" | "error" | "copied";
type TitleActionState = "idle" | "saving" | "error" | "saved";
type TitleDraft = { upper: string; lower: string };
type AppView = "workspace" | "archive";
type PlaybackSpeedSettings = {
  speed: number;
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
  title: string;
  titleUpper: string;
  titleLower: string;
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

type Snapshot = {
  jobId: string;
  jobStatus: JobStatus;
  jobPhase: string | null;
  jobProgress: number;
  jobMessage: string | null;
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
  episodeNumber: number;
  eventSeq: number;
};

type ArchiveItem = {
  id: string;
  jobId: string;
  storylineId: string | null;
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
  error?: string | null;
  project_name?: string;
  projectName?: string;
  source_url?: string | null;
  sourceUrl?: string | null;
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
  episode_number?: number;
  episodeNumber?: number;
  seq?: number;
  event_seq?: number;
};

type EventPayload =
  | ApiSnapshot
  | { snapshot?: ApiSnapshot; seq?: number; event_seq?: number }
  | { event: "heartbeat"; seq?: number; event_seq?: number };

const DEMO_TITLES = [
  "숫자보다 앞선 고객의 한마디",
  "완벽한 계획보다 빠른 첫 실행",
  "기능을 덜어내 이탈을 막은 방법",
];

const DEMO_SUMMARIES = [
  "대표의 판단 기준을 초반 3초에 배치하고, 중반에는 실제 문제 해결 과정을 압축합니다.",
  "인터뷰의 실행 원칙을 질문과 답의 리듬으로 보여주며 업무 현장감을 살립니다.",
  "고객 관점 전환을 중심으로 짧은 전개와 강한 마무리 문장을 구성합니다.",
];

const DEMO_SECTIONS: StorySection[][] = [
  [
    { beat: "훅", role: "첫 3초에 시선을 붙잡는 문장", text: "숫자가 아니라 고객의 한마디가 가장 중요한 판단 기준이었습니다." },
    { beat: "맥락", role: "이야기를 이해시키는 배경", text: "빠르게 성장하던 시기에도 팀은 매일 같은 질문으로 우선순위를 확인했습니다." },
    { beat: "갈등", role: "문제와 긴장을 선명하게 만드는 구간", text: "지표는 좋아 보였지만 실제 고객이 겪는 불편은 좀처럼 줄지 않았습니다." },
    { beat: "전환", role: "생각이나 행동이 바뀌는 순간", text: "회의실을 나와 고객을 직접 만나자 우리가 놓친 문제가 선명하게 보였습니다." },
    { beat: "핵심 장면", role: "변화를 증명하는 구체적인 장면", text: "그날 바로 제품 순서를 바꾸고 가장 작은 불편부터 하나씩 해결했습니다." },
    { beat: "라스트 답", role: "영상이 남기는 결론과 메시지", text: "좋은 판단은 더 많은 숫자가 아니라 더 가까이 들은 목소리에서 시작됩니다." },
  ],
  [
    { beat: "훅", role: "첫 3초에 시선을 붙잡는 문장", text: "완벽한 계획을 기다렸다면 우리는 아직도 시작하지 못했을 겁니다." },
    { beat: "맥락", role: "이야기를 이해시키는 배경", text: "처음에는 사람도 예산도 부족해서 매일 예상하지 못한 문제가 생겼습니다." },
    { beat: "갈등", role: "문제와 긴장을 선명하게 만드는 구간", text: "준비가 부족하다는 이유로 중요한 결정을 계속 미루고 싶어졌습니다." },
    { beat: "전환", role: "생각이나 행동이 바뀌는 순간", text: "작게 실행하고 결과를 확인하는 편이 오래 고민하는 것보다 빠르다는 걸 배웠습니다." },
    { beat: "핵심 장면", role: "변화를 증명하는 구체적인 장면", text: "일주일짜리 실험을 반복하자 팀이 스스로 답을 찾기 시작했습니다." },
    { beat: "라스트 답", role: "영상이 남기는 결론과 메시지", text: "실행력은 정답을 아는 능력이 아니라 다음 답을 빨리 확인하는 습관입니다." },
  ],
  [
    { beat: "훅", role: "첫 3초에 시선을 붙잡는 문장", text: "고객이 떠나는 이유는 우리가 설명하지 않은 작은 순간에 숨어 있었습니다." },
    { beat: "맥락", role: "이야기를 이해시키는 배경", text: "기능은 계속 늘었지만 처음 방문한 고객은 어디서 시작해야 할지 어려워했습니다." },
    { beat: "갈등", role: "문제와 긴장을 선명하게 만드는 구간", text: "팀은 더 많은 기능이 필요하다고 생각했지만 고객은 이미 충분히 복잡하다고 말했습니다." },
    { beat: "전환", role: "생각이나 행동이 바뀌는 순간", text: "무엇을 더할지가 아니라 무엇을 덜어낼지를 기준으로 제품을 다시 보기 시작했습니다." },
    { beat: "핵심 장면", role: "변화를 증명하는 구체적인 장면", text: "첫 화면의 선택지를 절반으로 줄이자 고객의 다음 행동이 눈에 띄게 빨라졌습니다." },
    { beat: "라스트 답", role: "영상이 남기는 결론과 메시지", text: "고객 관점은 친절한 설명이 아니라 망설일 이유를 먼저 없애는 일입니다." },
  ],
];

const STATUS_LABEL: Record<LaneStatus, string> = {
  queued: "대기",
  rendering: "렌더 중",
  ready: "준비됨",
  overlaying: "오버레이 반영",
  failed: "실패",
};

const EMPTY_TITLE = "제목 준비 중";
const INSTAGRAM_CAPTION_CTA = "다음 이야기가 궁금하다면 디원을 팔로우해주세요 🚀";
const EMPTY_SUMMARY = "YouTube 인터뷰 링크를 넣으면 클립 후보와 후킹 제목이 여기에 표시됩니다.";
const ACTIVE_JOB_STATUSES = new Set<JobStatus>(["loading", "generating", "rendering_base", "rendering_overlay", "exporting"]);
const GENERATION_JOB_STATUSES = new Set<JobStatus>(["loading", "generating", "rendering_base", "rendering_overlay"]);
const GENERATION_STAGES = [
  { label: "소스 확인", description: "저장된 영상·자막은 재사용하고, 없을 때만 다운로드합니다." },
  { label: "자막 정리", description: "원문 자막과 타임코드를 분석 가능한 형태로 정리합니다." },
  { label: "후보 10개 분석", description: "선택한 유형에서 겹치지 않는 유익한 내용을 찾습니다." },
  { label: "선택 릴스 제작", description: "고른 후보만 30~40초 영상으로 제작합니다." },
] as const;
const CONTENT_TYPE_OPTIONS: Array<{ value: ContentType; label: string; example: string }> = [
  { value: "story", label: "스토리형", example: "회사가 망하기 직전에 바꾼 한 가지" },
  { value: "strategy", label: "전략형", example: "광고 없이 첫 고객을 만든 방법" },
  { value: "failure", label: "실패 분석형", example: "6개월을 낭비하게 만든 잘못된 가정" },
  { value: "principle", label: "원칙형", example: "확장보다 이것이 먼저입니다" },
];
const ALL_CONTENT_TYPES = CONTENT_TYPE_OPTIONS.map((option) => option.value);
const MIN_PLAYBACK_SPEED = 1;
const MAX_PLAYBACK_SPEED = 1.5;
const PLAYBACK_SPEED_STEP = 0.05;
const DEFAULT_PLAYBACK_SPEED = 1.2;
const DEFAULT_EPISODE_NUMBER = 1;
const REELS_EDITOR_LOGO_URL = new URL("../../assets/reels-editor-icon.png", import.meta.url).href;
const PROVIDER_OPTIONS: Array<{ value: ModelProvider; label: string; description: string }> = [
  { value: "codex-cli", label: "Codex CLI", description: "로컬 Codex 인증과 설치된 기본 모델을 사용합니다." },
  { value: "claude-cli", label: "Claude CLI", description: "설치된 Claude Code CLI를 사용합니다." },
  { value: "openai", label: "OpenAI API", description: "OPENAI_API_KEY 환경변수의 자격증명을 사용합니다." },
  { value: "kimi", label: "Kimi API", description: "MOONSHOT_API_KEY 환경변수의 자격증명을 사용합니다." },
];

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
  return Array.from(new Intl.Segmenter("ko", { granularity: "grapheme" }).segment(compact)).length;
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
  const graphemes = Array.from(new Intl.Segmenter("ko", { granularity: "grapheme" }).segment(normalized), (item) => item.segment);
  const midpoint = Math.ceil(graphemes.length / 2);
  return { upper: graphemes.slice(0, midpoint).join(""), lower: graphemes.slice(midpoint).join("") };
}

function titleValidationMessage(draft: TitleDraft): string | null {
  if (!draft.lower.trim()) return "두 번째 제목을 입력하세요.";
  const length = titleDisplayLength(combineTitleLines(draft));
  if (length < 6) return "공백을 제외한 화면 제목을 6자 이상 입력하세요.";
  if (length > 24) return "공백을 제외한 화면 제목은 24자까지 입력할 수 있습니다.";
  return null;
}

function cacheBustedMediaUrl(url: string | null, revision: string | number): string | null {
  if (!url) return null;
  const parsed = new URL(url, window.location.origin);
  parsed.searchParams.set("revision", String(revision));
  return `${parsed.pathname}${parsed.search}${parsed.hash}`;
}

function formatArchiveDate(value: string | null): string {
  if (!value) return "완료 날짜 없음";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("ko-KR", { dateStyle: "medium", timeStyle: "short" }).format(date);
}

function normalizeArchiveItem(item: ApiArchiveItem, index: number): ArchiveItem | null {
  if (item.status && !["ready", "completed"].includes(item.status)) return null;
  const jobId = item.job_id ?? item.jobId;
  if (!jobId) return null;
  const storylineId = item.storyline_id ?? item.storylineId ?? null;
  const sourceUrl = item.source_url ?? item.sourceUrl ?? null;
  const videoUrl = mediaUrl(item.video_url ?? item.videoUrl ?? null);
  if (!videoUrl) return null;
  return {
    id: item.id ?? `${jobId}:${storylineId ?? index}`,
    jobId,
    storylineId,
    episodeNumber: positiveInteger(item.episode_number ?? item.episodeNumber),
    projectName: item.project_name ?? item.projectName ?? item.source_title ?? item.sourceTitle ?? "이름 없는 인터뷰",
    reelTitle: item.reel_title ?? item.reelTitle ?? item.storyline_title ?? item.storylineTitle ?? item.title ?? "제목 없는 릴스",
    sourceUrl,
    thumbnailUrl:
      item.source_thumbnail_url
      ?? item.sourceThumbnailUrl
      ?? item.thumbnail_url
      ?? item.thumbnailUrl
      ?? youtubeThumbnailUrl(sourceUrl),
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
  if (phase === "transcript") return 1;
  if (phase === "analyzing") return 2;
  if (status === "generating" || phase === "generating") return 3;
  if (["rendering", "overlay"].includes(phase ?? "") || status === "rendering_base" || status === "rendering_overlay") return 3;
  return 0;
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
    label: `릴스 ${index + 1}`,
    hook: "대기 중",
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
    sourceLabel: "YouTube 링크 없음",
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
    episodeNumber: DEFAULT_EPISODE_NUMBER,
    eventSeq: 0,
    storylines: [],
  };
}

function makeDemoSnapshot(media?: MediaItem[]): Snapshot {
  const items = media?.length ? media : [1, 2, 3].map((number) => ({ name: `sample-${number}.mp4`, url: `/media/sample-${number}.mp4` }));
  const showGenerationProgress = new URLSearchParams(window.location.search).has("generation-progress");
  return {
    jobId: "demo-job-kim-hyunji",
    jobStatus: showGenerationProgress ? "rendering_base" : "ready",
    jobPhase: showGenerationProgress ? "rendering" : "ready",
    jobProgress: showGenerationProgress ? 64 : 100,
    jobMessage: showGenerationProgress
      ? "릴스 2: 제목·자막 오버레이와 오디오를 합성하는 중입니다. · 전체 1/3개 완료"
      : "대표 영상 3개가 준비되었습니다.",
    jobError: null,
    projectName: "김현지대표인터뷰",
    sourceUrl: "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    transcriptLanguage: "en",
    transcriptKind: "automatic",
    sourceLabel: "YouTube · 영어 원문 자동 자막",
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
    episodeNumber: 37,
    eventSeq: 1,
    storylines: [0, 1, 2].map((index) => ({
      id: `storyline-${index + 1}`,
      serverId: `storyline-${index + 1}`,
      index: index + 1,
      label: `릴스 ${index + 1}`,
      hook: ["판단 기준", "실행 원칙", "고객 관점"][index],
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
      label: storyline.label ?? `릴스 ${index + 1}`,
      hook: storyline.hook ?? title ?? "대표 영상",
      summary: storyline.summary ?? EMPTY_SUMMARY,
      sections: (storyline.sections ?? []).filter(
        (section) => section.beat.trim() && section.role.trim() && section.text.trim(),
      ),
      status: storyline.status ?? "queued",
      progress: storyline.progress ?? 0,
      videoUrl: mediaUrl(storyline.video_url ?? storyline.videoUrl ?? null),
      title,
      titleUpper: storyline.title_upper ?? storyline.titleUpper ?? fallbackLines.upper,
      titleLower: storyline.title_lower ?? storyline.titleLower ?? fallbackLines.lower,
      instagramCaption: storyline.instagram_caption ?? storyline.instagramCaption ?? "",
      error: storyline.error,
      revision: storyline.revision ?? 1,
    };
  });
  while (storylines.length < targetStorylineCount) {
    storylines.push(makePlaceholderStoryline(storylines.length));
  }

  return {
    jobId: payload.job_id ?? payload.jobId ?? "active-job",
    jobStatus: payload.status ?? "idle",
    jobPhase: payload.phase ?? null,
    jobProgress: progressPercent(payload.progress),
    jobMessage: payload.message ?? null,
    jobError: payload.error ?? null,
    projectName: payload.project_name ?? payload.projectName ?? "Reels Editor",
    sourceUrl: payload.source_url ?? payload.sourceUrl ?? null,
    transcriptLanguage: payload.transcript_language ?? payload.transcriptLanguage ?? null,
    transcriptKind: payload.transcript_kind ?? payload.transcriptKind ?? null,
    sourceLabel: payload.source_label ?? payload.sourceLabel ?? "선택된 소스",
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
      typeLabel: candidate.type_label ?? candidate.typeLabel ?? "원칙형",
      title: candidate.title ?? "제목 없음",
      summary: candidate.summary ?? "",
      takeaway: candidate.takeaway ?? "",
    })),
    selectedCandidateIds: payload.selected_candidate_ids ?? payload.selectedCandidateIds ?? [],
    provider: modelProvider(payload.provider),
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

async function readSnapshot(): Promise<Snapshot> {
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

  const snapshotResponse = await apiFetch("/api/snapshot");
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
      <div className={`${className} thumbnail-fallback`} role="img" aria-label={`${alt} 미리보기를 불러오지 못했습니다`}>
        <ImageOff size={18} aria-hidden="true" />
        <span>미리보기 없음</span>
      </div>
    );
  }

  return <img className={className} src={src} alt={alt} onError={() => setFailed(true)} />;
}

function App() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedExportIds, setSelectedExportIds] = useState<string[]>([]);
  const [subtitlesEnabled, setSubtitlesEnabled] = useState(true);
  const [connection, setConnection] = useState<ConnectionState>("connecting");
  const [exportState, setExportState] = useState<ExportState>("idle");
  const [selectedContentTypes, setSelectedContentTypes] = useState<ContentType[]>(ALL_CONTENT_TYPES);
  const [selectedCandidateIds, setSelectedCandidateIds] = useState<string[]>([]);
  const [selectedProvider, setSelectedProvider] = useState<ModelProvider>("codex-cli");
  const [playbackSpeed, setPlaybackSpeed] = useState(DEFAULT_PLAYBACK_SPEED);
  const [speedSettingsSaveState, setSpeedSettingsSaveState] = useState<SettingsSaveState>("idle");
  const [youtubeUrl, setYoutubeUrl] = useState("");
  const [youtubeError, setYoutubeError] = useState<string | null>(null);
  const [episodeInput, setEpisodeInput] = useState(String(DEFAULT_EPISODE_NUMBER));
  const [appView, setAppView] = useState<AppView>("workspace");
  const [archiveMode, setArchiveMode] = useState(false);
  const [archiveItems, setArchiveItems] = useState<ArchiveItem[]>([]);
  const [archiveLoading, setArchiveLoading] = useState(false);
  const [archiveError, setArchiveError] = useState<string | null>(null);
  const [openingArchiveId, setOpeningArchiveId] = useState<string | null>(null);
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
  const [liveMessage, setLiveMessage] = useState("대시보드 연결 중");
  const [captionStates, setCaptionStates] = useState<Record<string, CaptionActionState>>({});
  const [titleDrafts, setTitleDrafts] = useState<Record<string, TitleDraft>>({});
  const [titleStates, setTitleStates] = useState<Record<string, TitleActionState>>({});
  const [titleErrors, setTitleErrors] = useState<Record<string, string | null>>({});
  const [exportPath, setExportPath] = useState<string | null>(null);
  const videoRefs = useRef<Record<string, HTMLVideoElement | null>>({});
  const eventSeqRef = useRef(0);
  const activeJobIdRef = useRef<string | null>(null);
  const archiveModeRef = useRef(false);
  const exportSelectionSeededRef = useRef(false);
  const speedSaveTimerRef = useRef<number | undefined>(undefined);

  const applySnapshot = useCallback((next: Snapshot) => {
    const jobChanged = activeJobIdRef.current !== next.jobId;
    activeJobIdRef.current = next.jobId;
    if (jobChanged) exportSelectionSeededRef.current = false;
    const defaultSelectedId = next.selectedStorylineId
      ?? next.storylines.find((storyline) => storyline.status === "ready")?.id
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
      const retained = current.filter((id) => availableIds.has(id));
      if (!exportSelectionSeededRef.current && defaultSelectedId) {
        exportSelectionSeededRef.current = true;
        return [defaultSelectedId];
      }
      return retained;
    });
    setSubtitlesEnabled(next.subtitlesEnabled);
    if (jobChanged) {
      setSelectedContentTypes(next.contentTypes.length > 0 ? next.contentTypes : ALL_CONTENT_TYPES);
      setSelectedCandidateIds(next.selectedCandidateIds);
      setSelectedProvider(next.provider);
      setYoutubeUrl(next.sourceUrl ?? "");
      setEpisodeInput(String(next.episodeNumber));
      setYoutubeError(null);
      setTitleStates({});
      setTitleErrors({});
      setExportState("idle");
      setExportPath(null);
    }
    setConnection(next.connection);
    eventSeqRef.current = jobChanged ? next.eventSeq : Math.max(eventSeqRef.current, next.eventSeq);
    setLiveMessage(next.jobMessage ?? `${next.projectName} 작업 상태를 불러왔습니다.`);
  }, []);

  useEffect(() => {
    let cancelled = false;
    readSnapshot()
      .then((payload) => {
        if (!cancelled) applySnapshot(payload);
      })
      .catch(() => {
        if (!cancelled) {
          setSnapshot(makeEmptySnapshot("disconnected"));
          setConnection("disconnected");
          setLiveMessage("백엔드 연결이 끊겨 빈 작업 상태를 표시합니다.");
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
        if (!response.ok) throw new Error("재생 배속 설정을 불러오지 못했습니다.");
        const settings = (await response.json()) as PlaybackSpeedSettings;
        if (!cancelled) setPlaybackSpeed(normalizePlaybackSpeed(settings.speed));
      })
      .catch(() => {
        if (!cancelled) setSpeedSettingsSaveState("error");
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
    if (pendingViewFocusRef.current !== appView) return;
    const heading = appView === "archive" ? archiveHeadingRef.current : workspaceHeadingRef.current;
    if (!heading) return;
    heading.focus();
    pendingViewFocusRef.current = null;
  }, [appView, snapshot?.jobId]);

  useEffect(() => {
    if (isDemoMode()) return undefined;
    let closedByEffect = false;
    let reconnectAttempt = 0;
    let reconnectTimer: number | undefined;
    let events: WebSocket | null = null;

    const connect = () => {
      events = new WebSocket(wsUrl("/api/events", { after: eventSeqRef.current }));
      events.onmessage = (event) => {
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
          applySnapshot(archiveModeRef.current ? completedOnlySnapshot(normalized) : normalized);
        } catch {
          setLiveMessage("이벤트 메시지를 해석하지 못했습니다.");
        }
      };
      events.onclose = () => {
        if (closedByEffect) return;
        setConnection("disconnected");
        void readSnapshot()
          .then((next) => applySnapshot(archiveModeRef.current ? completedOnlySnapshot(next) : next))
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
  }, [applySnapshot, eventConnectionVersion]);

  const storylines = snapshot?.storylines ?? [];
  const selectedStoryline = storylines.find((storyline) => storyline.id === selectedId) ?? null;
  const selectedExportStorylines = storylines.filter((storyline) => selectedExportIds.includes(storyline.id));
  const readySelected = selectedExportStorylines.length > 0
    && selectedExportStorylines.every((storyline) => storyline.status === "ready");
  const jobBusy = ACTIVE_JOB_STATUSES.has(snapshot?.jobStatus ?? "idle") || storylines.some(
    (storyline) => !storyline.serverId.startsWith("placeholder-") && ["queued", "rendering", "overlaying"].includes(storyline.status),
  );
  const canAnalyze = Boolean(snapshot?.sourceUrl) && selectedContentTypes.length > 0 && !jobBusy;
  const candidateSelectionActive = snapshot?.jobStatus === "awaiting_selection";
  const generateLabel = jobBusy ? "처리 중" : "다시 분석";
  const generationActive = GENERATION_JOB_STATUSES.has(snapshot?.jobStatus ?? "idle");
  const activeGenerationStage = generationStageIndex(snapshot?.jobPhase, snapshot?.jobStatus ?? "idle");
  const generationProgress = snapshot?.jobProgress ?? 0;
  const episodeNumber = positiveInteger(episodeInput, 0);
  const episodeValid = Number.isInteger(Number(episodeInput)) && Number(episodeInput) > 0 && String(Number(episodeInput)) === episodeInput.trim();
  const sourceThumbnailUrl = youtubeThumbnailUrl(youtubeUrl);

  const stats = useMemo(() => {
    const ready = storylines.filter((storyline) => storyline.status === "ready").length;
    const failed = storylines.filter((storyline) => storyline.status === "failed").length;
    return { ready, failed, total: storylines.length };
  }, [storylines]);

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

  async function patchSelection(storyline: Storyline, subtitlesOn = subtitlesEnabled) {
    if (isDemoMode() || !snapshot) return;
    await apiMutation(`/api/jobs/${snapshot.jobId}/storylines/${storyline.serverId}/selection`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ subtitles_on: subtitlesOn }),
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
          ? `${storyline.label} 영상을 내보내기 목록에 추가했습니다.`
          : `${storyline.label} 영상을 내보내기 목록에서 제외했습니다.`,
      );
      return next;
    });
  }

  function retryStoryline(storyline: Storyline) {
    setLiveMessage(`${storyline.label} 대표 영상을 다시 렌더합니다.`);
    if (isDemoMode()) {
      updateStoryline(storyline.id, { status: "rendering", progress: 38, error: undefined });
      window.setTimeout(() => {
        updateStoryline(storyline.id, { status: "ready", progress: 100 });
        setLiveMessage(`${storyline.label} 대표 영상이 준비되었습니다.`);
      }, 500);
      return;
    }
    if (snapshot) {
      void apiMutation(`/api/jobs/${snapshot.jobId}/storylines/${storyline.serverId}/retry`, { method: "POST" }).catch(() =>
        setLiveMessage("다시 시도 요청이 실패했습니다."),
      );
    }
  }

  async function generateInstagramCaption(storyline: Storyline) {
    if (storyline.status !== "ready") return;
    setCaptionStates((current) => ({ ...current, [storyline.id]: "generating" }));
    setLiveMessage(`${storyline.label} Instagram 캡션을 생성합니다.`);
    try {
      if (isDemoMode()) {
        await new Promise((resolve) => window.setTimeout(resolve, 450));
        updateStoryline(storyline.id, {
          instagramCaption: `Ep ${snapshot?.episodeNumber ?? DEFAULT_EPISODE_NUMBER}. ${storyline.title}\n\n이 릴스는 창업가가 고객의 문제를 먼저 확인하고, 가장 작은 실행으로 시장의 반응을 검증한 과정을 다룹니다. 제품을 완성한 뒤 알리는 것이 아니라 실제 대화에서 구매 이유를 찾았습니다.\n\n중요한 것은 더 많은 기능이 아니었습니다. 반복해서 들리는 불편 중 고객이 비용을 지불할 만큼 큰 문제 하나를 선택하고, 그 문제를 해결하는 제안을 먼저 만들었습니다.\n\n1인 창업가에게 시간과 자원은 가장 중요한 생존 조건입니다. 작은 고객 인터뷰와 유료 제안은 제품 개발과 마케팅을 동시에 검증하면서 불필요한 실행을 줄이는 방법이 될 수 있습니다.\n\n여러분은 지금 제품을 설명하고 있나요, 아니면 고객이 돈을 내고 해결하고 싶은 문제를 확인하고 있나요?\n\n${INSTAGRAM_CAPTION_CTA}`,
        });
      } else {
        if (!snapshot) return;
        const response = await apiMutation(`/api/jobs/${snapshot.jobId}/storylines/${storyline.serverId}/caption`, {
          method: "POST",
        });
        const normalized = normalizeSnapshot((await response.json()) as ApiSnapshot);
        applySnapshot(archiveModeRef.current ? completedOnlySnapshot(normalized) : normalized);
      }
      setCaptionStates((current) => ({ ...current, [storyline.id]: "idle" }));
      setLiveMessage(`${storyline.label} Instagram 캡션이 준비되었습니다.`);
    } catch (error) {
      setCaptionStates((current) => ({ ...current, [storyline.id]: "error" }));
      setLiveMessage(error instanceof Error ? error.message : "Instagram 캡션 생성에 실패했습니다.");
    }
  }

  async function copyInstagramCaption(storyline: Storyline) {
    if (!storyline.instagramCaption) return;
    try {
      await navigator.clipboard.writeText(storyline.instagramCaption);
      setCaptionStates((current) => ({ ...current, [storyline.id]: "copied" }));
      setLiveMessage(`${storyline.label} 캡션을 클립보드에 복사했습니다.`);
      window.setTimeout(() => {
        setCaptionStates((current) => ({ ...current, [storyline.id]: "idle" }));
      }, 1400);
    } catch {
      setCaptionStates((current) => ({ ...current, [storyline.id]: "error" }));
      setLiveMessage("캡션을 복사하지 못했습니다. 텍스트를 직접 선택해 복사하세요.");
    }
  }

  function toggleSubtitles() {
    setSubtitlesEnabled((enabled) => {
      const next = !enabled;
      setLiveMessage(next ? "자막 오버레이를 켭니다." : "자막 오버레이를 끕니다.");
      if (selectedStoryline) {
        if (isDemoMode()) {
          updateStoryline(selectedStoryline.id, { status: "overlaying", progress: 94 });
          window.setTimeout(() => updateStoryline(selectedStoryline.id, { status: "ready", progress: 100 }), 350);
        }
        void patchSelection(selectedStoryline, next).catch(() =>
          setLiveMessage("자막 변경 요청이 실패했습니다."),
        );
      }
      return next;
    });
  }

  async function reconnect() {
    setConnection("connecting");
    setLiveMessage("백엔드에 다시 연결합니다.");
    try {
      const next = await readSnapshot();
      applySnapshot(archiveModeRef.current ? completedOnlySnapshot(next) : next);
    } catch {
      setConnection("disconnected");
      setLiveMessage("재연결하지 못했습니다.");
    }
  }

  async function clearProject() {
    if (!snapshot?.sourceUrl || jobBusy) return;
    setLiveMessage("현재 인터뷰 선택을 비웁니다.");
    try {
      if (isDemoMode()) {
        applySnapshot(makeEmptySnapshot("connected"));
      } else {
        const response = await apiMutation("/api/snapshot", { method: "DELETE" });
        applySnapshot(normalizeSnapshot((await response.json()) as ApiSnapshot));
      }
      setYoutubeUrl("");
      setLiveMessage("인터뷰 선택을 비웠습니다. 기존 작업 파일은 유지됩니다.");
    } catch {
      setLiveMessage("프로젝트 선택을 비우지 못했습니다.");
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
      setArchiveError(error instanceof Error ? error.message : "과거 릴스를 불러오지 못했습니다.");
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
      setLiveMessage(`에피소드 ${item.episodeNumber}의 과거 릴스를 열었습니다.`);
    } catch (error) {
      setArchiveError(error instanceof Error ? error.message : "과거 릴스를 열지 못했습니다.");
    } finally {
      setOpeningArchiveId(null);
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
    setLiveMessage(`${storyline.label} 화면 제목을 영상에 반영합니다.`);
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
      setLiveMessage(`${storyline.label} 화면 제목과 영상 오버레이를 수정했습니다.`);
    } catch (error) {
      const detail = error instanceof Error ? error.message : "화면 제목을 수정하지 못했습니다.";
      setTitleStates((current) => ({ ...current, [storyline.id]: "error" }));
      setTitleErrors((current) => ({ ...current, [storyline.id]: `${detail} 이전 영상은 그대로 재생할 수 있습니다.` }));
      setLiveMessage(detail);
    }
  }

  async function startYoutubeJob(sourceUrl: string) {
    const normalized = sourceUrl.trim();
    if (!normalized) {
      const message = "YouTube 인터뷰 링크를 입력하세요.";
      setYoutubeError(message);
      setLiveMessage(message);
      return;
    }
    if (!youtubeVideoId(normalized)) {
      const message = "지원되는 YouTube 영상 링크를 입력하세요.";
      setYoutubeError(message);
      setLiveMessage(message);
      return;
    }
    setYoutubeError(null);
    if (selectedContentTypes.length === 0) {
      const message = "콘텐츠 유형을 하나 이상 선택하세요.";
      setYoutubeError(message);
      setLiveMessage(message);
      return;
    }
    if (!episodeValid) {
      const message = "회차는 1 이상의 정수로 입력하세요.";
      setYoutubeError(message);
      setLiveMessage(message);
      return;
    }
    setLiveMessage("YouTube 영상을 읽고 콘텐츠 후보 10개를 분석합니다.");
    const response = await apiMutation("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        youtube_url: normalized,
        episode_number: episodeNumber,
        content_types: selectedContentTypes,
        provider: selectedProvider,
      }),
    });
    applySnapshot(normalizeSnapshot((await response.json()) as ApiSnapshot));
    setEventConnectionVersion((version) => version + 1);
  }

  function toggleContentType(contentType: ContentType) {
    if (jobBusy) return;
    setSelectedContentTypes((current) => (
      current.includes(contentType)
        ? current.filter((value) => value !== contentType)
        : [...current, contentType]
    ));
    setYoutubeError(null);
  }

  function toggleCandidate(candidateId: string) {
    setSelectedCandidateIds((current) => (
      current.includes(candidateId)
        ? current.filter((value) => value !== candidateId)
        : [...current, candidateId]
    ));
  }

  async function generateSelectedCandidates() {
    if (!snapshot || !candidateSelectionActive || selectedCandidateIds.length === 0) return;
    setLiveMessage(`선택한 후보 ${selectedCandidateIds.length}개의 릴스를 생성합니다.`);
    const response = await apiMutation(`/api/jobs/${snapshot.jobId}/generate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ candidate_ids: selectedCandidateIds }),
    });
    applySnapshot(normalizeSnapshot((await response.json()) as ApiSnapshot));
    setEventConnectionVersion((version) => version + 1);
  }

  function submitYoutube(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (jobBusy) return;
    if (isDemoMode()) {
      setLiveMessage("YouTube 링크에서 콘텐츠 후보 10개를 분석합니다.");
      return;
    }
    void startYoutubeJob(youtubeUrl).catch((error) => {
      const detail = error instanceof Error ? error.message : "YouTube 링크를 처리하지 못했습니다.";
      setYoutubeError(detail);
      setLiveMessage(detail);
    });
  }

  async function exportSelected() {
    if (!readySelected || !snapshot) return;
    setExportState("exporting");
    setExportPath(null);
    setLiveMessage(`선택한 영상 ${selectedExportStorylines.length}개 내보내기를 준비합니다.`);
    try {
      let completedPath = "~/Movies/Reels Editor/";
      if (!isDemoMode()) {
        const response = await apiMutation(`/api/jobs/${snapshot.jobId}/export-batch`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            storyline_ids: selectedExportStorylines.map((storyline) => storyline.serverId),
            subtitles_on: subtitlesEnabled,
          }),
        });
        const payload = await response.json().catch(() => null) as unknown;
        completedPath = exportedPathFromPayload(payload) ?? completedPath;
      } else {
        await new Promise((resolve) => window.setTimeout(resolve, 450));
        completedPath = `~/Movies/Reels Editor/Ep-${snapshot.episodeNumber}_${snapshot.projectName}/`;
      }
      setExportState("done");
      setExportPath(completedPath);
      setLiveMessage(`선택한 영상 ${selectedExportStorylines.length}개를 ${completedPath}에 저장했습니다.`);
    } catch (error) {
      setExportState("failed");
      const detail = error instanceof Error ? `: ${error.message}` : "";
      setLiveMessage(`내보내기에 실패했습니다${detail}`);
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
      setLiveMessage(`재생 배속을 ${playbackSpeedLabel(settings.speed)}배로 저장했습니다.`);
    } catch (error) {
      setSpeedSettingsSaveState("error");
      setLiveMessage(error instanceof Error ? error.message : "재생 배속 저장에 실패했습니다.");
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

  function cancelJob() {
    if (!snapshot || isDemoMode() || !jobBusy) return;
    setLiveMessage("작업 취소를 요청했습니다.");
    void apiMutation(`/api/jobs/${snapshot.jobId}/cancel`, { method: "POST" }).catch(() =>
      setLiveMessage("작업 취소 요청이 실패했습니다."),
    );
  }

  function focusLane(index: number) {
    const story = storylines[index - 1];
    const video = story ? videoRefs.current[story.id] : null;
    video?.focus();
  }

  function playSelected() {
    if (!selectedStoryline) return;
    const selectedVideo = videoRefs.current[selectedStoryline.id];
    if (!selectedVideo) return;
    Object.entries(videoRefs.current).forEach(([id, video]) => {
      if (video && id !== selectedStoryline.id) video.pause();
    });
    if (selectedVideo.paused) void selectedVideo.play().catch(() => undefined);
    else selectedVideo.pause();
  }

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      if (target?.matches("input, textarea, select, [contenteditable='true']")) return;
      const key = event.key.toLowerCase();
      if (event.metaKey && key === "e") {
        event.preventDefault();
        void exportSelected();
      } else if (event.altKey && ["1", "2", "3"].includes(event.key)) {
        event.preventDefault();
        focusLane(Number(event.key));
      } else if (["1", "2", "3"].includes(event.key) && !event.metaKey && !event.ctrlKey) {
        event.preventDefault();
        const story = storylines[Number(event.key) - 1];
        if (story?.status === "ready") selectForExport(story);
      } else if (event.code === "Space") {
        event.preventDefault();
        playSelected();
      } else if (key === "s" && !event.metaKey && !event.ctrlKey) {
        event.preventDefault();
        toggleSubtitles();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  });

  function closeSettingsPopover() {
    restoreSettingsFocusRef.current = true;
    setSettingsOpen(false);
  }

  useEffect(() => {
    if (settingsOpen) {
      const firstControl = settingsFirstControlRef.current;
      if (firstControl && !firstControl.disabled) firstControl.focus();
      else settingsDialogRef.current?.focus();
      return;
    }
    if (!restoreSettingsFocusRef.current) return;
    restoreSettingsFocusRef.current = false;
    settingsTriggerRef.current?.focus();
  }, [settingsOpen]);

  // 설정은 팝오버 안에서만 열리므로, 바깥을 누르거나 Esc를 눌러 닫는다.
  useEffect(() => {
    if (!settingsOpen) return;
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
  }, [settingsOpen]);

  function SettingsPopover() {
    return (
      <div ref={settingsDialogRef} className="settings-popover" role="dialog" aria-label="생성 설정" tabIndex={-1}>
        <div className="settings-field">
          <div className="settings-field-heading">
            <h3>재생 배속</h3>
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
            aria-label="재생 배속"
            aria-valuetext={`${playbackSpeedLabel(playbackSpeed)}배`}
            style={{
              "--range-progress": `${((playbackSpeed - MIN_PLAYBACK_SPEED) / (MAX_PLAYBACK_SPEED - MIN_PLAYBACK_SPEED)) * 100}%`,
            } as React.CSSProperties}
            onChange={(event) => updatePlaybackSpeed(Number(event.target.value))}
          />
          <p className={speedSettingsSaveState === "error" ? "settings-note error" : "settings-note"}>
            {speedSettingsSaveState === "saving"
              ? "저장 중"
              : speedSettingsSaveState === "saved"
                ? "저장됨"
                : speedSettingsSaveState === "error"
                  ? "저장 실패"
                  : jobBusy
                    ? "작업 중에는 바꿀 수 없습니다"
                    : "다음 생성부터 적용됩니다"}
          </p>
        </div>

        <div className="settings-field">
          <div className="settings-field-heading">
            <h3>모델</h3>
          </div>
          <select
            id="model-provider"
            aria-label="모델 프로바이더"
            value={selectedProvider}
            disabled={jobBusy}
            onChange={(event) => setSelectedProvider(event.target.value as ModelProvider)}
          >
            {PROVIDER_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
          <p className="settings-note">
            {PROVIDER_OPTIONS.find((option) => option.value === selectedProvider)?.description}
          </p>
        </div>
      </div>
    );
  }

  function onVideoPlay(id: string) {
    Object.entries(videoRefs.current).forEach(([otherId, video]) => {
      if (otherId !== id && video) video.pause();
    });
  }

  if (!snapshot) {
    return (
      <main className="loading-shell" aria-busy="true">
        <Loader2 className="spin" aria-hidden="true" />
        <p>대시보드 준비 중</p>
      </main>
    );
  }

  if (appView === "archive") {
    return (
      <main className="app-shell archive-shell">
        <div className="topbar">
          <div className="project-brand">
            <img className="brand-mark" src={REELS_EDITOR_LOGO_URL} alt="Reels Editor 로고" />
            <div className="project-block">
              <p className="eyebrow">Reels Editor</p>
              <h1 ref={archiveHeadingRef} className="view-focus-target" tabIndex={-1}>과거 릴스</h1>
            </div>
          </div>
          <div className="workbar-actions" aria-label="과거 릴스 도구">
            <button type="button" className="ghost-button" onClick={() => {
              archiveModeRef.current = false;
              pendingViewFocusRef.current = "workspace";
              setArchiveMode(false);
              setAppView("workspace");
            }}>
              작업으로 돌아가기
            </button>
          </div>
        </div>

        <section className="archive-workspace" aria-labelledby="archive-title" aria-busy={archiveLoading}>
          <header className="archive-header">
            <div>
              <p className="eyebrow">완료된 영상만 표시</p>
              <h2 id="archive-title">다시 꺼내 쓸 릴스</h2>
              <p>영상을 열면 재생, 캡션 생성·복사, 고정 폴더로 다시 내보내기를 할 수 있습니다.</p>
            </div>
            <strong>{archiveItems.length}<span>개</span></strong>
          </header>

          {archiveLoading ? (
            <div className="archive-state" role="status"><Loader2 className="spin" aria-hidden="true" /> 과거 릴스를 불러오는 중입니다.</div>
          ) : archiveError ? (
            <div className="archive-state error" role="alert">
              <CircleAlert aria-hidden="true" />
              <span>{archiveError}</span>
              <button type="button" onClick={() => { void showArchive(); }}>다시 불러오기</button>
            </div>
          ) : archiveItems.length === 0 ? (
            <div className="archive-state empty">
              <History aria-hidden="true" />
              <strong>완료된 릴스가 아직 없습니다.</strong>
              <span>영상 제작이 끝나면 이곳에서 다시 열 수 있습니다.</span>
            </div>
          ) : (
            <div className="archive-list" role="list">
              {archiveItems.map((item) => (
                <article className="archive-item" role="listitem" key={item.id}>
                  <div className="archive-preview">
                    {item.thumbnailUrl ? (
                      <Thumbnail src={item.thumbnailUrl} alt={`${item.projectName} YouTube 썸네일`} className="archive-thumbnail" />
                    ) : item.videoUrl ? (
                      <video src={item.videoUrl} preload="metadata" muted aria-label={`${item.reelTitle} 영상 미리보기`} />
                    ) : (
                      <div className="archive-thumbnail thumbnail-fallback" role="img" aria-label="미리보기 없음"><ImageOff aria-hidden="true" /></div>
                    )}
                    <span>Ep {item.episodeNumber}</span>
                  </div>
                  <div className="archive-copy">
                    <p className="eyebrow">에피소드 {item.episodeNumber}</p>
                    <h3>{item.reelTitle}</h3>
                    <p>{item.projectName}</p>
                    <small><Clock3 size={13} aria-hidden="true" /> {formatArchiveDate(item.completedAt)}</small>
                  </div>
                  <button
                    type="button"
                    className="archive-open"
                    disabled={openingArchiveId !== null}
                    onClick={() => { void openArchiveItem(item); }}
                    aria-label={`${item.reelTitle} 열기`}
                  >
                    {openingArchiveId === item.id ? <Loader2 size={16} className="spin" /> : null}
                    {openingArchiveId === item.id ? "여는 중" : "열기"}
                  </button>
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
          <img className="brand-mark" src={REELS_EDITOR_LOGO_URL} alt="Reels Editor 로고" />
          <div className="project-block">
            <p className="eyebrow">Reels Editor</p>
            <h1 ref={workspaceHeadingRef} className="view-focus-target" tabIndex={-1}>{snapshot.projectName}</h1>
          </div>
        </div>
        <div className="workbar-actions" aria-label="작업 도구">
          <button type="button" className="ghost-button archive-button" onClick={() => { void showArchive(); }}>
            <History size={17} /> 과거 릴스
          </button>
          {!archiveMode ? (
            <div className="settings-menu" ref={settingsMenuRef}>
              <button
                ref={settingsTriggerRef}
                type="button"
                className={settingsOpen ? "icon-button active" : "icon-button"}
                aria-label="생성 설정"
                title="생성 설정"
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
                <Settings2 size={17} />
              </button>
              {settingsOpen ? <SettingsPopover /> : null}
            </div>
          ) : null}
          {!archiveMode ? (
            <>
              <button
                type="button"
                className="ghost-button"
                disabled={!snapshot.sourceUrl || jobBusy}
                onClick={clearProject}
              >
                <FolderX size={17} /> 비우기
              </button>
              <button
                type="button"
                className="ghost-button"
                disabled={!canAnalyze}
                onClick={() => {
                  if (!isDemoMode()) {
                    if (snapshot.sourceUrl) {
                      setLiveMessage("YouTube 인터뷰에서 콘텐츠 후보 10개를 다시 분석합니다.");
                      void startYoutubeJob(snapshot.sourceUrl).catch((error) => {
                        const detail = error instanceof Error ? error.message : "생성 요청이 실패했습니다.";
                        setYoutubeError(detail);
                        setLiveMessage(detail);
                      });
                      return;
                    }
                    setLiveMessage("먼저 YouTube 인터뷰 링크를 입력하세요.");
                    return;
                  }
                  setLiveMessage("콘텐츠 후보 10개를 다시 분석합니다.");
                }}
              >
                <RefreshCcw size={17} /> {generateLabel}
              </button>
            </>
          ) : <span className="archive-mode-badge"><History size={14} /> 보관함에서 열림</span>}
          <button type="button" className="icon-button" onClick={reconnect} aria-label="재연결"><RefreshCcw size={18} /></button>
          {jobBusy ? (
            <button type="button" className="icon-button danger" onClick={cancelJob} aria-label="작업 취소" title="작업 취소">
              <Square size={16} />
            </button>
          ) : null}
        </div>
      </div>

      <form className="youtube-source" onSubmit={submitYoutube} hidden={archiveMode}>
        <div className="youtube-source-controls">
          {sourceThumbnailUrl ? (
            <Thumbnail src={sourceThumbnailUrl} alt="입력한 YouTube 영상 썸네일" className="youtube-thumbnail" />
          ) : null}
          <div className="youtube-source-entry">
            <label htmlFor="youtube-url" className="sr-only">창업가 인터뷰 YouTube 링크</label>
            <span aria-hidden="true"><Link size={17} /></span>
            <input
              id="youtube-url"
              type="url"
              inputMode="url"
              autoComplete="url"
              placeholder="https://www.youtube.com/watch?v=..."
              value={youtubeUrl}
              disabled={jobBusy}
              aria-invalid={Boolean(youtubeError)}
              aria-describedby="youtube-source-help"
              onChange={(event) => {
                setYoutubeUrl(event.target.value);
                setYoutubeError(null);
              }}
            />
            <button type="submit" disabled={jobBusy || !youtubeUrl.trim() || !episodeValid || selectedContentTypes.length === 0}>
              {jobBusy ? <Loader2 size={16} className="spin" /> : <Scissors size={16} />}
              {jobBusy ? "분석 중" : "후보 10개 분석"}
            </button>
          </div>
          <label className="episode-field" htmlFor="episode-number">
            <span>에피소드</span>
            <input
              id="episode-number"
              type="number"
              inputMode="numeric"
              min="1"
              step="1"
              value={episodeInput}
              disabled={jobBusy}
              aria-label="에피소드 번호"
              aria-invalid={!episodeValid}
              aria-describedby="youtube-source-help"
              onChange={(event) => {
                setEpisodeInput(event.target.value);
                setYoutubeError(null);
              }}
            />
            <span className="episode-total">/ 1000</span>
          </label>
        </div>
        <fieldset className="content-type-picker" disabled={jobBusy}>
          <legend className="sr-only">찾을 릴스 유형</legend>
          {CONTENT_TYPE_OPTIONS.map((option) => (
            <label
              key={option.value}
              title={option.example}
              className={selectedContentTypes.includes(option.value) ? "selected" : ""}
            >
              <input
                type="checkbox"
                name="content-type"
                value={option.value}
                checked={selectedContentTypes.includes(option.value)}
                onChange={() => toggleContentType(option.value)}
              />
              <Check size={13} aria-hidden="true" />
              {option.label}
            </label>
          ))}
        </fieldset>
        <p id="youtube-source-help" className={youtubeError ? "youtube-source-help error" : "youtube-source-help"}>
          {youtubeError ?? "분석이 끝나면 원하는 후보를 복수 선택합니다. 최종 영상은 항상 30~40초로 제작됩니다."}
        </p>
      </form>

      {snapshot.jobStatus === "failed" && snapshot.jobError ? (
        <section className="notice error" role="alert">
          <CircleAlert size={18} aria-hidden="true" />
          <span><strong>클립 생성 실패</strong>{snapshot.jobError}</span>
        </section>
      ) : null}

      {candidateSelectionActive ? (
        <section className="candidate-workspace" aria-labelledby="candidate-workspace-title">
          <header className="candidate-workspace-header">
            <div>
              <p className="eyebrow">분석 완료 · 중복 제거됨</p>
              <h2 id="candidate-workspace-title">만들고 싶은 릴스를 선택하세요</h2>
              <p>선택한 후보만 30~40초 영상으로 제작합니다.</p>
            </div>
            <strong>{selectedCandidateIds.length}<span>개 선택</span></strong>
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
                    <span className={`candidate-type ${candidate.contentType}`}>{candidate.typeLabel}</span>
                    <strong>{candidate.title}</strong>
                    <span>{candidate.summary}</span>
                    <small><b>핵심 도움</b>{candidate.takeaway}</small>
                  </span>
                  <span className="candidate-check" aria-hidden="true"><Check size={17} /></span>
                </label>
              );
            })}
          </div>
          <div className="candidate-action">
            <span>{selectedCandidateIds.length > 0 ? `선택한 ${selectedCandidateIds.length}개만 제작합니다.` : "후보를 하나 이상 선택하세요."}</span>
            <button
              type="button"
              disabled={selectedCandidateIds.length === 0}
              onClick={() => {
                void generateSelectedCandidates().catch((error) => {
                  setLiveMessage(error instanceof Error ? error.message : "릴스 생성 요청이 실패했습니다.");
                });
              }}
            >
              <Scissors size={17} /> 선택한 후보로 릴스 생성
            </button>
          </div>
        </section>
      ) : null}

      <section className="status-row" aria-label="작업 상태">
        <div>
          <span className={`connection-dot ${connection}`} />
          <strong>{connection === "connected" ? "로컬 엔진 연결됨" : connection === "connecting" ? "연결 중" : "연결 끊김"}</strong>
          <small>{snapshot.sourceLabel}</small>
        </div>
        <div>
          <strong>{candidateSelectionActive ? `${snapshot.candidates.length}/10` : `${stats.ready}/${stats.total}`}</strong>
          <small>{candidateSelectionActive ? "분석된 후보" : "준비된 대표 영상"}</small>
        </div>
        <div>
          <strong>{candidateSelectionActive ? selectedCandidateIds.length : stats.failed}</strong>
          <small>{candidateSelectionActive ? "선택한 후보" : "실패한 릴스"}</small>
        </div>
        <div><strong>{candidateSelectionActive ? "30–40초" : subtitlesEnabled ? "ON" : "OFF"}</strong><small>{candidateSelectionActive ? "고정 영상 길이" : "클립 자막"}</small></div>
      </section>

      {generationActive ? (
        <section className="generation-progress" aria-labelledby="generation-progress-title" aria-live="polite">
          <div className="generation-progress-heading">
            <div className="generation-progress-title">
              <span className="generation-progress-icon" aria-hidden="true"><Loader2 size={17} className="spin" /></span>
              <div>
                <p className="eyebrow">생성 진행 · {activeGenerationStage + 1}/{GENERATION_STAGES.length}단계</p>
                <h2 id="generation-progress-title">{GENERATION_STAGES[activeGenerationStage].label}</h2>
                <p>{snapshot?.jobMessage ?? GENERATION_STAGES[activeGenerationStage].description}</p>
              </div>
            </div>
            <strong className="generation-progress-percent">{generationProgress}%</strong>
          </div>
          <div
            className="generation-progress-track"
            role="progressbar"
            aria-label="전체 영상 생성 진행률"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={generationProgress}
          >
            <span style={{ width: `${generationProgress}%` }} />
          </div>
          <ol className="generation-steps">
            {GENERATION_STAGES.map((stage, index) => {
              const state = index < activeGenerationStage ? "done" : index === activeGenerationStage ? "active" : "upcoming";
              return (
                <li className={state} key={stage.label}>
                  <span aria-hidden="true">{state === "done" ? <Check size={13} /> : index + 1}</span>
                  <div><strong>{stage.label}</strong><small>{stage.description}</small></div>
                </li>
              );
            })}
          </ol>
          <p className="generation-progress-detail">
            준비 완료 {stats.ready}개 · 렌더링 {storylines.filter((storyline) => storyline.status === "rendering").length}개 · 오버레이 {storylines.filter((storyline) => storyline.status === "overlaying").length}개
          </p>
        </section>
      ) : null}

      {connection === "disconnected" ? (
        <section className="notice" role="status">
          <WifiOff size={18} aria-hidden="true" />
          <span>로컬 Python 엔진과 연결이 끊겼습니다. 현재 화면은 마지막 상태입니다.</span>
          <button type="button" onClick={reconnect}>다시 연결</button>
        </section>
      ) : null}

      <section className="lane-scroller" aria-label="생성된 릴스 비교" hidden={storylines.length === 0}>
        <div className="lanes">
          {storylines.map((storyline) => {
            const titleDraft = titleDrafts[storyline.id]
              ?? { upper: storyline.titleUpper, lower: storyline.titleLower };
            const titleChanged = titleDraft.upper.trim() !== storyline.titleUpper
              || titleDraft.lower.trim() !== storyline.titleLower;
            return (
            <article className={`lane ${selectedExportIds.includes(storyline.id) ? "selected-lane" : ""}`} key={storyline.id} aria-labelledby={`${storyline.id}-title`}>
              <header className="lane-header">
                <div>
                  <p className="eyebrow">{storyline.label}</p>
                  <h2 id={`${storyline.id}-title`}>{storyline.hook}</h2>
                </div>
                <span className={`status-pill ${statusTone(storyline.status)}`}>
                  {storyline.status === "ready" ? <Check size={14} /> : storyline.status === "failed" ? <CircleAlert size={14} /> : <Loader2 size={14} className="spin" />}
                  {STATUS_LABEL[storyline.status]}
                </span>
              </header>

              <div className="phone-frame">
                {storyline.videoUrl ? (
                  <video
                    ref={(node) => { videoRefs.current[storyline.id] = node; }}
                    controls
                    preload="metadata"
                    muted={selectedId !== storyline.id}
                    src={storyline.videoUrl}
                    onPlay={() => onVideoPlay(storyline.id)}
                    aria-label={`${storyline.label} 대표 영상`}
                  />
                ) : (
                  <div className="video-placeholder">렌더 대기 중</div>
                )}
                {storyline.status !== "ready" ? (
                  <div className="render-overlay" aria-live="polite">
                    {storyline.status === "failed" ? "렌더 실패" : `${storyline.progress}%`}
                  </div>
                ) : null}
              </div>

              <section className="story-structure" aria-label={`${storyline.label} 콘텐츠 구성`}>
                <div className="story-structure-heading">
                  <strong>콘텐츠 구성</strong>
                  <span>{storyline.sections.length > 0 ? `${storyline.sections.length}개 구간` : "구성 대기"}</span>
                </div>
                {storyline.sections.length > 0 ? (
                  <ol className="story-beats">
                    {storyline.sections.map((section, sectionIndex) => (
                      <li
                        className={section.beat.includes("훅") ? "story-beat is-hook" : "story-beat"}
                        key={`${section.beat}-${sectionIndex}`}
                      >
                        <span className="story-beat-index" aria-hidden="true">{String(sectionIndex + 1).padStart(2, "0")}</span>
                        <div className="story-beat-content">
                          <div className="story-beat-heading">
                            <strong>{section.beat}</strong>
                            <span>{section.role}</span>
                          </div>
                          <p>{section.text}</p>
                        </div>
                      </li>
                    ))}
                  </ol>
                ) : (
                  <p className="summary">{storyline.summary}</p>
                )}
              </section>

              {storyline.status === "ready" ? (
                <div className="lane-title title-editor">
                  <div className="title-editor-heading">
                    <p className="eyebrow">화면 제목</p>
                    <span>{titleDisplayLength(combineTitleLines(titleDraft))}/24자</span>
                  </div>
                  <div className="title-editor-controls">
                    <div className="title-editor-fields">
                      {([
                        { key: "upper", label: "첫 번째 제목", tone: "흰색" },
                        { key: "lower", label: "두 번째 제목", tone: "주황색" },
                      ] as const).map(({ key, label, tone }) => (
                        <label className={`title-editor-field ${key}`} key={key} htmlFor={`${storyline.id}-title-${key}`}>
                          <span><i aria-hidden="true" />{label}<small>{tone}</small></span>
                          <input
                            id={`${storyline.id}-title-${key}`}
                            type="text"
                            value={titleDraft[key]}
                            disabled={titleStates[storyline.id] === "saving"}
                            aria-invalid={Boolean(titleErrors[storyline.id])}
                            aria-describedby={`${storyline.id}-title-help`}
                            onChange={(event) => {
                              const nextDraft = { ...titleDraft, [key]: event.target.value };
                              setTitleDrafts((current) => ({ ...current, [storyline.id]: nextDraft }));
                              setTitleStates((current) => ({ ...current, [storyline.id]: "idle" }));
                              setTitleErrors((current) => ({ ...current, [storyline.id]: titleValidationMessage(nextDraft) }));
                            }}
                          />
                        </label>
                      ))}
                    </div>
                    <button
                      type="button"
                      disabled={titleStates[storyline.id] === "saving" || !titleChanged}
                      onClick={() => { void updateTitle(storyline); }}
                    >
                      {titleStates[storyline.id] === "saving" ? <Loader2 size={15} className="spin" /> : <Pencil size={15} />}
                      {titleStates[storyline.id] === "saving" ? "반영 중" : "수정하기"}
                    </button>
                  </div>
                  <p
                    id={`${storyline.id}-title-help`}
                    className={titleErrors[storyline.id] ? "title-editor-help error" : titleStates[storyline.id] === "saved" ? "title-editor-help success" : "title-editor-help"}
                    role={titleErrors[storyline.id] ? "alert" : "status"}
                  >
                    {titleErrors[storyline.id]
                      ?? (titleStates[storyline.id] === "saving"
                        ? "기존 영상은 유지한 채 제목 오버레이를 다시 렌더링합니다."
                        : titleStates[storyline.id] === "saved"
                          ? "화면 제목과 재생 영상에 수정 내용이 반영되었습니다."
                          : "두 입력창의 문구가 영상의 흰색·주황색 제목에 각각 반영됩니다.")}
                  </p>
                </div>
              ) : (
                <div className="lane-title">
                  <p className="eyebrow">화면 제목</p>
                  <strong>{storyline.title}</strong>
                </div>
              )}

              <section className={storyline.instagramCaption ? "caption-tool has-caption" : "caption-tool"} aria-label={`${storyline.label} Instagram 캡션`}>
                <div className="caption-tool-heading">
                  <div>
                    <MessageSquareText size={16} aria-hidden="true" />
                    <h3>Instagram 캡션</h3>
                  </div>
                  <button
                    type="button"
                    disabled={storyline.status !== "ready" || captionStates[storyline.id] === "generating"}
                    onClick={() => { void generateInstagramCaption(storyline); }}
                  >
                    {captionStates[storyline.id] === "generating" ? <Loader2 size={15} className="spin" /> : <MessageSquareText size={15} />}
                    {captionStates[storyline.id] === "generating"
                      ? "캡션 생성 중"
                      : storyline.instagramCaption
                        ? "다시 생성"
                        : "캡션 생성하기"}
                  </button>
                </div>
                {storyline.instagramCaption ? (
                  <div className="caption-result">
                    <div className="caption-text" tabIndex={0}>{storyline.instagramCaption}</div>
                    <button type="button" className="caption-copy" onClick={() => { void copyInstagramCaption(storyline); }}>
                      {captionStates[storyline.id] === "copied" ? <Check size={15} /> : <Copy size={15} />}
                      {captionStates[storyline.id] === "copied" ? "복사됨" : "캡션 복사"}
                    </button>
                  </div>
                ) : (
                  <p>이 릴스의 실제 내용에 맞춘 게시글 캡션을 만듭니다.</p>
                )}
                {captionStates[storyline.id] === "error" ? <p className="caption-error">캡션 작업에 실패했습니다. 다시 시도해주세요.</p> : null}
              </section>

              <div className="lane-footer">
                <label className="select-video">
                  <input
                    type="checkbox"
                    name="selected-video"
                    checked={selectedExportIds.includes(storyline.id)}
                    disabled={storyline.status !== "ready"}
                    onChange={(event) => selectForExport(storyline, event.target.checked)}
                  />
                  <span>내보내기 선택</span>
                </label>
              {storyline.status === "failed" && !archiveMode ? <button type="button" disabled={jobBusy} onClick={() => retryStoryline(storyline)}>다시 시도</button> : null}
              </div>
              {storyline.error ? <p className="lane-error" role="alert">{storyline.error}</p> : null}
            </article>
            );
          })}
        </div>
      </section>

      <section className="export-bar" aria-label="내보내기" hidden={storylines.length === 0}>
        <div className="export-summary">
          <strong>{selectedExportStorylines.length > 0 ? `${selectedExportStorylines.length}개 영상 선택됨` : "선택된 영상 없음"}</strong>
          <span>
            {exportState === "done" && exportPath
              ? `저장 위치: ${exportPath}`
              : selectedExportStorylines.length > 0
                ? `${selectedExportStorylines.map((storyline) => storyline.label).join(" · ")} · ~/Movies/Reels Editor/에 저장됩니다.`
                : "준비된 대표 영상을 복수로 선택할 수 있습니다."}
          </span>
        </div>
        {!archiveMode ? (
          <label className="switch">
            <input type="checkbox" checked={subtitlesEnabled} onChange={toggleSubtitles} role="switch" aria-checked={subtitlesEnabled} />
            <span className="switch-track" aria-hidden="true"><Subtitles size={15} /></span>
            <span>자막 {subtitlesEnabled ? "ON" : "OFF"}</span>
          </label>
        ) : <span className="fixed-export-note">고정 보관 폴더</span>}
        <button type="button" className="export-button" disabled={!readySelected || exportState === "exporting"} onClick={exportSelected}>
          {exportState === "exporting" ? <Loader2 size={17} className="spin" /> : <Download size={17} />}
          {exportState === "done" ? "저장 완료" : archiveMode ? "보관 영상 다시 내보내기" : `선택 영상 ${selectedExportStorylines.length}개 내보내기`}
        </button>
      </section>

      <div className="sr-only" role="status" aria-live="polite">{liveMessage}</div>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
